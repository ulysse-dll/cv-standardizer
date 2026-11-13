"""File d'attente des CV à traiter, et mémoire des lots déjà traités.

Un CV met une à plusieurs minutes sur CPU : impossible de faire patienter
une requête HTTP pendant tout un lot. On fonctionne donc en deux temps :

1. le serveur reçoit les fichiers, crée un "job" (un lot) et répond tout de suite ;
2. un fil d'exécution séparé (thread) traite les CV UN PAR UN en arrière-plan,
   pendant que la page web redemande régulièrement où en est le job.

Un seul CV à la fois : le CPU est déjà à 100 % sur un CV, en lancer deux en
parallèle ne ferait que les ralentir tous les deux.

Chaque lot a son dossier dans outputs/ :

    outputs/<identifiant>/job.json            l'état du lot (pour le retrouver après un redémarrage)
    outputs/<identifiant>/01_CV_Nom.json      le CV structuré      } les fichiers
    outputs/<identifiant>/01_CV_Nom.pdf       le CV standardisé    } que l'on
    outputs/<identifiant>/01_CV_Nom.pptx      la diapositive       } télécharge
    outputs/<identifiant>/01_CV_Nom.html      l'aperçu
    outputs/<identifiant>/01_photo.jpg        la photo trouvée dans le CV
    outputs/<identifiant>/01_source.txt       le texte extrait du fichier d'origine
"""

import json
import os
import queue
import re
import shutil
import subprocess
import threading
import time
import unicodedata
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

from app import preview
from app.config import Settings
from app.extraction import ExtractionError
from app.llm.base import LLMError, LLMProvider
from app.photo import prepare_photo
from app.pipeline import StructuringError, build_documents, process_cv
from app.schema import CV
from app.slides import render_deck
from app.theme import theme_from_settings
from app.timing import logger

# Ce qu'on recopie tel quel entre un Item en mémoire et le fichier job.json.
_SAVED_FIELDS = (
    "index", "filename", "status", "error", "attempts", "extraction_method",
    "timings", "warnings", "output_stem", "has_pdf", "edited",
)
INTERRUPTED = "Traitement interrompu par l'arrêt du serveur : renvoie ce fichier."


@dataclass
class Item:
    """Un CV dans un job."""

    index: int
    filename: str  # nom du fichier envoyé
    data: Optional[bytes] = None  # contenu du fichier ; effacé de la mémoire dès qu'il est traité
    status: str = "pending"  # pending -> running -> done | error
    error: Optional[str] = None
    cv: Optional[CV] = None
    attempts: int = 0
    extraction_method: Optional[str] = None
    timings: Dict[str, float] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    output_stem: Optional[str] = None  # nom des fichiers produits, sans extension
    has_pdf: bool = False
    step: Optional[str] = None  # étape en cours : "extraction", "llm" ou "rendu"
    progress: float = 0.0  # avancement de l'étape en cours, de 0 à 1
    source_text: str = ""  # le texte extrait du fichier (pour comparer avec le résultat)
    photo: Optional[bytes] = None  # la photo du candidat
    edited: bool = False  # vrai si l'utilisateur a corrigé le résultat à la main
    started: Optional[float] = None  # heure de début du traitement (horloge time.monotonic)

    @property
    def number(self) -> str:
        """ "01", "02"... : le numéro du CV dans le lot, en tête des noms de fichiers."""
        return f"{self.index + 1:02d}"


@dataclass
class Job:
    id: str
    items: List[Item]
    anonymous: bool = False  # lot anonyme : « Candidat 01 », sans coordonnées ni photo
    created: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    finished: threading.Event = field(default_factory=threading.Event)

    @property
    def status(self) -> str:
        return "done" if self.finished.is_set() else "running"


def slugify(text: str) -> str:
    """ "Inès Benali" -> "Ines_Benali" : un nom de fichier sans accent ni caractère spécial."""
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9]+", "_", ascii_text).strip("_")[:60] or "sans_nom"


# Un serveur qui tourne des semaines ne doit pas garder tous les lots en
# mémoire (textes, photos...). Au-delà de ce nombre, les plus anciens lots
# terminés sont oubliés. Leurs fichiers restent dans outputs/.
MAX_JOBS_IN_MEMORY = 30
_JOB_FOLDER = re.compile(r"[0-9a-f]{12}")  # la forme d'un identifiant de lot


@contextmanager
def keep_awake() -> Iterator[Optional[subprocess.Popen]]:
    """Empêche le Mac de se mettre en veille pendant le bloc `with`.

    Un lot dure longtemps (plus d'une minute par CV). Sans ça, un Mac réglé
    pour s'endormir vite suspend le traitement dès qu'on s'éloigne du clavier.
    `caffeinate` est un petit programme fourni avec macOS : tant qu'il tourne,
    la machine reste éveillée (l'écran, lui, peut s'éteindre).
    Ailleurs que sur Mac, ce bloc ne fait rien.
    """
    command = shutil.which("caffeinate")
    # -i : pas de veille automatique. -w : caffeinate s'arrête tout seul si
    # notre serveur s'arrête, même brutalement.
    process = subprocess.Popen([command, "-i", "-w", str(os.getpid())]) if command else None
    try:
        yield process
    finally:
        if process:
            process.terminate()
            process.wait()


class JobQueue:
    def __init__(self, provider: LLMProvider, settings: Settings, outputs_dir: Path):
        self.provider = provider
        self.settings = settings
        self.outputs_dir = outputs_dir
        self.theme = theme_from_settings(settings)
        self._jobs: Dict[str, Job] = {}
        self._queue: "queue.Queue[Job]" = queue.Queue()
        # daemon=True : ce thread s'arrête tout seul quand le serveur s'arrête.
        self._worker = threading.Thread(target=self._run, daemon=True, name="cv-worker")

    def start(self) -> None:
        """Au démarrage du serveur : ménage, puis on recharge les lots déjà traités."""
        self.delete_expired()
        self._load_saved_jobs()
        self._worker.start()

    def submit(self, files: List[Tuple[str, bytes]], anonymous: bool = False) -> Job:
        """Enregistre un lot de fichiers (nom, contenu) et rend la main immédiatement."""
        items = [Item(index=i, filename=name, data=data) for i, (name, data) in enumerate(files)]
        job = Job(id=uuid.uuid4().hex[:12], items=items, anonymous=anonymous)
        self._jobs[job.id] = job
        self._forget_old_jobs()
        self.delete_expired()
        self._queue.put(job)
        return job

    def _forget_old_jobs(self) -> None:
        # Un dictionnaire Python garde l'ordre d'ajout : les premiers sont les plus anciens.
        finished = [job for job in self._jobs.values() if job.finished.is_set()]
        while len(self._jobs) > MAX_JOBS_IN_MEMORY and finished:
            del self._jobs[finished.pop(0).id]

    def get(self, job_id: str) -> Optional[Job]:
        return self._jobs.get(job_id)

    def all_jobs(self) -> List[Job]:
        """Les lots connus, du plus récent au plus ancien."""
        return sorted(self._jobs.values(), key=lambda job: job.created, reverse=True)

    def job_dir(self, job: Job) -> Path:
        return self.outputs_dir / job.id

    # ------------------------------------------------ côté arrière-plan ---
    def _run(self) -> None:
        while True:
            job = self._queue.get()  # attend ici tant qu'il n'y a rien à faire
            with keep_awake():
                for item in job.items:
                    if job.id in self._jobs:  # le lot a pu être supprimé entre-temps
                        self._process(job, item)
            job.finished.set()
            if job.id in self._jobs:
                self._save_state(job)

    def _process(self, job: Job, item: Item) -> None:
        item.status = "running"
        item.started = time.monotonic()

        def on_progress(step: str, fraction: float) -> None:
            item.step, item.progress = step, fraction

        try:
            result = process_cv(
                item.data or b"", item.filename, self.provider, self.settings, on_progress,
                anonymous_number=item.index + 1 if job.anonymous else None,
            )
            item.cv = result.cv
            item.attempts = result.attempts
            item.extraction_method = result.extraction_method
            item.timings = result.timings
            item.warnings = result.warnings
            item.source_text = result.source_text
            item.photo = result.photo
            self._save(job, item, result.html, result.pdf, result.pptx)
            item.status = "done"
        except (ExtractionError, LLMError, StructuringError) as error:
            # Erreurs "prévues" : leur message est écrit pour l'utilisateur.
            item.status, item.error = "error", str(error)
            logger.warning("[%s] échec : %s", item.filename, error)
        except Exception as error:  # un bug imprévu ne doit pas bloquer le reste du lot
            item.status, item.error = "error", f"Erreur inattendue : {error}"
            logger.exception("[%s] erreur inattendue", item.filename)
        finally:
            item.data = None  # on ne garde pas le fichier d'origine en mémoire
            item.step = None
            self._save_state(job)

    # ------------------------------------------- corrections à la main ---
    def update_cv(self, job: Job, item: Item, cv: CV) -> None:
        """Remplace le CV d'un item par une version corrigée, et refait tous les documents.

        Aucun LLM ici : c'est rapide (quelques secondes, surtout pour le PDF).
        """
        item.cv, item.edited = cv, True
        # Les alertes « À vérifier » concernaient la version du modèle : elles tombent.
        item.warnings = [w for w in item.warnings if not w.startswith("À vérifier")]
        self._rebuild(job, item)

    def set_photo(self, job: Job, item: Item, image: bytes) -> None:
        """Remplace (ou ajoute) la photo par une image choisie par l'utilisateur.
        Lève ValueError si le fichier n'est pas une image lisible."""
        item.photo = prepare_photo(image)
        self._rebuild(job, item)

    def remove_photo(self, job: Job, item: Item) -> None:
        """Retire la photo (mal choisie, ou non souhaitée) : les initiales la remplacent."""
        item.photo = None
        self._rebuild(job, item)

    def _rebuild(self, job: Job, item: Item) -> None:
        documents = build_documents(item.cv, item.photo, self.theme)
        outdated = ("Génération PDF", "Diapositive")  # ces deux-là sont recalculées
        item.warnings = [w for w in item.warnings if not w.startswith(outdated)] + documents.warnings
        self._delete_documents(job, item)  # si le nom a changé, le nom des fichiers aussi
        self._save(job, item, documents.html, documents.pdf, documents.pptx)
        self._save_state(job)

    # -------------------------------------------- documents pour un lot ---
    def deck(self, job: Job) -> bytes:
        """Un seul PowerPoint pour tout le lot : une diapositive par CV réussi."""
        candidates = [(item.cv, item.photo) for item in job.items if item.status == "done"]
        return render_deck(candidates, self.theme)

    def slide_preview(self, job: Job, item: Item) -> Optional[bytes]:
        """L'image de la diapositive (PNG), fabriquée à la demande puis gardée de côté."""
        folder = self.job_dir(job)
        cached = folder / f"{item.output_stem}.slide.png"
        if not cached.exists():
            image = preview.pptx_to_png(folder / f"{item.output_stem}.pptx")
            if image is None:
                return None
            cached.write_bytes(image)
        return cached.read_bytes()

    # ------------------------------------------------ fichiers du lot ---
    def _delete_documents(self, job: Job, item: Item) -> None:
        folder = self.job_dir(job)
        for extension in ("json", "html", "pdf", "pptx", "slide.png"):
            (folder / f"{item.output_stem}.{extension}").unlink(missing_ok=True)

    def _save(self, job: Job, item: Item, html: str, pdf: Optional[bytes], pptx: bytes) -> None:
        """Écrit les fichiers d'un CV dans outputs/<job>/."""
        folder = self.job_dir(job)
        folder.mkdir(parents=True, exist_ok=True)
        # Le numéro en tête évite que deux CV du même nom s'écrasent.
        item.output_stem = f"{item.number}_CV_{slugify(item.cv.identity.full_name)}"
        (folder / f"{item.output_stem}.json").write_text(item.cv.model_dump_json(indent=2), encoding="utf-8")
        (folder / f"{item.output_stem}.html").write_text(html, encoding="utf-8")
        (folder / f"{item.output_stem}.pptx").write_bytes(pptx)
        (folder / f"{item.output_stem}.slide.png").unlink(missing_ok=True)  # l'image de la diapo est périmée
        item.has_pdf = pdf is not None
        if pdf is not None:
            (folder / f"{item.output_stem}.pdf").write_bytes(pdf)
        # La photo et le texte d'origine : pour pouvoir tout refaire après un redémarrage.
        photo_path = folder / f"{item.number}_photo.jpg"
        if item.photo:
            photo_path.write_bytes(item.photo)
        else:
            photo_path.unlink(missing_ok=True)
        (folder / f"{item.number}_source.txt").write_text(item.source_text, encoding="utf-8")

    def _save_state(self, job: Job) -> None:
        """Écrit job.json : l'état du lot, relu au prochain démarrage du serveur."""
        folder = self.job_dir(job)
        folder.mkdir(parents=True, exist_ok=True)
        state = {
            "id": job.id,
            "created": job.created.isoformat(),
            "anonymous": job.anonymous,
            "items": [{name: getattr(item, name) for name in _SAVED_FIELDS} for item in job.items],
        }
        # On écrit d'abord un fichier provisoire puis on le renomme : si le serveur
        # s'arrête au milieu de l'écriture, l'ancien job.json reste intact.
        temporary = folder / "job.json.tmp"
        temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(folder / "job.json")

    def _load_saved_jobs(self) -> None:
        """Relit les job.json de outputs/ : les lots survivent à un redémarrage."""
        loaded = []
        for state_path in self.outputs_dir.glob("*/job.json"):
            try:
                loaded.append(self._load_job(state_path))
            except Exception as error:  # un dossier abîmé ne doit pas empêcher de démarrer
                logger.warning("Lot illisible, ignoré (%s) : %s", state_path.parent.name, error)
        loaded.sort(key=lambda job: job.created)
        for job in loaded[-MAX_JOBS_IN_MEMORY:]:
            self._jobs[job.id] = job
        if loaded:
            logger.info("%d lot(s) précédent(s) retrouvé(s) dans %s", len(self._jobs), self.outputs_dir)

    def _load_job(self, state_path: Path) -> Job:
        folder = state_path.parent
        state = json.loads(state_path.read_text(encoding="utf-8"))
        items = []
        for saved in state["items"]:
            item = Item(**{name: saved[name] for name in _SAVED_FIELDS})
            if item.status == "done":
                item.cv = CV.model_validate_json((folder / f"{item.output_stem}.json").read_text(encoding="utf-8"))
                photo_path, text_path = folder / f"{item.number}_photo.jpg", folder / f"{item.number}_source.txt"
                item.photo = photo_path.read_bytes() if photo_path.exists() else None
                item.source_text = text_path.read_text(encoding="utf-8") if text_path.exists() else ""
            elif item.status != "error":
                # Le serveur s'est arrêté pendant ce lot : le fichier envoyé n'existe plus.
                item.status, item.error = "error", INTERRUPTED
            items.append(item)
        job = Job(id=state["id"], items=items, anonymous=state.get("anonymous", False),
                  created=datetime.fromisoformat(state["created"]))
        job.finished.set()
        return job

    # ---------------------------------------------------- suppression ---
    def delete(self, job: Job) -> None:
        """Supprime un lot : ses fichiers sur le disque et sa trace en mémoire."""
        self._jobs.pop(job.id, None)
        shutil.rmtree(self.job_dir(job), ignore_errors=True)

    def delete_expired(self) -> None:
        """Supprime les lots plus vieux que OUTPUT_RETENTION_DAYS (0 = on garde tout).

        Les CV sont des données personnelles : mieux vaut ne pas les garder
        indéfiniment. On ne touche qu'aux dossiers qui ont la forme d'un lot.
        """
        days = self.settings.output_retention_days
        if days <= 0 or not self.outputs_dir.exists():
            return
        limit = datetime.now(timezone.utc) - timedelta(days=days)
        for folder in self.outputs_dir.iterdir():
            if not folder.is_dir() or not _JOB_FOLDER.fullmatch(folder.name):
                continue
            job = self._jobs.get(folder.name)
            if job is not None and not job.finished.is_set():
                continue  # jamais un lot en cours
            last_change = datetime.fromtimestamp(folder.stat().st_mtime, timezone.utc)
            if last_change < limit:
                logger.info("Lot %s supprimé : plus de %d jours.", folder.name, days)
                self._jobs.pop(folder.name, None)
                shutil.rmtree(folder, ignore_errors=True)

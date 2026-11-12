"""File d'attente des CV à traiter.

Un CV met une à plusieurs minutes sur CPU : impossible de faire patienter
une requête HTTP pendant tout un lot. On fonctionne donc en deux temps :

1. le serveur reçoit les fichiers, crée un "job" et répond tout de suite ;
2. un fil d'exécution séparé (thread) traite les CV UN PAR UN en arrière-plan,
   pendant que la page web redemande régulièrement où en est le job.

Un seul CV à la fois : le CPU est déjà à 100 % sur un CV, en lancer deux en
parallèle ne ferait que les ralentir tous les deux.
"""

import queue
import re
import threading
import unicodedata
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from app.config import Settings
from app.extraction import ExtractionError
from app.llm.base import LLMError, LLMProvider
from app.pipeline import StructuringError, process_cv
from app.schema import CV
from app.timing import logger


@dataclass
class Item:
    """Un CV dans un job."""

    index: int
    filename: str  # nom du fichier envoyé
    data: Optional[bytes]  # contenu du fichier ; effacé de la mémoire dès qu'il est traité
    status: str = "pending"  # pending -> running -> done | error
    error: Optional[str] = None
    cv: Optional[CV] = None
    attempts: int = 0
    extraction_method: Optional[str] = None
    timings: Dict[str, float] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    output_stem: Optional[str] = None  # nom des fichiers produits, sans extension
    has_pdf: bool = False


@dataclass
class Job:
    id: str
    items: List[Item]
    finished: threading.Event = field(default_factory=threading.Event)

    @property
    def status(self) -> str:
        return "done" if self.finished.is_set() else "running"


def slugify(text: str) -> str:
    """ "Inès Benali" -> "Ines_Benali" : un nom de fichier sans accent ni caractère spécial."""
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9]+", "_", ascii_text).strip("_")[:60] or "sans_nom"


class JobQueue:
    def __init__(self, provider: LLMProvider, settings: Settings, outputs_dir: Path):
        self.provider = provider
        self.settings = settings
        self.outputs_dir = outputs_dir
        self._jobs: Dict[str, Job] = {}
        self._queue: "queue.Queue[Job]" = queue.Queue()
        # daemon=True : ce thread s'arrête tout seul quand le serveur s'arrête.
        self._worker = threading.Thread(target=self._run, daemon=True, name="cv-worker")

    def start(self) -> None:
        self._worker.start()

    def submit(self, files: List[Tuple[str, bytes]]) -> Job:
        """Enregistre un lot de fichiers (nom, contenu) et rend la main immédiatement."""
        items = [Item(index=i, filename=name, data=data) for i, (name, data) in enumerate(files)]
        job = Job(id=uuid.uuid4().hex[:12], items=items)
        self._jobs[job.id] = job
        self._queue.put(job)
        return job

    def get(self, job_id: str) -> Optional[Job]:
        return self._jobs.get(job_id)

    def job_dir(self, job: Job) -> Path:
        return self.outputs_dir / job.id

    # ------------------------------------------------ côté arrière-plan ---
    def _run(self) -> None:
        while True:
            job = self._queue.get()  # attend ici tant qu'il n'y a rien à faire
            for item in job.items:
                self._process(job, item)
            job.finished.set()

    def _process(self, job: Job, item: Item) -> None:
        item.status = "running"
        try:
            result = process_cv(item.data or b"", item.filename, self.provider, self.settings)
            item.cv = result.cv
            item.attempts = result.attempts
            item.extraction_method = result.extraction_method
            item.timings = result.timings
            item.warnings = result.warnings
            self._save(job, item, result.html, result.pdf)
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

    def _save(self, job: Job, item: Item, html: str, pdf: Optional[bytes]) -> None:
        """Écrit les fichiers produits dans outputs/<job>/."""
        folder = self.job_dir(job)
        folder.mkdir(parents=True, exist_ok=True)
        # Le numéro en tête évite que deux CV du même nom s'écrasent.
        item.output_stem = f"{item.index + 1:02d}_CV_{slugify(item.cv.identity.full_name)}"
        (folder / f"{item.output_stem}.json").write_text(
            item.cv.model_dump_json(indent=2), encoding="utf-8"
        )
        (folder / f"{item.output_stem}.html").write_text(html, encoding="utf-8")
        if pdf is not None:
            (folder / f"{item.output_stem}.pdf").write_bytes(pdf)
            item.has_pdf = True

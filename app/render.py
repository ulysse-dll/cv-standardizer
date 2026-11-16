"""Étape finale : fabriquer le CV standardisé à partir du CV validé.

    CV (Pydantic) --Jinja2--> HTML --WeasyPrint ou navigateur--> PDF

Le HTML sert aussi d'aperçu dans le navigateur.

Deux moteurs PDF : WeasyPrint (qui a besoin de la bibliothèque Pango) et, à
défaut, un navigateur de la famille Chrome déjà installé sur la machine.
"""

import base64
import contextlib
import io
import os
import re
import shutil
import signal
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import List, Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.schema import CV

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

# autoescape : tout texte venu du CV est "échappé". Si un CV contient du code
# HTML ou JavaScript, il s'affichera comme du texte au lieu d'être exécuté.
_env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=select_autoescape(["html"]))

LABELS = {
    "fr": {
        "summary": "Profil", "experiences": "Expériences professionnelles", "education": "Formation",
        "skills": "Compétences", "languages": "Langues", "certifications": "Certifications",
        "interests": "Centres d'intérêt", "present": "aujourd'hui",
        "contact": "Coordonnées", "footer": "Profil candidat · Confidentiel",
    },
    "en": {
        "summary": "Profile", "experiences": "Experience", "education": "Education",
        "skills": "Skills", "languages": "Languages", "certifications": "Certifications",
        "interests": "Interests", "present": "present",
        "contact": "Contact", "footer": "Candidate profile · Confidential",
    },
}
_FRENCH_WORDS = {"le", "la", "les", "des", "du", "et", "de", "en", "pour", "avec", "dans", "sur", "un", "une"}
# « a » et « on » sont aussi des mots français (« elle a », « on a ») : on ne les compte pas.
_ENGLISH_WORDS = {"the", "and", "of", "for", "with", "in", "to", "an", "by", "from"}


class PDFUnavailableError(Exception):
    """Aucun moteur PDF n'a pu produire le fichier."""


def detect_language(cv: CV) -> str:
    """Devine si le CV est en français ou en anglais, pour choisir les titres de rubrique."""
    texts = [cv.title or "", cv.summary or ""]
    for job in cv.experiences:
        texts.append(job.job_title)
        texts.extend(job.highlights)
    words = re.findall(r"[a-zàâçéèêëîïôûùüœ]+", " ".join(texts).lower())
    french = sum(word in _FRENCH_WORDS for word in words)
    english = sum(word in _ENGLISH_WORDS for word in words)
    return "en" if english > french else "fr"


def period(start: Optional[str], end: Optional[str], present_label: str = "present") -> str:
    """Affiche une période : "03/2021 – aujourd'hui", ou une seule date, ou rien."""
    parts = [present_label if part == "present" else part for part in (start, end) if part]
    return " – ".join(parts)


def render_html(cv: CV, photo: Optional[bytes] = None, accent: str = "#1F4E79") -> str:
    """`photo` : la photo du candidat (JPEG), affichée en rond dans l'en-tête. `accent` : la couleur des titres."""
    lang = detect_language(cv)
    labels = LABELS[lang]
    template = _env.get_template("cv.html")
    return template.render(
        cv=cv,
        photo=base64.b64encode(photo).decode("ascii") if photo else None,
        accent=accent,
        lang=lang,
        labels=labels,
        period=lambda start, end: period(start, end, labels["present"]),
    )


def render_pdf(html: str) -> bytes:
    """HTML -> PDF, avec le premier moteur disponible (voir pdf_engine)."""
    engine = pdf_engine()
    if engine == "weasyprint":
        # Import ici, et pas en haut du fichier : si Pango manque, seul le PDF
        # tombe en panne. Le reste de l'application (JSON, aperçu) continue.
        from weasyprint import HTML

        return HTML(string=html).write_pdf()
    if engine == "navigateur":
        return _pdf_with_browser(html, find_browser())
    raise PDFUnavailableError(
        "Génération PDF indisponible : ni WeasyPrint (bibliothèque Pango) ni navigateur "
        "Chrome, Chromium, Edge ou Brave trouvés. Voir le README, section Installation."
    )


def pdf_engine() -> Optional[str]:
    """Le moteur qui fabriquera les PDF : "weasyprint", "navigateur", ou None."""
    if weasyprint_available():
        return "weasyprint"
    if find_browser():
        return "navigateur"
    return None


def pdf_available() -> bool:
    return pdf_engine() is not None


@lru_cache
def weasyprint_available() -> bool:
    """WeasyPrint peut-il se charger ? (lru_cache : on ne fait le test qu'une fois.)"""
    # Quand Pango manque, WeasyPrint affiche un long message en anglais avant
    # d'échouer. On le fait taire : notre propre message est plus utile.
    silence = io.StringIO()
    try:
        with contextlib.redirect_stdout(silence), contextlib.redirect_stderr(silence):
            import weasyprint  # noqa: F401
    except (ImportError, OSError):
        return False
    return True


# ------------------------------------------- plan B : un navigateur -------
# Chrome et ses cousins savent "imprimer" une page HTML en PDF sans ouvrir de
# fenêtre (mode "headless"). C'est le même moteur que Fichier > Imprimer.
_BROWSER_APPS = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
]
_BROWSER_COMMANDS = ["google-chrome", "chromium", "chromium-browser", "microsoft-edge"]
BROWSER_TIMEOUT_S = 60


@lru_cache
def find_browser() -> Optional[str]:
    for path in _BROWSER_APPS:
        if Path(path).exists():
            return path
    for command in _BROWSER_COMMANDS:
        found = shutil.which(command)
        if found:
            return found
    return None


def _run_browser(command: List[str]) -> None:
    """Lance le navigateur et attend sa fin, sans jamais rester bloqué.

    Un navigateur démarre plusieurs programmes auxiliaires. S'il se fige, il
    faut tous les arrêter, sinon ils continuent de tourner en arrière-plan :
    - start_new_session=True les met dans un groupe à part ;
    - passé le délai, os.killpg arrête tout le groupe d'un coup.
    On ne lit pas ce que le navigateur affiche (DEVNULL) : attendre ce texte
    pourrait nous bloquer à notre tour.
    """
    try:
        process = subprocess.Popen(
            command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True
        )
    except OSError as error:
        raise PDFUnavailableError(f"Génération PDF impossible : le navigateur n'a pas démarré ({error}).") from error
    try:
        process.wait(timeout=BROWSER_TIMEOUT_S)
    except subprocess.TimeoutExpired as error:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except OSError:
            process.kill()
        process.wait()
        raise PDFUnavailableError(
            f"Génération PDF impossible : le navigateur n'a pas répondu en {BROWSER_TIMEOUT_S} s."
        ) from error


def _pdf_with_browser(html: str, browser: str) -> bytes:
    # Le navigateur lit un fichier et en écrit un autre : on passe par un
    # dossier temporaire, supprimé (avec son contenu) dès la sortie du "with".
    with tempfile.TemporaryDirectory(prefix="cv-pdf-") as folder:
        source = Path(folder) / "cv.html"
        target = Path(folder) / "cv.pdf"
        source.write_text(html, encoding="utf-8")
        command = [
            browser,
            "--headless=new",  # pas de fenêtre
            "--disable-gpu",
            "--no-first-run",
            "--disable-extensions",
            # Vie privée : le navigateur n'a aucune raison d'aller sur Internet.
            # Cette règle fait échouer toute résolution de nom de domaine.
            "--host-resolver-rules=MAP * ~NOTFOUND",
            # Deuxième verrou : toute connexion passerait par un "proxy" qui
            # n'existe pas (le port 9 de cette machine), donc échouerait.
            "--proxy-server=127.0.0.1:9",
            "--disable-background-networking",
            "--disable-component-update",
            # Un profil vide et jetable : on ne touche pas au Chrome de l'utilisateur.
            f"--user-data-dir={Path(folder) / 'profil'}",
            "--no-pdf-header-footer",  # pas de date ni d'URL en marge
            f"--print-to-pdf={target}",
            source.as_uri(),
        ]
        _run_browser(command)
        if not target.exists():
            raise PDFUnavailableError("Génération PDF impossible : le navigateur n'a produit aucun fichier.")
        return target.read_bytes()

"""Étape finale : fabriquer le CV standardisé à partir du CV validé.

    CV (Pydantic) --Jinja2--> HTML --WeasyPrint--> PDF

Le HTML sert aussi d'aperçu dans le navigateur.
"""

import re
from functools import lru_cache
from pathlib import Path
from typing import Optional

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
        "present": "aujourd'hui",
    },
    "en": {
        "summary": "Profile", "experiences": "Experience", "education": "Education",
        "skills": "Skills", "languages": "Languages", "certifications": "Certifications",
        "present": "present",
    },
}
_FRENCH_WORDS = {"le", "la", "les", "des", "du", "et", "de", "en", "pour", "avec", "dans", "sur", "un", "une"}
_ENGLISH_WORDS = {"the", "and", "of", "for", "with", "in", "to", "on", "a", "an", "by", "from"}


class PDFUnavailableError(Exception):
    """WeasyPrint ne peut pas tourner (bibliothèque Pango absente)."""


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


def render_html(cv: CV) -> str:
    lang = detect_language(cv)
    labels = LABELS[lang]
    template = _env.get_template("cv.html")
    return template.render(
        cv=cv,
        lang=lang,
        labels=labels,
        period=lambda start, end: period(start, end, labels["present"]),
    )


def render_pdf(html: str) -> bytes:
    # Import ici, et pas en haut du fichier : si Pango manque, seul le PDF
    # tombe en panne. Le reste de l'application (JSON, aperçu) continue.
    if not pdf_available():
        raise PDFUnavailableError(
            "Génération PDF indisponible : WeasyPrint ne trouve pas la bibliothèque Pango. "
            "Voir le README, section Installation."
        )
    from weasyprint import HTML

    return HTML(string=html).write_pdf()


@lru_cache
def pdf_available() -> bool:
    """WeasyPrint peut-il se charger ? (lru_cache : on ne fait le test qu'une fois.)"""
    try:
        import weasyprint  # noqa: F401
    except (ImportError, OSError):
        return False
    return True

"""Le « thème » des documents produits : couleurs et logo, réglables dans .env.

    THEME_ACCENT=#1F4E79       la couleur principale (bandeau, titres de rubrique)
    THEME_STRIPE=#E8A33D       le fin trait de couleur sous le bandeau de la diapositive
    THEME_LOGO_PATH=logo.png   un logo, affiché en haut à droite de la diapositive

Le PDF et la diapositive utilisent la même couleur principale.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

from app.config import ROOT_DIR, Settings
from app.timing import logger

DEFAULT_ACCENT = "#1F4E79"
DEFAULT_STRIPE = "#E8A33D"


@dataclass(frozen=True)
class Theme:
    accent: str = DEFAULT_ACCENT
    stripe: str = DEFAULT_STRIPE
    logo: Optional[bytes] = None  # le contenu du fichier image, ou None


def hex_to_rgb(color: str) -> Tuple[int, int, int]:
    """ "#1F4E79" -> (31, 78, 121)"""
    return int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)


def _valid_color(value: str, default: str, name: str) -> str:
    if re.fullmatch(r"#[0-9a-fA-F]{6}", value.strip()):
        return value.strip().upper()
    logger.warning("%s=%r n'est pas une couleur du type #1F4E79 : valeur par défaut utilisée.", name, value)
    return default


def theme_from_settings(settings: Settings) -> Theme:
    """Construit le thème d'après .env. Une valeur invalide est ignorée, avec un avertissement."""
    logo = None
    if settings.theme_logo_path:
        path = Path(settings.theme_logo_path).expanduser()
        if not path.is_absolute():
            path = ROOT_DIR / path  # un chemin relatif part du dossier du projet
        if path.is_file():
            logo = path.read_bytes()
        else:
            logger.warning("THEME_LOGO_PATH : fichier introuvable (%s), pas de logo.", path)
    return Theme(
        accent=_valid_color(settings.theme_accent, DEFAULT_ACCENT, "THEME_ACCENT"),
        stripe=_valid_color(settings.theme_stripe, DEFAULT_STRIPE, "THEME_STRIPE"),
        logo=logo,
    )

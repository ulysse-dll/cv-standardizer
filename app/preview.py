"""Fabriquer une IMAGE de la diapositive, pour l'afficher dans la page web.

Un navigateur ne sait pas afficher un fichier .pptx. Sur Mac, on demande donc
l'image à « Coup d'œil » (Quick Look, l'aperçu qu'on obtient dans le Finder
avec la barre d'espace), via la commande `qlmanage` fournie avec macOS.

Ailleurs que sur Mac, il n'y a pas d'aperçu : la page masque simplement
l'onglet, et la diapositive reste téléchargeable.
"""

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

PREVIEW_WIDTH = 1600  # largeur de l'image, en pixels
TIMEOUT_S = 60


def preview_available() -> bool:
    return shutil.which("qlmanage") is not None


def pptx_to_png(pptx_path: Path) -> Optional[bytes]:
    """L'image PNG de la première diapositive du fichier, ou None si c'est impossible."""
    command = shutil.which("qlmanage")
    if command is None or not pptx_path.exists():
        return None
    with tempfile.TemporaryDirectory(prefix="cv-diapo-") as folder:
        try:
            # -t : fabriquer une vignette ; -s : sa taille ; -o : le dossier où l'écrire.
            subprocess.run(
                [command, "-t", "-s", str(PREVIEW_WIDTH), "-o", folder, str(pptx_path)],
                capture_output=True, timeout=TIMEOUT_S, check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        image = Path(folder) / f"{pptx_path.name}.png"  # qlmanage ajoute ".png" au nom du fichier
        return image.read_bytes() if image.exists() else None

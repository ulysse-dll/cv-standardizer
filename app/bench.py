"""Mesure la vitesse du pipeline sur ta machine, sans passer par le serveur web.

    python -m app.bench                      # les 4 faux CV de samples/
    python -m app.bench chemin/vers/cv.pdf   # un ou plusieurs fichiers précis

Affiche, pour chaque CV, la durée de chaque étape en secondes.
"""

import sys
from pathlib import Path

from app.config import ROOT_DIR, get_settings
from app.llm import get_provider
from app.pipeline import process_cv
from app.timing import setup_logging

STEPS = ["extraction", "llm", "validation", "html", "pdf"]


def main() -> None:
    setup_logging()
    settings = get_settings()
    provider = get_provider(settings)
    paths = [Path(arg) for arg in sys.argv[1:]] or sorted(
        path for path in (ROOT_DIR / "samples").iterdir() if path.suffix in (".pdf", ".docx")
    )

    rows = []
    for path in paths:
        try:
            result = process_cv(path.read_bytes(), path.name, provider, settings)
            cells = [f"{result.timings.get(step, 0):.1f}" for step in STEPS]
            rows.append([path.name, *cells, f"{sum(result.timings.values()):.1f}", str(result.attempts)])
        except Exception as error:  # on continue avec les autres fichiers
            rows.append([path.name, *["-"] * len(STEPS), "-", f"ÉCHEC : {error}"])

    header = ["fichier", *STEPS, "total", "essais"]
    widths = [max(len(row[i]) for row in [header, *rows]) for i in range(len(header))]
    print(f"\nModèle : {provider.model} ({provider.name}) — durées en secondes")
    for row in [header, *rows]:
        print("  ".join(cell.ljust(width) for cell, width in zip(row, widths)))


if __name__ == "__main__":
    main()

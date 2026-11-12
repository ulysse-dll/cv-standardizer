"""Outils partagés par tous les tests (pytest charge ce fichier tout seul)."""

from pathlib import Path

import pytest

from samples.generate_samples import SAMPLES, SAMPLES_DIR


@pytest.fixture(scope="session")
def samples_dir() -> Path:
    """Le dossier des faux CV. On régénère ceux qui manqueraient."""
    for filename, make in SAMPLES.items():
        if not (SAMPLES_DIR / filename).exists():
            make(SAMPLES_DIR / filename)
    return SAMPLES_DIR

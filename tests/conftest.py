"""Outils partagés par tous les tests (pytest charge ce fichier tout seul)."""

from pathlib import Path

import pytest

from app import render
from samples.generate_samples import SAMPLES, SAMPLES_DIR


@pytest.fixture(autouse=True)
def skip_slow_pdf(request, monkeypatch):
    """Par défaut, les tests ne fabriquent pas de PDF : lancer un navigateur
    prend plus d'une seconde par CV. Seuls les tests marqués `real_pdf` le font.
    (autouse=True : cette fixture s'applique à tous les tests, sans la demander.)"""
    if "real_pdf" not in request.keywords:
        monkeypatch.setattr(render, "pdf_engine", lambda: None)


@pytest.fixture(scope="session")
def samples_dir() -> Path:
    """Le dossier des faux CV. On régénère ceux qui manqueraient."""
    for filename, make in SAMPLES.items():
        if not (SAMPLES_DIR / filename).exists():
            make(SAMPLES_DIR / filename)
    return SAMPLES_DIR

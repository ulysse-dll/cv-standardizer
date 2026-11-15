"""Outils partagés par tous les tests (pytest charge ce fichier tout seul)."""

import os
from pathlib import Path

import pytest

# Dans les tests, pas de relance ciblée du LLM : chaque faux modèle n'a que les
# réponses qu'on lui a données. Les tests de la relance la réactivent eux-mêmes.
os.environ["LLM_REPAIR"] = "false"

from app import render, timing
from samples.generate_samples import SAMPLES, SAMPLES_DIR
from samples.hard_samples import HARD_SAMPLES


@pytest.fixture(autouse=True)
def skip_slow_pdf(request, monkeypatch):
    """Par défaut, les tests ne fabriquent pas de PDF : lancer un navigateur
    prend plus d'une seconde par CV. Seuls les tests marqués `real_pdf` le font.
    (autouse=True : cette fixture s'applique à tous les tests, sans la demander.)"""
    if "real_pdf" not in request.keywords:
        monkeypatch.setattr(render, "pdf_engine", lambda: None)


@pytest.fixture(scope="session", autouse=True)
def logs_in_a_temporary_folder(tmp_path_factory):
    """Les tests écrivent leurs journaux dans un dossier jetable, pas dans logs/ :
    sinon le vrai journal se remplit de faux échecs voulus par les tests."""
    timing.LOGS_DIR = tmp_path_factory.mktemp("logs")


@pytest.fixture(scope="session")
def samples_dir() -> Path:
    """Le dossier des faux CV. On régénère ceux qui manqueraient."""
    for filename, make in {**SAMPLES, **HARD_SAMPLES}.items():
        if not (SAMPLES_DIR / filename).exists():
            make(SAMPLES_DIR / filename)
    return SAMPLES_DIR

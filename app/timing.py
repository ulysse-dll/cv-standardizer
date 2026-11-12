"""Chronomètre par étape, pour mesurer la vitesse du pipeline.

Utilisation :

    timer = StepTimer("mon_cv.pdf")
    with timer.step("extraction"):
        ...  # le code à mesurer
    timer.steps  ->  {"extraction": 0.42}

Chaque étape est aussi écrite dans les logs (console + logs/cv_agent.log).
"""

import logging
import time
from contextlib import contextmanager
from typing import Dict

from app.config import LOGS_DIR

logger = logging.getLogger("cv_agent")


def setup_logging() -> None:
    """Envoie les logs vers la console et vers un fichier. À appeler une fois."""
    if logger.handlers:  # déjà configuré
        return
    LOGS_DIR.mkdir(exist_ok=True)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%H:%M:%S")
    for handler in (
        logging.StreamHandler(),
        logging.FileHandler(LOGS_DIR / "cv_agent.log", encoding="utf-8"),
    ):
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)


class StepTimer:
    """Mesure la durée de chaque étape du traitement d'un CV."""

    def __init__(self, label: str):
        self.label = label
        self.steps: Dict[str, float] = {}

    @contextmanager
    def step(self, name: str):
        start = time.perf_counter()
        try:
            yield
        finally:
            # `finally` : la durée est notée même si l'étape lève une erreur.
            duration = time.perf_counter() - start
            # Une étape rejouée (ex. le retry du LLM) s'additionne.
            self.steps[name] = round(self.steps.get(name, 0.0) + duration, 2)
            logger.info("[%s] %s : %.2f s", self.label, name, duration)

    @property
    def total(self) -> float:
        return round(sum(self.steps.values()), 2)

"""Point d'entrée du serveur web (FastAPI).

Lancement :  uvicorn app.main:app --reload
"""

from fastapi import FastAPI

from app.config import get_settings
from app.timing import setup_logging

setup_logging()
app = FastAPI(title="CV Standardizer")


@app.get("/health")
def health() -> dict:
    """Petit test de vie : le serveur répond-il, et avec quel provider ?"""
    settings = get_settings()
    return {"status": "ok", "provider": settings.llm_provider}

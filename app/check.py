"""Diagnostic : tout est-il en place pour faire tourner l'application ?

    python -m app.check

À lancer après une installation, ou quand quelque chose ne marche pas. Chaque
ligne commence par :
    [ok]      c'est bon
    [info]    facultatif, l'application marche sans
    [ERREUR]  à corriger, avec la marche à suivre

Le programme se termine avec le code 0 si tout l'indispensable est là, 1 sinon
(pratique dans un script d'installation).
"""

import sys
import tempfile
from pathlib import Path
from typing import List, Tuple

import httpx

from app import ocr, photo, render
from app.config import OUTPUTS_DIR, Settings, get_settings
from app.llm import ConfigError, get_provider
from app.schema import CV
from app.slides import render_pptx

OK, INFO, ERROR = "ok", "info", "ERREUR"
Result = Tuple[str, str]  # (niveau, message)

SAMPLE_CV = CV.model_validate({"identity": {"full_name": "Essai Diagnostic"}, "title": "CV d'essai"})


def check_python() -> Result:
    version = ".".join(str(part) for part in sys.version_info[:3])
    if sys.version_info < (3, 9):
        return ERROR, f"Python {version} : il faut Python 3.9 ou plus récent."
    return OK, f"Python {version}"


def check_ocr() -> Result:
    engine = ocr.ocr_engine()
    if engine is None:
        return INFO, "OCR absent : les PDF scannés seront refusés (installe Tesseract ; sur Mac, pyobjc-framework-Vision)."
    return OK, f"OCR : {engine}"


def check_pdf() -> Result:
    engine = render.pdf_engine()
    if engine is None:
        return INFO, "Export PDF absent : il faut la bibliothèque Pango (WeasyPrint) ou un navigateur Chrome, Chromium, Edge ou Brave."
    try:
        pdf = render.render_pdf(render.render_html(SAMPLE_CV))
    except render.PDFUnavailableError as error:
        return ERROR, f"Export PDF ({engine}) : {error}"
    return OK, f"Export PDF : {engine} (essai réussi, {len(pdf)} octets)"


def check_pptx() -> Result:
    try:
        pptx, _ = render_pptx(SAMPLE_CV)
    except Exception as error:
        return ERROR, f"Diapositive PowerPoint : {error}"
    return OK, f"Diapositive PowerPoint (essai réussi, {len(pptx)} octets)"


def check_photo() -> Result:
    if photo.face_detection_available():
        return OK, "Photo : détection de visage de macOS disponible"
    return INFO, "Photo : pas de détection de visage (hors Mac), choix d'après la forme de l'image seulement."


def check_outputs() -> Result:
    try:
        OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=str(OUTPUTS_DIR)):
            pass
    except OSError as error:
        return ERROR, f"Le dossier {OUTPUTS_DIR} n'est pas accessible en écriture : {error}"
    return OK, f"Dossier des résultats : {OUTPUTS_DIR}"


def check_llm(settings: Settings) -> List[Result]:
    try:
        provider = get_provider(settings)
    except ConfigError as error:
        return [(ERROR, f"Configuration du LLM (.env) : {error}")]
    results: List[Result] = [(OK, f"Provider : {provider.name}, modèle : {provider.model}")]

    if settings.is_remote:
        # On ne contacte pas un service distant juste pour vérifier.
        results.append((INFO, "Provider distant : le texte des CV quitte cette machine. Faux CV uniquement."))
        return results

    base_url = settings.ollama_base_url.rstrip("/")
    try:
        answer = httpx.get(f"{base_url}/api/tags", timeout=5)
        answer.raise_for_status()
    except httpx.HTTPError:
        results.append((ERROR, f"Ollama ne répond pas sur {base_url}. Ouvre l'application Ollama, ou lance : ollama serve"))
        return results
    results.append((OK, f"Ollama répond sur {base_url}"))

    installed = [model.get("name", "") for model in answer.json().get("models", [])]
    wanted = provider.model if ":" in provider.model else f"{provider.model}:latest"
    if wanted in installed:
        results.append((OK, f"Modèle {provider.model} installé"))
    else:
        results.append((ERROR, f"Modèle {provider.model} absent. Lance : ollama pull {provider.model}"))
    return results


def run_checks(settings: Settings) -> List[Result]:
    return [check_python(), check_outputs(), check_ocr(), check_pdf(), check_pptx(), check_photo(), *check_llm(settings)]


def main() -> int:
    results = run_checks(get_settings())
    for level, message in results:
        print(f"[{level}]".ljust(9), message)
    errors = sum(level == ERROR for level, _ in results)
    print()
    print("Tout est prêt : lance ./run.sh" if not errors else f"{errors} point(s) à corriger avant de lancer l'application.")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())

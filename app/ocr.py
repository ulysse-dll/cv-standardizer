"""OCR : lire le texte d'une image (une page de CV scannée).

Deux moteurs, tous les deux 100 % locaux et gratuits :

- Tesseract, s'il est installé (fonctionne sur Mac, Linux, Windows) ;
- sinon, sur Mac, l'OCR intégré à macOS (le framework « Vision » d'Apple,
  celui qui permet de copier du texte depuis une photo). Rien à installer à
  part le pont Python `pyobjc-framework-Vision`.

Le reste de l'application n'appelle que `read_image(png, languages)`.
"""

import io
import shutil
import sys
from functools import lru_cache
from pathlib import Path
from typing import List, Optional

# Tesseract nomme les langues "fra", "eng"... ; Apple attend "fr-FR", "en-US"...
_VISION_LANGUAGES = {
    "fra": "fr-FR", "eng": "en-US", "deu": "de-DE", "spa": "es-ES", "ita": "it-IT", "por": "pt-BR",
}


class OCRError(Exception):
    """L'OCR a échoué. Le message est affichable à l'utilisateur."""


def find_tesseract() -> Optional[str]:
    """Cherche le programme tesseract : à côté de Python d'abord, puis dans le PATH."""
    beside_python = Path(sys.executable).parent / "tesseract"
    if beside_python.exists():
        return str(beside_python)
    return shutil.which("tesseract")


@lru_cache
def vision_available() -> bool:
    """L'OCR de macOS est-il utilisable ? (lru_cache : on ne teste qu'une fois.)"""
    if sys.platform != "darwin":
        return False
    try:
        import Vision  # noqa: F401
    except ImportError:
        return False
    return True


def ocr_engine() -> Optional[str]:
    """Le moteur qui sera utilisé : "tesseract", "apple-vision", ou None s'il n'y en a aucun."""
    if find_tesseract():
        return "tesseract"
    if vision_available():
        return "apple-vision"
    return None


def read_image(png: bytes, languages: str = "fra+eng") -> str:
    """Renvoie le texte lu dans une image PNG. `languages` suit la notation Tesseract."""
    engine = ocr_engine()
    if engine == "tesseract":
        return _read_with_tesseract(png, languages)
    if engine == "apple-vision":
        return _read_with_vision(png, languages)
    raise OCRError("Aucun moteur d'OCR disponible.")


# ---------------------------------------------------------- Tesseract -----
def _usable_languages(pytesseract, wanted: str) -> str:
    """Garde, parmi les langues demandées, celles réellement installées."""
    installed = set(pytesseract.get_languages(config=""))
    usable = [lang for lang in wanted.split("+") if lang in installed]
    return "+".join(usable) or "eng"


def _read_with_tesseract(png: bytes, languages: str) -> str:
    import pytesseract
    from PIL import Image

    pytesseract.pytesseract.tesseract_cmd = find_tesseract()
    image = Image.open(io.BytesIO(png))
    return pytesseract.image_to_string(image, lang=_usable_languages(pytesseract, languages))


# ------------------------------------------------------- Apple Vision -----
def _read_with_vision(png: bytes, languages: str) -> str:
    # Imports ici : ces modules n'existent que sur Mac.
    import objc
    import Vision
    from Foundation import NSData

    wanted: List[str] = [_VISION_LANGUAGES[code] for code in languages.split("+") if code in _VISION_LANGUAGES]

    # autorelease_pool : libère la mémoire utilisée par macOS dès la fin du bloc.
    with objc.autorelease_pool():
        request = Vision.VNRecognizeTextRequest.alloc().init()
        request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)  # lent mais précis
        request.setUsesLanguageCorrection_(True)
        request.setRecognitionLanguages_(wanted or ["en-US"])

        image = NSData.dataWithBytes_length_(png, len(png))
        handler = Vision.VNImageRequestHandler.alloc().initWithData_options_(image, None)
        success, error = handler.performRequests_error_([request], None)
        if not success:
            raise OCRError(f"L'OCR de macOS a échoué : {error}")

        # Une "observation" = une ligne de texte repérée dans l'image, de haut en bas.
        lines = [str(observation.topCandidates_(1)[0].string()) for observation in request.results() or []]
    return "\n".join(lines)

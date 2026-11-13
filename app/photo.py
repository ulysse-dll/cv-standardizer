"""Retrouver la photo du candidat dans son CV, SANS LLM.

    PDF  -> les images de la première page ; pour un PDF scanné, on cherche
            un visage dans l'image de la page.
    DOCX -> les images rangées dans le fichier (dossier word/media).

Comment reconnaître LA photo parmi les images (logos, pictogrammes...) ?

1. Par la forme : une photo d'identité est à peu près carrée ou en portrait,
   ni minuscule, ni large comme la page.
2. Sur Mac, par le contenu : macOS sait repérer un visage dans une image
   (framework Vision, le même que pour l'OCR, 100 % local). Une image qui
   contient un visage passe devant les autres, et sert à bien cadrer.

Le résultat est toujours une image JPEG carrée, ou None s'il n'y a pas de
photo. C'est une estimation : l'utilisateur peut retirer une photo mal
choisie depuis la page web.
"""

import io
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import fitz  # PyMuPDF
from PIL import Image

from app import ocr
from app.timing import logger

# ----- ce qu'on accepte comme "photo possible" -----
MIN_RATIO, MAX_RATIO = 0.6, 1.3  # largeur / hauteur : du portrait au presque carré
MIN_SIDE_POINTS = 50  # dans un PDF : au moins 1,8 cm de côté (72 points = 2,54 cm)
MAX_PAGE_SHARE = 0.45  # ... et au plus 45 % de la largeur de la page
MIN_SIDE_PIXELS = 90  # dans un DOCX : au moins 90 pixels de côté
RENDER_DPI = 200  # résolution utilisée pour "photographier" un morceau de page
OUTPUT_SIZE = 500  # côté de la photo produite, en pixels

# Un visage détecté : (gauche, haut, largeur, hauteur), en fractions de l'image
# (0 à 1), l'origine étant en haut à gauche.
Box = Tuple[float, float, float, float]


@dataclass
class Candidate:
    image: Image.Image
    area: float  # surface affichée : à défaut de visage, la plus grande image gagne


# ------------------------------------------------- détection de visage ----
def face_detection_available() -> bool:
    return ocr.vision_available()


def detect_faces(image: Image.Image) -> List[Box]:
    """Les visages trouvés dans l'image, du plus grand au plus petit ([] hors Mac)."""
    if not face_detection_available():
        return []
    import objc
    import Vision
    from Foundation import NSData

    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="PNG")
    png = buffer.getvalue()

    boxes: List[Box] = []
    with objc.autorelease_pool():
        request = Vision.VNDetectFaceRectanglesRequest.alloc().init()
        data = NSData.dataWithBytes_length_(png, len(png))
        handler = Vision.VNImageRequestHandler.alloc().initWithData_options_(data, None)
        success, _ = handler.performRequests_error_([request], None)
        if not success:
            return []
        for observation in request.results() or []:
            box = observation.boundingBox()
            # Vision mesure depuis le BAS de l'image : on convertit en "depuis le haut".
            top = 1 - box.origin.y - box.size.height
            boxes.append((box.origin.x, top, box.size.width, box.size.height))
    return sorted(boxes, key=lambda box: box[2] * box[3], reverse=True)


# -------------------------------------------------------- recadrage -------
def crop_square(image: Image.Image, face: Optional[Box] = None, tight: bool = False) -> Image.Image:
    """Découpe un carré dans l'image.

    - sans visage connu : le plus grand carré possible, calé vers le haut
      (sur une photo en portrait, le visage est dans la partie haute) ;
    - avec un visage : carré centré sur lui ;
    - tight=True (page scannée) : on ne garde que les alentours du visage,
      sinon on emporterait le texte du CV avec la photo.
    """
    width, height = image.size
    side = float(min(width, height))
    center_x, center_y = width / 2, side / 2 + (height - side) * 0.15

    if face:
        left, top, face_width, face_height = face
        center_x = (left + face_width / 2) * width
        # On vise un peu sous le milieu du visage, pour garder le haut des épaules.
        center_y = (top + face_height * 0.6) * height
        if tight:
            side = min(side, 2.3 * max(face_width * width, face_height * height))

    # On passe en pixels entiers (sinon l'arrondi peut donner 257 x 258), et
    # le carré ne doit pas sortir de l'image.
    side = int(side)
    x0 = int(min(max(center_x - side / 2, 0), width - side))
    y0 = int(min(max(center_y - side / 2, 0), height - side))
    return image.crop((x0, y0, x0 + side, y0 + side))


def _to_jpeg(image: Image.Image) -> bytes:
    image = image.convert("RGB").resize((OUTPUT_SIZE, OUTPUT_SIZE), Image.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=90)
    return buffer.getvalue()


def _has_photo_shape(width: float, height: float) -> bool:
    return height > 0 and MIN_RATIO <= width / height <= MAX_RATIO


def _choose(candidates: List[Candidate]) -> Optional[bytes]:
    """Parmi les images possibles : celle qui contient un visage, sinon la plus grande."""
    candidates.sort(key=lambda candidate: candidate.area, reverse=True)
    for candidate in candidates:
        faces = detect_faces(candidate.image)
        if faces:
            return _to_jpeg(crop_square(candidate.image, faces[0]))
    if candidates:
        return _to_jpeg(crop_square(candidates[0].image))
    return None


# ---------------------------------------------------------------- PDF -----
def _pixmap_to_image(pixmap: "fitz.Pixmap") -> Image.Image:
    return Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)


def photo_from_pdf(data: bytes) -> Optional[bytes]:
    document = fitz.open(stream=data, filetype="pdf")
    if document.needs_pass or len(document) == 0:
        return None
    page = document[0]  # la photo est toujours sur la première page

    candidates: List[Candidate] = []
    for image_info in page.get_images(full=True):
        for rect in page.get_image_rects(image_info[0]):  # où l'image est posée sur la page
            rect = rect & page.rect  # on ignore ce qui dépasse de la page
            if rect.is_empty or not _has_photo_shape(rect.width, rect.height):
                continue
            if min(rect.width, rect.height) < MIN_SIDE_POINTS or rect.width > MAX_PAGE_SHARE * page.rect.width:
                continue
            # On "photographie" cette zone de la page : on obtient l'image telle
            # qu'elle est affichée (recadrée, tournée, avec son masque rond...).
            pixmap = page.get_pixmap(clip=rect, dpi=RENDER_DPI, colorspace=fitz.csRGB, alpha=False)
            candidates.append(Candidate(_pixmap_to_image(pixmap), rect.width * rect.height))

    photo = _choose(candidates)
    if photo is None and face_detection_available():
        # Aucune image candidate : c'est peut-être un PDF scanné (une seule
        # grande image par page). On cherche alors un visage dans la page entière.
        pixmap = page.get_pixmap(dpi=RENDER_DPI, colorspace=fitz.csRGB, alpha=False)
        whole_page = _pixmap_to_image(pixmap)
        faces = detect_faces(whole_page)
        if faces:
            photo = _to_jpeg(crop_square(whole_page, faces[0], tight=True))
    return photo


# --------------------------------------------------------------- DOCX -----
_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff"}


def photo_from_docx(data: bytes) -> Optional[bytes]:
    # Un .docx est une archive ZIP ; ses images sont dans le dossier word/media/.
    candidates: List[Candidate] = []
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for name in archive.namelist():
            if not name.startswith("word/media/") or Path(name).suffix.lower() not in _IMAGE_EXTENSIONS:
                continue
            try:
                image = Image.open(io.BytesIO(archive.read(name)))
                image.load()
            except Exception:  # image illisible : on passe à la suivante
                continue
            width, height = image.size
            if min(width, height) >= MIN_SIDE_PIXELS and _has_photo_shape(width, height):
                candidates.append(Candidate(image.convert("RGB"), width * height))
    return _choose(candidates)


def prepare_photo(image_bytes: bytes) -> bytes:
    """Une image choisie par l'utilisateur -> photo carrée (JPEG), centrée sur le visage si on en trouve un.
    Lève ValueError si le fichier n'est pas une image lisible."""
    try:
        image = Image.open(io.BytesIO(image_bytes))
        image.load()
    except Exception as error:
        raise ValueError("Ce fichier n'est pas une image lisible (JPEG ou PNG attendu).") from error
    image = image.convert("RGB")
    faces = detect_faces(image)
    return _to_jpeg(crop_square(image, faces[0] if faces else None))


# ------------------------------------------------------ point d'entrée ----
def extract_photo(data: bytes, filename: str) -> Optional[bytes]:
    """La photo du candidat (JPEG carré), ou None. Ne lève jamais d'erreur :
    une photo introuvable ne doit pas empêcher de standardiser le CV."""
    extension = Path(filename).suffix.lower()
    try:
        if extension == ".pdf":
            return photo_from_pdf(data)
        if extension == ".docx":
            return photo_from_docx(data)
    except Exception as error:
        logger.warning("[%s] recherche de la photo impossible : %s", filename, error)
    return None

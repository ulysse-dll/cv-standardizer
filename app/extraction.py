"""Étape 1 du pipeline : sortir le texte brut d'un CV, SANS LLM.

    PDF  -> PyMuPDF. Si une page n'a pas de texte (PDF scanné), OCR Tesseract.
    DOCX -> python-docx, en lisant paragraphes ET tableaux dans l'ordre.

Le point d'entrée est `extract_text(data, filename)`. On travaille sur les
octets du fichier (bytes) : rien n'a besoin d'être écrit sur le disque.
"""

import io
import re
import shutil
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import fitz  # PyMuPDF
from docx import Document
from docx.table import Table

# En dessous de ce nombre de caractères, on considère qu'une page n'a pas de
# "vrai" texte et qu'il s'agit probablement d'une image scannée.
MIN_CHARS_PER_PAGE = 40
OCR_DPI = 300  # résolution de l'image envoyée à Tesseract


class ExtractionError(Exception):
    """Le fichier n'a pas pu être lu. Le message est affichable à l'utilisateur."""


class UnsupportedFormatError(ExtractionError):
    pass


class OCRUnavailableError(ExtractionError):
    pass


@dataclass
class ExtractionResult:
    text: str
    method: str  # "pdf-text", "pdf-ocr" ou "docx"
    pages: int


def clean_text(text: str) -> str:
    """Compacte le texte : chaque caractère inutile est un token de trop pour le LLM."""
    # NFKC remplace les caractères "de présentation" par leur forme simple : la
    # ligature « ﬁ » (un seul caractère dans beaucoup de PDF) redevient "fi",
    # l'espace insécable redevient une espace normale, etc.
    text = unicodedata.normalize("NFKC", text).replace("\t", " ")
    lines = [re.sub(r" {2,}", " ", line).strip() for line in text.splitlines()]
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)  # jamais plus d'une ligne vide d'affilée
    return text.strip()


# ---------------------------------------------------------------- OCR -----
def find_tesseract() -> Optional[str]:
    """Cherche le programme tesseract : à côté de Python d'abord, puis dans le PATH."""
    beside_python = Path(sys.executable).parent / "tesseract"
    if beside_python.exists():
        return str(beside_python)
    return shutil.which("tesseract")


def _usable_languages(pytesseract, wanted: str) -> str:
    """Garde, parmi les langues demandées, celles réellement installées."""
    installed = set(pytesseract.get_languages(config=""))
    usable = [lang for lang in wanted.split("+") if lang in installed]
    return "+".join(usable) or "eng"


def ocr_page(page: "fitz.Page", languages: str) -> str:
    """Transforme une page en image, puis lit l'image avec Tesseract."""
    import pytesseract
    from PIL import Image

    command = find_tesseract()
    if command is None:
        raise OCRUnavailableError(
            "Ce PDF est scanné (image sans texte) et Tesseract n'est pas installé : "
            "OCR impossible. Voir le README, section Installation."
        )
    pytesseract.pytesseract.tesseract_cmd = command

    pixmap = page.get_pixmap(dpi=OCR_DPI, colorspace=fitz.csGRAY)
    image = Image.frombytes("L", (pixmap.width, pixmap.height), pixmap.samples)
    return pytesseract.image_to_string(image, lang=_usable_languages(pytesseract, languages))


# ---------------------------------------------------------------- PDF -----
def extract_pdf(data: bytes, ocr_languages: str = "fra+eng") -> ExtractionResult:
    try:
        document = fitz.open(stream=data, filetype="pdf")
    except Exception as error:
        raise ExtractionError(f"PDF illisible : {error}") from error
    if document.needs_pass:
        raise ExtractionError("Ce PDF est protégé par un mot de passe.")

    page_texts: List[str] = []
    used_ocr = False
    for page in document:
        text = page.get_text("text")
        has_real_text = len(text.strip()) >= MIN_CHARS_PER_PAGE
        # Pas de texte mais une image : c'est une page scannée -> OCR.
        # (Une page vraiment vide n'a pas d'image : on ne lance pas l'OCR pour rien.)
        if not has_real_text and page.get_images():
            text = ocr_page(page, ocr_languages)
            used_ocr = True
        page_texts.append(text)

    return ExtractionResult(
        text=clean_text("\n\n".join(page_texts)),
        method="pdf-ocr" if used_ocr else "pdf-text",
        pages=len(document),
    )


# --------------------------------------------------------------- DOCX -----
def _cell_text(cell) -> str:
    """Texte d'une cellule, y compris un éventuel tableau imbriqué dedans."""
    parts: List[str] = []
    for block in cell.iter_inner_content():
        if isinstance(block, Table):
            parts.extend(_table_lines(block))
        else:
            parts.extend(block.text.splitlines())  # un paragraphe peut contenir des sauts de ligne
    return " / ".join(part.strip() for part in parts if part.strip())


def _table_lines(table: Table) -> List[str]:
    """Une ligne de texte par ligne du tableau, cellules séparées par " | "."""
    lines = []
    for row in table.rows:
        cells: List[str] = []
        for cell in row.cells:
            text = _cell_text(cell)
            # Une cellule fusionnée apparaît plusieurs fois de suite : on dédoublonne.
            if text and (not cells or cells[-1] != text):
                cells.append(text)
        if cells:
            lines.append(" | ".join(cells))
    return lines


def extract_docx(data: bytes) -> ExtractionResult:
    try:
        document = Document(io.BytesIO(data))
    except Exception as error:
        raise ExtractionError(f"DOCX illisible : {error}") from error

    lines: List[str] = []
    # Les coordonnées sont parfois rangées dans l'en-tête de page.
    for section in document.sections:
        lines.extend(paragraph.text for paragraph in section.header.paragraphs)
    # Corps du document : paragraphes et tableaux, dans l'ordre où ils apparaissent.
    for block in document.iter_inner_content():
        if isinstance(block, Table):
            lines.extend(_table_lines(block))
        else:
            lines.append(block.text)
    text = clean_text("\n".join(lines))

    if len(text) < MIN_CHARS_PER_PAGE:
        # Plan B : certains CV "design" mettent tout dans des zones de texte, que
        # python-docx ne parcourt pas. On ramasse alors tous les morceaux de texte
        # bruts du fichier (balises <w:t>), sans se soucier de la mise en page.
        raw = [node.text for node in document.element.body.iter() if node.tag.endswith("}t") and node.text]
        text = clean_text("\n".join(raw))

    return ExtractionResult(text=text, method="docx", pages=len(document.sections))


# ------------------------------------------------------ point d'entrée ----
def extract_text(data: bytes, filename: str, ocr_languages: str = "fra+eng") -> ExtractionResult:
    """Choisit la bonne méthode selon l'extension du fichier."""
    extension = Path(filename).suffix.lower()
    if extension == ".pdf":
        result = extract_pdf(data, ocr_languages)
    elif extension == ".docx":
        result = extract_docx(data)
    else:
        raise UnsupportedFormatError(
            f"Format « {extension or filename} » non pris en charge : envoie un PDF ou un DOCX."
        )
    if not result.text:
        raise ExtractionError("Aucun texte trouvé dans ce fichier.")
    return result

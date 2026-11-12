"""Tests de l'extraction de texte sur les 4 faux CV du dossier samples/."""

import pytest

from app import ocr
from app.extraction import (
    ExtractionError,
    OCRUnavailableError,
    UnsupportedFormatError,
    clean_text,
    extract_text,
)

needs_ocr = pytest.mark.skipif(ocr.ocr_engine() is None, reason="Aucun OCR (ni Tesseract, ni macOS)")


def _extract(samples_dir, filename):
    return extract_text((samples_dir / filename).read_bytes(), filename)


def test_pdf_one_column(samples_dir):
    result = _extract(samples_dir, "cv_classique_fr.pdf")
    assert result.method == "pdf-text"
    assert result.pages == 1
    for expected in ("Camille Lefèvre", "camille.lefevre@example.com", "Novalys Logistique", "Master Informatique"):
        assert expected in result.text


def test_pdf_ligatures_are_expanded(samples_dir):
    # Dans le PDF, "Profil" est écrit avec la ligature « ﬁ » (1 seul caractère).
    result = _extract(samples_dir, "cv_classique_fr.pdf")
    assert "Profil" in result.text
    assert "ﬁ" not in result.text


def test_pdf_two_columns_keeps_each_column_together(samples_dir):
    result = _extract(samples_dir, "cv_two_columns_en.pdf")
    assert result.method == "pdf-text"
    for expected in ("Daniel Okafor", "daniel.okafor@example.org", "Brightcart Ltd", "MSc Data Science"):
        assert expected in result.text
    # La colonne de gauche (Skills) ne doit pas être mélangée à celle de droite :
    # les deux lignes du poste restent l'une sous l'autre.
    lines = result.text.splitlines()
    position = lines.index("Senior Data Analyst, Brightcart Ltd")
    assert lines[position + 1].startswith("Jan 2022")


def test_pdf_with_photo_and_logo_still_gives_its_text(samples_dir):
    # Une photo et un logo sur la page ne doivent pas déclencher l'OCR : le texte est là.
    result = _extract(samples_dir, "cv_photo_fr.pdf")
    assert result.method == "pdf-text"
    for expected in ("Léa Marchand", "lea.marchand@example.org", "Studio Garonne", "Master Design d'interaction"):
        assert expected in result.text


def test_docx_reads_tables(samples_dir):
    result = _extract(samples_dir, "cv_tableaux_fr.docx")
    assert result.method == "docx"
    for expected in ("Inès Benali", "ines.benali@example.net", "Maison Océane", "Audencia Business School"):
        assert expected in result.text
    # Une ligne de tableau = une ligne de texte, cellules séparées par " | ".
    assert "2017 – 2020 | Chargée d'acquisition / VéloVille (mobilité), Rennes | " in result.text


@needs_ocr
def test_scanned_pdf_uses_ocr(samples_dir):
    result = _extract(samples_dir, "cv_scanne_fr.pdf")
    assert result.method == "pdf-ocr"
    text = result.text.lower()
    for expected in ("thomas girard", "comptable", "bordeaux", "sage 100", "thomas.girard@example.com"):
        assert expected in text


def test_scanned_pdf_without_any_ocr_gives_clear_error(samples_dir, monkeypatch):
    monkeypatch.setattr(ocr, "ocr_engine", lambda: None)
    with pytest.raises(OCRUnavailableError):
        _extract(samples_dir, "cv_scanne_fr.pdf")


def test_tesseract_is_preferred_when_installed(monkeypatch):
    monkeypatch.setattr(ocr, "find_tesseract", lambda: "/usr/local/bin/tesseract")
    assert ocr.ocr_engine() == "tesseract"
    # Sans Tesseract, on se rabat sur l'OCR de macOS s'il est là.
    monkeypatch.setattr(ocr, "find_tesseract", lambda: None)
    monkeypatch.setattr(ocr, "vision_available", lambda: True)
    assert ocr.ocr_engine() == "apple-vision"


def test_unsupported_format_is_rejected():
    with pytest.raises(UnsupportedFormatError):
        extract_text(b"bonjour", "cv.txt")


def test_corrupted_files_are_rejected():
    with pytest.raises(ExtractionError):
        extract_text(b"ceci n'est pas un pdf", "cv.pdf")
    with pytest.raises(ExtractionError):
        extract_text(b"ceci n'est pas un docx", "cv.docx")


def test_extension_case_does_not_matter(samples_dir):
    data = (samples_dir / "cv_classique_fr.pdf").read_bytes()
    assert extract_text(data, "CV.PDF").method == "pdf-text"


def test_clean_text_compacts_whitespace():
    raw = "  Jean   Dupont \t\n\n\n\n\nDéveloppeur Python  \n"
    assert clean_text(raw) == "Jean Dupont\n\nDéveloppeur Python"

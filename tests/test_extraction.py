"""Tests de l'extraction de texte sur les 4 faux CV du dossier samples/."""

import pytest

from app import extraction
from app.extraction import (
    ExtractionError,
    OCRUnavailableError,
    UnsupportedFormatError,
    clean_text,
    extract_text,
    find_tesseract,
)

needs_tesseract = pytest.mark.skipif(find_tesseract() is None, reason="Tesseract n'est pas installé")


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


def test_docx_reads_tables(samples_dir):
    result = _extract(samples_dir, "cv_tableaux_fr.docx")
    assert result.method == "docx"
    for expected in ("Inès Benali", "ines.benali@example.net", "Maison Océane", "Audencia Business School"):
        assert expected in result.text
    # Une ligne de tableau = une ligne de texte, cellules séparées par " | ".
    assert "2017 – 2020 | Chargée d'acquisition / VéloVille (mobilité), Rennes | " in result.text


@needs_tesseract
def test_scanned_pdf_uses_ocr(samples_dir):
    result = _extract(samples_dir, "cv_scanne_fr.pdf")
    assert result.method == "pdf-ocr"
    text = result.text.lower()
    for expected in ("thomas girard", "comptable", "bordeaux", "sage 100"):
        assert expected in text


def test_scanned_pdf_without_tesseract_gives_clear_error(samples_dir, monkeypatch):
    monkeypatch.setattr(extraction, "find_tesseract", lambda: None)
    with pytest.raises(OCRUnavailableError):
        _extract(samples_dir, "cv_scanne_fr.pdf")


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

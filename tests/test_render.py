"""Tests de la génération du CV standardisé (HTML, et PDF si WeasyPrint fonctionne)."""

import fitz  # PyMuPDF, pour relire le PDF produit
import pytest

from app import render
from app.render import PDFUnavailableError, detect_language, pdf_available, period, render_html, render_pdf
from app.schema import CV
from tests.test_schema import VALID_CV


def test_html_contains_the_cv_content():
    html = render_html(CV.model_validate(VALID_CV))
    for expected in ("Camille Lefèvre", "Novalys", "Master Informatique", "FastAPI", "Anglais (C1)"):
        assert expected in html
    assert "Expériences professionnelles" in html  # CV français -> rubriques en français
    assert "03/2021 – aujourd&#39;hui" in html  # "present" est affiché dans la langue du CV


def test_english_cv_gets_english_headings():
    cv = CV.model_validate(
        {
            "identity": {"full_name": "Daniel Okafor"},
            "summary": "Data analyst with 5 years of experience in the retail sector.",
            "experiences": [{"job_title": "Data Analyst", "highlights": ["Built the weekly dashboard for the team"]}],
        }
    )
    assert detect_language(cv) == "en"
    assert "Experience" in render_html(cv)


def test_education_shows_school_and_city():
    cv = CV.model_validate(
        {
            "identity": {"full_name": "Inès Benali"},
            "education": [{"degree": "Master Marketing digital", "school": "Audencia Business School", "location": "Nantes"}],
        }
    )
    assert "Audencia Business School, Nantes" in render_html(cv)


def test_empty_sections_are_hidden():
    html = render_html(CV.model_validate({"identity": {"full_name": "Jean Dupont"}}))
    assert "Jean Dupont" in html
    assert "<h2>" not in html  # aucune rubrique vide


def test_html_in_the_cv_is_neutralized():
    # Un CV piégé ne doit pas pouvoir injecter de script dans l'aperçu.
    cv = CV.model_validate({"identity": {"full_name": "<script>alert(1)</script>"}})
    html = render_html(cv)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_period_formats():
    assert period("2019", "2021") == "2019 – 2021"
    assert period("2019", None) == "2019"
    assert period(None, None) == ""
    assert period("01/2022", "present", "aujourd'hui") == "01/2022 – aujourd'hui"


@pytest.mark.real_pdf
@pytest.mark.skipif(not pdf_available(), reason="Aucun moteur PDF (ni WeasyPrint, ni navigateur)")
def test_pdf_is_generated():
    pdf = render_pdf(render_html(CV.model_validate(VALID_CV)))
    assert pdf.startswith(b"%PDF")
    # Le PDF contient du vrai texte (pas une image) : on le relit avec PyMuPDF.
    document = fitz.open(stream=pdf, filetype="pdf")
    assert len(document) == 1
    assert "Camille Lefèvre" in document[0].get_text()


@pytest.mark.real_pdf
@pytest.mark.skipif(render.find_browser() is None, reason="Aucun navigateur de la famille Chrome")
def test_pdf_falls_back_to_the_browser_without_weasyprint(monkeypatch):
    monkeypatch.setattr(render, "weasyprint_available", lambda: False)
    assert render.pdf_engine() == "navigateur"
    assert render_pdf("<html><body><p>Bonjour</p></body></html>").startswith(b"%PDF")


def test_no_pdf_engine_gives_a_clear_error(monkeypatch):
    monkeypatch.setattr(render, "pdf_engine", lambda: None)
    with pytest.raises(PDFUnavailableError, match="Génération PDF indisponible"):
        render_pdf("<html></html>")

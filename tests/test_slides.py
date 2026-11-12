"""Tests de la diapositive PowerPoint : on la fabrique, puis on la relit avec python-pptx."""

import io

from pptx import Presentation
from pptx.util import Inches

from app.schema import CV
from app.slides import MAIN_TEXT_WIDTH, Line, estimated_height, fit_main, render_pptx
from tests.test_schema import VALID_CV


def _slide_text(pptx: bytes) -> str:
    """Tout le texte de la (seule) diapo du fichier."""
    presentation = Presentation(io.BytesIO(pptx))
    assert len(presentation.slides) == 1
    shapes = presentation.slides[0].shapes
    return "\n".join(shape.text_frame.text for shape in shapes if shape.has_text_frame)


def test_slide_contains_the_cv_content():
    pptx, notes = render_pptx(CV.model_validate(VALID_CV))
    text = _slide_text(pptx)
    for expected in ("Camille Lefèvre", "Développeuse Python", "Novalys", "03/2021 – aujourd'hui",
                     "Master Informatique", "FastAPI", "Anglais — C1", "AWS Cloud Practitioner"):
        assert expected in text
    assert "EXPÉRIENCES PROFESSIONNELLES" in text  # CV français -> rubriques en français
    assert notes == []  # rien n'a été raccourci


def test_slide_is_one_16_9_page():
    pptx, _ = render_pptx(CV.model_validate(VALID_CV))
    presentation = Presentation(io.BytesIO(pptx))
    assert presentation.slide_width == Inches(13.333)
    assert presentation.slide_height == Inches(7.5)


def test_english_cv_gets_english_headings():
    cv = CV.model_validate(
        {
            "identity": {"full_name": "Daniel Okafor"},
            "summary": "Data analyst with 5 years of experience in the retail sector.",
            "experiences": [{"job_title": "Data Analyst", "highlights": ["Built the weekly dashboard for the team"]}],
        }
    )
    assert "EXPERIENCE" in _slide_text(render_pptx(cv)[0])


def test_nearly_empty_cv_still_gives_a_slide():
    pptx, notes = render_pptx(CV.model_validate({"identity": {"full_name": "Jean Dupont"}}))
    assert "Jean Dupont" in _slide_text(pptx)
    assert notes == []


def _long_cv(jobs: int, highlights: int) -> CV:
    job = {
        "job_title": "Responsable de projets informatiques", "company": "Société Exemple", "start": "2020", "end": "2021",
        "highlights": ["Pilotage d'un projet de migration de données avec plusieurs équipes et prestataires."] * highlights,
    }
    return CV.model_validate({"identity": {"full_name": "Jean Dupont"}, "experiences": [job] * jobs})


def test_medium_cv_shrinks_the_font_but_keeps_everything():
    labels = {"summary": "Profil", "experiences": "Expériences", "education": "Formation",
              "certifications": "Certifications", "present": "aujourd'hui"}
    fit = fit_main(_long_cv(jobs=7, highlights=4), labels)
    assert fit.size < 12
    assert fit.dropped == []
    assert sum(line.runs[0][0].startswith("•") for line in fit.lines) == 28  # 7 postes x 4 réalisations


def test_very_long_cv_drops_highlights_and_says_so():
    cv = _long_cv(jobs=9, highlights=6)
    pptx, notes = render_pptx(cv)
    assert len(notes) == 1 and "réalisations limitées" in notes[0]
    text = _slide_text(pptx)
    assert text.count("Responsable de projets informatiques") == 9  # tous les postes restent
    assert text.count("•") < 9 * 6


def test_estimated_height_grows_with_text_and_font_size():
    short = [Line([("Bonjour", False, None)])]
    long = [Line([("Bonjour " * 60, False, None)])]
    assert estimated_height(long, 10, MAIN_TEXT_WIDTH) > estimated_height(short, 10, MAIN_TEXT_WIDTH)
    assert estimated_height(long, 12, MAIN_TEXT_WIDTH) > estimated_height(long, 9, MAIN_TEXT_WIDTH)

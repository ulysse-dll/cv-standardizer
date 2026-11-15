"""Tests de la fiche PowerPoint : on la fabrique, puis on la relit avec python-pptx."""

import io

from PIL import Image
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pptx.util import Inches

from app.render import LABELS
from app.schema import CV
from app.slides import (
    CONTENT_WIDTH, SIDE_WIDTH, Line, chips_height, estimated_height, initials, new_presentation, palette_from_theme,
    plan_main, plan_side, render_deck, render_pptx, round_photo, slide_texts,
)
from app.theme import Theme
from samples.generate_samples import _png, draw_portrait
from tests.test_schema import VALID_CV

FRENCH = LABELS["fr"]


def _text(pptx: bytes) -> str:
    texts = slide_texts(pptx)
    assert len(texts) == 1
    return texts[0]


def _pictures(pptx: bytes) -> list:
    shapes = Presentation(io.BytesIO(pptx)).slides[0].shapes
    return [shape for shape in shapes if shape.shape_type == MSO_SHAPE_TYPE.PICTURE]


def test_slide_contains_the_cv_content():
    pptx, notes = render_pptx(CV.model_validate(VALID_CV))
    text = _text(pptx)
    for expected in ("Camille Lefèvre", "Développeuse back-end", "Développeuse Python\nNovalys, Lyon",
                     "03/2021 – aujourd'hui", "•  API REST", "Master Informatique", "Python", "FastAPI",
                     "Anglais  C1", "AWS Cloud Practitioner", "camille.lefevre@example.com"):
        assert expected in text
    for heading in ("COORDONNÉES", "LANGUES", "FORMATION", "COMPÉTENCES", "EXPÉRIENCES PROFESSIONNELLES"):
        assert heading in text  # CV français -> rubriques en français
    assert "Profil candidat · Confidentiel" in text  # le pied de page
    assert notes == []  # rien n'a été raccourci


def test_slide_is_one_16_9_page():
    pptx, _ = render_pptx(CV.model_validate(VALID_CV))
    presentation = Presentation(io.BytesIO(pptx))
    assert presentation.slide_width == Inches(13.333)
    assert presentation.slide_height == Inches(7.5)


def _shapes(pptx: bytes):
    return list(Presentation(io.BytesIO(pptx)).slides[0].shapes)


def test_each_skill_is_a_rounded_chip():
    pptx, _ = render_pptx(CV.model_validate(VALID_CV))
    chips = [shape for shape in _shapes(pptx) if shape.shape_type == MSO_SHAPE_TYPE.AUTO_SHAPE
             and shape.has_text_frame and shape.text_frame.text in ("Python", "FastAPI")]
    assert len(chips) == 2
    assert chips[0].top == chips[1].top and chips[0].left < chips[1].left  # côte à côte, dans l'ordre


def test_timeline_puts_dates_left_of_each_job_and_jobs_in_order():
    cv = CV.model_validate({**VALID_CV, "experiences": VALID_CV["experiences"] + [
        {"job_title": "Stagiaire", "company": "Mairie", "start": "2018", "end": "2019", "highlights": ["Outil interne"]}]})
    shapes = _shapes(render_pptx(cv)[0])
    find = lambda start: next(s for s in shapes if s.has_text_frame and s.text_frame.text.startswith(start))
    first_dates, first_job = find("03/2021"), find("Développeuse Python")
    second_dates, second_job = find("2018 – 2019"), find("Stagiaire")
    assert first_dates.top == first_job.top and first_dates.left < first_job.left  # la date sur la même ligne, à gauche
    assert second_job.top > first_job.top and second_dates.top == second_job.top  # le poste suivant en dessous
    assert first_job.left > Inches(SIDE_WIDTH)  # dans la partie claire, pas dans la colonne sombre


def test_contact_is_in_the_dark_side_column():
    shapes = _shapes(render_pptx(CV.model_validate(VALID_CV))[0])
    side = next(s for s in shapes if s.has_text_frame and "camille.lefevre@example.com" in s.text_frame.text)
    assert side.left + side.width <= Inches(SIDE_WIDTH)
    assert "COORDONNÉES" in side.text_frame.text and "FORMATION" in side.text_frame.text


def test_without_photo_the_slide_shows_the_initials():
    pptx, _ = render_pptx(CV.model_validate(VALID_CV))
    assert _pictures(pptx) == []
    assert "CL" in _text(pptx).split("\n")  # le rond des initiales de Camille Lefèvre


def test_with_a_photo_the_slide_contains_the_picture_in_the_top_left_corner():
    pptx, _ = render_pptx(CV.model_validate(VALID_CV), _png(draw_portrait(300)))
    pictures = _pictures(pptx)
    assert len(pictures) == 1
    picture = pictures[0]
    assert picture.width == picture.height  # un rond, pas un ovale
    assert picture.left + picture.width < Inches(SIDE_WIDTH) and picture.top < Inches(1)  # en haut de la colonne
    assert "CL" not in _text(pptx).split("\n")  # plus d'initiales : la photo les remplace


def test_unreadable_photo_falls_back_to_the_initials():
    pptx, _ = render_pptx(CV.model_validate(VALID_CV), b"ceci n'est pas une image")
    assert _pictures(pptx) == []
    assert "CL" in _text(pptx).split("\n")


def test_round_photo_has_transparent_corners():
    rounded = Image.open(io.BytesIO(round_photo(_png(draw_portrait(200)))))
    assert rounded.mode == "RGBA" and rounded.width == rounded.height
    assert rounded.getpixel((2, 2))[3] == 0  # coin : transparent
    assert rounded.getpixel((rounded.width // 2, rounded.height // 2))[3] == 255  # centre : opaque


def test_initials():
    assert initials("Camille Lefèvre") == "CL"
    assert initials("Jean-Pierre de La Tour") == "JT"  # premier et dernier mot
    assert initials("Madonna") == "M"
    assert initials("") == "?"


def test_english_cv_gets_english_headings_and_footer():
    cv = CV.model_validate(
        {
            "identity": {"full_name": "Daniel Okafor", "email": "daniel@example.org"},
            "summary": "Data analyst with 5 years of experience in the retail sector.",
            "experiences": [{"job_title": "Data Analyst", "highlights": ["Built the weekly dashboard for the team"]}],
        }
    )
    text = _text(render_pptx(cv)[0])
    assert "EXPERIENCE" in text and "CONTACT" in text and "Candidate profile · Confidential" in text


def test_nearly_empty_cv_still_gives_a_slide():
    pptx, notes = render_pptx(CV.model_validate({"identity": {"full_name": "Jean Dupont"}}))
    assert "Jean Dupont" in _text(pptx)
    assert notes == []


def _long_cv(jobs: int, highlights: int) -> CV:
    job = {
        "job_title": "Responsable de projets informatiques", "company": "Société Exemple", "start": "2020", "end": "2021",
        "highlights": ["Pilotage d'un projet de migration de données avec plusieurs équipes et prestataires."] * highlights,
    }
    return CV.model_validate({"identity": {"full_name": "Jean Dupont"}, "experiences": [job] * jobs})


def test_medium_cv_shrinks_the_font_but_keeps_everything():
    plan = plan_main(_long_cv(jobs=4, highlights=4))
    assert plan.size < 11.5
    assert plan.max_highlights == 4 and plan.dropped == []


def test_very_long_cv_drops_highlights_and_says_so():
    cv = _long_cv(jobs=9, highlights=6)
    pptx, notes = render_pptx(cv)
    assert any("réalisations limitées" in note for note in notes)
    text = _text(pptx)
    assert text.count("Responsable de projets informatiques") == 9  # tous les postes restent
    assert text.count("•") < 9 * 6


def test_skills_are_reduced_before_the_last_highlights():
    cv = CV.model_validate({
        "identity": {"full_name": "Jean Dupont"},
        "skills": [f"Compétence numéro {n}" for n in range(14)],
        "experiences": [{"job_title": f"Poste {n}", "company": "Société", "start": "2020", "end": "2021",
                         "highlights": ["Une réalisation assez longue pour occuper une ligne entière de la fiche."] * 3}
                        for n in range(6)],
    })
    plan = plan_main(cv)
    assert plan.max_highlights >= 1  # on garde au moins une réalisation par poste...
    assert plan.max_skills < 14  # ...quitte à montrer moins de compétences
    assert any("compétences limitées" in note for note in plan.dropped)


def test_side_column_gives_up_the_interests_when_it_is_too_long():
    cv = CV.model_validate({
        "identity": {"full_name": "Jean Dupont", "email": "jean@example.com", "phone": "01 02 03 04 05", "location": "Paris"},
        "languages": [{"name": f"Langue {n}", "level": "courant"} for n in range(6)],
        "education": [{"degree": f"Diplôme supérieur de gestion numéro {n}", "school": "École Exemple de Management", "start": "2000", "end": "2002"} for n in range(6)],
        "certifications": [{"name": f"Certification professionnelle numéro {n}", "issuer": "Organisme", "date": "2020"} for n in range(5)],
        "interests": ["Cyclisme", "Photographie"],
    })
    plan = plan_side(cv, FRENCH, palette_from_theme(Theme()))
    assert plan.size < 10.5
    assert any("centres d'intérêt" in note or "trop longue" in note for note in plan.dropped)


def test_chips_wrap_on_several_rows():
    one_row = chips_height(["SQL", "Git"], 10, 8)
    three_rows = chips_height(["Une compétence au nom très long"] * 6, 10, 8)
    assert three_rows > 2 * one_row
    assert chips_height([], 10, 8) == 0


def test_estimated_height_grows_with_text_and_font_size():
    short = [Line([("Bonjour", False, None)])]
    long = [Line([("Bonjour " * 60, False, None)])]
    assert estimated_height(long, 10, CONTENT_WIDTH) > estimated_height(short, 10, CONTENT_WIDTH)
    assert estimated_height(long, 12, CONTENT_WIDTH) > estimated_height(long, 9, CONTENT_WIDTH)


def test_theme_accent_gives_a_darker_side_column_and_a_pale_chip():
    palette = palette_from_theme(Theme(accent="#1F4E79"))
    assert sum(palette.side) < sum(palette.accent) < sum(palette.chip)  # sombre < couleur < très clair


# ------------------------------------------------ lot et pied de page -----
def test_deck_numbers_its_slides():
    first = CV.model_validate({"identity": {"full_name": "Alice Martin"}})
    second = CV.model_validate({"identity": {"full_name": "Bob Durand"}})
    texts = slide_texts(render_deck([(first, None), (second, None)]))
    assert "Alice Martin" in texts[0] and "1 / 2" in texts[0]
    assert "Bob Durand" in texts[1] and "2 / 2" in texts[1]


def test_footer_text_can_be_changed():
    pptx, _ = render_pptx(CV.model_validate(VALID_CV), None, Theme(footer="Cabinet Exemple · Usage interne"))
    assert "Cabinet Exemple · Usage interne" in _text(pptx)
    assert "Confidentiel" not in _text(pptx)


# ------------------------------------------------ modèle d'entreprise -----
def _company_template() -> bytes:
    """Un faux modèle d'entreprise : format 4:3, avec une diapo d'exemple à l'intérieur."""
    template = Presentation()  # le modèle par défaut de python-pptx est en 4:3
    example = template.slides.add_slide(template.slide_layouts[0])
    example.shapes.title.text = "Diapo d'exemple du modèle"
    buffer = io.BytesIO()
    template.save(buffer)
    return buffer.getvalue()


def test_company_template_is_used_instead_of_our_own_design():
    theme = Theme(template=_company_template())
    pptx, _ = render_pptx(CV.model_validate(VALID_CV), None, theme)
    presentation = Presentation(io.BytesIO(pptx))
    assert presentation.slide_width == Inches(10)  # la taille du modèle (4:3) est conservée
    assert len(presentation.slides) == 1  # la diapo d'exemple du modèle a été retirée
    text = _text(pptx)
    assert "Camille Lefèvre" in text and "Diapo d'exemple" not in text
    assert "Confidentiel" not in text  # le pied de page est celui du modèle, pas le nôtre
    assert len(presentation.slides[0].placeholders) == 0  # pas de zone « Cliquez pour ajouter un titre »
    # Tout reste dans la diapo, bien qu'elle soit moins large que la nôtre.
    for shape in presentation.slides[0].shapes:
        assert shape.left >= 0 and shape.left + shape.width <= presentation.slide_width + 1


def test_new_presentation_without_template_is_ours():
    assert new_presentation().slide_width == Inches(13.333)

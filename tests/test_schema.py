"""Tests du schéma Pydantic : ce qu'on accepte, ce qu'on refuse, ce qu'on nettoie."""

import pytest
from pydantic import ValidationError

from app.schema import CV, cv_json_schema, normalize_date

VALID_CV = {
    "identity": {
        "full_name": "Camille Lefèvre",
        "email": "camille.lefevre@example.com",
        "phone": "01 23 45 67 89",
        "location": "Lyon",
        "links": ["linkedin.com/in/camille-lefevre-faux"],
    },
    "title": "Développeuse back-end",
    "summary": "Six ans d'expérience en Python.",
    "experiences": [
        {
            "job_title": "Développeuse Python",
            "company": "Novalys",
            "location": "Lyon",
            "start": "03/2021",
            "end": "present",
            "highlights": ["API REST", "Migration PostgreSQL"],
        }
    ],
    "education": [{"degree": "Master Informatique", "school": "Université Lyon 1", "start": "2016", "end": "2018"}],
    "skills": ["Python", "FastAPI"],
    "languages": [{"name": "Anglais", "level": "C1"}],
    "certifications": [{"name": "AWS Cloud Practitioner", "issuer": "AWS", "date": "2022"}],
}


def test_valid_cv_is_accepted():
    cv = CV.model_validate(VALID_CV)
    assert cv.identity.full_name == "Camille Lefèvre"
    assert cv.experiences[0].highlights == ["API REST", "Migration PostgreSQL"]
    assert cv.languages[0].level == "C1"


def test_minimal_cv_only_needs_a_name():
    cv = CV.model_validate({"identity": {"full_name": "Jean Dupont"}})
    assert cv.title is None
    assert cv.experiences == []
    assert cv.identity.links == []


def test_missing_name_is_rejected():
    with pytest.raises(ValidationError):
        CV.model_validate({"identity": {"email": "x@example.com"}})


@pytest.mark.parametrize("fake_empty", ["", "   ", "N/A", "null", "Unknown"])
def test_empty_name_is_rejected(fake_empty):
    with pytest.raises(ValidationError):
        CV.model_validate({"identity": {"full_name": fake_empty}})


def test_wrong_type_is_rejected():
    # experiences doit être une liste d'objets, pas un texte
    with pytest.raises(ValidationError):
        CV.model_validate({"identity": {"full_name": "Jean Dupont"}, "experiences": "dix ans chez Acme"})


def test_experience_without_job_title_is_rejected():
    with pytest.raises(ValidationError):
        CV.model_validate({"identity": {"full_name": "Jean Dupont"}, "experiences": [{"company": "Acme"}]})


def test_values_are_cleaned():
    cv = CV.model_validate(
        {
            "identity": {"full_name": "  Jean \n Dupont ", "email": "N/A", "phone": "", "links": None},
            "title": "null",
            "skills": ["Python", "", "  SQL  ", "n/a"],
            "languages": None,
        }
    )
    assert cv.identity.full_name == "Jean Dupont"
    assert cv.identity.email is None
    assert cv.identity.phone is None
    assert cv.identity.links == []
    assert cv.title is None
    assert cv.skills == ["Python", "SQL"]
    assert cv.languages == []


@pytest.mark.parametrize(
    "written, expected",
    [
        ("Mars 2021", "03/2021"),
        ("Sept. 2018", "09/2018"),
        ("février 2018", "02/2018"),
        ("Jan 2022", "01/2022"),
        ("depuis janvier 2019", "01/2019"),
        ("3/2021", "03/2021"),
        ("2021-03", "03/2021"),
        ("2018", "2018"),
        ("aujourd'hui", "present"),
        ("Present", "present"),
        ("En cours", "present"),
        ("été 2019", "été 2019"),  # non reconnue : on n'y touche pas
    ],
)
def test_dates_are_normalized(written, expected):
    assert normalize_date(written) == expected


def test_dates_are_normalized_inside_a_cv():
    cv = CV.model_validate(
        {
            "identity": {"full_name": "Jean Dupont"},
            "experiences": [{"job_title": "Dev", "start": "Mars 2021", "end": "aujourd'hui"}],
            "certifications": [{"name": "AWS", "date": "juin 2022"}],
        }
    )
    assert (cv.experiences[0].start, cv.experiences[0].end) == ("03/2021", "present")
    assert cv.certifications[0].date == "06/2022"


def test_invalid_json_text_is_rejected():
    with pytest.raises(ValidationError):
        CV.model_validate_json('{"identity": {"full_name": "Jean"')  # JSON coupé


def test_json_round_trip():
    cv = CV.model_validate(VALID_CV)
    assert CV.model_validate_json(cv.model_dump_json()) == cv


def test_llm_schema_requires_every_field():
    schema = cv_json_schema()
    # Le champ "title" du CV ne doit pas disparaître pendant le nettoyage du schéma.
    assert set(schema["required"]) == set(CV.model_fields)
    assert set(schema["$defs"]["Experience"]["required"]) == {
        "job_title", "company", "location", "start", "end", "highlights",
    }


def test_empty_entries_added_by_the_model_are_dropped():
    # Vu avec gemma3:4b : une expérience entièrement vide en fin de liste.
    data = {
        **VALID_CV,
        "experiences": VALID_CV["experiences"]
        + [{"job_title": None, "company": "null", "location": None, "start": None, "end": None, "highlights": []}],
    }
    assert len(CV.model_validate(data).experiences) == 1


def test_entry_with_content_but_no_title_is_still_refused():
    # Une entrée qui contient de l'information n'est pas jetée en silence :
    # la validation échoue, ce qui déclenche le retry.
    data = {**VALID_CV, "experiences": [{"job_title": None, "company": "Novalys"}]}
    with pytest.raises(ValidationError):
        CV.model_validate(data)


def test_name_in_capitals_is_rewritten():
    assert CV.model_validate({"identity": {"full_name": "THOMAS GIRARD"}}).identity.full_name == "Thomas Girard"
    assert CV.model_validate({"identity": {"full_name": "JEAN-PIERRE D'ARCY"}}).identity.full_name == "Jean-Pierre D'Arcy"
    # Un nom déjà en minuscules et majuscules n'est pas touché.
    assert CV.model_validate({"identity": {"full_name": "Inès de la Tour"}}).identity.full_name == "Inès de la Tour"

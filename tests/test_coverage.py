"""Tests des filets de sécurité : lignes oubliées et valeurs inventées par le LLM."""

from app.coverage import find_missing_lines, find_unsupported_values
from app.schema import CV

SOURCE = """Daniel Okafor
Data Analyst
Experience
Senior Data Analyst, Brightcart Ltd
Jan 2022 – Present | Manchester
Education
MSc Data Science
University of Leeds, 2018 – 2019
BSc Mathematics
University of Sheffield, 2015 – 2018"""

COMPLETE = {
    "identity": {"full_name": "Daniel Okafor", "location": "Manchester"},
    "title": "Data Analyst",
    "experiences": [{"job_title": "Senior Data Analyst", "company": "Brightcart Ltd", "start": "Jan 2022", "end": "Present"}],
    "education": [
        {"degree": "MSc Data Science", "school": "University of Leeds", "start": "2018", "end": "2019"},
        {"degree": "BSc Mathematics", "school": "University of Sheffield", "start": "2015", "end": "2018"},
    ],
}


def test_complete_cv_raises_no_alert():
    assert find_missing_lines(SOURCE, CV.model_validate(COMPLETE)) == []


def test_forgotten_degree_is_reported():
    incomplete = {**COMPLETE, "education": COMPLETE["education"][:1]}  # le second diplôme a disparu
    assert find_missing_lines(SOURCE, CV.model_validate(incomplete)) == ["BSc Mathematics"]


def test_section_headings_and_rewritten_dates_are_not_reported():
    # "Experience" / "Education" ne sont jamais recopiés, et "Jan 2022 – Present"
    # devient "01/2022 – present" : aucune de ces lignes ne doit déclencher d'alerte.
    source = "Expériences professionnelles\nPériode | Poste et entreprise | Réalisations\nMars 2021 – aujourd'hui"
    cv = CV.model_validate({"identity": {"full_name": "Jean Dupont"}})
    assert find_missing_lines(source, cv) == []


def test_faithful_cv_has_no_unsupported_value():
    # Les dates réécrites ("Jan 2022" -> "01/2022") ne comptent pas comme inventées.
    assert find_unsupported_values(SOURCE, CV.model_validate(COMPLETE)) == []


def test_invented_value_is_reported():
    invented = {**COMPLETE, "certifications": [{"name": "AWS Solutions Architect", "issuer": "Amazon"}]}
    assert find_unsupported_values(SOURCE, CV.model_validate(invented)) == ["AWS Solutions Architect", "Amazon"]


def test_case_and_accents_do_not_count_as_invented():
    # Un scan donne souvent "THOMAS GIRARD" ou perd un accent : ce n'est pas une invention.
    source = "THOMAS GIRARD\nEtablissement des bilans"
    cv = CV.model_validate({"identity": {"full_name": "Thomas Girard"}, "skills": ["Établissement des bilans"]})
    assert find_unsupported_values(source, cv) == []


def test_long_lines_are_shortened_and_list_is_limited():
    source = "\n".join(f"ligne oubliée numéro {n} " + "blabla " * 20 for n in range(10))
    missing = find_missing_lines(source, CV.model_validate({"identity": {"full_name": "Jean Dupont"}}))
    assert len(missing) == 5
    assert all(len(line) <= 80 for line in missing)

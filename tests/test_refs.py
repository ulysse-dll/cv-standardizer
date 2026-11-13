"""Tests du mode « références » : le modèle désigne les lignes, Python recopie."""

import json

from app import refs
from app.pipeline import structure_cv
from app.prompts import SYSTEM_PROMPT, system_prompt
from app.schema import cv_json_schema
from app.timing import StepTimer
from tests.test_pipeline import FakeProvider

TEXT = """Camille Lefèvre
Profil
Développeuse back-end avec six ans d'expérience dans la conception d'API et de pipelines
de données. À l'aise en équipe agile.
Développeuse Python senior — Novalys Logistique, Lyon
• Conception d'une API REST de suivi de colis.
• Réduction de 40 % du temps de réponse grâce à la mise
en cache Redis.
2020 – 2024 | Cheffe de projet | Refonte du site. Budget annuel de 600 k€."""


def test_number_lines_strips_bullets_merges_wrapped_lines_and_splits_cells():
    numbered, segments = refs.number_lines(TEXT)
    assert segments[2] == "Développeuse back-end avec six ans d'expérience dans la conception d'API et de pipelines de données. À l'aise en équipe agile."
    assert segments[4] == "Conception d'une API REST de suivi de colis."
    assert segments[5] == "Réduction de 40 % du temps de réponse grâce à la mise en cache Redis."
    assert segments[6:] == ["2020 – 2024", "Cheffe de projet", "Refonte du site. Budget annuel de 600 k€."]
    assert numbered.splitlines()[0] == "1| Camille Lefèvre" and numbered.splitlines()[4].startswith("5| Conception")


def test_refs_schema_replaces_the_two_text_fields_by_numbers():
    schema = refs.refs_schema(cv_json_schema())
    assert "summary" not in schema["properties"] and schema["properties"]["summary_lines"]["items"] == {"type": "integer"}
    experience = schema["$defs"]["Experience"]
    assert "highlights" not in experience["properties"] and "highlight_lines" in experience["required"]
    assert "highlights" in cv_json_schema()["$defs"]["Experience"]["properties"]  # le schéma normal n'est pas modifié


def test_resolve_turns_numbers_back_into_text_and_ignores_bad_numbers():
    _, segments = refs.number_lines(TEXT)
    answer = {"summary_lines": [3], "experiences": [{"job_title": "Dev", "highlight_lines": [5, 6, 6, 99, 0]}]}
    result = refs.resolve(answer, segments)
    assert result["summary"].startswith("Développeuse back-end")
    assert result["experiences"][0]["highlights"] == [segments[4], segments[5]]  # doublon et numéros absurdes ignorés
    assert "summary_lines" not in result and "highlight_lines" not in result["experiences"][0]


def test_system_prompt_swaps_only_the_highlights_rule():
    with_refs = system_prompt(refs.REFS_RULES)
    assert "highlight_lines" in with_refs and "- highlights:" not in with_refs
    assert with_refs.splitlines()[:7] == SYSTEM_PROMPT.splitlines()[:7]
    assert system_prompt() == SYSTEM_PROMPT


def test_structure_cv_in_refs_mode_copies_the_lines_itself():
    answer = json.dumps({
        "identity": {"full_name": "Camille Lefèvre", "email": None, "phone": None, "location": None, "links": []},
        "title": None, "summary_lines": [3],
        "experiences": [{"job_title": "Développeuse Python senior", "company": "Novalys Logistique", "location": "Lyon",
                         "start": None, "end": None, "highlight_lines": [5, 6]}],
        "education": [], "skills": [], "languages": [], "certifications": [],
    })
    provider = FakeProvider([answer])
    cv, attempts = structure_cv(TEXT, provider, StepTimer("test"), copy_mode="refs")
    assert attempts == 1
    assert "5| Conception" in provider.prompts[0]  # le modèle a reçu le texte numéroté
    assert cv.experiences[0].highlights == [
        "Conception d'une API REST de suivi de colis.",
        "Réduction de 40 % du temps de réponse grâce à la mise en cache Redis.",
    ]
    assert cv.summary.endswith("À l'aise en équipe agile.")

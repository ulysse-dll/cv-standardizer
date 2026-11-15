"""Tests du banc d'essai : la notation, sans vrai LLM."""

import copy

from app.config import Settings
from app.coverage import normalize
from app.eval import CRITERIA, EXPECTED_DIR, evaluate_file, format_table, overlap, score_cv
from app.schema import CV
from tests.test_pipeline import FakeProvider
from tests.test_schema import VALID_CV


def _cv(**changes) -> CV:
    return CV.model_validate({**copy.deepcopy(VALID_CV), **changes})


def test_normalize_ignores_case_accents_and_punctuation():
    assert normalize("  Lefèvre. ") == normalize("LEFEVRE") == "lefevre"
    assert normalize(None) == ""


def test_overlap():
    assert overlap(["Python", "FastAPI"], ["fastapi", "python"]) == 1.0  # l'ordre et la casse ne comptent pas
    assert overlap(["Python", "FastAPI"], ["Python"]) == 0.5  # un oubli
    assert overlap(["Python"], ["Python", "Excel"]) == 0.5  # un ajout coûte autant qu'un oubli
    assert overlap([], []) == 1.0


def test_identical_cv_gets_the_maximum_everywhere():
    scores = score_cv(_cv(), _cv())
    assert list(scores) == CRITERIA
    assert set(scores.values()) == {100.0}


def test_invented_highlight_lowers_only_the_highlights_score():
    got = _cv()
    got.experiences[0].highlights.append("Réalisation inventée de toutes pièces")
    scores = score_cv(_cv(), got)
    assert scores["réalisations"] < 100  # 2 bonnes sur 3 en tout
    assert scores["postes"] == scores["dates"] == scores["compétences"] == 100


def test_missing_job_costs_on_jobs_dates_and_highlights():
    scores = score_cv(_cv(), _cv(experiences=[]))
    assert scores["postes"] == scores["dates"] == scores["réalisations"] == 0
    assert scores["formation"] == 100


def test_wrong_end_date_is_half_the_dates_score():
    got = _cv()
    got.experiences[0].end = None  # « present » oublié
    assert score_cv(_cv(), got)["dates"] == 50


def test_every_sample_has_an_expected_answer_that_is_a_valid_cv(samples_dir):
    samples = [path for path in samples_dir.iterdir() if path.suffix in (".pdf", ".docx")]
    assert len(samples) == 9  # 5 faciles + 4 difficiles
    for path in samples:
        CV.model_validate_json((EXPECTED_DIR / f"{path.stem}.json").read_text(encoding="utf-8"))


def test_evaluate_file_with_a_perfect_model(samples_dir):
    # Le faux modèle récite la bonne réponse : il doit avoir 100.
    answer = (EXPECTED_DIR / "cv_tableaux_fr.json").read_text(encoding="utf-8")
    row = evaluate_file(samples_dir / "cv_tableaux_fr.docx", FakeProvider([answer]), Settings(_env_file=None))
    assert row.total == 100 and row.attempts == 1 and row.error is None
    assert row.invented == 0 and row.missing == 0
    assert "MOYENNE" in format_table([row])


def test_evaluate_file_counts_a_failure_as_zero(samples_dir):
    row = evaluate_file(samples_dir / "cv_tableaux_fr.docx", FakeProvider(["pas du JSON", "toujours pas"]), Settings(_env_file=None))
    assert row.total == 0 and "valide" in row.error

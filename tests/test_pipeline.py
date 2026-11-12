"""Tests du pipeline, SANS vrai LLM.

On remplace le provider par un faux qui renvoie des réponses écrites
d'avance. Les tests sont ainsi instantanés et ne dépendent pas d'Ollama.
"""

import json

import pytest

from app.config import Settings
from app.llm.base import LLMProvider, LLMResult
from app.pipeline import StructuringError, process_cv, structure_cv
from app.timing import StepTimer

VALID_JSON = json.dumps(
    {
        "identity": {"full_name": "Inès Benali", "email": "ines.benali@example.net",
                     "phone": None, "location": "Nantes", "links": []},
        "title": "Cheffe de projet marketing digital",
        "summary": None,
        "experiences": [],
        "education": [],
        "skills": ["SEO"],
        "languages": [],
        "certifications": [],
    }
)
TRUNCATED_JSON = VALID_JSON[:60]  # du JSON coupé en plein milieu
NAMELESS_JSON = json.dumps({"identity": {"full_name": ""}})  # JSON correct, mais CV sans nom


class FakeProvider(LLMProvider):
    """Un faux LLM : il renvoie, dans l'ordre, les réponses qu'on lui a données."""

    name = "fake"
    model = "fake-model"

    def __init__(self, answers):
        self.answers = list(answers)
        self.prompts = []  # on note ce qu'on nous envoie, pour le vérifier ensuite

    def generate_json(self, system, user, schema, on_progress=None):
        self.prompts.append(user)
        answer = self.answers.pop(0)
        if on_progress:  # comme un vrai modèle : on signale l'avancement en deux fois
            on_progress(len(answer) // 2)
            on_progress(len(answer))
        return LLMResult(text=answer)


def test_valid_answer_needs_one_call():
    provider = FakeProvider([VALID_JSON])
    cv, attempts = structure_cv("texte du CV", provider, StepTimer("test"))
    assert attempts == 1
    assert len(provider.prompts) == 1
    assert cv.identity.full_name == "Inès Benali"


@pytest.mark.parametrize("bad_answer", [TRUNCATED_JSON, NAMELESS_JSON, "désolé, je ne peux pas"])
def test_invalid_answer_triggers_one_retry(bad_answer):
    provider = FakeProvider([bad_answer, VALID_JSON])
    cv, attempts = structure_cv("texte du CV", provider, StepTimer("test"))
    assert attempts == 2
    assert cv.identity.full_name == "Inès Benali"
    # Le second prompt signale l'erreur et redonne le CV.
    assert "rejected" in provider.prompts[1]
    assert "texte du CV" in provider.prompts[1]


def test_two_invalid_answers_give_up():
    provider = FakeProvider([TRUNCATED_JSON, TRUNCATED_JSON, VALID_JSON])
    with pytest.raises(StructuringError):
        structure_cv("texte du CV", provider, StepTimer("test"))
    assert len(provider.prompts) == 2  # 1 essai + 1 retry, jamais plus


def test_process_cv_end_to_end(samples_dir):
    provider = FakeProvider([VALID_JSON])
    settings = Settings(_env_file=None)
    data = (samples_dir / "cv_tableaux_fr.docx").read_bytes()

    result = process_cv(data, "cv_tableaux_fr.docx", provider, settings)

    assert result.extraction_method == "docx"
    assert result.attempts == 1
    assert "Inès Benali" in provider.prompts[0]  # le texte extrait est bien parti au LLM
    assert "Inès Benali" in result.html  # le CV standardisé a été généré
    assert set(result.timings) == {"extraction", "llm", "validation", "html", "pdf"}


def test_progress_is_reported_step_by_step(samples_dir):
    seen = []  # la liste des (étape, fraction) reçus
    data = (samples_dir / "cv_tableaux_fr.docx").read_bytes()
    process_cv(
        data, "cv_tableaux_fr.docx", FakeProvider([VALID_JSON]), Settings(_env_file=None),
        on_progress=lambda step, fraction: seen.append((step, fraction)),
    )
    steps = [step for step, _ in seen]
    assert steps[0] == "extraction" and steps[-1] == "rendu"
    llm_fractions = [fraction for step, fraction in seen if step == "llm"]
    assert llm_fractions == sorted(llm_fractions)  # la barre ne recule jamais
    assert 0 < llm_fractions[-1] <= 0.97  # et ne dit jamais 100 % avant la fin


def test_very_long_cv_is_cut_with_a_warning(samples_dir):
    provider = FakeProvider([VALID_JSON])
    settings = Settings(_env_file=None, max_cv_chars=200)
    data = (samples_dir / "cv_classique_fr.pdf").read_bytes()

    result = process_cv(data, "cv_classique_fr.pdf", provider, settings)

    assert any("CV très long" in warning for warning in result.warnings)
    assert len(provider.prompts[0]) < 250

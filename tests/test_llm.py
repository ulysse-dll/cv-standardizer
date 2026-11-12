"""Tests de la couche LLM, sans réseau : on intercepte l'appel HTTP."""

import json
from contextlib import contextmanager

import httpx
import pytest

from app.config import Settings
from app.llm import ConfigError, get_provider
from app.llm.base import LLMError
from app.llm.ollama import OllamaProvider
from app.llm.openai_compat import OpenAICompatProvider, inline_refs
from app.schema import cv_json_schema


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)  # _env_file=None : on ignore le vrai .env


# ------------------------------------------------- choix du provider -----
def test_default_provider_is_local_ollama():
    provider = get_provider(_settings())
    assert isinstance(provider, OllamaProvider)
    assert provider.base_url == "http://localhost:11434"


@pytest.mark.parametrize("provider_name", ["gemini", "custom"])
def test_remote_providers_are_blocked_by_default(provider_name):
    with pytest.raises(ConfigError, match="ALLOW_REMOTE"):
        get_provider(_settings(llm_provider=provider_name, gemini_api_key="k", custom_base_url="http://x", custom_model="m"))


def test_gemini_needs_an_api_key():
    with pytest.raises(ConfigError, match="GEMINI_API_KEY"):
        get_provider(_settings(llm_provider="gemini", allow_remote=True))


def test_gemini_uses_the_openai_format():
    provider = get_provider(_settings(llm_provider="gemini", allow_remote=True, gemini_api_key="k"))
    assert isinstance(provider, OpenAICompatProvider)
    assert provider.name == "gemini"


def test_custom_can_speak_ollama_or_openai():
    base = dict(llm_provider="custom", allow_remote=True, custom_base_url="http://x", custom_model="m")
    assert isinstance(get_provider(_settings(**base)), OpenAICompatProvider)
    assert isinstance(get_provider(_settings(custom_api_style="ollama", **base)), OllamaProvider)


# ------------------------------------------------------ appel Ollama -----
def _fake_ollama(monkeypatch, status=200, lines=(), sent=None):
    """Remplace httpx.stream par un faux Ollama qui répond les lignes données."""

    @contextmanager
    def fake_stream(method, url, json, headers, timeout):
        if sent is not None:
            sent.update(url=url, json=json)
        yield httpx.Response(status, content="\n".join(lines).encode("utf-8"))

    monkeypatch.setattr(httpx, "stream", fake_stream)


def test_ollama_call_sends_schema_and_reads_speed(monkeypatch):
    sent = {}
    # Ollama envoie la réponse en plusieurs morceaux, puis une dernière ligne de statistiques.
    lines = [
        json.dumps({"message": {"content": '{"ok": '}, "done": False}),
        json.dumps({"message": {"content": "true}"}, "done": False}),
        json.dumps({
            "message": {"content": ""}, "done": True, "done_reason": "stop",
            "prompt_eval_count": 500, "eval_count": 100,
            "eval_duration": 10_000_000_000,  # 10 secondes, en nanosecondes
        }),
    ]
    _fake_ollama(monkeypatch, lines=lines, sent=sent)
    schema = cv_json_schema()
    progress = []
    result = OllamaProvider("http://localhost:11434/", "gemma3:4b").generate_json(
        "sys", "user", schema, on_progress=progress.append
    )

    assert sent["url"] == "http://localhost:11434/api/chat"
    assert sent["json"]["format"] == schema  # la sortie JSON est bien forcée
    assert sent["json"]["stream"] is True
    assert sent["json"]["options"]["temperature"] == 0
    assert result.text == '{"ok": true}'  # les morceaux sont recollés dans l'ordre
    assert progress == [7, 12, 12]  # nombre de caractères écrits, après chaque morceau
    assert result.tokens_per_second == 10.0  # 100 tokens en 10 s
    assert result.truncated is False


def test_ollama_missing_model_explains_how_to_fix(monkeypatch):
    _fake_ollama(monkeypatch, status=404, lines=['{"error": "model not found"}'])
    with pytest.raises(LLMError, match="ollama pull gemma3:4b"):
        OllamaProvider("http://localhost:11434", "gemma3:4b").generate_json("s", "u", {})


def test_ollama_error_in_the_middle_of_the_answer_is_reported(monkeypatch):
    _fake_ollama(monkeypatch, lines=['{"message": {"content": "{"}}', '{"error": "plus de mémoire"}'])
    with pytest.raises(LLMError, match="plus de mémoire"):
        OllamaProvider("http://localhost:11434", "gemma3:4b").generate_json("s", "u", {})


def test_ollama_not_running_explains_how_to_fix(monkeypatch):
    def refuse(*args, **kwargs):
        raise httpx.ConnectError("connexion refusée")

    monkeypatch.setattr(httpx, "stream", refuse)
    with pytest.raises(LLMError, match="ollama serve"):
        OllamaProvider("http://localhost:11434", "gemma3:4b").generate_json("s", "u", {})


# ------------------------------------------------ format OpenAI ----------
def test_inline_refs_removes_every_reference():
    flat = inline_refs(cv_json_schema())
    assert "$defs" not in flat
    assert "$ref" not in str(flat)
    # Le sous-modèle Identity est maintenant écrit directement à sa place.
    assert "full_name" in flat["properties"]["identity"]["properties"]


def test_openai_call_reads_the_answer(monkeypatch):
    sent = {}

    def fake_post(url, json, headers, timeout):
        sent.update(url=url, json=json, headers=headers)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"ok": true}'}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 500, "completion_tokens": 100},
            },
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    provider = OpenAICompatProvider("gemini", "https://exemple.test/v1/", "un-modele", api_key="cle")
    result = provider.generate_json("sys", "user", cv_json_schema())

    assert sent["url"] == "https://exemple.test/v1/chat/completions"
    assert sent["headers"] == {"Authorization": "Bearer cle"}
    assert sent["json"]["response_format"]["type"] == "json_schema"
    assert result.text == '{"ok": true}'
    assert result.output_tokens == 100

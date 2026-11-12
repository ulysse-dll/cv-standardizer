"""Tests du diagnostic (python -m app.check), sans réseau."""

import httpx

from app import check
from app.config import Settings


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


def _fake_ollama(monkeypatch, models):
    answer = httpx.Response(200, json={"models": [{"name": name} for name in models]}, request=httpx.Request("GET", "http://x"))
    monkeypatch.setattr(httpx, "get", lambda url, timeout: answer)


def test_everything_ready(monkeypatch):
    _fake_ollama(monkeypatch, ["gemma3:4b", "llama3.2:3b"])
    results = check.check_llm(_settings())
    assert [level for level, _ in results] == [check.OK, check.OK, check.OK]


def test_missing_model_explains_how_to_fix(monkeypatch):
    _fake_ollama(monkeypatch, ["llama3.2:3b"])
    level, message = check.check_llm(_settings())[-1]
    assert level == check.ERROR
    assert "ollama pull gemma3:4b" in message


def test_ollama_not_running_explains_how_to_fix(monkeypatch):
    def refuse(url, timeout):
        raise httpx.ConnectError("connexion refusée")

    monkeypatch.setattr(httpx, "get", refuse)
    level, message = check.check_llm(_settings())[-1]
    assert level == check.ERROR
    assert "ollama serve" in message


def test_remote_provider_is_not_contacted(monkeypatch):
    def forbidden(url, timeout):
        raise AssertionError("le diagnostic ne doit pas appeler un service distant")

    monkeypatch.setattr(httpx, "get", forbidden)
    results = check.check_llm(_settings(llm_provider="gemini", allow_remote=True, gemini_api_key="k"))
    assert results[-1][0] == check.INFO


def test_bad_configuration_is_an_error():
    results = check.check_llm(_settings(llm_provider="gemini"))  # sans ALLOW_REMOTE
    assert results == [(check.ERROR, results[0][1])] and "ALLOW_REMOTE" in results[0][1]


def test_local_checks_never_crash():
    # Python, dossier de sortie, OCR, PDF (coupé pendant les tests), diapositive, photo.
    for function in (check.check_python, check.check_outputs, check.check_ocr, check.check_pdf, check.check_pptx, check.check_photo):
        level, message = function()
        assert level in (check.OK, check.INFO) and message

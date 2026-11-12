"""Choix du provider LLM d'après le fichier .env."""

from app.config import Settings
from app.llm.base import LLMError, LLMProvider, LLMResult
from app.llm.ollama import OllamaProvider
from app.llm.openai_compat import OpenAICompatProvider

__all__ = ["ConfigError", "LLMError", "LLMProvider", "LLMResult", "get_provider"]


class ConfigError(Exception):
    """Le fichier .env est incomplet ou incohérent."""


def get_provider(settings: Settings) -> LLMProvider:
    """Construit le provider demandé par LLM_PROVIDER, après les garde-fous."""
    if settings.llm_provider == "ollama":
        return OllamaProvider(
            base_url=settings.ollama_base_url,
            model=settings.ollama_model,
            num_ctx=settings.ollama_num_ctx,
            keep_alive=settings.ollama_keep_alive,
            timeout_s=settings.llm_timeout_s,
            max_output_tokens=settings.llm_max_output_tokens,
        )

    # À partir d'ici, le texte des CV quitte la machine : accord explicite exigé.
    if not settings.allow_remote:
        raise ConfigError(
            f"LLM_PROVIDER={settings.llm_provider} envoie le texte des CV hors de cette machine. "
            "Si c'est voulu (faux CV, démo), ajoute ALLOW_REMOTE=true dans le fichier .env."
        )

    if settings.llm_provider == "gemini":
        if not settings.gemini_api_key:
            raise ConfigError("LLM_PROVIDER=gemini demande une clé : renseigne GEMINI_API_KEY dans .env.")
        return OpenAICompatProvider(
            name="gemini",
            base_url=settings.gemini_base_url,
            model=settings.gemini_model,
            api_key=settings.gemini_api_key,
            timeout_s=settings.llm_timeout_s,
        )

    # custom
    if not settings.custom_base_url or not settings.custom_model:
        raise ConfigError("LLM_PROVIDER=custom demande CUSTOM_BASE_URL et CUSTOM_MODEL dans .env.")
    if settings.custom_api_style == "ollama":
        return OllamaProvider(
            name="custom",
            base_url=settings.custom_base_url,
            model=settings.custom_model,
            num_ctx=settings.ollama_num_ctx,
            keep_alive=settings.ollama_keep_alive,
            timeout_s=settings.llm_timeout_s,
            max_output_tokens=settings.llm_max_output_tokens,
            api_key=settings.custom_api_key,
        )
    return OpenAICompatProvider(
        name="custom",
        base_url=settings.custom_base_url,
        model=settings.custom_model,
        api_key=settings.custom_api_key,
        timeout_s=settings.llm_timeout_s,
    )

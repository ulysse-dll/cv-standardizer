"""Configuration de l'application, lue depuis le fichier .env.

pydantic-settings fait le lien automatiquement : la variable LLM_PROVIDER du
fichier .env remplit le champ `llm_provider` ci-dessous (la casse est ignorée).
Chaque champ a une valeur par défaut, donc l'app démarre même sans .env.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

# Dossier racine du projet (le parent du dossier app/).
ROOT_DIR = Path(__file__).resolve().parent.parent
OUTPUTS_DIR = ROOT_DIR / "outputs"
LOGS_DIR = ROOT_DIR / "logs"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ROOT_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",  # une variable inconnue dans .env ne fait pas planter l'app
    )

    llm_provider: Literal["ollama", "gemini", "custom"] = "ollama"
    allow_remote: bool = False

    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "gemma3:4b"
    ollama_num_ctx: int = 8192
    ollama_keep_alive: str = "30m"

    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai"

    custom_api_style: Literal["openai", "ollama"] = "openai"
    custom_base_url: str = ""
    custom_model: str = ""
    custom_api_key: str = ""

    llm_timeout_s: int = 900
    llm_max_output_tokens: int = 2500
    max_cv_chars: int = 12000
    ocr_languages: str = "fra+eng"

    @property
    def is_remote(self) -> bool:
        """Vrai si le texte des CV sort de la machine avec ce provider."""
        return self.llm_provider != "ollama"


@lru_cache
def get_settings() -> Settings:
    """Lit le .env une seule fois, puis renvoie toujours le même objet."""
    return Settings()

"""L'interface commune à tous les providers LLM.

Le reste de l'application ne connaît que `LLMProvider.generate_json(...)`.
Peu importe que derrière ce soit Ollama, Gemini ou une URL perso : c'est ce
qui rend les providers interchangeables.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


class LLMError(Exception):
    """Le LLM n'a pas pu répondre. Le message est affichable à l'utilisateur."""


@dataclass
class LLMResult:
    text: str  # la réponse brute du modèle (du JSON, normalement)
    prompt_tokens: Optional[int] = None  # taille de ce qu'on a envoyé
    output_tokens: Optional[int] = None  # taille de ce qu'il a écrit
    tokens_per_second: Optional[float] = None  # vitesse d'écriture
    truncated: bool = False  # vrai si le modèle a été coupé avant d'avoir fini


class LLMProvider(ABC):
    name: str  # "ollama", "gemini" ou "custom"
    model: str

    @abstractmethod
    def generate_json(self, system: str, user: str, schema: dict) -> LLMResult:
        """Envoie les deux messages au modèle et exige une réponse JSON conforme au schéma."""

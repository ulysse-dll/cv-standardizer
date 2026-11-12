"""Provider Ollama, via son API native (POST /api/chat).

Pourquoi l'API native plutôt que l'endpoint compatible OpenAI d'Ollama ?
Parce qu'elle seule accepte `options.num_ctx` (la taille de la fenêtre de
contexte). Avec la valeur par défaut, un long CV serait tronqué en silence.

Le paramètre clé est `format` : on y met le JSON Schema du CV, et Ollama
contraint alors la génération pour que la sortie respecte ce schéma.
"""

import json
import time
from typing import List, Optional

import httpx

from app.llm.base import LLMError, LLMProvider, LLMResult, ProgressCallback


class OllamaProvider(LLMProvider):
    def __init__(
        self,
        base_url: str,
        model: str,
        num_ctx: int = 8192,
        keep_alive: str = "30m",
        timeout_s: int = 900,
        max_output_tokens: int = 2500,
        api_key: str = "",
        name: str = "ollama",
    ):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.num_ctx = num_ctx
        self.keep_alive = keep_alive
        self.timeout_s = timeout_s
        self.max_output_tokens = max_output_tokens
        self.api_key = api_key

    def generate_json(
        self, system: str, user: str, schema: dict, on_progress: Optional[ProgressCallback] = None
    ) -> LLMResult:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "format": schema,  # <- force une sortie JSON conforme au schéma
            "stream": True,  # la réponse arrive morceau par morceau (voir plus bas)
            "keep_alive": self.keep_alive,  # garde le modèle en RAM entre deux CV
            "options": {
                "temperature": 0,  # pas de créativité : on veut une copie fidèle
                "num_ctx": self.num_ctx,
                "num_predict": self.max_output_tokens,
            },
        }
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        too_slow = LLMError(
            f"Le modèle n'a pas répondu en {self.timeout_s} s. Augmente LLM_TIMEOUT_S ou prends un modèle plus petit."
        )

        pieces: List[str] = []  # les morceaux de texte, dans l'ordre d'arrivée
        written = 0
        last: dict = {}  # le dernier message d'Ollama, qui contient les statistiques
        started = time.monotonic()
        try:
            # En mode "stream", Ollama envoie une ligne de JSON par token écrit,
            # au lieu d'une seule réponse à la fin. On peut ainsi suivre l'avancement.
            with httpx.stream(
                "POST", f"{self.base_url}/api/chat", json=payload, headers=headers, timeout=self.timeout_s
            ) as response:
                if response.status_code == 404:
                    raise LLMError(
                        f"Le modèle « {self.model} » n'est pas installé. Lance : ollama pull {self.model}"
                    )
                if response.status_code != 200:
                    response.read()  # en mode stream, il faut lire le corps avant de l'afficher
                    raise LLMError(f"Ollama a répondu {response.status_code} : {response.text[:300]}")

                for line in response.iter_lines():
                    if not line:
                        continue
                    last = json.loads(line)
                    if last.get("error"):
                        raise LLMError(f"Ollama a signalé une erreur : {last['error']}")
                    piece = last.get("message", {}).get("content", "")
                    pieces.append(piece)
                    written += len(piece)
                    if on_progress:
                        on_progress(written)
                    if time.monotonic() - started > self.timeout_s:
                        raise too_slow
        except httpx.ConnectError as error:
            raise LLMError(
                f"Impossible de joindre Ollama sur {self.base_url}. Est-il lancé ? (commande : ollama serve)"
            ) from error
        except httpx.TimeoutException as error:
            raise too_slow from error
        except httpx.HTTPError as error:
            raise LLMError(f"Erreur réseau vers Ollama : {error}") from error
        except json.JSONDecodeError as error:
            raise LLMError(f"Réponse illisible d'Ollama : {error}") from error

        # Ollama donne ses durées en nanosecondes (1 s = 1 000 000 000 ns).
        output_tokens = last.get("eval_count")
        eval_seconds = last.get("eval_duration", 0) / 1e9
        speed = round(output_tokens / eval_seconds, 1) if output_tokens and eval_seconds else None

        return LLMResult(
            text="".join(pieces),
            prompt_tokens=last.get("prompt_eval_count"),
            output_tokens=output_tokens,
            tokens_per_second=speed,
            truncated=last.get("done_reason") == "length",
        )

"""Provider Ollama, via son API native (POST /api/chat).

Pourquoi l'API native plutôt que l'endpoint compatible OpenAI d'Ollama ?
Parce qu'elle seule accepte `options.num_ctx` (la taille de la fenêtre de
contexte). Avec la valeur par défaut, un long CV serait tronqué en silence.

Le paramètre clé est `format` : on y met le JSON Schema du CV, et Ollama
contraint alors la génération pour que la sortie respecte ce schéma.
"""

import httpx

from app.llm.base import LLMError, LLMProvider, LLMResult


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

    def generate_json(self, system: str, user: str, schema: dict) -> LLMResult:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "format": schema,  # <- force une sortie JSON conforme au schéma
            "stream": False,  # on attend la réponse complète, d'un bloc
            "keep_alive": self.keep_alive,  # garde le modèle en RAM entre deux CV
            "options": {
                "temperature": 0,  # pas de créativité : on veut une copie fidèle
                "num_ctx": self.num_ctx,
                "num_predict": self.max_output_tokens,
            },
        }
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

        try:
            response = httpx.post(
                f"{self.base_url}/api/chat", json=payload, headers=headers, timeout=self.timeout_s
            )
        except httpx.ConnectError as error:
            raise LLMError(
                f"Impossible de joindre Ollama sur {self.base_url}. Est-il lancé ? (commande : ollama serve)"
            ) from error
        except httpx.TimeoutException as error:
            raise LLMError(
                f"Le modèle n'a pas répondu en {self.timeout_s} s. Augmente LLM_TIMEOUT_S ou prends un modèle plus petit."
            ) from error
        except httpx.HTTPError as error:
            raise LLMError(f"Erreur réseau vers Ollama : {error}") from error

        if response.status_code == 404:
            raise LLMError(
                f"Le modèle « {self.model} » n'est pas installé. Lance : ollama pull {self.model}"
            )
        if response.status_code != 200:
            raise LLMError(f"Ollama a répondu {response.status_code} : {response.text[:300]}")

        data = response.json()
        # Ollama donne ses durées en nanosecondes (1 s = 1 000 000 000 ns).
        output_tokens = data.get("eval_count")
        eval_seconds = data.get("eval_duration", 0) / 1e9
        speed = round(output_tokens / eval_seconds, 1) if output_tokens and eval_seconds else None

        return LLMResult(
            text=data.get("message", {}).get("content", ""),
            prompt_tokens=data.get("prompt_eval_count"),
            output_tokens=output_tokens,
            tokens_per_second=speed,
            truncated=data.get("done_reason") == "length",
        )

"""Provider "compatible OpenAI" : POST {base_url}/chat/completions.

Ce format est devenu un standard : Gemini, Ollama (sous /v1), LM Studio,
vLLM... le parlent tous. Il sert ici aux providers `gemini` et `custom`.
Le schéma JSON passe par le champ `response_format`.
"""

import copy
from typing import Any, Optional

import httpx

from app.llm.base import LLMError, LLMProvider, LLMResult, ProgressCallback


def inline_refs(schema: dict) -> dict:
    """Remplace les renvois {"$ref": "#/$defs/X"} par la définition de X.

    Pydantic range les sous-modèles dans "$defs" et y renvoie par "$ref".
    Certains serveurs ne comprennent pas ces renvois : on leur donne donc un
    schéma "à plat", sans aucun renvoi.
    """
    definitions = schema.get("$defs", {})

    def resolve(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                name = node["$ref"].split("/")[-1]
                return resolve(copy.deepcopy(definitions[name]))
            return {key: resolve(value) for key, value in node.items() if key != "$defs"}
        if isinstance(node, list):
            return [resolve(item) for item in node]
        return node

    return resolve(schema)


class OpenAICompatProvider(LLMProvider):
    def __init__(self, name: str, base_url: str, model: str, api_key: str = "", timeout_s: int = 900):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout_s = timeout_s

    def generate_json(
        self, system: str, user: str, schema: dict, on_progress: Optional[ProgressCallback] = None
    ) -> LLMResult:
        # on_progress n'est pas utilisé : la réponse arrive ici d'un seul bloc.
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "cv", "schema": inline_refs(schema)},
            },
        }
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

        try:
            response = httpx.post(
                f"{self.base_url}/chat/completions", json=payload, headers=headers, timeout=self.timeout_s
            )
        except httpx.TimeoutException as error:
            raise LLMError(f"Pas de réponse de {self.base_url} en {self.timeout_s} s.") from error
        except httpx.HTTPError as error:
            raise LLMError(f"Impossible de joindre {self.base_url} : {error}") from error

        if response.status_code != 200:
            raise LLMError(f"{self.name} a répondu {response.status_code} : {response.text[:300]}")

        data = response.json()
        try:
            choice = data["choices"][0]
            text = choice["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as error:
            raise LLMError(f"Réponse inattendue de {self.name} : {str(data)[:300]}") from error

        usage = data.get("usage") or {}
        return LLMResult(
            text=text,
            prompt_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
            truncated=choice.get("finish_reason") == "length",
        )

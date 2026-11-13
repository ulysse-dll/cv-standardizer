"""Mode « références » (expérimental) : le modèle DÉSIGNE les lignes au lieu de les recopier.

L'idée : recopier une réalisation coûte une vingtaine de tokens au modèle, et
c'est là qu'il invente ou déforme. Si on numérote les lignes du CV, il peut
répondre « réalisations = lignes 12, 13, 14 » (quelques tokens), et c'est
Python qui recopie le texte, à l'identique.

    texte du CV --number_lines--> "1| Camille Lefèvre\n2| Développeuse..."
    réponse du LLM : {"summary_lines": [5, 6], "experiences": [{"highlight_lines": [9, 10], ...}]}
    --resolve--> le même JSON qu'en mode normal, avec "summary" et "highlights" en texte

Seuls le résumé et les réalisations passent par des numéros : un intitulé de
poste ou une date ne sont qu'un MORCEAU de ligne, il faut toujours les écrire.

Activé par LLM_COPY_MODE=refs dans .env. Voir le README pour les mesures.
"""

import copy
import re
from typing import Any, Dict, List, Tuple

_BULLET = re.compile(r"^\s*[•\-–*·▪■●]\s*")
_ENDS_A_SENTENCE = re.compile(r"[.!?:;]$")

REFS_RULES = """- Each CV line starts with its number, like "12| text". Never write these numbers inside a text value.
- highlight_lines: the NUMBERS of the bullet-point lines written under that job. Never add one, never repeat one.
- summary_lines: the NUMBERS of the lines of the profile or summary paragraph. [] if there is none."""


def number_lines(text: str) -> Tuple[str, List[str]]:
    """Découpe le texte en segments numérotés à partir de 1.

    - une cellule de tableau (séparée par " | ") = un segment ;
    - la puce en tête de ligne est retirée ;
    - une ligne qui continue la précédente (elle commence par une minuscule
      et la précédente ne finit pas une phrase) lui est recollée : dans un PDF,
      une longue réalisation est coupée en deux lignes.
    """
    segments: List[str] = []
    for line in text.splitlines():
        for part in line.split(" | "):
            had_bullet = bool(_BULLET.match(part))
            part = _BULLET.sub("", part).strip()
            if not part:
                continue
            continues = part[0].islower() and segments and not had_bullet and not _ENDS_A_SENTENCE.search(segments[-1])
            if continues and " | " not in line:
                segments[-1] = f"{segments[-1]} {part}"
            else:
                segments.append(part)
    numbered = "\n".join(f"{number}| {segment}" for number, segment in enumerate(segments, start=1))
    return numbered, segments


def refs_schema(cv_schema: dict) -> dict:
    """Le JSON Schema du CV, où le résumé et les réalisations sont des listes de numéros."""
    schema = copy.deepcopy(cv_schema)
    numbers = {"type": "array", "items": {"type": "integer"}}

    def rename(properties: Dict[str, Any], required: List[str], old: str, new: str) -> None:
        # On garde l'ordre des champs : le modèle les écrit dans cet ordre.
        items = [(new, numbers) if key == old else (key, value) for key, value in properties.items()]
        properties.clear()
        properties.update(items)
        required[:] = [new if key == old else key for key in required]

    rename(schema["properties"], schema["required"], "summary", "summary_lines")
    experience = schema["$defs"]["Experience"]
    rename(experience["properties"], experience["required"], "highlights", "highlight_lines")
    return schema


def resolve(answer: Dict[str, Any], segments: List[str]) -> Dict[str, Any]:
    """Remplace les numéros de lignes par le texte de ces lignes."""

    def lines(numbers: Any) -> List[str]:
        chosen = []
        for number in numbers if isinstance(numbers, list) else []:
            # Un numéro hors du CV, ou donné deux fois, est ignoré.
            if isinstance(number, int) and 1 <= number <= len(segments) and segments[number - 1] not in chosen:
                chosen.append(segments[number - 1])
        return chosen

    result = dict(answer)
    result["summary"] = " ".join(lines(result.pop("summary_lines", []))) or None
    experiences = []
    for job in result.get("experiences") or []:
        if isinstance(job, dict):
            job = dict(job)
            job["highlights"] = lines(job.pop("highlight_lines", []))
        experiences.append(job)
    result["experiences"] = experiences
    return result

"""Version anonyme d'un CV, pour un tri « à l'aveugle ».

On retire ce qui identifie la personne : nom, e-mail, téléphone, adresse,
liens. La photo est retirée par ailleurs (voir pipeline.py). Le parcours, les
compétences, les écoles et les entreprises restent.
"""

import re
from typing import Any

from app.render import detect_language
from app.schema import CV


def anonymize(cv: CV, number: int) -> CV:
    """Renvoie une copie du CV où le candidat s'appelle « Candidat 03 » (number = 3)."""
    label = "Candidate" if detect_language(cv) == "en" else "Candidat"
    # Le nom peut aussi être cité dans le résumé ou une réalisation : on l'y masque.
    name_parts = [part for part in re.split(r"[\s\-]+", cv.identity.full_name) if len(part) >= 3]
    pattern = re.compile(r"\b(" + "|".join(re.escape(part) for part in name_parts) + r")\b", re.IGNORECASE) if name_parts else None

    def scrub(value: Any) -> Any:
        if isinstance(value, str):
            return pattern.sub("…", value) if pattern else value
        if isinstance(value, list):
            return [scrub(item) for item in value]
        if isinstance(value, dict):
            return {key: scrub(item) for key, item in value.items()}
        return value

    data = scrub(cv.model_dump())
    data["identity"] = {"full_name": f"{label} {number:02d}", "email": None, "phone": None, "location": None, "links": []}
    return CV.model_validate(data)

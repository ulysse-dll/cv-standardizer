"""Filet de sécurité : le LLM a-t-il oublié des lignes du CV ?

Un petit modèle saute parfois une ligne (un diplôme, un stage) sans prévenir.
On ne peut pas l'en empêcher, mais on peut le REPÉRER sans LLM : pour chaque
ligne du texte d'origine, on regarde si ses mots se retrouvent quelque part
dans le résultat. Si presque aucun n'y est, la ligne est signalée à
l'utilisateur, qui vérifie lui-même.

C'est une approximation : elle peut signaler une ligne sans importance, ou
laisser passer un oubli. Elle ne remplace pas une relecture.
"""

import re
from typing import List

from app.schema import CV, _MONTHS

# Mots qu'on ne compte pas : ceux des titres de rubrique et des en-têtes de
# tableau (jamais recopiés dans le résultat), et ceux des dates (réécrites).
_IGNORED_WORDS = set(_MONTHS) | {
    "aujourd", "hui", "present", "présent", "depuis", "since",
    "expérience", "expériences", "professionnelle", "professionnelles", "professionnel", "parcours",
    "formation", "formations", "diplômes", "compétences", "langues", "profil", "résumé",
    "certifications", "coordonnées", "contact", "centres", "intérêt", "intérêts",
    "période", "poste", "entreprise", "réalisations", "outils", "méthodes",
    "experience", "work", "employment", "history", "professional", "education", "skills",
    "languages", "profile", "summary", "interests", "and", "the", "des", "les",
}


def _words(text: str) -> List[str]:
    """Les mots d'au moins 3 lettres et les années, en minuscules."""
    found = re.findall(r"[^\W\d_]{3,}|\d{4}", text.lower())
    return [word for word in found if word not in _IGNORED_WORDS]


def find_missing_lines(source_text: str, cv: CV, limit: int = 5) -> List[str]:
    """Lignes du texte d'origine dont moins de la moitié des mots sont dans le résultat."""
    output_words = set(_words(cv.model_dump_json()))
    missing = []
    for line in source_text.splitlines():
        words = _words(line)
        if len(words) < 2:  # trop peu de mots pour juger
            continue
        found = sum(word in output_words for word in words)
        if found / len(words) < 0.5:
            missing.append(line if len(line) <= 80 else line[:77] + "...")
    return missing[:limit]

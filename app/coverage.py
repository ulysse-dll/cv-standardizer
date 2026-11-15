"""Deux filets de sécurité, SANS LLM, qui comparent le résultat au texte d'origine.

Un petit modèle fait deux sortes d'erreurs sans prévenir :

1. il OUBLIE une ligne du CV (un diplôme, un stage)   -> find_missing_lines
2. il INVENTE une valeur qui n'est pas dans le CV      -> find_unsupported_values

On ne peut pas l'en empêcher, mais on peut le REPÉRER en comparant les mots :
ceux d'une ligne d'origine doivent se retrouver dans le résultat, et ceux
d'une valeur du résultat doivent se retrouver dans le texte d'origine.
L'utilisateur est prévenu et vérifie lui-même.

C'est une approximation : elle peut signaler un détail sans importance, ou
laisser passer une erreur. Elle ne remplace pas une relecture.
"""

import re
import unicodedata
from typing import Any, Iterator, List, Optional

from app.schema import CV, _DATE_FIELDS, _MONTHS

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
    # autres titres de rubrique rencontrés
    "academic", "background", "career", "toolbox", "training", "spoken", "about", "propos",
    "certification", "expertise", "hobbies", "loisirs", "divers", "references", "références",
    "objectif", "objective", "qualifications", "diplôme", "études", "studies", "personal", "details",
}


def normalize(text: Optional[str]) -> str:
    """Minuscules, sans accents ni ponctuation : « Lefèvre. » et « lefevre » sont égaux."""
    text = unicodedata.normalize("NFKD", (text or "").lower())
    text = "".join(char for char in text if not unicodedata.combining(char))
    return " ".join(re.findall(r"[a-z0-9]+", text))


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
            missing.append(_shorten(line))
    return missing[:limit]


# ------------------------------------------------- valeurs inventées ------
def _plain_words(text: str) -> List[str]:
    """Comme _words, mais sans les accents : « Établissement » et « Etablissement »
    comptent pour le même mot (le modèle ou l'OCR en perdent parfois un)."""
    without_accents = unicodedata.normalize("NFKD", text.lower())
    without_accents = "".join(char for char in without_accents if not unicodedata.combining(char))
    return re.findall(r"[^\W\d_]{3,}|\d{4}", without_accents)


def _text_values(node: Any) -> Iterator[str]:
    """Toutes les valeurs texte du CV, sauf les dates (elles sont réécrites exprès)."""
    if isinstance(node, str):
        yield node
    elif isinstance(node, list):
        for item in node:
            yield from _text_values(item)
    elif isinstance(node, dict):
        for key, value in node.items():
            if key not in _DATE_FIELDS:
                yield from _text_values(value)


def find_unsupported_values(source_text: str, cv: CV, limit: int = 5) -> List[str]:
    """Valeurs du résultat dont moins de la moitié des mots viennent du texte d'origine."""
    source_words = set(_plain_words(source_text))
    suspicious = []
    for value in _text_values(cv.model_dump()):
        words = _plain_words(value)
        if not words:  # un numéro de téléphone, "C1"... : rien à comparer
            continue
        found = sum(word in source_words for word in words)
        if found / len(words) < 0.5:
            suspicious.append(_shorten(value))
    return suspicious[:limit]


def _shorten(text: str) -> str:
    return text if len(text) <= 80 else text[:77] + "..."

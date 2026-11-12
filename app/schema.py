"""Le schéma d'un CV standardisé.

Ces classes Pydantic servent trois fois :
1. on en tire un "JSON Schema" envoyé au LLM pour forcer la forme de sa réponse ;
2. on valide la réponse du LLM avec (types, champs obligatoires) ;
3. on les donne au template HTML pour générer le CV final.

Choix pour un petit modèle : peu de niveaux, et des dates en texte libre que
l'on uniformise ensuite nous-mêmes en Python (voir normalize_date).
"""

import re
from typing import Any, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

# Ce que les petits modèles écrivent quand ils ne trouvent pas l'info.
_EMPTY_MARKERS = {"", "null", "none", "n/a", "na", "-", "unknown", "inconnu", "non renseigné"}


def _clean(value: Any) -> Any:
    """Nettoie une valeur venue du LLM : espaces en trop, faux "vides"."""
    if isinstance(value, str):
        value = " ".join(value.split())  # retire espaces et retours à la ligne en trop
        return None if value.lower() in _EMPTY_MARKERS else value
    if isinstance(value, list):
        cleaned = [_clean(item) for item in value]
        return [item for item in cleaned if not _is_empty(item)]
    return value


def _is_empty(value: Any) -> bool:
    """Vrai pour une valeur sans aucune information, y compris une entrée de liste
    dont tous les champs sont vides. Un petit modèle ajoute parfois une telle
    entrée à la fin d'une liste (une expérience {"job_title": null, ...}) :
    on la retire, au lieu de refuser tout le CV à cause d'elle."""
    if isinstance(value, dict):
        return all(_is_empty(item) for item in value.values())
    if isinstance(value, list):
        return all(_is_empty(item) for item in value)
    if isinstance(value, str):
        return " ".join(value.split()).lower() in _EMPTY_MARKERS
    return value is None


_MONTHS = {
    "janvier": 1, "janv": 1, "jan": 1, "january": 1,
    "février": 2, "fevrier": 2, "févr": 2, "fév": 2, "fev": 2, "feb": 2, "february": 2,
    "mars": 3, "mar": 3, "march": 3,
    "avril": 4, "avr": 4, "apr": 4, "april": 4,
    "mai": 5, "may": 5,
    "juin": 6, "jun": 6, "june": 6,
    "juillet": 7, "juil": 7, "jul": 7, "july": 7,
    "août": 8, "aout": 8, "aug": 8, "august": 8,
    "septembre": 9, "sept": 9, "sep": 9, "september": 9,
    "octobre": 10, "oct": 10, "october": 10,
    "novembre": 11, "nov": 11, "november": 11,
    "décembre": 12, "decembre": 12, "déc": 12, "dec": 12, "december": 12,
}
_PRESENT_WORDS = {
    "present", "présent", "aujourd'hui", "aujourd’hui", "actuel", "actuellement", "en cours",
    "en poste", "à ce jour", "now", "current", "currently", "today", "ongoing",
}
_DATE_FIELDS = {"start", "end", "date"}


def normalize_date(value: Any) -> Any:
    """Uniformise une date : "Mars 2021" -> "03/2021", "aujourd'hui" -> "present".

    C'est fait ici, en Python, plutôt que demandé au LLM : c'est gratuit,
    instantané, et ça donne toujours le même résultat. Une date qu'on ne
    reconnaît pas est laissée telle quelle.
    """
    if not isinstance(value, str):
        return value
    text = value.lower().rstrip(".")
    text = re.sub(r"^(depuis|since|from)\s+", "", text)  # "depuis janvier 2019"
    if text in _PRESENT_WORDS:
        return "present"
    match = re.fullmatch(r"([a-zéûôèç]+)\.?,? (\d{4})", text)  # "mars 2021", "Sept. 2018"
    if match and match.group(1) in _MONTHS:
        return f"{_MONTHS[match.group(1)]:02d}/{match.group(2)}"
    match = re.fullmatch(r"(\d{1,2}) ?[/.-] ?(\d{4})", text)  # "3/2021", "03-2021"
    if match and 1 <= int(match.group(1)) <= 12:
        return f"{int(match.group(1)):02d}/{match.group(2)}"
    match = re.fullmatch(r"(\d{4}) ?[/.-] ?(\d{1,2})", text)  # "2021-03"
    if match and 1 <= int(match.group(2)) <= 12:
        return f"{int(match.group(2)):02d}/{match.group(1)}"
    return value


class CleanModel(BaseModel):
    """Classe de base : nettoie toutes les valeurs AVANT la validation."""

    @model_validator(mode="before")
    @classmethod
    def _clean_values(cls, data: Any) -> Any:
        if isinstance(data, dict):
            return {key: _clean(value) for key, value in data.items()}
        return data

    @field_validator("*", mode="before")
    @classmethod
    def _fix_field(cls, value: Any, info: Any) -> Any:
        # Si le LLM écrit null à la place d'une liste, on met une liste vide.
        if value is None and cls.model_fields[info.field_name].default_factory is list:
            return []
        if info.field_name in _DATE_FIELDS:
            return normalize_date(value)
        return value


class Identity(CleanModel):
    full_name: str = Field(min_length=1)
    email: Optional[str] = None
    phone: Optional[str] = None
    location: Optional[str] = None
    links: List[str] = Field(default_factory=list)

    @field_validator("full_name")
    @classmethod
    def _fix_capitals(cls, value: str) -> str:
        # Beaucoup de CV écrivent le nom tout en majuscules : "THOMAS GIRARD".
        # Standardiser, c'est aussi écrire tous les noms de la même façon.
        return value.title() if value.isupper() else value


class Experience(CleanModel):
    job_title: str = Field(min_length=1)
    company: Optional[str] = None
    location: Optional[str] = None
    start: Optional[str] = None
    end: Optional[str] = None
    highlights: List[str] = Field(default_factory=list)


class Education(CleanModel):
    degree: str = Field(min_length=1)
    school: Optional[str] = None
    location: Optional[str] = None
    start: Optional[str] = None
    end: Optional[str] = None


class Language(CleanModel):
    name: str = Field(min_length=1)
    level: Optional[str] = None


class Certification(CleanModel):
    name: str = Field(min_length=1)
    issuer: Optional[str] = None
    date: Optional[str] = None


class CV(CleanModel):
    identity: Identity
    title: Optional[str] = None
    summary: Optional[str] = None
    experiences: List[Experience] = Field(default_factory=list)
    education: List[Education] = Field(default_factory=list)
    skills: List[str] = Field(default_factory=list)
    languages: List[Language] = Field(default_factory=list)
    certifications: List[Certification] = Field(default_factory=list)


def _require_all_properties(node: Any) -> None:
    """Parcourt le schéma et rend chaque champ obligatoire, sans titres ni défauts."""
    if isinstance(node, list):
        for item in node:
            _require_all_properties(item)
        return
    if not isinstance(node, dict):
        return
    node.pop("title", None)
    node.pop("default", None)
    for key, value in node.items():
        if key in ("properties", "$defs"):
            # Ici les clés sont des NOMS (de champs, de classes), pas des
            # mots-clés du schéma : on ne nettoie que leurs valeurs. Sans ça,
            # le champ "title" du CV serait supprimé par erreur.
            for sub_schema in value.values():
                _require_all_properties(sub_schema)
        else:
            _require_all_properties(value)
    if "properties" in node:
        node["required"] = list(node["properties"])


def cv_json_schema() -> dict:
    """Le JSON Schema du CV, tel qu'on l'envoie au LLM.

    Côté validation, un champ optionnel absent est toléré (il vaut None ou []).
    Côté LLM, on exige au contraire TOUS les champs : le modèle remplit
    toujours le même gabarit, quitte à écrire null, au lieu de choisir quoi
    omettre. C'est plus fiable avec un petit modèle.
    """
    schema = CV.model_json_schema()
    _require_all_properties(schema)
    return schema

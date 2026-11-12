"""Le schéma d'un CV standardisé.

Ces classes Pydantic servent trois fois :
1. on en tire un "JSON Schema" envoyé au LLM pour forcer la forme de sa réponse ;
2. on valide la réponse du LLM avec (types, champs obligatoires) ;
3. on les donne au template HTML pour générer le CV final.

Choix pour un petit modèle : peu de niveaux et des dates en texte libre.
"""

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
        return [item for item in cleaned if item not in (None, "", [], {})]
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
    def _none_to_empty_list(cls, value: Any, info: Any) -> Any:
        """Si le LLM écrit null à la place d'une liste, on met une liste vide."""
        field = cls.model_fields[info.field_name]
        if value is None and field.default_factory is list:
            return []
        return value


class Identity(CleanModel):
    full_name: str = Field(min_length=1)
    email: Optional[str] = None
    phone: Optional[str] = None
    location: Optional[str] = None
    links: List[str] = Field(default_factory=list)


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

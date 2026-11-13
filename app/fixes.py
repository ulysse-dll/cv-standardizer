"""Corrections faites en Python, d'après le texte d'origine, APRÈS le passage du LLM.

Quand une information est écrite noir sur blanc dans le CV, mieux vaut la
retrouver avec une règle simple que compter sur le modèle : c'est gratuit,
instantané, et ça donne toujours le même résultat.

Pour l'instant, une seule correction : le poste en cours.
"""

import re
from typing import List

from app.coverage import normalize
from app.schema import CV

# Les mots qui disent qu'un poste dure encore.
_STILL_GOING = re.compile(
    r"\b(depuis|since|à ce jour|a ce jour|aujourd.hui|présent|present|actuel|actuellement|en cours|en poste"
    r"|current|currently|now|to date|ongoing)\b",
    re.IGNORECASE,
)
_BULLET = re.compile(r"^\s*[•\-–*·▪■●]")


def _lines_about(job_title: str, lines: List[str]) -> List[str]:
    """Les passages du CV qui parlent de ce poste : la ligne qui contient son
    intitulé, plus la suivante si c'est une ligne courte sans puce (souvent les dates)."""
    wanted = normalize(job_title)
    passages = []
    for index, line in enumerate(lines):
        if wanted and wanted in normalize(line):
            following = lines[index + 1] if index + 1 < len(lines) else ""
            if len(following) > 60 or _BULLET.match(following):
                following = ""
            passages.append(f"{line} {following}")
    return passages


def fill_current_jobs(cv: CV, source_text: str) -> CV:
    """Un poste sans date de fin, que le CV décrit par « depuis janvier 2019 » ou
    « 2019 – aujourd'hui », reçoit la fin "present".

    Le modèle garde souvent la date de début et oublie que le poste est en
    cours. Par prudence, on exige que l'année de début figure dans le même
    passage que le mot-clé : « depuis » ailleurs dans le CV ne compte pas.
    """
    lines = source_text.splitlines()
    for job in cv.experiences:
        if job.end is not None or not job.start:
            continue
        year = re.search(r"\d{4}", job.start)
        for passage in _lines_about(job.job_title, lines):
            if _STILL_GOING.search(passage) and year and year.group() in passage:
                job.end = "present"
                break
    return cv

"""Corrections faites en Python, d'après le texte d'origine, APRÈS le passage du LLM.

Quand une information est écrite noir sur blanc dans le CV, mieux vaut la
retrouver avec une règle simple que compter sur le modèle : c'est gratuit,
instantané, et ça donne toujours le même résultat.

Deux corrections : le poste en cours, et les coordonnées (e-mail, téléphone).
"""

import difflib
import re
from typing import List, Optional

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


# ----------------------------------------------------- coordonnées --------
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# Un numéro de téléphone : des groupes de chiffres séparés par espace, point ou tiret.
_PHONE = re.compile(r"(?<![\d/])\+?\(?\d{1,4}\)?(?:[ .\-]?\(?\d{1,4}\)?){2,6}(?![\d/])")


def _digits(text: str) -> str:
    return re.sub(r"\D", "", text)


def _closest(value: Optional[str], candidates: List[str]) -> Optional[str]:
    """Le candidat du CV qui correspond à la valeur du modèle.

    - la valeur figure telle quelle dans le CV : on la garde ;
    - un seul candidat dans le CV : c'est forcément lui ;
    - plusieurs : celui qui ressemble le plus à la valeur du modèle, s'il lui ressemble assez.
    """
    if not candidates:
        return value
    if value in candidates:
        return value
    if len(candidates) == 1:
        return candidates[0]
    close = difflib.get_close_matches(value or "", candidates, n=1, cutoff=0.8)
    return close[0] if close else value


def fix_contact(cv: CV, source_text: str) -> CV:
    """L'e-mail et le téléphone sont repris tels qu'ils sont écrits dans le CV.

    Le modèle recopie caractère par caractère, et se trompe parfois d'une
    lettre (vu : « pria.raman@... » pour « priya.raman@... »). Une adresse
    fausse d'une lettre est inutilisable : on la remplace par celle que l'on
    retrouve dans le texte, avec une expression régulière.
    """
    emails = list(dict.fromkeys(match.lower() for match in _EMAIL.findall(source_text)))
    current = cv.identity.email.lower() if cv.identity.email else None
    fixed = _closest(current, emails)
    if fixed != current:
        cv.identity.email = fixed

    # Un vrai numéro a entre 9 et 15 chiffres : cela écarte les années et les codes postaux.
    phones = [match.strip() for match in _PHONE.findall(source_text) if 9 <= len(_digits(match)) <= 15]
    by_digits = {_digits(phone): phone for phone in phones}
    current_digits = _digits(cv.identity.phone or "")
    if current_digits not in by_digits:
        best = _closest(current_digits or None, list(by_digits))
        if best in by_digits:
            cv.identity.phone = by_digits[best]
    return cv


def apply_fixes(cv: CV, source_text: str) -> CV:
    """Toutes les corrections de ce fichier, dans l'ordre."""
    return fix_contact(fill_current_jobs(cv, source_text), source_text)

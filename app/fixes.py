"""Corrections faites en Python, d'après le texte d'origine, APRÈS le passage du LLM.

Quand une information est écrite noir sur blanc dans le CV, mieux vaut la
retrouver avec une règle simple que compter sur le modèle : c'est gratuit,
instantané, et ça donne toujours le même résultat.

Cinq corrections : l'intitulé de poste qui a avalé l'entreprise, le poste en
cours, les coordonnées (e-mail, téléphone), les faux centres d'intérêt, et la
date collée au nom d'une certification.
"""

import difflib
import re
from typing import List, Optional

from app.coverage import normalize
from app.schema import CV, Certification

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


# ------------------------------------------- intitulé + entreprise --------
# Les séparateurs qu'on trouve entre un poste et son entreprise : « — », « – », « | ».
# (Pas le simple tiret : « Responsable marketing - communication » est un seul intitulé.)
_TITLE_SEPARATOR = re.compile(r"\s+[—–|]\s+")


def split_job_titles(cv: CV) -> CV:
    """« Directeur de site — Translog Centre, Saran » -> poste, entreprise et lieu séparés.

    Sur un CV long, le modèle recopie parfois toute la ligne dans l'intitulé
    du poste (vu avec gemma3:4b). Deux cas :
    - l'entreprise est vide : on la reprend dans ce qui suit le séparateur ;
    - l'entreprise est déjà remplie et se retrouve après le séparateur : la
      fin de l'intitulé faisait doublon, on la retire.
    """
    for job in cv.experiences:
        parts = _TITLE_SEPARATOR.split(job.job_title, maxsplit=1)
        if len(parts) != 2 or not parts[0].strip() or not parts[1].strip():
            continue
        head, tail = parts[0].strip(), parts[1].strip()
        if job.company is None:
            company, comma, place = tail.rpartition(", ")
            job.job_title = head
            job.company = company if comma else tail
            if comma and job.location is None:
                job.location = place
        elif normalize(job.company) in normalize(tail):
            job.job_title = head
    return cv


# ----------------------------------------------- centres d'intérêt --------
_INTERESTS_HEADING = re.compile(
    r"int[ée]r[êe]ts?|loisirs|hobbies|interests|passions?|activit[ée]s? (?:extra|personnelles?)|leisure", re.IGNORECASE
)


# Les titres de rubrique d'un CV, pour savoir « sous quel titre » se trouve une ligne.
_CERTIFICATIONS_HEADING = re.compile(r"^(certifications?|certificates?|habilitations?)\b", re.IGNORECASE)
_OTHER_HEADING = re.compile(
    r"^(exp[ée]riences?|parcours|formations?|education|dipl[ôo]mes?|comp[ée]tences|skills|langues|languages"
    r"|profil|profile|summary|r[ée]sum[ée]|coordonn[ée]es|contact|centres? d.int[ée]r[êe]ts?|interests|loisirs|hobbies)\b",
    re.IGNORECASE,
)


def _is_under_certifications(lines: List[str], index: int) -> bool:
    """La ligne n° index est-elle dans la rubrique « Certifications » du CV ?
    On remonte jusqu'au premier titre de rubrique rencontré (une ligne courte)."""
    for line in reversed(lines[:index]):
        if len(line.split()) <= 5:
            if _CERTIFICATIONS_HEADING.match(line.strip()):
                return True
            if _OTHER_HEADING.match(line.strip()):
                return False
    return False


def _rescue_certifications(cv: CV, source_text: str) -> None:
    """Un « centre d'intérêt » qui est en réalité une ligne de la rubrique
    Certifications du CV retourne parmi les certifications (vu sur un CV long :
    la dernière certification et sa date rangées dans les centres d'intérêt)."""
    lines = source_text.splitlines()
    known = {normalize(item.name) for item in cv.certifications}
    for interest in cv.interests:
        wanted = normalize(interest)
        if not wanted or wanted in known or re.fullmatch(r"\d{4}", interest.strip()):
            continue
        index = next((i for i, line in enumerate(lines) if wanted in normalize(line)), None)
        if index is not None and _is_under_certifications(lines, index):
            years = re.findall(r"\b(?:19|20)\d{2}\b", lines[index].replace(interest, ""))
            cv.certifications.append(Certification(name=interest, date=years[-1] if years else None))
            known.add(wanted)


def clean_interests(cv: CV, source_text: str) -> CV:
    """Retire les faux centres d'intérêt.

    Depuis que le CV a une rubrique « centres d'intérêt », le modèle y range
    parfois ce qu'il ne sait pas placer (vu : une certification et sa date).
    Une certification égarée là est d'abord remise à sa place. Ensuite, si
    le CV d'origine n'a aucune rubrique de centres d'intérêt, la liste est
    vidée ; sinon on en retire une année seule et ce qui figure déjà dans les
    compétences ou les certifications.
    """
    _rescue_certifications(cv, source_text)
    if not _INTERESTS_HEADING.search(source_text):
        cv.interests = []
        return cv
    elsewhere = {normalize(skill) for skill in cv.skills} | {normalize(item.name) for item in cv.certifications}
    cv.interests = [
        interest for interest in cv.interests
        if not re.fullmatch(r"\d{4}", interest.strip()) and normalize(interest) not in elsewhere
    ]
    return cv


# ------------------------------------------- date collée au nom -----------
# Une année en fin de nom, précédée d'une virgule, d'un tiret ou entre parenthèses.
_TRAILING_YEAR = re.compile(r"[\s,;–—-]*\(?\b((?:19|20)\d{2})\)?\s*$")


def tidy_certifications(cv: CV) -> CV:
    """« CACES R489 catégories 1, 3 et 5, 2003 » -> nom « CACES R489 catégories 1, 3 et 5 », date « 2003 ».

    Le modèle recopie parfois la ligne entière dans le nom (vu sur le CV long).
    On ne détache l'année que si la date est vide ou dit déjà la même chose.
    """
    for item in cv.certifications:
        match = _TRAILING_YEAR.search(item.name)
        if not match or match.start() == 0:  # pas d'année en fin de nom, ou le nom n'est QUE l'année
            continue
        year = match.group(1)
        if item.date in (None, year):
            item.name, item.date = item.name[: match.start()].strip(), year
    return cv


def apply_fixes(cv: CV, source_text: str) -> CV:
    """Toutes les corrections de ce fichier, dans l'ordre."""
    cv = split_job_titles(cv)  # d'abord : le poste en cours se cherche par l'intitulé
    cv = fill_current_jobs(cv, source_text)
    cv = fix_contact(cv, source_text)
    cv = clean_interests(cv, source_text)  # peut ajouter une certification : avant le rangement ci-dessous
    return tidy_certifications(cv)

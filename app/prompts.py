"""Les prompts envoyés au LLM.

Ils sont volontairement courts et en anglais : sur CPU, chaque token lu ou
écrit coûte du temps, et les petits modèles suivent mieux des consignes
brèves. La FORME de la réponse n'est pas décrite ici : c'est le JSON Schema
(paramètre `format`) qui l'impose.

Chaque règle répond à une erreur réellement observée. La règle sur
"highlights" est longue exprès : avec « max 4 per job », gemma3:4b
complétait jusqu'à 4 en inventant des réalisations ou en recopiant celles
du poste voisin.
"""

from typing import List

SYSTEM_PROMPT = """You convert a CV into JSON.
Rules:
- Copy facts from the CV only. Never invent. Unknown value: null.
- Keep the CV's language. Do not translate.
- experiences: every job and internship in the CV, newest first.
- education: every degree in the CV, newest first.
- Dates: "MM/YYYY" or "YYYY".
- highlights: only the bullet points written under that job, copied as they are. Never add one, never repeat one. A job with one bullet point gets one highlight.
- skills: short keywords only.
- interests: hobbies only, taken from a section named like Interests, Hobbies, Centres d'intérêt or Loisirs. No such section: [].
- job_title: the job name only. The employer goes in company, the city in location.
- Output minified JSON on one line."""


def build_user_prompt(cv_text: str) -> str:
    return f"CV:\n{cv_text}"


def build_repair_prompt(cv_text: str, missing_lines: List[str]) -> str:
    """Relance ciblée : le premier résultat était valide, mais des lignes du CV n'y figuraient pas."""
    quoted = "\n".join(f"- {line}" for line in missing_lines)
    return (
        f"Your previous answer forgot these lines of the CV:\n{quoted}\n"
        f"Answer again with the complete CV. Put each forgotten line in the field where it belongs.\n\nCV:\n{cv_text}"
    )


def build_retry_prompt(cv_text: str, error: str) -> str:
    """Deuxième essai : on redonne le CV en signalant ce qui n'allait pas."""
    return (
        f"Your previous answer was rejected: {error}\n"
        f"Answer again with complete, valid JSON.\n\nCV:\n{cv_text}"
    )

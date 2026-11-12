"""Les prompts envoyés au LLM.

Ils sont volontairement courts et en anglais : sur CPU, chaque token lu ou
écrit coûte du temps, et les petits modèles suivent mieux des consignes
brèves. La FORME de la réponse n'est pas décrite ici : c'est le JSON Schema
(paramètre `format`) qui l'impose.
"""

SYSTEM_PROMPT = """You convert a CV into JSON.
Rules:
- Copy facts from the CV only. Never invent. Unknown value: null.
- Keep the CV's language. Do not translate.
- Include every job (internships too) and every degree, most recent first.
- Dates: "MM/YYYY" or "YYYY".
- highlights: the job's bullet points, max 4 per job.
- skills: short keywords only.
- Output minified JSON on one line."""


def build_user_prompt(cv_text: str) -> str:
    return f"CV:\n{cv_text}"


def build_retry_prompt(cv_text: str, error: str) -> str:
    """Deuxième essai : on redonne le CV en signalant ce qui n'allait pas."""
    return (
        f"Your previous answer was rejected: {error}\n"
        f"Answer again with complete, valid JSON.\n\nCV:\n{cv_text}"
    )

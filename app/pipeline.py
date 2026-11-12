"""Le pipeline complet pour UN CV :

    fichier -> texte (extraction.py) -> JSON (LLM) -> validation Pydantic
            -> 1 nouvel essai si le JSON est invalide -> CV validé
            -> HTML puis PDF (render.py)

Chaque étape est chronométrée (timing.py).
"""

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from pydantic import ValidationError

from app.config import Settings
from app.coverage import find_missing_lines, find_unsupported_values
from app.extraction import ExtractionResult, extract_text
from app.llm.base import LLMProvider, ProgressCallback
from app.prompts import SYSTEM_PROMPT, build_retry_prompt, build_user_prompt
from app.render import PDFUnavailableError, render_html, render_pdf
from app.schema import CV, cv_json_schema
from app.timing import StepTimer, logger

MAX_ATTEMPTS = 2  # 1 essai + 1 retry automatique

# Pour suivre l'avancement : on nous prête une fonction, qu'on appelle avec le
# nom de l'étape en cours ("extraction", "llm", "rendu") et une fraction de 0 à 1.
StepCallback = Callable[[str, float], None]
# Le JSON produit fait à peu près la longueur du texte du CV, plus les noms
# des champs (mesuré sur les faux CV). Sert à estimer l'avancement du LLM.
JSON_OVERHEAD_CHARS = 450


class StructuringError(Exception):
    """Le LLM n'a pas produit de JSON valide, même après le retry."""


@dataclass
class PipelineResult:
    cv: CV
    html: str  # le CV standardisé, en HTML (sert d'aperçu)
    pdf: Optional[bytes]  # le même en PDF, ou None si WeasyPrint est indisponible
    extraction_method: str  # "pdf-text", "pdf-ocr" ou "docx"
    attempts: int  # 1 = bon du premier coup, 2 = il a fallu le retry
    timings: Dict[str, float]  # durée de chaque étape, en secondes
    source_text: str = ""  # le texte extrait du fichier, tel que le LLM l'a reçu
    warnings: List[str] = field(default_factory=list)


def summarize_error(error: ValidationError) -> str:
    """Résume une erreur Pydantic en une phrase courte (elle part dans le prompt du retry)."""
    problems = []
    for detail in error.errors()[:3]:  # 3 problèmes suffisent, le prompt doit rester court
        location = ".".join(str(part) for part in detail["loc"]) or "JSON"
        problems.append(f"{location}: {detail['msg']}")
    return "; ".join(problems)


def structure_cv(
    text: str, provider: LLMProvider, timer: StepTimer, on_progress: Optional[ProgressCallback] = None
) -> Tuple[CV, int]:
    """Demande au LLM de structurer le texte. Renvoie le CV validé et le nombre d'essais."""
    schema = cv_json_schema()
    user_prompt = build_user_prompt(text)
    last_error = ""

    for attempt in range(1, MAX_ATTEMPTS + 1):
        with timer.step("llm"):
            result = provider.generate_json(SYSTEM_PROMPT, user_prompt, schema, on_progress)
        logger.info(
            "[%s] essai %d : %s tokens lus, %s tokens écrits, %s tokens/s",
            timer.label, attempt, result.prompt_tokens, result.output_tokens, result.tokens_per_second,
        )
        if result.truncated:
            logger.warning("[%s] réponse coupée : LLM_MAX_OUTPUT_TOKENS est trop bas pour ce CV", timer.label)

        try:
            with timer.step("validation"):
                cv = CV.model_validate_json(result.text)
            return cv, attempt
        except ValidationError as error:
            last_error = summarize_error(error)
            logger.warning("[%s] essai %d invalide : %s", timer.label, attempt, last_error)
            user_prompt = build_retry_prompt(text, last_error)

    raise StructuringError(
        f"Le modèle n'a pas produit de CV valide après {MAX_ATTEMPTS} essais ({last_error})."
    )


def process_cv(
    data: bytes,
    filename: str,
    provider: LLMProvider,
    settings: Settings,
    on_progress: Optional[StepCallback] = None,
) -> PipelineResult:
    """Traite un fichier CV de bout en bout et renvoie le CV structuré."""
    timer = StepTimer(filename)
    warnings: List[str] = []

    def report(step: str, fraction: float = 0.0) -> None:
        if on_progress:
            on_progress(step, fraction)

    report("extraction")
    with timer.step("extraction"):
        extraction: ExtractionResult = extract_text(data, filename, settings.ocr_languages)

    text = extraction.text
    if len(text) > settings.max_cv_chars:
        text = text[: settings.max_cv_chars]
        warnings.append(
            f"CV très long : seuls les {settings.max_cv_chars} premiers caractères ont été analysés."
        )
    logger.info("[%s] %s, %d page(s), %d caractères", filename, extraction.method, extraction.pages, len(text))

    # Avancement du LLM = caractères déjà écrits / caractères attendus. On
    # plafonne à 97 % : l'estimation n'est pas exacte, la barre ne doit pas
    # afficher 100 % avant la vraie fin.
    expected_chars = len(text) + JSON_OVERHEAD_CHARS
    report("llm")
    cv, attempts = structure_cv(
        text, provider, timer, lambda written: report("llm", min(written / expected_chars, 0.97))
    )
    report("rendu")

    missing = find_missing_lines(text, cv)
    if missing:
        quoted = " ; ".join(f"« {line} »" for line in missing)
        warnings.append(f"À vérifier : ces lignes du CV d'origine ne se retrouvent pas dans le résultat : {quoted}")
        logger.warning("[%s] %d ligne(s) peut-être oubliée(s) par le modèle", filename, len(missing))
    invented = find_unsupported_values(text, cv)
    if invented:
        quoted = " ; ".join(f"« {value} »" for value in invented)
        warnings.append(f"À vérifier : ces valeurs du résultat ne se retrouvent pas dans le CV d'origine : {quoted}")
        logger.warning("[%s] %d valeur(s) peut-être inventée(s) par le modèle", filename, len(invented))

    with timer.step("html"):
        html = render_html(cv)
    pdf = None
    try:
        with timer.step("pdf"):
            pdf = render_pdf(html)
    except PDFUnavailableError as error:
        warnings.append(str(error))  # pas de PDF, mais le JSON et l'aperçu restent utilisables

    logger.info("[%s] terminé en %.1f s (%d essai(s))", filename, timer.total, attempts)

    return PipelineResult(
        cv=cv,
        html=html,
        pdf=pdf,
        extraction_method=extraction.method,
        attempts=attempts,
        timings=dict(timer.steps),
        source_text=text,
        warnings=warnings,
    )

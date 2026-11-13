"""Le pipeline complet pour UN CV :

    fichier -> texte (extraction.py) + photo (photo.py) -> JSON (LLM) -> validation Pydantic
            -> 1 nouvel essai si le JSON est invalide -> CV validé
            -> HTML puis PDF (render.py), diapositive PowerPoint (slides.py)

Chaque étape est chronométrée (timing.py).
"""

import json
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from pydantic import ValidationError

from app.anonymize import anonymize
from app.config import Settings
from app.coverage import find_missing_lines, find_unsupported_values
from app.extraction import ExtractionResult, extract_text
from app.fixes import fill_current_jobs
from app.llm.base import LLMProvider, ProgressCallback
from app.photo import extract_photo
from app import refs
from app.prompts import build_retry_prompt, build_user_prompt, system_prompt
from app.render import PDFUnavailableError, render_html, render_pdf
from app.schema import CV, cv_json_schema
from app.slides import render_pptx
from app.theme import Theme, theme_from_settings
from app.timing import StepTimer, logger

MAX_ATTEMPTS = 2  # 1 essai + 1 retry automatique

# Pour suivre l'avancement : on nous prête une fonction, qu'on appelle avec le
# nom de l'étape en cours ("extraction", "llm", "rendu") et une fraction de 0 à 1.
StepCallback = Callable[[str, float], None]
# Le JSON produit fait à peu près la longueur du texte du CV, plus les noms
# des champs : entre 400 et 800 caractères de plus sur les faux CV. On prend
# large : mieux vaut une barre qui finit d'un coup à 85 % qu'une barre bloquée
# à 97 %. Sert seulement à estimer l'avancement du LLM.
JSON_OVERHEAD_CHARS = 700


class StructuringError(Exception):
    """Le LLM n'a pas produit de JSON valide, même après le retry."""


@dataclass
class PipelineResult:
    cv: CV
    html: str  # le CV standardisé, en HTML (sert d'aperçu)
    pdf: Optional[bytes]  # le même en PDF, ou None si WeasyPrint est indisponible
    pptx: bytes  # le même en une diapositive PowerPoint
    extraction_method: str  # "pdf-text", "pdf-ocr" ou "docx"
    attempts: int  # 1 = bon du premier coup, 2 = il a fallu le retry
    timings: Dict[str, float]  # durée de chaque étape, en secondes
    source_text: str = ""  # le texte extrait du fichier, tel que le LLM l'a reçu
    photo: Optional[bytes] = None  # la photo du candidat trouvée dans le fichier, s'il y en a une
    warnings: List[str] = field(default_factory=list)


def summarize_error(error: ValidationError) -> str:
    """Résume une erreur Pydantic en une phrase courte (elle part dans le prompt du retry)."""
    problems = []
    for detail in error.errors()[:3]:  # 3 problèmes suffisent, le prompt doit rester court
        location = ".".join(str(part) for part in detail["loc"]) or "JSON"
        problems.append(f"{location}: {detail['msg']}")
    return "; ".join(problems)


def structure_cv(
    text: str,
    provider: LLMProvider,
    timer: StepTimer,
    on_progress: Optional[ProgressCallback] = None,
    copy_mode: str = "text",
) -> Tuple[CV, int]:
    """Demande au LLM de structurer le texte. Renvoie le CV validé et le nombre d'essais.

    copy_mode="refs" : mode expérimental où le modèle désigne les lignes par
    leur numéro au lieu de les recopier (voir refs.py).
    """
    use_refs = copy_mode == "refs"
    schema, system, shown_text, segments = cv_json_schema(), system_prompt(), text, []
    if use_refs:
        shown_text, segments = refs.number_lines(text)
        schema, system = refs.refs_schema(schema), system_prompt(refs.REFS_RULES)
    user_prompt = build_user_prompt(shown_text)
    last_error = ""

    for attempt in range(1, MAX_ATTEMPTS + 1):
        with timer.step("llm"):
            result = provider.generate_json(system, user_prompt, schema, on_progress)
        logger.info(
            "[%s] essai %d : %s tokens lus, %s tokens écrits, %s tokens/s",
            timer.label, attempt, result.prompt_tokens, result.output_tokens, result.tokens_per_second,
        )
        if result.truncated:
            logger.warning("[%s] réponse coupée : LLM_MAX_OUTPUT_TOKENS est trop bas pour ce CV", timer.label)

        try:
            with timer.step("validation"):
                if use_refs:
                    # Les numéros de lignes redeviennent du texte, puis validation habituelle.
                    cv = CV.model_validate(refs.resolve(json.loads(result.text), segments))
                else:
                    cv = CV.model_validate_json(result.text)
                cv = fill_current_jobs(cv, text)  # correction sans LLM (voir fixes.py)
            return cv, attempt
        except (ValidationError, json.JSONDecodeError) as error:
            last_error = summarize_error(error) if isinstance(error, ValidationError) else f"invalid JSON: {error}"
            logger.warning("[%s] essai %d invalide : %s", timer.label, attempt, last_error)
            user_prompt = build_retry_prompt(shown_text, last_error)

    raise StructuringError(
        f"Le modèle n'a pas produit de CV valide après {MAX_ATTEMPTS} essais ({last_error})."
    )


@dataclass
class Documents:
    """Les fichiers fabriqués à partir d'un CV validé."""

    html: str
    pdf: Optional[bytes]
    pptx: bytes
    warnings: List[str]


def build_documents(cv: CV, photo: Optional[bytes], theme: Theme, timer: Optional[StepTimer] = None) -> Documents:
    """CV validé (+ photo) -> HTML, PDF et diapositive. Aucun LLM ici.

    Sert après le passage du modèle, et à chaque correction faite à la main.
    """
    timer = timer or StepTimer(cv.identity.full_name)
    warnings: List[str] = []
    with timer.step("html"):
        html = render_html(cv, photo, theme.accent)
    pdf = None
    try:
        with timer.step("pdf"):
            pdf = render_pdf(html)
    except PDFUnavailableError as error:
        warnings.append(str(error))  # pas de PDF, mais le JSON et l'aperçu restent utilisables
    with timer.step("pptx"):
        pptx, slide_notes = render_pptx(cv, photo, theme)
    # Un CV long ne tient pas toujours sur une diapo : on dit ce qui a été raccourci.
    warnings.extend(f"Diapositive : {note}." for note in slide_notes)
    return Documents(html, pdf, pptx, warnings)


def process_cv(
    data: bytes,
    filename: str,
    provider: LLMProvider,
    settings: Settings,
    on_progress: Optional[StepCallback] = None,
    anonymous_number: Optional[int] = None,
) -> PipelineResult:
    """Traite un fichier CV de bout en bout et renvoie le CV structuré.

    `anonymous_number` : si on le donne (3, par exemple), le résultat est
    anonyme : « Candidat 03 », sans coordonnées ni photo.
    """
    timer = StepTimer(filename)
    warnings: List[str] = []

    def report(step: str, fraction: float = 0.0) -> None:
        if on_progress:
            on_progress(step, fraction)

    report("extraction")
    with timer.step("extraction"):
        extraction: ExtractionResult = extract_text(data, filename, settings.ocr_languages)
    with timer.step("photo"):
        photo = extract_photo(data, filename)  # None s'il n'y a pas de photo

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
        text, provider, timer, lambda written: report("llm", min(written / expected_chars, 0.97)),
        copy_mode=settings.llm_copy_mode,
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

    if anonymous_number is not None:
        # À partir d'ici, plus rien ne permet de reconnaître la personne.
        cv, photo, text = anonymize(cv, anonymous_number), None, ""
        # Les alertes citent des lignes du CV d'origine, où le nom peut figurer : on masque le détail.
        warnings = [
            "À vérifier : des écarts avec le CV d'origine ont été relevés (détail masqué : lot anonyme)."
            if warning.startswith("À vérifier") else warning
            for warning in warnings
        ]
        warnings = list(dict.fromkeys(warnings))  # sans doublon, dans le même ordre
    documents = build_documents(cv, photo, theme_from_settings(settings), timer)
    warnings.extend(documents.warnings)

    logger.info("[%s] terminé en %.1f s (%d essai(s))", filename, timer.total, attempts)

    return PipelineResult(
        cv=cv,
        html=documents.html,
        pdf=documents.pdf,
        pptx=documents.pptx,
        photo=photo,
        extraction_method=extraction.method,
        attempts=attempts,
        timings=dict(timer.steps),
        source_text=text,
        warnings=warnings,
    )

"""Point d'entrée du serveur web (FastAPI).

Lancement :  uvicorn app.main:app

Routes :
    GET  /                                  la page web
    GET  /health                            test de vie
    GET  /api/config                        provider utilisé, OCR et PDF disponibles ?
    POST /api/process                       1 CV, la réponse arrive quand il est traité
    POST /api/batch                         plusieurs CV, répond tout de suite (job)
    GET  /api/batch/{job}                   avancement du job
    GET  /api/batch/{job}/items/{n}/{kind}  un résultat (kind = html, json ou pdf)
    GET  /api/batch/{job}/items/{n}/text    le texte extrait du fichier d'origine
    PUT  /api/batch/{job}/items/{n}         enregistre un CV corrigé à la main
    GET  /api/batch/{job}/zip               tous les résultats dans un ZIP
"""

import io
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List, Optional, Tuple

from fastapi import Body, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse, Response
from pydantic import ValidationError

from app import ocr, render
from app.batch import Item, Job, JobQueue
from app.config import OUTPUTS_DIR, Settings, get_settings
from app.llm import LLMProvider, get_provider
from app.pipeline import summarize_error
from app.schema import CV
from app.timing import logger, setup_logging

STATIC_DIR = Path(__file__).resolve().parent / "static"
ALLOWED_EXTENSIONS = {".pdf", ".docx"}
MAX_FILE_BYTES = 15 * 1024 * 1024  # 15 Mo par fichier
MAX_FILES_PER_BATCH = 50
MEDIA_TYPES = {"html": "text/html; charset=utf-8", "json": "application/json", "pdf": "application/pdf"}


def create_app(
    provider: Optional[LLMProvider] = None,
    settings: Optional[Settings] = None,
    outputs_dir: Path = OUTPUTS_DIR,
) -> FastAPI:
    """Fabrique l'application. Les tests passent ici un faux provider."""
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Ce bloc s'exécute une fois, au démarrage du serveur.
        setup_logging()
        # get_provider lève une ConfigError si le .env est incohérent
        # (ex. gemini sans ALLOW_REMOTE=true) : le serveur refuse alors de démarrer.
        llm = provider or get_provider(settings)
        app.state.jobs = JobQueue(llm, settings, outputs_dir)
        app.state.jobs.start()
        logger.info("Provider : %s, modèle : %s", llm.name, llm.model)
        if settings.is_remote:
            logger.warning("ATTENTION : le texte des CV est envoyé hors de cette machine (%s).", llm.name)
        yield

    app = FastAPI(title="CV Standardizer", lifespan=lifespan)

    def read_upload(upload: UploadFile) -> bytes:
        data = upload.file.read()
        if len(data) > MAX_FILE_BYTES:
            raise HTTPException(413, f"« {upload.filename} » dépasse 15 Mo.")
        return data

    def find_job(job_id: str) -> Job:
        job = app.state.jobs.get(job_id)
        if job is None:
            raise HTTPException(404, "Job inconnu (le serveur a peut-être redémarré).")
        return job

    def find_done_item(job_id: str, index: int) -> Tuple[Job, Item]:
        job = find_job(job_id)
        if not 0 <= index < len(job.items) or job.items[index].status != "done":
            raise HTTPException(404, "Ce résultat n'est pas disponible.")
        return job, job.items[index]

    def item_view(job: Job, item: Item) -> dict:
        """Ce que l'API renvoie pour un CV (jamais le contenu du fichier d'origine)."""
        base_url = f"/api/batch/{job.id}/items/{item.index}"
        done = item.status == "done"
        return {
            "index": item.index,
            "filename": item.filename,
            "status": item.status,
            "step": item.step,
            "progress": round(item.progress, 3),
            "edited": item.edited,
            "error": item.error,
            "name": item.cv.identity.full_name if item.cv else None,
            "attempts": item.attempts,
            "extraction_method": item.extraction_method,
            "timings": item.timings,
            "total_seconds": round(sum(item.timings.values()), 2),
            "warnings": item.warnings,
            "links": {
                "html": f"{base_url}/html" if done else None,
                "json": f"{base_url}/json" if done else None,
                "pdf": f"{base_url}/pdf" if done and item.has_pdf else None,
            },
        }

    def job_view(job: Job) -> dict:
        return {"job_id": job.id, "status": job.status, "items": [item_view(job, item) for item in job.items]}

    # ------------------------------------------------------------ routes --
    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "provider": settings.llm_provider}

    @app.get("/api/config")
    def config() -> dict:
        llm = app.state.jobs.provider
        return {
            "provider": llm.name,
            "model": llm.model,
            "remote": settings.is_remote,
            "ocr_engine": ocr.ocr_engine(),  # "tesseract", "apple-vision" ou null
            "pdf_engine": render.pdf_engine(),  # "weasyprint", "navigateur" ou null
        }

    @app.post("/api/process")
    def process_one(file: UploadFile = File(...)) -> dict:
        """Traite un seul CV et attend la fin. Pratique en ligne de commande (curl)."""
        filename = file.filename or "cv"
        if Path(filename).suffix.lower() not in ALLOWED_EXTENSIONS:
            raise HTTPException(400, "Format non pris en charge : envoie un PDF ou un DOCX.")
        job = app.state.jobs.submit([(filename, read_upload(file))])
        job.finished.wait()  # passe par la même file que les lots : un CV à la fois
        item = job.items[0]
        if item.status == "error":
            raise HTTPException(422, item.error)
        return {**item_view(job, item), "job_id": job.id, "cv": item.cv.model_dump()}

    @app.post("/api/batch")
    def create_batch(files: List[UploadFile] = File(...)) -> dict:
        """Reçoit plusieurs CV et répond tout de suite avec l'identifiant du job."""
        if len(files) > MAX_FILES_PER_BATCH:
            raise HTTPException(400, f"Maximum {MAX_FILES_PER_BATCH} fichiers par lot.")
        # Un fichier au mauvais format n'annule pas le lot : il sera marqué en erreur.
        job = app.state.jobs.submit([(upload.filename or "cv", read_upload(upload)) for upload in files])
        return job_view(job)

    @app.get("/api/batch/{job_id}")
    def batch_status(job_id: str) -> dict:
        return job_view(find_job(job_id))

    @app.get("/api/batch/{job_id}/items/{index}/text", response_class=PlainTextResponse)
    def source_text(job_id: str, index: int) -> str:
        """Le texte extrait du fichier d'origine, tel que le LLM l'a reçu."""
        return find_done_item(job_id, index)[1].source_text

    @app.put("/api/batch/{job_id}/items/{index}")
    def save_correction(job_id: str, index: int, corrected: dict = Body(...)) -> dict:
        """Reçoit un CV corrigé à la main, le valide, et régénère HTML et PDF."""
        job, item = find_done_item(job_id, index)
        try:
            cv = CV.model_validate(corrected)  # même validation que pour la réponse du LLM
        except ValidationError as error:
            raise HTTPException(422, f"CV invalide : {summarize_error(error)}")
        app.state.jobs.update_cv(job, item, cv)
        return item_view(job, item)

    @app.get("/api/batch/{job_id}/items/{index}/{kind}")
    def download_result(job_id: str, index: int, kind: str) -> Response:
        job = find_job(job_id)
        if kind not in MEDIA_TYPES or not 0 <= index < len(job.items):
            raise HTTPException(404, "Résultat introuvable.")
        item = job.items[index]
        path = app.state.jobs.job_dir(job) / f"{item.output_stem}.{kind}"
        if item.status != "done" or not path.exists():
            raise HTTPException(404, "Ce résultat n'est pas disponible.")
        if kind == "html":  # l'aperçu s'affiche dans la page, il ne se télécharge pas
            return Response(path.read_bytes(), media_type=MEDIA_TYPES[kind])
        return FileResponse(path, media_type=MEDIA_TYPES[kind], filename=path.name)

    @app.get("/api/batch/{job_id}/zip")
    def download_zip(job_id: str) -> Response:
        """Tous les PDF et JSON du job dans une archive ZIP."""
        job = find_job(job_id)
        folder = app.state.jobs.job_dir(job)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for item in job.items:
                for extension in ("pdf", "json"):
                    path = folder / f"{item.output_stem}.{extension}"
                    if item.status == "done" and path.exists():
                        archive.write(path, path.name)
        return Response(
            buffer.getvalue(),
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="cv_standardises_{job.id}.zip"'},
        )

    return app


app = create_app()

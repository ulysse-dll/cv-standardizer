"""Point d'entrée du serveur web (FastAPI).

Lancement :  uvicorn app.main:app

Routes :
    GET  /                                  la page web
    GET  /health                            test de vie
    GET  /api/config                        provider utilisé, OCR et PDF disponibles ?
    POST /api/process                       1 CV, la réponse arrive quand il est traité
    POST /api/batch                         plusieurs CV, répond tout de suite (job)
    GET  /api/batch/{job}                   avancement du job
    GET  /api/batch/{job}/items/{n}/{kind}  un résultat (kind = html, json, pdf ou pptx)
    GET  /api/batch/{job}/items/{n}/text    le texte extrait du fichier d'origine
    PUT  /api/batch/{job}/items/{n}         enregistre un CV corrigé à la main
    GET  /api/batch/{job}/items/{n}/photo   la photo du candidat
    PUT  .../items/{n}/photo                remplace la photo par une image envoyée
    DELETE .../items/{n}/photo              retire la photo
    GET  /api/batch/{job}/items/{n}/slide   l'image de la diapositive (sur Mac)
    GET  /api/batch/{job}/pptx              un seul PowerPoint pour tout le lot
    GET  /api/batches                       les lots précédents
    DELETE /api/batch/{job}                 supprime un lot et ses fichiers

Si APP_PASSWORD est défini dans .env, le navigateur demande ce mot de passe.
    GET  /api/batch/{job}/zip               tous les résultats dans un ZIP
"""

import base64
import io
import os
import secrets
import time
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List, Optional, Tuple

from fastapi import Body, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse, Response
from pydantic import ValidationError

from app import ocr, preview, render
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
MEDIA_TYPES = {
    "html": "text/html; charset=utf-8",
    "json": "application/json",
    "pdf": "application/pdf",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}


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
        if os.environ.get("HOST", "127.0.0.1") not in ("127.0.0.1", "localhost") and not settings.app_password:
            logger.warning("ATTENTION : serveur joignable depuis le réseau SANS mot de passe (voir APP_PASSWORD).")
        yield

    app = FastAPI(title="CV Standardizer", lifespan=lifespan)

    @app.middleware("http")
    async def require_password(request: Request, call_next):
        """Si APP_PASSWORD est défini, chaque requête doit le présenter.

        On utilise l'authentification « Basic » du web : le navigateur affiche
        lui-même une fenêtre de connexion (le nom d'utilisateur est libre).
        Sans HTTPS, le mot de passe circule en clair : à réserver à un réseau de confiance.
        """
        if settings.app_password and request.url.path != "/health":
            given = ""
            header = request.headers.get("Authorization", "")
            if header.startswith("Basic "):
                try:
                    given = base64.b64decode(header[6:]).decode("utf-8").partition(":")[2]
                except ValueError:
                    pass
            # compare_digest : comparaison qui ne révèle rien par sa durée.
            if not secrets.compare_digest(given.encode(), settings.app_password.encode()):
                return Response(
                    "Mot de passe requis.", status_code=401,
                    headers={"WWW-Authenticate": 'Basic realm="CV Standardizer", charset="UTF-8"'},
                )
        return await call_next(request)

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
        running = item.status == "running" and item.started is not None
        return {
            "index": item.index,
            "filename": item.filename,
            "status": item.status,
            "step": item.step,
            "progress": round(item.progress, 3),
            "elapsed_seconds": round(time.monotonic() - item.started, 1) if running else None,
            "edited": item.edited,
            "has_photo": item.photo is not None,
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
                "pptx": f"{base_url}/pptx" if done else None,
                "photo": f"{base_url}/photo" if done and item.photo else None,
                "slide": f"{base_url}/slide" if done and preview.preview_available() else None,
            },
        }

    def job_view(job: Job) -> dict:
        return {
            "job_id": job.id,
            "status": job.status,
            "anonymous": job.anonymous,
            "created": job.created.isoformat(),
            "items": [item_view(job, item) for item in job.items],
        }

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
            "slide_preview": preview.preview_available(),
            "retention_days": settings.output_retention_days,
        }

    @app.post("/api/process")
    def process_one(file: UploadFile = File(...), anonymous: bool = Form(False)) -> dict:
        """Traite un seul CV et attend la fin. Pratique en ligne de commande (curl)."""
        filename = file.filename or "cv"
        if Path(filename).suffix.lower() not in ALLOWED_EXTENSIONS:
            raise HTTPException(400, "Format non pris en charge : envoie un PDF ou un DOCX.")
        job = app.state.jobs.submit([(filename, read_upload(file))], anonymous)
        job.finished.wait()  # passe par la même file que les lots : un CV à la fois
        item = job.items[0]
        if item.status == "error":
            raise HTTPException(422, item.error)
        return {**item_view(job, item), "job_id": job.id, "cv": item.cv.model_dump()}

    @app.post("/api/batch")
    def create_batch(files: List[UploadFile] = File(...), anonymous: bool = Form(False)) -> dict:
        """Reçoit plusieurs CV et répond tout de suite avec l'identifiant du job.

        anonymous=true : les documents produits sont anonymes (« Candidat 01 »,
        sans coordonnées ni photo).
        """
        if len(files) > MAX_FILES_PER_BATCH:
            raise HTTPException(400, f"Maximum {MAX_FILES_PER_BATCH} fichiers par lot.")
        # Un fichier au mauvais format n'annule pas le lot : il sera marqué en erreur.
        uploads = [(upload.filename or "cv", read_upload(upload)) for upload in files]
        return job_view(app.state.jobs.submit(uploads, anonymous))

    @app.get("/api/batches")
    def list_batches() -> List[dict]:
        """Les lots précédents, du plus récent au plus ancien (ils survivent à un redémarrage)."""
        return [
            {
                "job_id": job.id,
                "status": job.status,
                "anonymous": job.anonymous,
                "created": job.created.isoformat(),
                "total": len(job.items),
                "done": sum(item.status == "done" for item in job.items),
                "names": [item.cv.identity.full_name for item in job.items if item.cv][:4],
            }
            for job in app.state.jobs.all_jobs()
        ]

    @app.delete("/api/batch/{job_id}")
    def delete_batch(job_id: str) -> dict:
        """Supprime un lot terminé : ses fichiers disparaissent du disque."""
        job = find_job(job_id)
        if job.status != "done":
            raise HTTPException(409, "Ce lot est encore en cours de traitement.")
        app.state.jobs.delete(job)
        return {"deleted": job_id}

    @app.get("/api/batch/{job_id}/pptx")
    def download_deck(job_id: str) -> Response:
        """Un seul PowerPoint pour tout le lot : une diapositive par candidat."""
        job = find_job(job_id)
        if not any(item.status == "done" for item in job.items):
            raise HTTPException(404, "Aucun CV prêt dans ce lot.")
        return Response(
            app.state.jobs.deck(job),
            media_type=MEDIA_TYPES["pptx"],
            headers={"Content-Disposition": f'attachment; filename="cv_standardises_{job.id}.pptx"'},
        )

    @app.get("/api/batch/{job_id}")
    def batch_status(job_id: str) -> dict:
        return job_view(find_job(job_id))

    @app.get("/api/batch/{job_id}/items/{index}/text", response_class=PlainTextResponse)
    def source_text(job_id: str, index: int) -> str:
        """Le texte extrait du fichier d'origine, tel que le LLM l'a reçu."""
        return find_done_item(job_id, index)[1].source_text

    @app.get("/api/batch/{job_id}/items/{index}/photo")
    def photo(job_id: str, index: int) -> Response:
        """La photo du candidat, telle qu'elle apparaît sur la diapositive."""
        item = find_done_item(job_id, index)[1]
        if item.photo is None:
            raise HTTPException(404, "Pas de photo pour ce CV.")
        return Response(item.photo, media_type="image/jpeg")

    @app.put("/api/batch/{job_id}/items/{index}/photo")
    def replace_photo(job_id: str, index: int, file: UploadFile = File(...)) -> dict:
        """Remplace (ou ajoute) la photo par une image envoyée, et refait les documents."""
        job, item = find_done_item(job_id, index)
        if job.anonymous:
            raise HTTPException(400, "Ce lot est anonyme : pas de photo.")
        try:
            app.state.jobs.set_photo(job, item, read_upload(file))
        except ValueError as error:
            raise HTTPException(422, str(error))
        return item_view(job, item)

    @app.delete("/api/batch/{job_id}/items/{index}/photo")
    def remove_photo(job_id: str, index: int) -> dict:
        """Retire la photo (le programme a pu se tromper d'image) et refait les documents."""
        job, item = find_done_item(job_id, index)
        app.state.jobs.remove_photo(job, item)
        return item_view(job, item)

    @app.get("/api/batch/{job_id}/items/{index}/slide")
    def slide_image(job_id: str, index: int) -> Response:
        """L'image de la diapositive, pour l'afficher dans la page (Mac uniquement)."""
        job, item = find_done_item(job_id, index)
        image = app.state.jobs.slide_preview(job, item)
        if image is None:
            raise HTTPException(404, "Aperçu de la diapositive indisponible sur cette machine.")
        return Response(image, media_type="image/png")

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
        """Tous les PDF, diapositives et JSON du job dans une archive ZIP."""
        job = find_job(job_id)
        folder = app.state.jobs.job_dir(job)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for item in job.items:
                for extension in ("pdf", "pptx", "json"):
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

"""Tests des routes HTTP, avec un faux LLM et un dossier de sortie temporaire."""

import io
import time
import zipfile

import pytest
from fastapi.testclient import TestClient
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE

from app import batch
from app.config import Settings
from app.main import create_app
from tests.test_pipeline import VALID_JSON, FakeProvider


@pytest.fixture
def client(tmp_path):
    # Le faux LLM répond toujours le même CV valide (20 réponses en réserve).
    app = create_app(provider=FakeProvider([VALID_JSON] * 20), settings=Settings(_env_file=None), outputs_dir=tmp_path)
    with TestClient(app) as test_client:  # "with" déclenche le démarrage de l'app
        yield test_client


def _upload(samples_dir, filename):
    return ("files", (filename, (samples_dir / filename).read_bytes()))


def _wait_until_done(client, job_id):
    for _ in range(100):
        job = client.get(f"/api/batch/{job_id}").json()
        if job["status"] == "done":
            return job
        time.sleep(0.05)
    raise AssertionError("le job n'a pas fini à temps")


def test_health_and_home_page(client):
    assert client.get("/health").json()["status"] == "ok"
    assert "CV Standardizer" in client.get("/").text


def test_config_describes_the_provider(client):
    config = client.get("/api/config").json()
    assert config["provider"] == "fake"
    assert config["remote"] is False


def test_process_one_cv(client, samples_dir):
    data = (samples_dir / "cv_tableaux_fr.docx").read_bytes()
    response = client.post("/api/process", files={"file": ("cv_tableaux_fr.docx", data)})
    assert response.status_code == 200
    body = response.json()
    assert body["cv"]["identity"]["full_name"] == "Inès Benali"
    assert body["status"] == "done"
    assert "llm" in body["timings"]
    # La diapositive PowerPoint se télécharge, avec le bon type de fichier.
    slide_file = client.get(body["links"]["pptx"])
    assert slide_file.status_code == 200
    assert "presentationml" in slide_file.headers["content-type"]
    assert slide_file.content.startswith(b"PK")
    # L'aperçu HTML est servi, et contient le nom.
    assert "Inès Benali" in client.get(body["links"]["html"]).text


def test_process_rejects_other_formats(client):
    response = client.post("/api/process", files={"file": ("cv.txt", b"bonjour")})
    assert response.status_code == 400


def test_process_reports_unreadable_file(client):
    response = client.post("/api/process", files={"file": ("cv.pdf", b"pas un vrai pdf")})
    assert response.status_code == 422
    assert "PDF illisible" in response.json()["detail"]


def test_batch_processes_every_file_and_keeps_going_after_an_error(client, samples_dir):
    files = [
        _upload(samples_dir, "cv_classique_fr.pdf"),
        ("files", ("notes.txt", b"pas un CV")),  # mauvais format, au milieu du lot
        _upload(samples_dir, "cv_tableaux_fr.docx"),
    ]
    created = client.post("/api/batch", files=files)
    assert created.status_code == 200

    job = _wait_until_done(client, created.json()["job_id"])
    assert [item["status"] for item in job["items"]] == ["done", "error", "done"]
    assert "non pris en charge" in job["items"][1]["error"]

    # Le JSON téléchargé est bien un CV.
    cv = client.get(job["items"][0]["links"]["json"]).json()
    assert cv["identity"]["full_name"] == "Inès Benali"

    # Le ZIP contient un JSON par CV réussi.
    archive = zipfile.ZipFile(io.BytesIO(client.get(f"/api/batch/{job['job_id']}/zip").content))
    json_files = [name for name in archive.namelist() if name.endswith(".json")]
    assert json_files == ["01_CV_Ines_Benali.json", "03_CV_Ines_Benali.json"]


def test_running_item_exposes_its_progress(client, samples_dir):
    created = client.post("/api/batch", files=[_upload(samples_dir, "cv_tableaux_fr.docx")]).json()
    assert {"step", "progress", "edited"} <= set(created["items"][0])
    job = _wait_until_done(client, created["job_id"])
    assert job["items"][0]["step"] is None  # plus d'étape en cours une fois terminé


def test_source_text_is_served_for_comparison(client, samples_dir):
    data = (samples_dir / "cv_tableaux_fr.docx").read_bytes()
    body = client.post("/api/process", files={"file": ("cv_tableaux_fr.docx", data)}).json()
    text = client.get(f"/api/batch/{body['job_id']}/items/0/text").text
    assert "Maison Océane" in text


def test_correction_is_saved_and_documents_are_rebuilt(client, samples_dir):
    data = (samples_dir / "cv_tableaux_fr.docx").read_bytes()
    body = client.post("/api/process", files={"file": ("cv_tableaux_fr.docx", data)}).json()
    url = f"/api/batch/{body['job_id']}/items/0"

    corrected = body["cv"]
    corrected["identity"]["full_name"] = "Inès Benali-Martin"
    corrected["skills"] = ["SEO", "Google Ads"]
    response = client.put(url, json=corrected)

    assert response.status_code == 200
    assert response.json()["edited"] is True
    assert response.json()["name"] == "Inès Benali-Martin"
    assert client.get(f"{url}/json").json()["skills"] == ["SEO", "Google Ads"]
    assert "Inès Benali-Martin" in client.get(f"{url}/html").text
    # Les fichiers ont été renommés : il ne reste qu'une version dans le ZIP.
    archive = zipfile.ZipFile(io.BytesIO(client.get(f"/api/batch/{body['job_id']}/zip").content))
    assert sorted(archive.namelist()) == ["01_CV_Ines_Benali_Martin.json", "01_CV_Ines_Benali_Martin.pptx"]
    # La diapositive a été refaite avec le nom corrigé.
    slide = Presentation(io.BytesIO(client.get(f"{url}/pptx").content)).slides[0]
    assert "Inès Benali-Martin" in "\n".join(shape.text_frame.text for shape in slide.shapes if shape.has_text_frame)


def test_invalid_correction_is_refused_and_changes_nothing(client, samples_dir):
    data = (samples_dir / "cv_tableaux_fr.docx").read_bytes()
    body = client.post("/api/process", files={"file": ("cv_tableaux_fr.docx", data)}).json()
    url = f"/api/batch/{body['job_id']}/items/0"

    response = client.put(url, json={"identity": {"full_name": ""}})  # un CV sans nom

    assert response.status_code == 422
    assert "full_name" in response.json()["detail"]
    assert client.get(f"{url}/json").json()["identity"]["full_name"] == "Inès Benali"


def test_unknown_job_is_a_404(client):
    assert client.get("/api/batch/inconnu").status_code == 404
    assert client.get("/api/batch/inconnu/items/0/json").status_code == 404


def test_photo_is_served_then_can_be_removed(client, samples_dir):
    data = (samples_dir / "cv_photo_fr.pdf").read_bytes()
    body = client.post("/api/process", files={"file": ("cv_photo_fr.pdf", data)}).json()
    url = f"/api/batch/{body['job_id']}/items/0"
    assert body["has_photo"] is True

    photo = client.get(body["links"]["photo"])
    assert photo.headers["content-type"] == "image/jpeg"
    has_picture = lambda: any(
        shape.shape_type == MSO_SHAPE_TYPE.PICTURE
        for shape in Presentation(io.BytesIO(client.get(f"{url}/pptx").content)).slides[0].shapes
    )
    assert has_picture()  # la diapositive contient la photo

    removed = client.delete(f"{url}/photo")
    assert removed.status_code == 200
    assert removed.json()["has_photo"] is False and removed.json()["links"]["photo"] is None
    assert client.get(f"{url}/photo").status_code == 404
    assert not has_picture()  # la diapositive a été refaite sans elle


def test_cv_without_photo_has_no_photo_link(client, samples_dir):
    data = (samples_dir / "cv_tableaux_fr.docx").read_bytes()
    body = client.post("/api/process", files={"file": ("cv_tableaux_fr.docx", data)}).json()
    assert body["has_photo"] is False and body["links"]["photo"] is None


def test_keep_awake_runs_caffeinate_only_during_the_block():
    with batch.keep_awake() as process:
        if process is None:  # pas sur Mac : rien à vérifier
            return
        assert process.poll() is None  # caffeinate tourne pendant le lot...
    assert process.poll() is not None  # ...et s'arrête à la fin


def test_keep_awake_does_nothing_without_caffeinate(monkeypatch):
    monkeypatch.setattr(batch.shutil, "which", lambda name: None)
    with batch.keep_awake() as process:
        assert process is None


def test_old_finished_jobs_are_forgotten(client, samples_dir, monkeypatch):
    monkeypatch.setattr(batch, "MAX_JOBS_IN_MEMORY", 2)
    data = (samples_dir / "cv_tableaux_fr.docx").read_bytes()
    job_ids = [
        client.post("/api/process", files={"file": ("cv_tableaux_fr.docx", data)}).json()["job_id"] for _ in range(3)
    ]
    assert client.get(f"/api/batch/{job_ids[0]}").status_code == 404  # le plus ancien a été oublié
    assert client.get(f"/api/batch/{job_ids[2]}").status_code == 200

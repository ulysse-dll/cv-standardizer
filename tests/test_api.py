"""Tests des routes HTTP, avec un faux LLM et un dossier de sortie temporaire."""

import io
import time
import zipfile

import pytest
from fastapi.testclient import TestClient

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


def test_unknown_job_is_a_404(client):
    assert client.get("/api/batch/inconnu").status_code == 404
    assert client.get("/api/batch/inconnu/items/0/json").status_code == 404

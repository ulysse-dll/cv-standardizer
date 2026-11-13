"""Tests des fonctions ajoutées autour du pipeline : lot anonyme, photo, PowerPoint
groupé, aperçu de la diapositive, historique, suppression, mot de passe, thème."""

import base64
import io
import json
import os
import time

import pytest
from fastapi.testclient import TestClient
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE_TYPE

from app import batch, preview
from app.anonymize import anonymize
from app.config import Settings
from app.main import create_app
from app.render import render_html
from app.schema import CV
from app.slides import render_deck, render_pptx
from app.theme import Theme, hex_to_rgb, theme_from_settings
from samples.generate_samples import _png, draw_logo, draw_portrait
from tests.test_pipeline import VALID_JSON, FakeProvider
from tests.test_schema import VALID_CV


def _app(tmp_path, **settings):
    return create_app(provider=FakeProvider([VALID_JSON] * 20), settings=Settings(_env_file=None, **settings), outputs_dir=tmp_path)


@pytest.fixture
def client(tmp_path):
    with TestClient(_app(tmp_path)) as test_client:
        yield test_client


def _process(client, samples_dir, filename="cv_tableaux_fr.docx", **form):
    data = (samples_dir / filename).read_bytes()
    response = client.post("/api/process", files={"file": (filename, data)}, data=form)
    assert response.status_code == 200, response.text
    return response.json()


def _slide_texts(pptx: bytes):
    return [
        "\n".join(shape.text_frame.text for shape in slide.shapes if shape.has_text_frame)
        for slide in Presentation(io.BytesIO(pptx)).slides
    ]


# ------------------------------------------------------------ anonymat ---
def test_anonymize_removes_identity_and_name_mentions():
    cv = CV.model_validate({**VALID_CV, "summary": "Camille Lefèvre a six ans d'expérience. Camille aime Python."})
    hidden = anonymize(cv, 3)
    assert hidden.identity.full_name == "Candidat 03"
    assert (hidden.identity.email, hidden.identity.phone, hidden.identity.location, hidden.identity.links) == (None, None, None, [])
    assert "Camille" not in hidden.summary and "Lefèvre" not in hidden.summary
    assert hidden.experiences[0].company == "Novalys"  # le parcours, lui, reste


def test_anonymous_batch_hides_the_person_everywhere(client, samples_dir):
    body = _process(client, samples_dir, "cv_photo_fr.pdf", anonymous="true")
    url = f"/api/batch/{body['job_id']}/items/0"
    assert body["name"] == "Candidat 01"
    assert body["has_photo"] is False  # la photo du CV n'est pas gardée
    assert client.get(f"/api/batch/{body['job_id']}").json()["anonymous"] is True
    for kind in ("json", "html"):
        text = client.get(f"{url}/{kind}").text
        assert "Benali" not in text and "example.net" not in text
    assert "Benali" not in _slide_texts(client.get(f"{url}/pptx").content)[0]
    assert client.get(f"{url}/text").text == ""  # le texte d'origine contient le nom : il est masqué
    assert client.put(f"{url}/photo", files={"file": ("p.png", _png(draw_portrait(200)))}).status_code == 400


# --------------------------------------------------------------- photo ---
def test_photo_is_in_the_html_and_can_be_replaced(client, samples_dir):
    body = _process(client, samples_dir, "cv_photo_fr.pdf")
    url = f"/api/batch/{body['job_id']}/items/0"
    assert "data:image/jpeg;base64," in client.get(f"{url}/html").text  # la photo est dans le CV (donc dans le PDF)

    before = client.get(f"{url}/photo").content
    replaced = client.put(f"{url}/photo", files={"file": ("p.png", _png(draw_logo()))})
    assert replaced.status_code == 200 and replaced.json()["has_photo"] is True
    assert client.get(f"{url}/photo").content != before

    assert client.delete(f"{url}/photo").json()["has_photo"] is False
    assert "data:image/jpeg;base64," not in client.get(f"{url}/html").text


def test_photo_can_be_added_to_a_cv_that_had_none(client, samples_dir):
    body = _process(client, samples_dir)
    url = f"/api/batch/{body['job_id']}/items/0"
    assert body["has_photo"] is False
    assert client.put(f"{url}/photo", files={"file": ("p.png", _png(draw_portrait(300)))}).json()["has_photo"] is True


def test_a_file_that_is_not_an_image_is_refused(client, samples_dir):
    body = _process(client, samples_dir)
    response = client.put(f"/api/batch/{body['job_id']}/items/0/photo", files={"file": ("p.png", b"pas une image")})
    assert response.status_code == 422 and "image" in response.json()["detail"]


# ---------------------------------------------------- PowerPoint du lot ---
def test_deck_has_one_slide_per_successful_cv(client, samples_dir):
    files = [("files", (name, (samples_dir / name).read_bytes())) for name in ("cv_classique_fr.pdf", "cv_tableaux_fr.docx")]
    files.insert(1, ("files", ("notes.txt", b"pas un CV")))  # un échec au milieu : pas de diapositive
    job_id = client.post("/api/batch", files=files).json()["job_id"]
    for _ in range(200):
        if client.get(f"/api/batch/{job_id}").json()["status"] == "done":
            break
        time.sleep(0.05)
    deck = client.get(f"/api/batch/{job_id}/pptx")
    assert "presentationml" in deck.headers["content-type"]
    assert len(_slide_texts(deck.content)) == 2


def test_render_deck_keeps_the_order():
    first = CV.model_validate({"identity": {"full_name": "Alice Martin"}})
    second = CV.model_validate({"identity": {"full_name": "Bob Durand"}})
    texts = _slide_texts(render_deck([(first, None), (second, None)]))
    assert "Alice Martin" in texts[0] and "Bob Durand" in texts[1]


# ---------------------------------------------- aperçu de la diapositive ---
@pytest.mark.skipif(not preview.preview_available(), reason="Pas de Quick Look (hors Mac)")
def test_slide_preview_is_a_png(client, samples_dir):
    body = _process(client, samples_dir)
    image = client.get(body["links"]["slide"])
    assert image.headers["content-type"] == "image/png"
    assert image.content.startswith(b"\x89PNG")


def test_without_quick_look_there_is_no_slide_link(client, samples_dir, monkeypatch):
    monkeypatch.setattr(preview, "preview_available", lambda: False)
    monkeypatch.setattr(preview, "pptx_to_png", lambda path: None)
    body = _process(client, samples_dir)
    assert body["links"]["slide"] is None
    assert client.get(f"/api/batch/{body['job_id']}/items/0/slide").status_code == 404


# ------------------------------------------- historique et redémarrage ---
def test_batches_survive_a_restart(tmp_path, samples_dir):
    with TestClient(_app(tmp_path)) as first_run:
        body = _process(first_run, samples_dir, "cv_photo_fr.pdf")
    job_id = body["job_id"]

    with TestClient(_app(tmp_path)) as second_run:  # un nouveau serveur, sur le même dossier
        job = second_run.get(f"/api/batch/{job_id}").json()
        item = job["items"][0]
        assert job["status"] == "done" and item["status"] == "done" and item["name"] == "Inès Benali"
        assert item["has_photo"] is True and second_run.get(item["links"]["photo"]).status_code == 200
        assert "Léa Marchand" in second_run.get(f"/api/batch/{job_id}/items/0/text").text
        assert second_run.get(item["links"]["json"]).json()["identity"]["full_name"] == "Inès Benali"
        listed = second_run.get("/api/batches").json()
        assert [entry["job_id"] for entry in listed] == [job_id] and listed[0]["names"] == ["Inès Benali"]
        # Et on peut encore corriger ce CV : les documents sont refaits.
        corrected = second_run.get(item["links"]["json"]).json()
        corrected["title"] = "Titre corrigé après redémarrage"
        assert second_run.put(f"/api/batch/{job_id}/items/0", json=corrected).status_code == 200
        assert "Titre corrigé après redémarrage" in second_run.get(item["links"]["html"]).text


def test_a_batch_interrupted_by_a_shutdown_is_reported(tmp_path):
    folder = tmp_path / "0123456789ab"
    folder.mkdir()
    state = {"id": "0123456789ab", "created": "2026-11-13T10:00:00+00:00", "anonymous": False, "items": [{
        "index": 0, "filename": "cv.pdf", "status": "running", "error": None, "attempts": 0, "extraction_method": None,
        "timings": {}, "warnings": [], "output_stem": None, "has_pdf": False, "edited": False}]}
    (folder / "job.json").write_text(json.dumps(state), encoding="utf-8")
    with TestClient(_app(tmp_path, output_retention_days=0)) as client:
        item = client.get("/api/batch/0123456789ab").json()["items"][0]
        assert item["status"] == "error" and "interrompu" in item["error"]


def test_delete_batch_removes_its_files(client, samples_dir, tmp_path):
    job_id = _process(client, samples_dir)["job_id"]
    assert (tmp_path / job_id / "job.json").exists()
    assert client.delete(f"/api/batch/{job_id}").status_code == 200
    assert not (tmp_path / job_id).exists()
    assert client.get(f"/api/batch/{job_id}").status_code == 404
    assert client.get("/api/batches").json() == []


def test_old_batches_are_deleted_but_other_folders_are_kept(tmp_path, samples_dir):
    with TestClient(_app(tmp_path, output_retention_days=7)) as client:
        job_id = _process(client, samples_dir)["job_id"]
        not_a_batch = tmp_path / "mes_notes"
        not_a_batch.mkdir()
        ten_days_ago = time.time() - 10 * 86400
        os.utime(tmp_path / job_id, (ten_days_ago, ten_days_ago))  # on vieillit le dossier de 10 jours
        os.utime(not_a_batch, (ten_days_ago, ten_days_ago))
        client.app.state.jobs.delete_expired()
        assert not (tmp_path / job_id).exists()
        assert not_a_batch.exists()  # ce n'est pas un lot : on n'y touche pas
        assert client.get(f"/api/batch/{job_id}").status_code == 404


def test_retention_zero_keeps_everything(tmp_path, samples_dir):
    with TestClient(_app(tmp_path, output_retention_days=0)) as client:
        job_id = _process(client, samples_dir)["job_id"]
        long_ago = time.time() - 1000 * 86400
        os.utime(tmp_path / job_id, (long_ago, long_ago))
        client.app.state.jobs.delete_expired()
        assert (tmp_path / job_id).exists()


# -------------------------------------------------------- mot de passe ---
def _basic(password: str) -> dict:
    return {"Authorization": "Basic " + base64.b64encode(f"moi:{password}".encode()).decode()}


def test_password_protects_everything_but_health(tmp_path):
    with TestClient(_app(tmp_path, app_password="s3cret")) as client:
        refused = client.get("/")
        assert refused.status_code == 401 and "Basic" in refused.headers["WWW-Authenticate"]
        assert client.get("/api/batches").status_code == 401
        assert client.get("/api/batches", headers=_basic("mauvais")).status_code == 401
        assert client.get("/api/batches", headers=_basic("s3cret")).status_code == 200
        assert client.get("/", headers=_basic("s3cret")).status_code == 200
        assert client.get("/health").status_code == 200  # reste ouvert, pour les sondes de surveillance


def test_without_password_everything_is_open(client):
    assert client.get("/").status_code == 200


# --------------------------------------------------------------- thème ---
def test_theme_reads_colors_and_ignores_invalid_ones(tmp_path):
    logo = tmp_path / "logo.png"
    logo.write_bytes(_png(draw_logo()))
    theme = theme_from_settings(Settings(_env_file=None, theme_accent="#0b6e4f", theme_stripe="rouge", theme_logo_path=str(logo)))
    assert theme.accent == "#0B6E4F"
    assert theme.stripe == "#E8A33D"  # « rouge » n'est pas une couleur valide : valeur par défaut
    assert theme.logo == logo.read_bytes()
    assert theme_from_settings(Settings(_env_file=None, theme_logo_path="absent.png")).logo is None
    assert hex_to_rgb("#0B6E4F") == (11, 110, 79)


def test_theme_colors_the_slide_and_the_html():
    cv = CV.model_validate(VALID_CV)
    theme = Theme(accent="#0B6E4F", stripe="#FF0000", logo=_png(draw_logo()))
    pptx, _ = render_pptx(cv, None, theme)
    shapes = Presentation(io.BytesIO(pptx)).slides[0].shapes
    fills = [shape.fill.fore_color.rgb for shape in shapes if shape.shape_type == MSO_SHAPE_TYPE.AUTO_SHAPE and shape.fill.type == 1]
    assert RGBColor(0x0B, 0x6E, 0x4F) in fills and RGBColor(0xFF, 0x00, 0x00) in fills
    assert sum(shape.shape_type == MSO_SHAPE_TYPE.PICTURE for shape in shapes) == 1  # le logo
    assert "#0B6E4F" in render_html(cv, None, "#0B6E4F")


def test_jobs_in_memory_constant_is_still_used():
    assert batch.MAX_JOBS_IN_MEMORY >= 1

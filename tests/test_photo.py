"""Tests de la recherche de la photo du candidat dans un CV."""

import io

import fitz
import pytest
from docx import Document
from docx.shared import Inches
from PIL import Image

from app import photo
from app.photo import crop_square, extract_photo
from samples.generate_samples import _png, draw_logo, draw_portrait


@pytest.fixture(autouse=True)
def no_face_detection(monkeypatch):
    """Les portraits de test sont DESSINÉS : aucun détecteur n'y voit un visage.
    On coupe donc la détection, pour que les tests donnent le même résultat sur
    Mac (où elle existe) et ailleurs. Les tests qui en ont besoin la remplacent."""
    monkeypatch.setattr(photo, "detect_faces", lambda image: [])


def _open(jpeg: bytes) -> Image.Image:
    return Image.open(io.BytesIO(jpeg))


def test_photo_is_found_in_the_sample_pdf(samples_dir):
    data = (samples_dir / "cv_photo_fr.pdf").read_bytes()
    image = _open(extract_photo(data, "cv_photo_fr.pdf"))
    assert image.format == "JPEG"
    assert image.size == (500, 500)  # toujours un carré, toujours la même taille
    # C'est bien le portrait (fond bleu clair en haut à gauche), pas le logo du bas de page.
    red, green, blue = image.getpixel((15, 15))
    assert blue > red and blue > 180


@pytest.mark.parametrize("filename", ["cv_classique_fr.pdf", "cv_two_columns_en.pdf", "cv_tableaux_fr.docx", "cv_scanne_fr.pdf"])
def test_cv_without_photo_gives_none(samples_dir, filename):
    assert extract_photo((samples_dir / filename).read_bytes(), filename) is None


def test_a_logo_alone_is_not_taken_for_a_photo():
    document = fitz.open()
    page = document.new_page()
    page.insert_image(fitz.Rect(50, 50, 250, 100), stream=_png(draw_logo()))  # large et plat
    page.insert_image(fitz.Rect(300, 50, 320, 70), stream=_png(draw_portrait(100)))  # minuscule : un pictogramme
    assert extract_photo(document.tobytes(), "logo.pdf") is None


def test_photo_is_found_in_a_docx_and_the_logo_is_ignored():
    document = Document()
    document.add_picture(io.BytesIO(_png(draw_logo())), width=Inches(2))
    document.add_paragraph("Léa Marchand")
    document.add_picture(io.BytesIO(_png(draw_portrait(300))), width=Inches(1.2))
    buffer = io.BytesIO()
    document.save(buffer)

    image = _open(extract_photo(buffer.getvalue(), "cv.docx"))
    assert image.size == (500, 500)
    red, green, blue = image.getpixel((15, 15))
    assert blue > 180  # le fond bleu clair du portrait, pas le logo


def test_unreadable_file_never_raises():
    assert extract_photo(b"pas un pdf", "cv.pdf") is None
    assert extract_photo(b"pas un docx", "cv.docx") is None
    assert extract_photo(b"texte", "cv.txt") is None


def test_crop_square_without_face_keeps_the_top_of_a_portrait():
    # Une image en hauteur, en trois bandes : rouge (lignes 0-14), bleue (15-114), verte (115-199).
    tall = Image.new("RGB", (100, 200), (0, 0, 255))
    tall.paste(Image.new("RGB", (100, 15), (255, 0, 0)), (0, 0))
    tall.paste(Image.new("RGB", (100, 85), (0, 255, 0)), (0, 115))
    square = crop_square(tall)
    assert square.size == (100, 100)
    # Calé vers le haut : on enlève 15 lignes en haut et 85 en bas (pas 50 et 50).
    # Il ne reste donc que la bande bleue.
    assert square.getpixel((50, 0)) == (0, 0, 255)
    assert square.getpixel((50, 99)) == (0, 0, 255)


def test_crop_square_is_centered_on_the_face():
    # Image large : moitié gauche rouge, moitié droite verte. Le "visage" est à droite.
    wide = Image.new("RGB", (400, 200), (255, 0, 0))
    wide.paste(Image.new("RGB", (200, 200), (0, 255, 0)), (200, 0))
    face_on_the_right = (0.70, 0.30, 0.10, 0.20)  # gauche, haut, largeur, hauteur (fractions)
    square = crop_square(wide, face_on_the_right)
    assert square.size == (200, 200)
    assert square.getpixel((100, 100)) == (0, 255, 0)  # le carré a suivi le visage
    assert square.getpixel((5, 100)) == (0, 255, 0)


def test_crop_square_tight_keeps_only_the_surroundings_of_the_face():
    # Page scannée : le visage occupe 10 % de la page -> on ne garde qu'un petit carré autour.
    page = Image.new("RGB", (1000, 1400))
    square = crop_square(page, (0.10, 0.10, 0.10, 0.08), tight=True)
    assert square.size[0] == square.size[1]
    assert 200 <= square.size[0] <= 300  # environ 2,3 fois la taille du visage (112 pixels)


def test_a_detected_face_wins_over_a_bigger_image(monkeypatch):
    # Deux images de forme "photo" : une grande sans visage, une petite avec.
    document = fitz.open()
    page = document.new_page()
    page.insert_image(fitz.Rect(50, 50, 200, 200), stream=_png(Image.new("RGB", (300, 300), (200, 30, 30))))
    page.insert_image(fitz.Rect(300, 50, 380, 130), stream=_png(Image.new("RGB", (300, 300), (30, 30, 200))))
    is_blue = lambda image: image.getpixel((image.width // 2, image.height // 2))[2] > 150
    monkeypatch.setattr(photo, "detect_faces", lambda image: [(0.3, 0.3, 0.4, 0.4)] if is_blue(image) else [])

    image = _open(extract_photo(document.tobytes(), "cv.pdf"))
    assert image.getpixel((250, 250))[2] > 150  # c'est la bleue (celle "avec un visage") qui est choisie

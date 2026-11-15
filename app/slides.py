"""Le CV standardisé sous forme d'UNE diapositive PowerPoint (.pptx).

    CV (Pydantic) + photo éventuelle --python-pptx--> fichier .pptx (une diapo 16:9)

Le modèle de diapo :

    +--------------------------------------------------------------+
    | (photo)  Nom du candidat                                     |  bandeau bleu
    |          Titre                                               |
    |          ville · téléphone · e-mail · lien                   |
    +=================== fin trait de couleur =====================+
    | COMPÉTENCES     |  PROFIL                                    |
    | LANGUES         |  EXPÉRIENCES                               |
    | FORMATION       |   • réalisations                           |
    | CERTIFICATIONS  |                                            |
    +-----------------+--------------------------------------------+
      colonne grise      colonne principale

Sans photo, un rond avec les initiales prend sa place : toutes les diapos
gardent la même allure.

La difficulté : une diapo a une taille fixe, et python-pptx ne sait pas
mesurer un texte. On ESTIME donc la hauteur du texte (nombre de caractères
par ligne), et on réduit la taille de police, puis le nombre de réalisations
par poste, jusqu'à ce que tout tienne.

Pour changer l'allure du modèle, tout est dans les constantes ci-dessous.
"""

import io
import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from PIL import Image, ImageDraw
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, MSO_AUTO_SIZE, PP_ALIGN
from pptx.util import Inches, Pt

from app.render import LABELS, detect_language, period
from app.schema import CV
from app.theme import Theme, hex_to_rgb

# ----- dimensions, en pouces (unité de PowerPoint ; 1 pouce = 72 points) -----
SLIDE_WIDTH, SLIDE_HEIGHT = 13.333, 7.5  # format 16:9
EDGE = 0.55  # marge à gauche et à droite de la diapo
HEADER_HEIGHT = 1.85  # hauteur du bandeau bleu
STRIPE_HEIGHT = 0.07  # le fin trait de couleur sous le bandeau
PHOTO_SIZE = 1.35  # diamètre de la photo ronde
PHOTO_TOP = (HEADER_HEIGHT - PHOTO_SIZE) / 2
HEADER_TEXT_LEFT = EDGE + PHOTO_SIZE + 0.4
HEADER_TEXT_WIDTH = SLIDE_WIDTH - HEADER_TEXT_LEFT - EDGE

BODY_TOP = HEADER_HEIGHT + STRIPE_HEIGHT + 0.33
BODY_HEIGHT = SLIDE_HEIGHT - BODY_TOP - 0.4
PANEL_WIDTH = 4.5  # largeur de la colonne grise
SIDE_TEXT_WIDTH = PANEL_WIDTH - EDGE - 0.4
MAIN_LEFT = PANEL_WIDTH + 0.45
MAIN_TEXT_WIDTH = SLIDE_WIDTH - MAIN_LEFT - EDGE

# ----- couleurs et police -----
FONT = "Arial"  # présente sur Mac comme sur Windows
ACCENT = RGBColor(0x1F, 0x4E, 0x79)  # le bleu du bandeau et des titres de rubrique
STRIPE = RGBColor(0xE8, 0xA3, 0x3D)  # le trait de couleur
PANEL = RGBColor(0xF1, 0xF4, 0xF8)  # le fond de la colonne de gauche
PLACEHOLDER = RGBColor(0x3A, 0x6E, 0xA5)  # le rond des initiales, sans photo
DARK = RGBColor(0x1F, 0x29, 0x33)
GREY = RGBColor(0x52, 0x60, 0x6D)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
PALE = RGBColor(0xC9, 0xDC, 0xEE)  # bleu très clair, lisible sur le bandeau

# Largeur moyenne d'un caractère = 0,5 x la taille de police. Mesuré sur des
# diapos réelles : 0,46 pour Arial. On garde une petite marge de sécurité.
CHAR_WIDTH = 0.5
LINE_HEIGHT = 1.2  # hauteur d'une ligne = 1,2 x la taille de police

MAX_SKILLS = 18
MAX_LINKS = 2
DOT = "\u00a0· "  # espace insécable + point médian : la ligne ne se coupe qu'APRÈS le point
WIDE_DOT = "\u00a0\u00a0·\u00a0 "  # le même, plus aéré (coordonnées, dates)

Run = Tuple[str, bool, RGBColor]  # (texte, gras ?, couleur)


@dataclass
class Line:
    """Un paragraphe de la diapo : un ou plusieurs morceaux de texte."""

    runs: List[Run]
    scale: float = 1.0  # taille par rapport à la taille de base du bloc
    space_before: float = 0.0  # espace au-dessus, en points
    heading: bool = False  # titre de rubrique : lettres légèrement espacées

    @property
    def length(self) -> int:
        return sum(len(text) for text, _, _ in self.runs)


@dataclass
class Fit:
    """Le résultat de l'ajustement : quoi écrire, et à quelle taille."""

    lines: List[Line]
    size: float  # taille de police de base, en points
    dropped: List[str] = field(default_factory=list)  # ce qu'on a dû retirer


def estimated_height(lines: List[Line], size: float, width_inches: float) -> float:
    """Hauteur estimée du texte, en points, pour une taille de police donnée."""
    total = 0.0
    for line in lines:
        font_size = size * line.scale
        chars_per_line = max(1, int(width_inches * 72 / (font_size * CHAR_WIDTH)))
        rows = max(1, math.ceil(line.length / chars_per_line))
        total += rows * font_size * LINE_HEIGHT + line.space_before
    return total


def _heading(text: str, first: bool, accent: RGBColor = ACCENT) -> Line:
    # Pas d'espace au-dessus de la toute première rubrique d'une colonne.
    return Line([(text.upper(), True, accent)], scale=0.85, space_before=0 if first else 13, heading=True)


def _detail(main: Optional[str], extra: Optional[str]) -> Optional[Line]:
    """Une ligne « école · dates » : le premier morceau en foncé, le second en gris."""
    runs: List[Run] = []
    if main:
        runs.append((main, False, DARK))
    if extra:
        runs.append(((DOT if main else "") + extra, False, GREY))
    return Line(runs, scale=0.95) if runs else None


def initials(full_name: str) -> str:
    """ "Camille Lefèvre" -> "CL" : affichées dans le rond quand il n'y a pas de photo."""
    words = [word for word in full_name.replace("-", " ").split() if word[0].isalpha()]
    if not words:
        return "?"
    return (words[0][0] + (words[-1][0] if len(words) > 1 else "")).upper()


# ----------------------------------------------- contenu des trois zones --
def header_lines(cv: CV) -> List[Line]:
    identity = cv.identity
    name_scale = 1.0 if len(identity.full_name) <= 34 else 0.8  # un nom très long est écrit plus petit
    lines = [Line([(identity.full_name, True, WHITE)], scale=name_scale)]
    if cv.title:
        lines.append(Line([(cv.title, False, PALE)], scale=0.5, space_before=2))
    contact = [identity.location, identity.phone, identity.email, *identity.links[:MAX_LINKS]]
    contact = [value for value in contact if value]
    if contact:
        lines.append(Line([(WIDE_DOT.join(contact), False, WHITE)], scale=0.37, space_before=7))
    return lines


def side_lines(cv: CV, labels: dict, max_skills: int = MAX_SKILLS, accent: RGBColor = ACCENT) -> List[Line]:
    """La colonne grise : compétences, langues, formation, certifications, centres d'intérêt."""
    lines: List[Line] = []
    if cv.skills:
        # À l'intérieur d'une compétence courte, les espaces deviennent insécables :
        # « tests utilisateurs » ne sera pas coupé en deux par un retour à la ligne.
        shown = [skill.replace(" ", "\u00a0") if len(skill) <= 28 else skill for skill in cv.skills[:max_skills]]
        text = DOT.join(shown) + (" …" if len(cv.skills) > max_skills else "")
        lines.append(_heading(labels["skills"], not lines, accent))
        lines.append(Line([(text, False, DARK)]))

    if cv.languages:
        lines.append(_heading(labels["languages"], not lines, accent))
        for language in cv.languages:
            runs: List[Run] = [(language.name, True, DARK)]
            if language.level:
                runs.append((f" — {language.level}", False, DARK))
            lines.append(Line(runs))

    if cv.education:
        lines.append(_heading(labels["education"], not lines, accent))
        for index, study in enumerate(cv.education):
            lines.append(Line([(study.degree, True, DARK)], space_before=0 if index == 0 else 5))
            where = ", ".join(part for part in (study.school, study.location) if part)
            detail = _detail(where, period(study.start, study.end, labels["present"]))
            if detail:
                lines.append(detail)

    if cv.certifications:
        lines.append(_heading(labels["certifications"], not lines, accent))
        for index, certification in enumerate(cv.certifications):
            lines.append(Line([(certification.name, True, DARK)], space_before=0 if index == 0 else 5))
            detail = _detail(certification.issuer, certification.date)
            if detail:
                lines.append(detail)

    if cv.interests:
        lines.append(_heading(labels["interests"], not lines, accent))
        lines.append(Line([(DOT.join(cv.interests[:8]), False, DARK)]))
    return lines


def main_lines(cv: CV, labels: dict, max_highlights: int, accent: RGBColor = ACCENT) -> List[Line]:
    """La colonne principale : profil et expériences."""
    lines: List[Line] = []
    if cv.summary:
        lines.append(_heading(labels["summary"], not lines, accent))
        lines.append(Line([(cv.summary, False, DARK)]))

    if cv.experiences:
        lines.append(_heading(labels["experiences"], not lines, accent))
        for index, job in enumerate(cv.experiences):
            where = ", ".join(part for part in (job.company, job.location) if part)
            runs = [(job.job_title, True, DARK)]
            if where:
                runs.append((f" — {where}", False, DARK))
            dates = period(job.start, job.end, labels["present"])
            if dates:
                runs.append((f"{WIDE_DOT}{dates}", False, GREY))
            lines.append(Line(runs, space_before=0 if index == 0 else 7))
            lines.extend(Line([(f"•  {text}", False, DARK)]) for text in job.highlights[:max_highlights])
    return lines


# ------------------------------------------------------- ajustement -------
SIZES_MAIN = (12, 11.5, 11, 10.5, 10, 9.5, 9)
SIZES_SIDE = (11, 10.5, 10, 9.5, 9, 8.5, 8)


def fit_main(cv: CV, labels: dict, accent: RGBColor = ACCENT) -> Fit:
    """Cherche la mise en page la plus lisible qui tient dans la colonne principale.

    On essaie d'abord de tout garder en réduisant la police (de 12 à 9 points).
    Si ça ne suffit pas, on garde moins de réalisations par poste, et on
    recommence. En tout dernier recours, tout est écrit en 8 points.
    """
    available = BODY_HEIGHT * 72
    most = max((len(job.highlights) for job in cv.experiences), default=0)
    for max_highlights in range(min(most, 6), -1, -1):
        lines = main_lines(cv, labels, max_highlights, accent)
        for size in SIZES_MAIN:
            if estimated_height(lines, size, MAIN_TEXT_WIDTH) <= available:
                dropped = []
                if max_highlights < most:
                    dropped.append(
                        f"réalisations limitées à {max_highlights} par poste pour tenir sur la diapositive"
                    )
                return Fit(lines, size, dropped)
    return Fit(main_lines(cv, labels, 0, accent), 8, ["CV trop long pour une diapositive : le texte peut déborder"])


def fit_side(cv: CV, labels: dict, accent: RGBColor = ACCENT) -> Fit:
    """Même principe pour la colonne grise : police réduite, puis moins de compétences."""
    available = BODY_HEIGHT * 72
    for max_skills in (MAX_SKILLS, 12, 8):
        lines = side_lines(cv, labels, max_skills, accent)
        for size in SIZES_SIDE:
            if estimated_height(lines, size, SIDE_TEXT_WIDTH) <= available:
                dropped = []
                if max_skills < min(len(cv.skills), MAX_SKILLS):
                    dropped.append(f"compétences limitées à {max_skills} pour tenir sur la diapositive")
                return Fit(lines, size, dropped)
    return Fit(side_lines(cv, labels, 8, accent), 8, ["colonne de gauche trop longue : le texte peut déborder"])


# ----------------------------------------------------------- écriture -----
def _rectangle(slide, left: float, top: float, width: float, height: float, color: RGBColor):
    shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(left), Inches(top), Inches(width), Inches(height))
    shape.fill.solid()
    shape.fill.fore_color.rgb = color
    shape.line.fill.background()  # pas de bordure
    shape.shadow.inherit = False  # pas d'ombre
    return shape


def _write(slide, left: float, top: float, width: float, height: float, fit: Fit, middle: bool = False) -> None:
    """Pose une zone de texte sur la diapo et y écrit les lignes."""
    box = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(height))
    frame = box.text_frame
    frame.word_wrap = True  # retour à la ligne automatique
    frame.auto_size = MSO_AUTO_SIZE.NONE  # la zone garde sa taille
    frame.vertical_anchor = MSO_ANCHOR.MIDDLE if middle else MSO_ANCHOR.TOP
    frame.margin_left = frame.margin_right = frame.margin_top = frame.margin_bottom = 0

    for index, line in enumerate(fit.lines):
        # Une zone de texte neuve contient déjà un paragraphe vide : on le réutilise.
        paragraph = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
        paragraph.space_before = Pt(line.space_before)
        for text, bold, color in line.runs:
            run = paragraph.add_run()
            run.text = text
            run.font.name = FONT
            run.font.size = Pt(fit.size * line.scale)
            run.font.bold = bold
            run.font.color.rgb = color
            if line.heading:
                # python-pptx n'a pas de réglage pour l'espacement des lettres : on
                # l'écrit directement dans le XML (60 = 0,6 point entre deux lettres).
                run.font._rPr.set("spc", "60")


def round_photo(photo: bytes, size: int = 600) -> bytes:
    """Découpe la photo en rond : renvoie un PNG carré dont les coins sont transparents.

    PowerPoint sait arrondir une image, mais d'autres logiciels (l'aperçu de
    macOS, Google Slides...) l'affichent alors carrée. En découpant l'image
    nous-mêmes, le rond est le même partout.
    """
    image = Image.open(io.BytesIO(photo)).convert("RGB")
    side = min(image.size)
    left, top = (image.width - side) // 2, (image.height - side) // 2
    image = image.crop((left, top, left + side, top + side)).resize((size, size), Image.LANCZOS)
    # Le masque : blanc = visible, noir = transparent. On le dessine 4 fois
    # trop grand puis on le réduit, pour un bord bien lisse.
    mask = Image.new("L", (size * 4, size * 4), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size * 4 - 1, size * 4 - 1), fill=255)
    image.putalpha(mask.resize((size, size), Image.LANCZOS))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _add_photo(slide, cv: CV, photo: Optional[bytes]) -> None:
    """La photo en rond, cerclée de blanc. Sans photo : un rond avec les initiales."""
    left, top, size = Inches(EDGE), Inches(PHOTO_TOP), Inches(PHOTO_SIZE)
    has_photo = False
    if photo:
        try:
            slide.shapes.add_picture(io.BytesIO(round_photo(photo)), left, top, size, size)
            has_photo = True
        except Exception:  # image illisible : on retombe sur les initiales
            pass

    # Le rond : simple cercle blanc par-dessus la photo, ou pastille pleine avec les initiales.
    circle = slide.shapes.add_shape(MSO_SHAPE.OVAL, left, top, size, size)
    circle.line.color.rgb = WHITE
    circle.line.width = Pt(2.25)
    circle.shadow.inherit = False
    if has_photo:
        circle.fill.background()  # pas de remplissage : on voit la photo à travers
        return
    circle.fill.solid()
    circle.fill.fore_color.rgb = PLACEHOLDER
    frame = circle.text_frame
    frame.vertical_anchor = MSO_ANCHOR.MIDDLE
    paragraph = frame.paragraphs[0]
    paragraph.alignment = PP_ALIGN.CENTER
    run = paragraph.add_run()
    run.text = initials(cv.identity.full_name)
    run.font.name, run.font.size, run.font.bold = FONT, Pt(30), True
    run.font.color.rgb = WHITE


LOGO_HEIGHT = 0.75  # hauteur du logo dans le bandeau, en pouces


def _add_logo(slide, logo: bytes) -> float:
    """Pose le logo en haut à droite du bandeau. Renvoie la largeur qu'il occupe (0 si illisible)."""
    try:
        picture = slide.shapes.add_picture(io.BytesIO(logo), 0, 0, height=Inches(LOGO_HEIGHT))
    except Exception:
        return 0.0
    picture.left = Inches(SLIDE_WIDTH - EDGE) - picture.width  # calé à droite
    picture.top = Inches((HEADER_HEIGHT - LOGO_HEIGHT) / 2)
    return picture.width / Inches(1) + 0.4


def new_presentation():
    presentation = Presentation()
    presentation.slide_width = Inches(SLIDE_WIDTH)
    presentation.slide_height = Inches(SLIDE_HEIGHT)
    presentation.core_properties.author = "CV Standardizer"
    return presentation


def add_cv_slide(presentation, cv: CV, photo: Optional[bytes] = None, theme: Optional[Theme] = None) -> List[str]:
    """Ajoute à la présentation la diapositive d'un candidat. Renvoie ce qui a dû être raccourci."""
    theme = theme or Theme()
    accent, stripe = RGBColor(*hex_to_rgb(theme.accent)), RGBColor(*hex_to_rgb(theme.stripe))
    labels = LABELS[detect_language(cv)]
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])  # 6 = diapo vide

    # Les fonds, du dessous vers le dessus : colonne grise, bandeau, trait de couleur.
    panel_top = HEADER_HEIGHT + STRIPE_HEIGHT
    _rectangle(slide, 0, panel_top, PANEL_WIDTH, SLIDE_HEIGHT - panel_top, PANEL)
    _rectangle(slide, 0, 0, SLIDE_WIDTH, HEADER_HEIGHT, accent)
    _rectangle(slide, 0, HEADER_HEIGHT, SLIDE_WIDTH, STRIPE_HEIGHT, stripe)

    _add_photo(slide, cv, photo)
    logo_width = _add_logo(slide, theme.logo) if theme.logo else 0.0
    header = Fit(header_lines(cv), 30)
    _write(slide, HEADER_TEXT_LEFT, 0, HEADER_TEXT_WIDTH - logo_width, HEADER_HEIGHT, header, middle=True)

    side, main = fit_side(cv, labels, accent), fit_main(cv, labels, accent)
    _write(slide, EDGE, BODY_TOP, SIDE_TEXT_WIDTH, BODY_HEIGHT, side)
    _write(slide, MAIN_LEFT, BODY_TOP, MAIN_TEXT_WIDTH, BODY_HEIGHT, main)
    return side.dropped + main.dropped


def _to_bytes(presentation) -> bytes:
    buffer = io.BytesIO()
    presentation.save(buffer)
    return buffer.getvalue()


def render_pptx(cv: CV, photo: Optional[bytes] = None, theme: Optional[Theme] = None) -> Tuple[bytes, List[str]]:
    """Renvoie le fichier .pptx d'UN candidat (en octets) et la liste de ce qui a dû être raccourci.

    `photo` : l'image du candidat (JPEG ou PNG), ou None. `theme` : couleurs et logo.
    """
    presentation = new_presentation()
    notes = add_cv_slide(presentation, cv, photo, theme)
    presentation.core_properties.title = f"CV - {cv.identity.full_name}"
    return _to_bytes(presentation), notes


def render_deck(candidates: List[Tuple[CV, Optional[bytes]]], theme: Optional[Theme] = None) -> bytes:
    """Un seul fichier .pptx pour tout un lot : une diapositive par candidat, dans l'ordre."""
    presentation = new_presentation()
    for cv, photo in candidates:
        add_cv_slide(presentation, cv, photo, theme)
    presentation.core_properties.title = f"CV standardisés ({len(candidates)})"
    return _to_bytes(presentation)

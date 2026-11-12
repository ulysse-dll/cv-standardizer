"""Le CV standardisé sous forme d'UNE diapositive PowerPoint (.pptx).

    CV (Pydantic) --python-pptx--> fichier .pptx (une diapo 16:9)

Mise en page : un bandeau bleu à gauche (nom, contact, compétences, langues)
et le parcours à droite (profil, expériences, formation, certifications).

La difficulté : une diapo a une taille fixe, et python-pptx ne sait pas
mesurer un texte. On ESTIME donc la hauteur du texte (nombre de caractères
par ligne), et on réduit la taille de police, puis le nombre de réalisations
par poste, jusqu'à ce que tout tienne.
"""

import io
import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, MSO_AUTO_SIZE
from pptx.util import Inches, Pt

from app.render import LABELS, detect_language, period
from app.schema import CV

# ----- dimensions, en pouces (unité de PowerPoint ; 1 pouce = 72 points) -----
SLIDE_WIDTH, SLIDE_HEIGHT = 13.333, 7.5  # format 16:9
SIDEBAR_WIDTH = 4.1
MARGIN = 0.45
SIDEBAR_TEXT_WIDTH = SIDEBAR_WIDTH - 2 * MARGIN
MAIN_LEFT = SIDEBAR_WIDTH + MARGIN
MAIN_TEXT_WIDTH = SLIDE_WIDTH - MAIN_LEFT - MARGIN
TEXT_HEIGHT = SLIDE_HEIGHT - 2 * MARGIN

FONT = "Arial"  # présente sur Mac comme sur Windows
ACCENT = RGBColor(0x1F, 0x4E, 0x79)
DARK = RGBColor(0x1F, 0x29, 0x33)
GREY = RGBColor(0x52, 0x60, 0x6D)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
PALE = RGBColor(0xC9, 0xDC, 0xEE)  # bleu très clair, lisible sur le bandeau

# Largeur moyenne d'un caractère = 0,5 x la taille de police. Mesuré sur des
# diapos réelles : 0,46 pour Arial. On garde une petite marge de sécurité.
CHAR_WIDTH = 0.5
LINE_HEIGHT = 1.2  # hauteur d'une ligne = 1,2 x la taille de police

MAX_SKILLS = 18
MAX_LINKS = 3

Run = Tuple[str, bool, RGBColor]  # (texte, gras ?, couleur)


@dataclass
class Line:
    """Un paragraphe de la diapo : un ou plusieurs morceaux de texte."""

    runs: List[Run]
    scale: float = 1.0  # taille par rapport à la taille de base du bloc
    space_before: float = 0.0  # espace au-dessus, en points

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


def _heading(text: str, color: RGBColor) -> Line:
    return Line([(text.upper(), True, color)], scale=0.82, space_before=11)


# -------------------------------------------------- contenu du bandeau ----
def sidebar_lines(cv: CV, labels: dict) -> List[Line]:
    identity = cv.identity
    lines = [Line([(identity.full_name, True, WHITE)], scale=2.3)]
    if cv.title:
        lines.append(Line([(cv.title, False, PALE)], scale=1.2, space_before=3))

    contact = [identity.location, identity.phone, identity.email, *identity.links[:MAX_LINKS]]
    contact = [value for value in contact if value]
    if contact:
        lines.append(_heading(labels["contact"], PALE))
        lines.extend(Line([(value, False, WHITE)]) for value in contact)

    if cv.skills:
        shown = cv.skills[:MAX_SKILLS]
        # " " = espace insécable : la ligne ne peut se couper qu'APRÈS le
        # point médian, jamais avant (sinon une ligne commencerait par " · ").
        text = " · ".join(shown) + (" …" if len(cv.skills) > MAX_SKILLS else "")
        lines.append(_heading(labels["skills"], PALE))
        lines.append(Line([(text, False, WHITE)]))

    if cv.languages:
        lines.append(_heading(labels["languages"], PALE))
        for language in cv.languages:
            level = f" — {language.level}" if language.level else ""
            lines.append(Line([(f"{language.name}{level}", False, WHITE)]))
    return lines


# ------------------------------------------- contenu de la partie droite --
def main_lines(cv: CV, labels: dict, max_highlights: int) -> List[Line]:
    lines: List[Line] = []
    if cv.summary:
        lines.append(_heading(labels["summary"], ACCENT))
        lines.append(Line([(cv.summary, False, DARK)]))

    if cv.experiences:
        lines.append(_heading(labels["experiences"], ACCENT))
        for job in cv.experiences:
            where = ", ".join(part for part in (job.company, job.location) if part)
            dates = period(job.start, job.end, labels["present"])
            runs: List[Run] = [(job.job_title, True, DARK)]
            if where:
                runs.append((f" — {where}", False, DARK))
            if dates:
                runs.append((f"   {dates}", False, GREY))
            lines.append(Line(runs, space_before=5))
            lines.extend(Line([(f"•  {text}", False, DARK)]) for text in job.highlights[:max_highlights])

    if cv.education:
        lines.append(_heading(labels["education"], ACCENT))
        for study in cv.education:
            where = ", ".join(part for part in (study.school, study.location) if part)
            dates = period(study.start, study.end, labels["present"])
            runs = [(study.degree, True, DARK)]
            if where:
                runs.append((f" — {where}", False, DARK))
            if dates:
                runs.append((f"   {dates}", False, GREY))
            lines.append(Line(runs, space_before=2))

    if cv.certifications:
        lines.append(_heading(labels["certifications"], ACCENT))
        for certification in cv.certifications:
            runs = [(certification.name, True, DARK)]
            if certification.issuer:
                runs.append((f" — {certification.issuer}", False, DARK))
            if certification.date:
                runs.append((f"   {certification.date}", False, GREY))
            lines.append(Line(runs, space_before=2))
    return lines


# ------------------------------------------------------- ajustement -------
def fit_main(cv: CV, labels: dict) -> Fit:
    """Cherche la mise en page la plus lisible qui tient sur la diapo.

    On essaie d'abord de tout garder en réduisant la police (de 12 à 9 points).
    Si ça ne suffit pas, on garde moins de réalisations par poste, et on
    recommence. En tout dernier recours, tout est écrit en 8 points.
    """
    available = TEXT_HEIGHT * 72
    most = max((len(job.highlights) for job in cv.experiences), default=0)
    for max_highlights in range(min(most, 6), -1, -1):
        lines = main_lines(cv, labels, max_highlights)
        for size in (12, 11, 10, 9):
            if estimated_height(lines, size, MAIN_TEXT_WIDTH) <= available:
                dropped = []
                if max_highlights < most:
                    dropped.append(
                        f"réalisations limitées à {max_highlights} par poste pour tenir sur la diapositive"
                    )
                return Fit(lines, size, dropped)
    return Fit(main_lines(cv, labels, 0), 8, ["CV trop long pour une diapositive : le texte peut déborder"])


def fit_sidebar(cv: CV, labels: dict) -> Fit:
    lines = sidebar_lines(cv, labels)
    available = TEXT_HEIGHT * 72
    for size in (11, 10, 9, 8):
        if estimated_height(lines, size, SIDEBAR_TEXT_WIDTH) <= available:
            return Fit(lines, size)
    return Fit(lines, 7.5)


# ----------------------------------------------------------- écriture -----
def _write(slide, left: float, width: float, fit: Fit) -> None:
    """Pose une zone de texte sur la diapo et y écrit les lignes."""
    box = slide.shapes.add_textbox(Inches(left), Inches(MARGIN), Inches(width), Inches(TEXT_HEIGHT))
    frame = box.text_frame
    frame.word_wrap = True  # retour à la ligne automatique
    frame.auto_size = MSO_AUTO_SIZE.NONE  # la zone garde sa taille
    frame.vertical_anchor = MSO_ANCHOR.TOP
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


def render_pptx(cv: CV) -> Tuple[bytes, List[str]]:
    """Renvoie le fichier .pptx (en octets) et la liste de ce qui a dû être raccourci."""
    lang = detect_language(cv)
    labels = {**LABELS[lang], "contact": "Contact"}

    presentation = Presentation()
    presentation.slide_width = Inches(SLIDE_WIDTH)
    presentation.slide_height = Inches(SLIDE_HEIGHT)
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])  # 6 = diapo vide

    # Le bandeau bleu de gauche : un simple rectangle, sans bordure.
    band = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, Inches(SIDEBAR_WIDTH), Inches(SLIDE_HEIGHT))
    band.fill.solid()
    band.fill.fore_color.rgb = ACCENT
    band.line.fill.background()
    band.shadow.inherit = False

    sidebar, main = fit_sidebar(cv, labels), fit_main(cv, labels)
    _write(slide, MARGIN, SIDEBAR_TEXT_WIDTH, sidebar)
    _write(slide, MAIN_LEFT, MAIN_TEXT_WIDTH, main)

    presentation.core_properties.title = f"CV - {cv.identity.full_name}"
    presentation.core_properties.author = "CV Standardizer"

    buffer = io.BytesIO()
    presentation.save(buffer)
    return buffer.getvalue(), sidebar.dropped + main.dropped

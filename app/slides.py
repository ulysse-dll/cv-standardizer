"""Le CV standardisé sous forme d'UNE diapositive PowerPoint (.pptx) : la fiche profil.

    CV (Pydantic) + photo éventuelle --python-pptx--> fichier .pptx (une diapo 16:9)

Le modèle de diapo :

    ┌────────────┬──────────────────────────────────────────────┐
    │████████████│  Nom du candidat                     [logo]  │
    │██ (photo) █│  Titre                                       │
    │████████████│  ━━━                                         │
    │COORDONNÉES │ ▌PROFIL                                      │
    │ville, tél. │  Résumé...                                   │
    │LANGUES     │ ▌COMPÉTENCES                                 │
    │FORMATION   │  (Python) (FastAPI) (Docker)   <- pastilles  │
    │CERTIFICAT. │ ▌EXPÉRIENCES PROFESSIONNELLES                │
    │████████████│  01/2021 – auj. ─○ Poste                     │
    │████████████│                  │  Entreprise, Ville        │
    │████████████│                  │  • réalisation            │
    │████████████│  09/2018 – ...  ─○ Poste        <- frise     │
    │████████████│  Profil candidat · Confidentiel       2 / 5  │
    └────────────┴──────────────────────────────────────────────┘
     colonne sombre             partie claire

Sans photo, un rond avec les initiales prend sa place.

La difficulté : une diapo a une taille fixe, et python-pptx ne sait pas
mesurer un texte. On ESTIME donc la hauteur de chaque bloc (nombre de
caractères par ligne), ce qui sert à deux choses :
- placer les blocs les uns sous les autres (chaque poste de la frise a sa
  position, calculée d'après la hauteur des postes précédents) ;
- choisir la mise en page qui tient : on réduit la taille de police, puis le
  nombre de réalisations par poste et de compétences, jusqu'à ce que ça passe.

Les couleurs viennent du thème (voir theme.py) : la colonne sombre est la
couleur principale assombrie, les pastilles la même couleur très éclaircie.
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
from pptx.util import Emu, Inches, Pt

from app.render import LABELS, detect_language, period
from app.schema import CV
from app.theme import Theme, hex_to_rgb

# ----- dimensions, en pouces, sur une diapo 16:9 de 13,333 x 7,5 -----
SLIDE_WIDTH, SLIDE_HEIGHT = 13.333, 7.5

SIDE_WIDTH = 4.05  # la colonne sombre
STRIPE_WIDTH = 0.07  # le liseré de couleur à sa droite
SIDE_PADDING = 0.5
PHOTO_SIZE = 2.0  # diamètre de la photo ronde
PHOTO_TOP = 0.55
SIDE_TEXT_TOP = 2.95
SIDE_TEXT_WIDTH = SIDE_WIDTH - 2 * SIDE_PADDING
SIDE_TEXT_HEIGHT = SLIDE_HEIGHT - SIDE_TEXT_TOP - 0.35

MAIN_LEFT = SIDE_WIDTH + 0.6
EDGE = 0.55  # marge à droite
MAIN_WIDTH = SLIDE_WIDTH - MAIN_LEFT - EDGE
NAME_TOP = 0.48
TITLE_TOP = 1.05
NAME_BAR_TOP = 1.5  # le petit trait de couleur sous le nom
BODY_TOP = 1.8
BODY_BOTTOM = 6.9
BODY_HEIGHT = BODY_BOTTOM - BODY_TOP
FOOTER_TOP = 7.02
LOGO_HEIGHT = 0.6

DATE_WIDTH = 1.6  # frise : la colonne des dates
MARK_WIDTH = 0.42  # frise : la place du trait vertical et de ses pastilles
CONTENT_WIDTH = MAIN_WIDTH - DATE_WIDTH - MARK_WIDTH
JOB_GAP = 0.14  # espace entre deux postes de la frise
BLOCK_GAP = 0.2  # espace entre deux rubriques

# ----- couleurs fixes et police -----
FONT = "Arial"  # présente sur Mac comme sur Windows
ACCENT = RGBColor(0x1F, 0x4E, 0x79)  # couleur principale par défaut (voir theme.py)
RULE = RGBColor(0xC5, 0xCC, 0xD3)  # les traits gris
DARK = RGBColor(0x1F, 0x29, 0x33)
GREY = RGBColor(0x5B, 0x68, 0x75)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)

# Largeur moyenne d'un caractère = 0,5 x la taille de police. Mesuré sur des
# diapos réelles : 0,46 pour Arial. On garde une petite marge de sécurité.
CHAR_WIDTH = 0.5
LINE_HEIGHT = 1.2  # hauteur d'une ligne = 1,2 x la taille de police

MAX_SKILLS = 14
MAX_LINKS = 2
NBSP = chr(0xA0)  # espace insécable
DOT = NBSP + "· "  # espace insécable + point médian : la ligne ne se coupe qu'APRÈS le point

Run = Tuple[str, bool, RGBColor]  # (texte, gras ?, couleur)


@dataclass
class Line:
    """Un paragraphe : un ou plusieurs morceaux de texte."""

    runs: List[Run]
    scale: float = 1.0  # taille par rapport à la taille de base du bloc
    space_before: float = 0.0  # espace au-dessus, en points
    heading: bool = False  # titre de rubrique : lettres légèrement espacées

    @property
    def length(self) -> int:
        return sum(len(text) for text, _, _ in self.runs)


@dataclass
class Palette:
    """Les couleurs d'une fiche, toutes déduites des deux couleurs du thème."""

    accent: RGBColor  # titres, dates, pastilles de la frise
    side: RGBColor  # le fond de la colonne sombre
    mark: RGBColor  # la seconde couleur : liseré, petits traits, titres de la colonne
    pale: RGBColor  # texte secondaire sur fond sombre
    chip: RGBColor  # le fond des pastilles de compétences


def _mix(color: Tuple[int, int, int], target: int, share: float) -> RGBColor:
    """Mélange une couleur avec du noir (target=0) ou du blanc (target=255)."""
    return RGBColor(*(round(channel + (target - channel) * share) for channel in color))


def palette_from_theme(theme: Theme) -> Palette:
    accent = hex_to_rgb(theme.accent)
    return Palette(
        accent=RGBColor(*accent),
        side=_mix(accent, 0, 0.30),  # 30 % plus sombre
        mark=RGBColor(*hex_to_rgb(theme.stripe)),
        pale=_mix(accent, 255, 0.72),
        chip=_mix(accent, 255, 0.87),
    )


def estimated_height(lines: List[Line], size: float, width_inches: float) -> float:
    """Hauteur estimée d'un texte, en points, pour une taille de police donnée."""
    total = 0.0
    for line in lines:
        font_size = size * line.scale
        chars_per_line = max(1, int(width_inches * 72 / (font_size * CHAR_WIDTH)))
        rows = max(1, math.ceil(line.length / chars_per_line))
        total += rows * font_size * LINE_HEIGHT + line.space_before
    return total


def _height(lines: List[Line], size: float, width: float) -> float:
    """La même estimation, en pouces."""
    return estimated_height(lines, size, width) / 72


def initials(full_name: str) -> str:
    """ "Camille Lefèvre" -> "CL" : affichées dans le rond quand il n'y a pas de photo."""
    words = [word for word in full_name.replace("-", " ").split() if word[0].isalpha()]
    if not words:
        return "?"
    return (words[0][0] + (words[-1][0] if len(words) > 1 else "")).upper()


# ------------------------------------------------ la colonne sombre -------
def side_lines(cv: CV, labels: dict, palette: Palette, with_interests: bool = True) -> List[Line]:
    """Coordonnées, langues, formation, certifications, centres d'intérêt."""
    lines: List[Line] = []

    def heading(label: str) -> None:
        # Pas d'espace au-dessus de la toute première rubrique.
        lines.append(Line([(label.upper(), True, palette.mark)], scale=0.84, space_before=13 if lines else 0, heading=True))

    def entries(items: List[Tuple[str, str]]) -> None:
        """Des couples (titre en gras, détail en clair) : diplômes, certifications."""
        for index, (main, detail) in enumerate(items):
            lines.append(Line([(main, True, WHITE)], space_before=1.5 if index == 0 else 5))
            if detail:
                lines.append(Line([(detail, False, palette.pale)], scale=0.93))

    identity = cv.identity
    contact = [value for value in (identity.location, identity.phone, identity.email, *identity.links[:MAX_LINKS]) if value]
    if contact:
        heading(labels["contact"])
        lines.extend(Line([(value, False, WHITE)], space_before=1.5) for value in contact)

    if cv.languages:
        heading(labels["languages"])
        for language in cv.languages:
            runs: List[Run] = [(language.name, True, WHITE)]
            if language.level:
                runs.append((f"  {language.level}", False, palette.pale))
            lines.append(Line(runs, space_before=1.5))

    if cv.education:
        heading(labels["education"])
        entries([
            (study.degree, DOT.join(part for part in (
                ", ".join(p for p in (study.school, study.location) if p), period(study.start, study.end, labels["present"])
            ) if part))
            for study in cv.education
        ])

    if cv.certifications:
        heading(labels["certifications"])
        entries([(item.name, DOT.join(part for part in (item.issuer, item.date) if part)) for item in cv.certifications])

    if cv.interests and with_interests:
        heading(labels["interests"])
        lines.append(Line([(DOT.join(cv.interests[:8]), False, WHITE)], space_before=1.5))
    return lines


@dataclass
class SidePlan:
    lines: List[Line]
    size: float
    dropped: List[str] = field(default_factory=list)


SIZES_SIDE = (10.5, 10, 9.5, 9, 8.5, 8)


def plan_side(cv: CV, labels: dict, palette: Palette, height: float = SIDE_TEXT_HEIGHT) -> SidePlan:
    """La plus grande police qui tient dans la colonne ; à défaut, sans les centres d'intérêt."""
    for with_interests in (True, False):
        lines = side_lines(cv, labels, palette, with_interests)
        for size in SIZES_SIDE:
            if _height(lines, size, SIDE_TEXT_WIDTH) <= height:
                dropped = []
                if cv.interests and not with_interests:
                    dropped.append("centres d'intérêt retirés pour tenir sur la diapositive")
                return SidePlan(lines, size, dropped)
    return SidePlan(side_lines(cv, labels, palette, False), 8, ["colonne de gauche trop longue : le texte peut déborder"])


# ------------------------------------------------- la partie claire -------
def job_lines(job, max_highlights: int, palette: Palette, compact: bool = False) -> List[Line]:
    """Un poste de la frise : intitulé, entreprise et ville, réalisations.

    compact=True : l'entreprise passe sur la ligne de l'intitulé. On gagne une
    ligne par poste, ce qui compte quand il y en a sept.
    """
    where = ", ".join(part for part in (job.company, job.location) if part)
    if compact:
        lines = [Line([(job.job_title, True, DARK)] + ([(f"  —  {where}", False, palette.accent)] if where else []))]
    else:
        lines = [Line([(job.job_title, True, DARK)])]
        if where:
            lines.append(Line([(where, False, palette.accent)], scale=0.95))
    lines += [Line([(f"•  {text}", False, DARK)], scale=0.97) for text in job.highlights[:max_highlights]]
    return lines


def _heading_height(size: float) -> float:
    return size * 1.9 / 72


def _chip_width(text: str, size: float) -> float:
    return len(text) * size * CHAR_WIDTH * 1.08 / 72 + 0.32


def chips_height(items: List[str], size: float, width: float) -> float:
    """Hauteur occupée par des pastilles rangées en lignes de `width` pouces."""
    if not items:
        return 0.0
    chip_height, gap, rows, x = size * 2.0 / 72, 0.08, 1, 0.0
    for item in items:
        chip = _chip_width(item, size)
        if x > 0 and x + chip > width:
            rows, x = rows + 1, 0.0
        x += chip + gap
    return rows * chip_height + (rows - 1) * gap


def main_height(cv: CV, size: float, max_highlights: int, max_skills: int, palette: Palette, compact: bool = False) -> float:
    """Hauteur estimée (en pouces) de tout ce qui se trouve sous le nom."""
    total = 0.0
    if cv.summary:
        total += _heading_height(size) + _height([Line([(cv.summary, False, DARK)])], size, MAIN_WIDTH) + BLOCK_GAP
    if cv.skills and max_skills:
        total += _heading_height(size) + chips_height(cv.skills[:max_skills], size * 0.92, MAIN_WIDTH) + BLOCK_GAP
    if cv.experiences:
        total += _heading_height(size)
        total += sum(
            _height(job_lines(job, max_highlights, palette, compact), size, CONTENT_WIDTH) + JOB_GAP for job in cv.experiences
        )
    return total


@dataclass
class MainPlan:
    size: float  # taille de police
    max_highlights: int  # réalisations gardées par poste
    max_skills: int  # compétences affichées
    compact: bool = False  # entreprise sur la ligne de l'intitulé, pour gagner de la place
    dropped: List[str] = field(default_factory=list)


SIZES_MAIN = (11.5, 11, 10.5, 10, 9.5, 9, 8.5)


def plan_main(cv: CV, palette: Optional[Palette] = None, height: float = BODY_HEIGHT) -> MainPlan:
    """Cherche la mise en page la plus complète qui tient sous le nom.

    On essaie, dans l'ordre : tout garder (en réduisant la police de 11,5 à
    8,5 points) ; puis moins de réalisations par poste ; puis moins de
    compétences ; puis la présentation compacte (entreprise sur la ligne de
    l'intitulé) ; en dernier, plus de réalisations du tout. Les postes, eux,
    sont toujours tous là.
    """
    palette = palette or palette_from_theme(Theme())
    most = min(max((len(job.highlights) for job in cv.experiences), default=0), 5)
    skills = min(len(cv.skills), MAX_SKILLS)
    fewer, few = min(skills, 8), min(skills, 5)  # 5 compétences : une seule ligne de pastilles
    # Chaque essai : (compétences affichées, réalisations par poste, présentation compacte ?)
    candidates = [(skills, kept, False) for kept in range(most, 1, -1)]
    candidates += [(fewer, kept, False) for kept in range(most, 0, -1)]
    candidates += [(fewer, kept, True) for kept in range(min(most, 2), 0, -1)]
    candidates += [(few, 1, True), (few, 0, True), (0, 0, True)]
    if most <= 1:
        candidates.insert(0, (skills, most, False))

    seen = set()
    for max_skills, max_highlights, compact in candidates:
        if (max_skills, max_highlights, compact) in seen:
            continue
        seen.add((max_skills, max_highlights, compact))
        for size in SIZES_MAIN:
            if main_height(cv, size, max_highlights, max_skills, palette, compact) <= height:
                dropped = []
                longest = max((len(job.highlights) for job in cv.experiences), default=0)
                if max_highlights < longest:
                    dropped.append(f"réalisations limitées à {max_highlights} par poste pour tenir sur la diapositive")
                if max_skills < len(cv.skills):
                    dropped.append(f"compétences limitées à {max_skills} pour tenir sur la diapositive")
                return MainPlan(size, max_highlights, max_skills, compact, dropped)
    return MainPlan(8.5, 0, 0, True, ["CV trop long pour une diapositive : le texte peut déborder"])


# ------------------------------------------------------------ dessin ------
class Canvas:
    """Convertit nos mesures (prévues pour une diapo 16:9 de 13,333 x 7,5 pouces)
    vers la taille réelle de la diapo. Sans modèle d'entreprise, rien ne change ;
    avec un modèle d'une autre taille (4:3, par exemple), tout est mis à l'échelle."""

    def __init__(self, presentation):
        self.scale_x = presentation.slide_width / Inches(SLIDE_WIDTH)
        self.scale_y = presentation.slide_height / Inches(SLIDE_HEIGHT)
        self.font_scale = min(self.scale_x, self.scale_y)

    def x(self, inches: float) -> Emu:
        return Emu(int(Inches(inches) * self.scale_x))

    def y(self, inches: float) -> Emu:
        return Emu(int(Inches(inches) * self.scale_y))

    def round(self, inches: float) -> Emu:
        """Pour ce qui doit rester rond (photo, pastilles de la frise) : la même échelle dans les deux sens."""
        return Emu(int(Inches(inches) * self.font_scale))

    def font(self, points: float) -> Pt:
        return Pt(points * self.font_scale)


def _rectangle(slide, canvas: Canvas, left: float, top: float, width: float, height: float, color: RGBColor,
               shape=MSO_SHAPE.RECTANGLE):
    item = slide.shapes.add_shape(shape, canvas.x(left), canvas.y(top), canvas.x(width), canvas.y(height))
    item.fill.solid()
    item.fill.fore_color.rgb = color
    item.line.fill.background()  # pas de bordure
    item.shadow.inherit = False  # pas d'ombre
    return item


def _write_lines(frame, lines: List[Line], size: float, canvas: Canvas, align=None) -> None:
    """Écrit des paragraphes dans une zone de texte."""
    for index, line in enumerate(lines):
        # Une zone de texte neuve contient déjà un paragraphe vide : on le réutilise.
        paragraph = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
        paragraph.space_before = Pt(line.space_before * canvas.font_scale)
        if align is not None:
            paragraph.alignment = align
        for text, bold, color in line.runs:
            run = paragraph.add_run()
            run.text = text
            run.font.name = FONT
            run.font.size = canvas.font(size * line.scale)
            run.font.bold = bold
            run.font.color.rgb = color
            if line.heading:
                # python-pptx n'a pas de réglage pour l'espacement des lettres : on
                # l'écrit directement dans le XML (90 = 0,9 point entre deux lettres).
                run.font._rPr.set("spc", "90")


def _text(slide, canvas: Canvas, left: float, top: float, width: float, height: float,
          lines: List[Line], size: float, align=None, anchor=MSO_ANCHOR.TOP) -> None:
    box = slide.shapes.add_textbox(canvas.x(left), canvas.y(top), canvas.x(width), canvas.y(height))
    frame = box.text_frame
    frame.word_wrap = True  # retour à la ligne automatique
    frame.auto_size = MSO_AUTO_SIZE.NONE  # la zone garde sa taille
    frame.vertical_anchor = anchor
    frame.margin_left = frame.margin_right = frame.margin_top = frame.margin_bottom = 0
    _write_lines(frame, lines, size, canvas, align)


def _heading(slide, canvas: Canvas, left: float, top: float, label: str, size: float, palette: Palette) -> float:
    """Un titre de rubrique précédé d'un petit trait de couleur. Renvoie la hauteur occupée."""
    _rectangle(slide, canvas, left, top + 0.02, 0.07, size * 1.15 / 72, palette.mark)
    _text(slide, canvas, left + 0.17, top, MAIN_WIDTH - 0.17, 0.3, [Line([(label.upper(), True, palette.accent)], heading=True)], size)
    return _heading_height(size)


def _chips(slide, canvas: Canvas, left: float, top: float, width: float, items: List[str], size: float, palette: Palette) -> float:
    """Les compétences en pastilles arrondies, rangées en lignes. Renvoie la hauteur occupée."""
    chip_height, gap = size * 2.0 / 72, 0.08
    x, y = left, top
    for item in items:
        chip = _chip_width(item, size)
        if x > left and x + chip > left + width:
            x, y = left, y + chip_height + gap  # ligne suivante
        shape = _rectangle(slide, canvas, x, y, chip, chip_height, palette.chip, MSO_SHAPE.ROUNDED_RECTANGLE)
        shape.adjustments[0] = 0.5  # coins complètement arrondis
        frame = shape.text_frame
        frame.margin_left = frame.margin_right = frame.margin_top = frame.margin_bottom = 0
        frame.vertical_anchor = MSO_ANCHOR.MIDDLE
        frame.word_wrap = False
        _write_lines(frame, [Line([(item.replace(" ", NBSP), False, palette.accent)])], size, canvas, PP_ALIGN.CENTER)
        x += chip + gap
    return chips_height(items, size, width)


def _timeline(slide, canvas: Canvas, left: float, top: float, cv: CV, labels: dict, plan: MainPlan, palette: Palette) -> None:
    """La frise : dates à gauche, pastille sur un trait vertical, poste et réalisations à droite."""
    tops, y = [], top
    for job in cv.experiences:  # la position de chaque poste dépend de la hauteur des précédents
        tops.append(y)
        y += _height(job_lines(job, plan.max_highlights, palette, plan.compact), plan.size, CONTENT_WIDTH) + JOB_GAP

    dot = plan.size * 0.95 / 72  # diamètre des pastilles, proportionnel au texte
    line_x = left + DATE_WIDTH + MARK_WIDTH / 2
    if len(tops) > 1:  # le trait vertical, de la première pastille à la dernière
        _rectangle(slide, canvas, line_x - 0.01, tops[0] + dot / 2 + 0.03, 0.02, tops[-1] - tops[0], RULE)
    for job, job_top in zip(cv.experiences, tops):
        dates = period(job.start, job.end, labels["present"])
        if dates:
            date_line = [Line([(dates, True, palette.accent)], scale=0.9)]
            _text(slide, canvas, left, job_top, DATE_WIDTH, 0.5, date_line, plan.size, align=PP_ALIGN.RIGHT)
        size = canvas.round(dot)
        center_x, center_y = canvas.x(line_x), canvas.y(job_top + 0.03 + dot / 2)
        circle = slide.shapes.add_shape(MSO_SHAPE.OVAL, center_x - size // 2, center_y - size // 2, size, size)
        circle.fill.solid()
        circle.fill.fore_color.rgb = WHITE
        circle.line.color.rgb = palette.accent
        circle.line.width = Pt(2)
        circle.shadow.inherit = False
        lines = job_lines(job, plan.max_highlights, palette, plan.compact)
        _text(slide, canvas, left + DATE_WIDTH + MARK_WIDTH, job_top, CONTENT_WIDTH,
              _height(lines, plan.size, CONTENT_WIDTH), lines, plan.size)


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


def _add_photo(slide, canvas: Canvas, cv: CV, photo: Optional[bytes], palette: Palette) -> None:
    """La grande photo ronde, en haut de la colonne sombre. Sans photo : un rond avec les initiales."""
    size = canvas.round(PHOTO_SIZE)
    left = canvas.x(SIDE_WIDTH / 2) - size // 2  # centrée dans la colonne
    top = canvas.y(PHOTO_TOP)
    has_photo = False
    if photo:
        try:
            slide.shapes.add_picture(io.BytesIO(round_photo(photo)), left, top, size, size)
            has_photo = True
        except Exception:  # image illisible : on retombe sur les initiales
            pass

    # Le cercle blanc : par-dessus la photo, ou autour de la pastille des initiales.
    circle = slide.shapes.add_shape(MSO_SHAPE.OVAL, left, top, size, size)
    circle.shadow.inherit = False
    circle.line.color.rgb = WHITE
    circle.line.width = Pt(3)
    if has_photo:
        circle.fill.background()  # pas de remplissage : on voit la photo à travers
        return
    circle.fill.solid()
    circle.fill.fore_color.rgb = palette.accent
    frame = circle.text_frame
    frame.vertical_anchor = MSO_ANCHOR.MIDDLE
    paragraph = frame.paragraphs[0]
    paragraph.alignment = PP_ALIGN.CENTER
    run = paragraph.add_run()
    run.text = initials(cv.identity.full_name)
    run.font.name, run.font.size, run.font.bold = FONT, canvas.font(52), True
    run.font.color.rgb = WHITE


def _add_logo(slide, canvas: Canvas, logo: bytes) -> float:
    """Pose le logo en haut à droite. Renvoie la largeur qu'il occupe, en pouces (0 si illisible)."""
    try:
        picture = slide.shapes.add_picture(io.BytesIO(logo), 0, 0, height=canvas.y(LOGO_HEIGHT))
    except Exception:
        return 0.0
    picture.left = canvas.x(SLIDE_WIDTH - EDGE) - picture.width  # calé à droite
    picture.top = canvas.y(NAME_TOP)
    return picture.width / canvas.x(1) + 0.4


# ------------------------------------------------------ présentation ------
_BLANK_LAYOUT_NAMES = {"blank", "vide", "vierge", "leer", "en blanco"}


def new_presentation(theme: Optional[Theme] = None):
    """Une présentation vide : la nôtre (16:9), ou le modèle .pptx de l'entreprise s'il y en a un."""
    if theme and theme.template:
        presentation = Presentation(io.BytesIO(theme.template))
        # Le modèle peut contenir des diapos d'exemple : on les retire toutes.
        slide_ids = presentation.slides._sldIdLst
        for slide_id in list(slide_ids):
            presentation.part.drop_rel(slide_id.rId)
            slide_ids.remove(slide_id)
    else:
        presentation = Presentation()
        presentation.slide_width = Inches(SLIDE_WIDTH)
        presentation.slide_height = Inches(SLIDE_HEIGHT)
    presentation.core_properties.author = "CV Standardizer"
    return presentation


def _blank_layout(presentation):
    """La mise en page la plus vide du modèle : celle qui s'appelle « Vide », sinon celle
    qui a le moins de zones à remplir."""
    layouts = list(presentation.slide_layouts)
    for layout in layouts:
        if layout.name.strip().lower() in _BLANK_LAYOUT_NAMES:
            return layout
    return min(layouts, key=lambda layout: len(layout.placeholders))


def add_cv_slide(
    presentation,
    cv: CV,
    photo: Optional[bytes] = None,
    theme: Optional[Theme] = None,
    page: Optional[Tuple[int, int]] = None,
) -> List[str]:
    """Ajoute à la présentation la fiche d'un candidat. Renvoie ce qui a dû être raccourci.

    `page` : (numéro, total) à afficher en pied de page, pour un PowerPoint de plusieurs fiches.
    """
    theme = theme or Theme()
    own_design = not theme.template  # avec un modèle d'entreprise : ni logo ni pied de page à nous
    palette = palette_from_theme(theme)
    labels = LABELS[detect_language(cv)]
    canvas = Canvas(presentation)
    # Quand la diapo est plus haute que large (modèle 4:3), il y a plus de place en hauteur.
    stretch = canvas.scale_y / canvas.font_scale

    slide = presentation.slides.add_slide(_blank_layout(presentation))
    for placeholder in list(slide.placeholders):  # les zones « Cliquez pour ajouter... » du modèle
        placeholder._element.getparent().remove(placeholder._element)

    # --- la colonne sombre : fond, liseré, photo, texte ---
    _rectangle(slide, canvas, 0, 0, SIDE_WIDTH, SLIDE_HEIGHT, palette.side)
    _rectangle(slide, canvas, SIDE_WIDTH, 0, STRIPE_WIDTH, SLIDE_HEIGHT, palette.mark)
    _add_photo(slide, canvas, cv, photo, palette)
    side = plan_side(cv, labels, palette, SIDE_TEXT_HEIGHT * stretch)
    if side.lines:
        _text(slide, canvas, SIDE_PADDING, SIDE_TEXT_TOP, SIDE_TEXT_WIDTH, SIDE_TEXT_HEIGHT, side.lines, side.size)

    # --- le haut de la partie claire : nom, titre, logo ---
    logo_width = _add_logo(slide, canvas, theme.logo) if own_design and theme.logo else 0.0
    name = cv.identity.full_name
    name_width = MAIN_WIDTH - logo_width
    _text(slide, canvas, MAIN_LEFT, NAME_TOP, name_width, 0.6, [Line([(name, True, palette.side)])], 30 if len(name) <= 30 else 24)
    if cv.title:
        _text(slide, canvas, MAIN_LEFT, TITLE_TOP, name_width, 0.35, [Line([(cv.title, False, palette.accent)])], 15)
    _rectangle(slide, canvas, MAIN_LEFT, NAME_BAR_TOP, 0.9, 0.05, palette.mark)

    # --- profil, compétences, frise : les uns sous les autres ---
    plan = plan_main(cv, palette, BODY_HEIGHT * stretch)
    y = BODY_TOP
    if cv.summary:
        y += _heading(slide, canvas, MAIN_LEFT, y, labels["summary"], plan.size, palette)
        lines = [Line([(cv.summary, False, DARK)])]
        height = _height(lines, plan.size, MAIN_WIDTH)
        _text(slide, canvas, MAIN_LEFT, y, MAIN_WIDTH, height, lines, plan.size)
        y += height + BLOCK_GAP
    skills = cv.skills[: plan.max_skills]
    if skills:
        y += _heading(slide, canvas, MAIN_LEFT, y, labels["skills"], plan.size, palette)
        y += _chips(slide, canvas, MAIN_LEFT, y, MAIN_WIDTH, skills, plan.size * 0.92, palette) + BLOCK_GAP
    if cv.experiences:
        y += _heading(slide, canvas, MAIN_LEFT, y, labels["experiences"], plan.size, palette)
        _timeline(slide, canvas, MAIN_LEFT, y, cv, labels, plan, palette)

    # --- le pied de page ---
    if own_design:
        _rectangle(slide, canvas, MAIN_LEFT, FOOTER_TOP, MAIN_WIDTH, 0.018, RULE)
        footer = theme.footer or labels["footer"]
        _text(slide, canvas, MAIN_LEFT, FOOTER_TOP + 0.08, 6, 0.25, [Line([(footer, False, GREY)])], 8.5)
        if page:
            number = [Line([(f"{page[0]} / {page[1]}", False, GREY)])]
            _text(slide, canvas, MAIN_LEFT + MAIN_WIDTH - 2, FOOTER_TOP + 0.08, 2, 0.25, number, 8.5, align=PP_ALIGN.RIGHT)
    return side.dropped + plan.dropped


def _to_bytes(presentation) -> bytes:
    buffer = io.BytesIO()
    presentation.save(buffer)
    return buffer.getvalue()


def render_pptx(cv: CV, photo: Optional[bytes] = None, theme: Optional[Theme] = None) -> Tuple[bytes, List[str]]:
    """Renvoie le fichier .pptx d'UN candidat (en octets) et la liste de ce qui a dû être raccourci.

    `photo` : l'image du candidat (JPEG ou PNG), ou None. `theme` : couleurs, logo, modèle.
    """
    presentation = new_presentation(theme)
    notes = add_cv_slide(presentation, cv, photo, theme)
    presentation.core_properties.title = f"CV - {cv.identity.full_name}"
    return _to_bytes(presentation), notes


def render_deck(candidates: List[Tuple[CV, Optional[bytes]]], theme: Optional[Theme] = None) -> bytes:
    """Un seul fichier .pptx pour tout un lot : une fiche par candidat, dans l'ordre, numérotées."""
    presentation = new_presentation(theme)
    for number, (cv, photo) in enumerate(candidates, start=1):
        add_cv_slide(presentation, cv, photo, theme, page=(number, len(candidates)))
    presentation.core_properties.title = f"CV standardisés ({len(candidates)})"
    return _to_bytes(presentation)


def slide_texts(pptx: bytes) -> List[str]:
    """Le texte de chaque diapositive d'un fichier .pptx (zones de texte, formes, tableaux).

    Sert à vérifier ce qu'une fiche contient, dans les tests et le diagnostic.
    Les espaces insécables sont rendues comme des espaces normales.
    """
    texts = []
    for slide in Presentation(io.BytesIO(pptx)).slides:
        parts: List[str] = []
        for shape in slide.shapes:
            if shape.has_text_frame and shape.text_frame.text:
                parts.append(shape.text_frame.text)
            if getattr(shape, "has_table", False):
                for row in shape.table.rows:
                    parts.extend(cell.text_frame.text for cell in row.cells)
        texts.append("\n".join(parts).replace(NBSP, " "))
    return texts

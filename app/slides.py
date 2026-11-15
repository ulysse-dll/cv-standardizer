"""Le CV standardisé sous forme d'UNE diapositive PowerPoint (.pptx), au format
« fiche profil » d'entreprise.

    CV (Pydantic) + photo éventuelle --python-pptx--> fichier .pptx (une diapo 16:9)

Le modèle de diapo :

    ▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔  fine barre de couleur
    (photo)  Nom du candidat                            [logo]
             Titre
    ───────────────────────────────────────────────────────────  filet
    ┌──────────────┐  PROFIL
    │ COORDONNÉES  │  ─────────────────────────────────────────
    │ LANGUES      │  Résumé...
    │ FORMATION    │  COMPÉTENCES
    │ CERTIFICATIONS│ ─────────────────────────────────────────
    │ CENTRES      │  EXPÉRIENCES PROFESSIONNELLES
    │ D'INTÉRÊT    │  ─────────────────────────────────────────
    │              │  01/2021 – aujourd'hui   Poste — Entreprise, Ville
    └──────────────┘                          • réalisation
    ───────────────────────────────────────────────────────────
    Profil candidat · Confidentiel                          2 / 5

Les deux colonnes sont des TABLEAUX : chaque ligne s'agrandit toute seule
selon son texte, les dates restent alignées dans leur colonne, et un filet
souligne chaque titre de rubrique.

Sans photo, un rond avec les initiales prend sa place.

La difficulté : une diapo a une taille fixe, et python-pptx ne sait pas
mesurer un texte. On ESTIME donc la hauteur du texte (nombre de caractères
par ligne), et on réduit la taille de police, puis le nombre de réalisations
par poste, jusqu'à ce que tout tienne.

On peut aussi partir du modèle .pptx d'une entreprise (THEME_TEMPLATE_PATH) :
son fond, son logo et son pied de page sont alors repris tels quels, et la
fiche se dessine par-dessus.
"""

import io
import math
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

from PIL import Image, ImageDraw
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, MSO_AUTO_SIZE, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Emu, Inches, Pt

from app.render import LABELS, detect_language, period
from app.schema import CV
from app.theme import Theme, hex_to_rgb

# ----- dimensions, en pouces, sur une diapo 16:9 de 13,333 x 7,5 -----
SLIDE_WIDTH, SLIDE_HEIGHT = 13.333, 7.5
EDGE = 0.55  # marge à gauche et à droite
TOP_BAR_HEIGHT = 0.14  # la fine barre de couleur tout en haut
SECOND_BAR_HEIGHT = 0.035  # le liseré de la seconde couleur, juste dessous
TITLE_TOP = 0.42
TITLE_HEIGHT = 0.92
TITLE_RULE_Y = 1.45  # le filet sous le titre
BODY_TOP = 1.65
BODY_BOTTOM = 6.78
FOOTER_RULE_Y = 6.92
BODY_HEIGHT = BODY_BOTTOM - BODY_TOP

PANEL_WIDTH = 3.2  # la colonne grise de gauche
PANEL_PADDING = 0.2
PHOTO_SIZE = 0.98  # diamètre de la photo ronde, à gauche du nom
TITLE_TEXT_LEFT = EDGE + PHOTO_SIZE + 0.28
SIDE_TEXT_WIDTH = PANEL_WIDTH - 2 * PANEL_PADDING
SIDE_TOP = BODY_TOP + PANEL_PADDING
SIDE_HEIGHT = BODY_BOTTOM - SIDE_TOP - 0.15

MAIN_LEFT = EDGE + PANEL_WIDTH + 0.4
MAIN_TEXT_WIDTH = SLIDE_WIDTH - MAIN_LEFT - EDGE
GUTTER_WIDTH = 1.8  # la colonne des dates, à gauche des expériences
CONTENT_WIDTH = MAIN_TEXT_WIDTH - GUTTER_WIDTH

# ----- couleurs et police -----
FONT = "Arial"  # présente sur Mac comme sur Windows
ACCENT = RGBColor(0x1F, 0x4E, 0x79)  # couleur par défaut (voir theme.py)
PANEL = RGBColor(0xF3, 0xF5, 0xF8)  # le fond de la colonne de gauche
RULE = RGBColor(0xC5, 0xCC, 0xD3)  # les filets gris
DARK = RGBColor(0x1F, 0x29, 0x33)
GREY = RGBColor(0x52, 0x60, 0x6D)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)

# Largeur moyenne d'un caractère = 0,5 x la taille de police. Mesuré sur des
# diapos réelles : 0,46 pour Arial. On garde une petite marge de sécurité.
CHAR_WIDTH = 0.5
LINE_HEIGHT = 1.2  # hauteur d'une ligne = 1,2 x la taille de police
CELL_BOTTOM = 3.0  # petite marge sous le texte de chaque ligne de tableau, en points

MAX_SKILLS = 18
MAX_LINKS = 2
NBSP = "\u00a0"  # espace insécable (écrite ainsi pour rester visible dans le code)
DOT = NBSP + "· "  # espace insécable + point médian : la ligne ne se coupe qu'APRÈS le point
NO_TABLE_STYLE = "{2D5ABB26-0587-4C30-8999-92F81FD0307C}"  # le style de tableau « aucun » de PowerPoint

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
class Row:
    """Une ligne de tableau : une cellule (sur toute la largeur) ou deux (dates | contenu)."""

    cells: List[List[Line]]
    heading: bool = False  # titre de rubrique : souligné d'un filet de couleur
    rule: bool = False  # filet gris en dessous (entre deux postes)
    space_before: float = 0.0  # marge au-dessus, en points


@dataclass
class Fit:
    """Le résultat de l'ajustement : quoi écrire, et à quelle taille."""

    rows: List[Row]
    size: float  # taille de police de base, en points
    dropped: List[str] = field(default_factory=list)  # ce qu'on a dû retirer

    @property
    def lines(self) -> List[Line]:
        """Tous les paragraphes, à plat (pratique pour les tests)."""
        return [line for row in self.rows for cell in row.cells for line in cell]


def estimated_height(lines: List[Line], size: float, width_inches: float) -> float:
    """Hauteur estimée d'un texte, en points, pour une taille de police donnée."""
    total = 0.0
    for line in lines:
        font_size = size * line.scale
        chars_per_line = max(1, int(width_inches * 72 / (font_size * CHAR_WIDTH)))
        rows = max(1, math.ceil(line.length / chars_per_line))
        total += rows * font_size * LINE_HEIGHT + line.space_before
    return total


def rows_height(rows: List[Row], size: float, widths: Sequence[float]) -> float:
    """Hauteur estimée d'un tableau : pour chaque ligne, sa cellule la plus haute."""
    total = 0.0
    for row in rows:
        cell_widths = widths if len(row.cells) > 1 else [sum(widths)]
        tallest = max(estimated_height(cell, size, width) for cell, width in zip(row.cells, cell_widths))
        total += tallest + row.space_before + CELL_BOTTOM
    return total


def _heading_row(text: str, first: bool, accent: RGBColor) -> Row:
    # Pas d'espace au-dessus de la toute première rubrique d'une colonne.
    line = Line([(text.upper(), True, accent)], scale=0.86, heading=True)
    return Row([[line]], heading=True, space_before=0 if first else 11)


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


# ------------------------------------------------- contenu des colonnes ---
def side_rows(cv: CV, labels: dict, accent: RGBColor = ACCENT, with_interests: bool = True) -> List[Row]:
    """La colonne grise : coordonnées, langues, formation, certifications, centres d'intérêt."""
    rows: List[Row] = []
    identity = cv.identity
    contact = [identity.location, identity.phone, identity.email, *identity.links[:MAX_LINKS]]
    contact = [value for value in contact if value]
    if contact:
        rows.append(_heading_row(labels["contact"], not rows, accent))
        rows.append(Row([[Line([(value, False, DARK)]) for value in contact]], space_before=3))

    if cv.languages:
        rows.append(_heading_row(labels["languages"], not rows, accent))
        lines = []
        for language in cv.languages:
            runs: List[Run] = [(language.name, True, DARK)]
            if language.level:
                runs.append((f" — {language.level}", False, DARK))
            lines.append(Line(runs))
        rows.append(Row([lines], space_before=3))

    if cv.education:
        rows.append(_heading_row(labels["education"], not rows, accent))
        lines = []
        for index, study in enumerate(cv.education):
            lines.append(Line([(study.degree, True, DARK)], space_before=0 if index == 0 else 4))
            where = ", ".join(part for part in (study.school, study.location) if part)
            detail = _detail(where, period(study.start, study.end, labels["present"]))
            if detail:
                lines.append(detail)
        rows.append(Row([lines], space_before=3))

    if cv.certifications:
        rows.append(_heading_row(labels["certifications"], not rows, accent))
        lines = []
        for index, certification in enumerate(cv.certifications):
            lines.append(Line([(certification.name, True, DARK)], space_before=0 if index == 0 else 4))
            detail = _detail(certification.issuer, certification.date)
            if detail:
                lines.append(detail)
        rows.append(Row([lines], space_before=3))

    if cv.interests and with_interests:
        rows.append(_heading_row(labels["interests"], not rows, accent))
        rows.append(Row([[Line([(DOT.join(cv.interests[:8]), False, DARK)])]], space_before=3))
    return rows


def main_rows(cv: CV, labels: dict, max_highlights: int, accent: RGBColor = ACCENT) -> List[Row]:
    """La colonne principale : profil, compétences, expériences (dates | poste et réalisations)."""
    rows: List[Row] = []
    if cv.summary:
        rows.append(_heading_row(labels["summary"], not rows, accent))
        rows.append(Row([[Line([(cv.summary, False, DARK)])]], space_before=3))

    if cv.skills:
        # À l'intérieur d'une compétence courte, les espaces deviennent insécables :
        # « tests utilisateurs » ne sera pas coupé en deux par un retour à la ligne.
        shown = [skill.replace(" ", NBSP) if len(skill) <= 28 else skill for skill in cv.skills[:MAX_SKILLS]]
        text = DOT.join(shown) + (" …" if len(cv.skills) > MAX_SKILLS else "")
        rows.append(_heading_row(labels["skills"], not rows, accent))
        rows.append(Row([[Line([(text, False, DARK)])]], space_before=3))

    if cv.experiences:
        rows.append(_heading_row(labels["experiences"], not rows, accent))
        for index, job in enumerate(cv.experiences):
            where = ", ".join(part for part in (job.company, job.location) if part)
            title: List[Run] = [(job.job_title, True, DARK)]
            if where:
                title.append((f" — {where}", False, DARK))
            content = [Line(title)]
            content += [Line([(f"•  {text}", False, DARK)]) for text in job.highlights[:max_highlights]]
            dates = period(job.start, job.end, labels["present"])
            gutter = [Line([(dates, False, GREY)], scale=0.92)]
            last = index == len(cv.experiences) - 1
            rows.append(Row([gutter, content], rule=not last, space_before=4))
    return rows


# ------------------------------------------------------- ajustement -------
SIZES_MAIN = (11.5, 11, 10.5, 10, 9.5, 9)
SIZES_SIDE = (10, 9.5, 9, 8.5, 8)


def fit_main(cv: CV, labels: dict, accent: RGBColor = ACCENT, height: float = BODY_HEIGHT) -> Fit:
    """Cherche la mise en page la plus lisible qui tient dans la colonne principale.

    On essaie d'abord de tout garder en réduisant la police (de 11,5 à 9 points).
    Si ça ne suffit pas, on garde moins de réalisations par poste, et on
    recommence. En tout dernier recours, tout est écrit en 8 points.
    """
    available = height * 72
    widths = (GUTTER_WIDTH, CONTENT_WIDTH)
    most = max((len(job.highlights) for job in cv.experiences), default=0)
    for max_highlights in range(min(most, 6), -1, -1):
        rows = main_rows(cv, labels, max_highlights, accent)
        for size in SIZES_MAIN:
            if rows_height(rows, size, widths) <= available:
                dropped = []
                if max_highlights < most:
                    dropped.append(
                        f"réalisations limitées à {max_highlights} par poste pour tenir sur la diapositive"
                    )
                return Fit(rows, size, dropped)
    return Fit(main_rows(cv, labels, 0, accent), 8, ["CV trop long pour une diapositive : le texte peut déborder"])


def fit_side(cv: CV, labels: dict, accent: RGBColor = ACCENT, height: float = SIDE_HEIGHT) -> Fit:
    """Même principe pour la colonne grise : police réduite, puis on renonce aux centres d'intérêt."""
    available = height * 72
    for with_interests in (True, False):
        rows = side_rows(cv, labels, accent, with_interests)
        for size in SIZES_SIDE:
            if rows_height(rows, size, [SIDE_TEXT_WIDTH]) <= available:
                dropped = []
                if cv.interests and not with_interests:
                    dropped.append("centres d'intérêt retirés pour tenir sur la diapositive")
                return Fit(rows, size, dropped)
    return Fit(side_rows(cv, labels, accent, False), 8, ["colonne de gauche trop longue : le texte peut déborder"])


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

    def font(self, points: float) -> Pt:
        return Pt(points * self.font_scale)


def _rectangle(slide, canvas: Canvas, left: float, top: float, width: float, height: float, color: RGBColor):
    shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, canvas.x(left), canvas.y(top), canvas.x(width), canvas.y(height))
    shape.fill.solid()
    shape.fill.fore_color.rgb = color
    shape.line.fill.background()  # pas de bordure
    shape.shadow.inherit = False  # pas d'ombre
    return shape


def _rule(slide, canvas: Canvas, top: float, color: RGBColor = RULE, width_points: float = 0.75) -> None:
    """Un filet horizontal sur toute la largeur utile de la diapo."""
    line = slide.shapes.add_connector(
        MSO_CONNECTOR.STRAIGHT, canvas.x(EDGE), canvas.y(top), canvas.x(SLIDE_WIDTH - EDGE), canvas.y(top)
    )
    line.line.color.rgb = color
    line.line.width = Pt(width_points)


def _write_lines(frame, lines: List[Line], size: float, canvas: Canvas) -> None:
    """Écrit des paragraphes dans une zone de texte ou une cellule de tableau."""
    frame.word_wrap = True  # retour à la ligne automatique
    for index, line in enumerate(lines):
        # Une zone de texte neuve contient déjà un paragraphe vide : on le réutilise.
        paragraph = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
        paragraph.space_before = Pt(line.space_before * canvas.font_scale)
        for text, bold, color in line.runs:
            run = paragraph.add_run()
            run.text = text
            run.font.name = FONT
            run.font.size = canvas.font(size * line.scale)
            run.font.bold = bold
            run.font.color.rgb = color
            if line.heading:
                # python-pptx n'a pas de réglage pour l'espacement des lettres : on
                # l'écrit directement dans le XML (70 = 0,7 point entre deux lettres).
                run.font._rPr.set("spc", "70")


def _text_box(slide, canvas: Canvas, left: float, top: float, width: float, height: float,
              lines: List[Line], size: float, align=None, anchor=MSO_ANCHOR.TOP) -> None:
    box = slide.shapes.add_textbox(canvas.x(left), canvas.y(top), canvas.x(width), canvas.y(height))
    frame = box.text_frame
    frame.auto_size = MSO_AUTO_SIZE.NONE  # la zone garde sa taille
    frame.vertical_anchor = anchor
    frame.margin_left = frame.margin_right = frame.margin_top = frame.margin_bottom = 0
    _write_lines(frame, lines, size, canvas)
    if align is not None:
        for paragraph in frame.paragraphs:
            paragraph.alignment = align


def _bottom_border(cell, color: RGBColor, width_points: float) -> None:
    """Trace un filet sous une cellule. python-pptx ne le propose pas : on écrit le XML."""
    properties = cell._tc.get_or_add_tcPr()
    line = properties.makeelement(qn("a:lnB"), {"w": str(int(Pt(width_points)))})
    fill = line.makeelement(qn("a:solidFill"), {})
    fill.append(fill.makeelement(qn("a:srgbClr"), {"val": str(color)}))
    line.append(fill)
    properties.insert(0, line)  # les bordures doivent précéder le remplissage dans le XML


def _table(slide, canvas: Canvas, left: float, top: float, widths: Sequence[float], fit: Fit, accent: RGBColor) -> None:
    """Pose un tableau sans quadrillage : une ligne par Row, qui grandit selon son texte."""
    if not fit.rows:
        return
    total_width = sum(widths)
    frame = slide.shapes.add_table(
        len(fit.rows), len(widths), canvas.x(left), canvas.y(top), canvas.x(total_width), Pt(10 * len(fit.rows))
    )
    table = frame.table
    # Par défaut PowerPoint colore les tableaux (bandes bleues) : on choisit le style « aucun ».
    properties = frame._element.graphic.graphicData.tbl.tblPr
    properties.set("firstRow", "0")
    properties.set("bandRow", "0")
    style = properties.find(qn("a:tableStyleId"))
    if style is not None:
        style.text = NO_TABLE_STYLE
    for index, width in enumerate(widths):
        table.columns[index].width = canvas.x(width)

    for index, row in enumerate(fit.rows):
        table.rows[index].height = Pt(8)  # hauteur minimale : la ligne grandit toute seule
        cells = [table.cell(index, column) for column in range(len(widths))]
        if len(row.cells) == 1 and len(cells) > 1:
            cells[0].merge(cells[-1])  # une rubrique occupe toute la largeur
        for position, cell in enumerate(cells):
            cell.margin_left = cell.margin_right = 0
            cell.margin_top = Pt(row.space_before * canvas.font_scale)
            cell.margin_bottom = Pt(CELL_BOTTOM * canvas.font_scale)
            cell.vertical_anchor = MSO_ANCHOR.TOP
            if row.heading:
                _bottom_border(cell, accent, 1.0)
            elif row.rule:
                _bottom_border(cell, RULE, 0.5)
            cell.fill.background()  # cellule transparente
            if position < len(row.cells):
                _write_lines(cell.text_frame, row.cells[position], fit.size, canvas)


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


def _add_photo(slide, canvas: Canvas, cv: CV, photo: Optional[bytes], accent: RGBColor) -> None:
    """La photo en rond, en haut à gauche, devant le nom. Sans photo : un rond avec les initiales."""
    # Un rond doit rester rond même si la diapo est déformée : on prend la plus petite échelle.
    size = Emu(int(Inches(PHOTO_SIZE) * canvas.font_scale))
    left, top = canvas.x(EDGE), canvas.y(TITLE_TOP + (TITLE_HEIGHT - PHOTO_SIZE) / 2)
    has_photo = False
    if photo:
        try:
            slide.shapes.add_picture(io.BytesIO(round_photo(photo)), left, top, size, size)
            has_photo = True
        except Exception:  # image illisible : on retombe sur les initiales
            pass

    # Le rond : simple cercle par-dessus la photo, ou pastille pleine avec les initiales.
    circle = slide.shapes.add_shape(MSO_SHAPE.OVAL, left, top, size, size)
    circle.shadow.inherit = False
    if has_photo:
        circle.fill.background()  # pas de remplissage : on voit la photo à travers
        circle.line.color.rgb = accent
        circle.line.width = Pt(1.25)
        return
    circle.fill.solid()
    circle.fill.fore_color.rgb = accent
    circle.line.fill.background()
    frame = circle.text_frame
    frame.vertical_anchor = MSO_ANCHOR.MIDDLE
    paragraph = frame.paragraphs[0]
    paragraph.alignment = PP_ALIGN.CENTER
    run = paragraph.add_run()
    run.text = initials(cv.identity.full_name)
    run.font.name, run.font.size, run.font.bold = FONT, canvas.font(26), True
    run.font.color.rgb = WHITE


LOGO_HEIGHT = 0.6  # hauteur du logo, en haut à droite, en pouces


def _add_logo(slide, canvas: Canvas, logo: bytes) -> float:
    """Pose le logo en haut à droite. Renvoie la largeur qu'il occupe, en pouces (0 si illisible)."""
    try:
        picture = slide.shapes.add_picture(io.BytesIO(logo), 0, 0, height=canvas.y(LOGO_HEIGHT))
    except Exception:
        return 0.0
    picture.left = canvas.x(SLIDE_WIDTH - EDGE) - picture.width  # calé à droite
    picture.top = canvas.y(TITLE_TOP + (TITLE_HEIGHT - LOGO_HEIGHT) / 2)
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
    own_design = not theme.template  # avec un modèle d'entreprise, on ne dessine ni barre, ni logo, ni pied de page
    accent, stripe = RGBColor(*hex_to_rgb(theme.accent)), RGBColor(*hex_to_rgb(theme.stripe))
    labels = LABELS[detect_language(cv)]
    canvas = Canvas(presentation)

    slide = presentation.slides.add_slide(_blank_layout(presentation))
    for placeholder in list(slide.placeholders):  # les zones « Cliquez pour ajouter... » du modèle
        placeholder._element.getparent().remove(placeholder._element)

    # --- le haut : barre de couleur, nom et titre, logo, filet ---
    logo_width = 0.0
    if own_design:
        _rectangle(slide, canvas, 0, 0, SLIDE_WIDTH, TOP_BAR_HEIGHT, accent)
        _rectangle(slide, canvas, 0, TOP_BAR_HEIGHT, SLIDE_WIDTH, SECOND_BAR_HEIGHT, stripe)
        if theme.logo:
            logo_width = _add_logo(slide, canvas, theme.logo)
    name = cv.identity.full_name
    title_lines = [Line([(name, True, accent)], scale=1.0 if len(name) <= 38 else 0.82)]
    if cv.title:
        title_lines.append(Line([(cv.title, False, GREY)], scale=0.5, space_before=2))
    _add_photo(slide, canvas, cv, photo, accent)
    title_width = SLIDE_WIDTH - TITLE_TEXT_LEFT - EDGE - logo_width
    _text_box(slide, canvas, TITLE_TEXT_LEFT, TITLE_TOP, title_width, TITLE_HEIGHT, title_lines, 26, anchor=MSO_ANCHOR.MIDDLE)
    _rule(slide, canvas, TITLE_RULE_Y)

    # --- la colonne grise ---
    _rectangle(slide, canvas, EDGE, BODY_TOP, PANEL_WIDTH, BODY_BOTTOM - BODY_TOP, PANEL)
    # Quand la diapo est plus haute que large (modèle 4:3), il y a plus de place en hauteur.
    stretch = canvas.scale_y / canvas.font_scale
    side = fit_side(cv, labels, accent, SIDE_HEIGHT * stretch)
    _table(slide, canvas, EDGE + PANEL_PADDING, SIDE_TOP, [SIDE_TEXT_WIDTH], side, accent)

    # --- la colonne principale ---
    main = fit_main(cv, labels, accent, BODY_HEIGHT * stretch)
    _table(slide, canvas, MAIN_LEFT, BODY_TOP, [GUTTER_WIDTH, CONTENT_WIDTH], main, accent)

    # --- le pied de page ---
    if own_design:
        _rule(slide, canvas, FOOTER_RULE_Y)
        footer = theme.footer or labels["footer"]
        _text_box(slide, canvas, EDGE, FOOTER_RULE_Y + 0.1, 8, 0.3, [Line([(footer, False, GREY)])], 8.5)
        if page:
            number = [Line([(f"{page[0]} / {page[1]}", False, GREY)])]
            _text_box(slide, canvas, SLIDE_WIDTH - EDGE - 2, FOOTER_RULE_Y + 0.1, 2, 0.3, number, 8.5, align=PP_ALIGN.RIGHT)
    return side.dropped + main.dropped


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
    """Le texte de chaque diapositive d'un fichier .pptx (zones de texte et tableaux).

    Sert à vérifier ce qu'une fiche contient, dans les tests et le diagnostic.
    Les espaces insécables sont rendues comme des espaces normales.
    """
    texts = []
    for slide in Presentation(io.BytesIO(pptx)).slides:
        parts: List[str] = []
        for shape in slide.shapes:
            if shape.has_text_frame:
                parts.append(shape.text_frame.text)
            if getattr(shape, "has_table", False):
                for row in shape.table.rows:
                    parts.extend(cell.text_frame.text for cell in row.cells)
        texts.append("\n".join(parts).replace(NBSP, " "))
    return texts

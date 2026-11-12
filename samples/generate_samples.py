"""Fabrique 4 faux CV de test, volontairement différents.

    python samples/generate_samples.py

1. cv_classique_fr.pdf      PDF une colonne, en français
2. cv_two_columns_en.pdf    PDF deux colonnes, en anglais
3. cv_tableaux_fr.docx      DOCX dont le contenu est rangé dans des tableaux
4. cv_scanne_fr.pdf         PDF "scanné" : une image, aucun texte -> force l'OCR

Toutes les personnes, entreprises et coordonnées sont inventées.
"""

import io
from pathlib import Path

import fitz  # c'est le nom d'import de PyMuPDF
from docx import Document
from docx.shared import Pt
from PIL import Image

SAMPLES_DIR = Path(__file__).resolve().parent
A4 = fitz.paper_rect("a4")  # 595 x 842 points

BASE_CSS = """
body { font-family: sans-serif; font-size: 10pt; color: #222; }
h1 { font-size: 20pt; margin: 0; }
h2 { font-size: 11.5pt; margin: 12pt 0 3pt 0; text-transform: uppercase; }
h3 { font-size: 10pt; margin: 6pt 0 1pt 0; }
p { margin: 2pt 0; }
ul { margin: 2pt 0; padding-left: 14pt; }
.muted { color: #555; }
"""


def _new_page():
    doc = fitz.open()
    page = doc.new_page(width=A4.width, height=A4.height)
    return doc, page


# --------------------------------------------------------------------------
# 1. PDF classique, une colonne, français
# --------------------------------------------------------------------------
CLASSIQUE_HTML = """
<h1>Camille Lefèvre</h1>
<p><b>Développeuse back-end Python</b></p>
<p class="muted">Lyon (69) · 01 23 45 67 89 · camille.lefevre@example.com · linkedin.com/in/camille-lefevre-faux</p>

<h2>Profil</h2>
<p>Développeuse back-end avec six ans d'expérience dans la conception d'API et de pipelines
de données. À l'aise en équipe agile, attachée à la qualité du code et aux tests automatisés.</p>

<h2>Expériences professionnelles</h2>
<h3>Développeuse Python senior — Novalys Logistique, Lyon</h3>
<p class="muted">Mars 2021 – aujourd'hui</p>
<ul>
  <li>Conception d'une API REST de suivi de colis (FastAPI, PostgreSQL), 2 millions de requêtes par jour.</li>
  <li>Réduction de 40 % du temps de réponse grâce à la mise en cache Redis.</li>
  <li>Encadrement de deux développeurs juniors.</li>
</ul>
<h3>Développeuse back-end — Atelier Pixel, Villeurbanne</h3>
<p class="muted">Septembre 2018 – Février 2021</p>
<ul>
  <li>Développement de sites e-commerce sous Django pour des PME régionales.</li>
  <li>Mise en place de l'intégration continue (GitLab CI) et des tests unitaires.</li>
</ul>
<h3>Stagiaire développement — Mairie de Grenoble</h3>
<p class="muted">Février 2018 – Juillet 2018</p>
<ul><li>Outil interne de gestion des demandes d'urbanisme.</li></ul>

<h2>Formation</h2>
<p><b>Master Informatique, parcours Génie logiciel</b> — Université Claude Bernard Lyon 1, 2016 – 2018</p>
<p><b>Licence Informatique</b> — Université Grenoble Alpes, 2013 – 2016</p>

<h2>Compétences</h2>
<p>Python, FastAPI, Django, PostgreSQL, Redis, Docker, Git, GitLab CI, Linux, pytest</p>

<h2>Langues</h2>
<p>Français (langue maternelle), Anglais (courant, TOEIC 915), Espagnol (notions)</p>

<h2>Certifications</h2>
<p>AWS Certified Cloud Practitioner — Amazon Web Services, 2022</p>
"""


def make_classique(path: Path) -> None:
    doc, page = _new_page()
    page.insert_htmlbox(fitz.Rect(50, 45, A4.width - 50, A4.height - 45), CLASSIQUE_HTML, css=BASE_CSS)
    doc.save(str(path))


# --------------------------------------------------------------------------
# 2. PDF deux colonnes, anglais
# --------------------------------------------------------------------------
SIDEBAR_HTML = """
<h1>Daniel Okafor</h1>
<p><b>Data Analyst</b></p>
<h2>Contact</h2>
<p>Manchester, UK</p>
<p>+44 20 7946 0123</p>
<p>daniel.okafor@example.org</p>
<p>github.com/dokafor-fake</p>
<h2>Skills</h2>
<ul>
  <li>SQL</li><li>Python (pandas)</li><li>Power BI</li><li>Tableau</li>
  <li>Excel</li><li>A/B testing</li><li>dbt</li>
</ul>
<h2>Languages</h2>
<p>English — native</p>
<p>French — intermediate (B1)</p>
<p>Igbo — conversational</p>
<h2>Certifications</h2>
<p>Google Data Analytics Certificate (Coursera, 2020)</p>
<p>Microsoft PL-300 Power BI Data Analyst (2023)</p>
"""

MAIN_HTML = """
<h2>Profile</h2>
<p>Data analyst with 5 years of experience turning messy retail and logistics data into dashboards
and clear recommendations for non-technical teams.</p>

<h2>Experience</h2>
<h3>Senior Data Analyst, Brightcart Ltd</h3>
<p class="muted">Jan 2022 – Present | Manchester</p>
<ul>
  <li>Built the weekly sales dashboard used by 40 store managers (Power BI).</li>
  <li>Ran pricing A/B tests that increased basket size by 6%.</li>
  <li>Migrated legacy Excel reports to dbt models.</li>
</ul>
<h3>Data Analyst, Northway Freight</h3>
<p class="muted">Jul 2019 – Dec 2021 | Leeds</p>
<ul>
  <li>Automated delivery delay reporting with Python and SQL.</li>
  <li>Cut monthly reporting time from 3 days to 4 hours.</li>
</ul>
<h3>Junior Analyst (Internship), City Council of Leeds</h3>
<p class="muted">Jun 2018 – Sep 2018 | Leeds</p>
<ul><li>Cleaned and analysed public transport survey data.</li></ul>

<h2>Education</h2>
<h3>MSc Data Science</h3>
<p>University of Leeds, 2018 – 2019</p>
<h3>BSc Mathematics</h3>
<p>University of Sheffield, 2015 – 2018</p>
"""

SIDEBAR_CSS = BASE_CSS + "body { color: #ffffff; font-size: 9.5pt; } h1 { font-size: 18pt; }"


def make_two_columns(path: Path) -> None:
    doc, page = _new_page()
    sidebar_width = 190
    # La colonne de gauche est un rectangle bleu foncé avec du texte blanc.
    page.draw_rect(fitz.Rect(0, 0, sidebar_width, A4.height), color=None, fill=(0.13, 0.22, 0.35))
    page.insert_htmlbox(fitz.Rect(18, 40, sidebar_width - 14, A4.height - 40), SIDEBAR_HTML, css=SIDEBAR_CSS)
    page.insert_htmlbox(fitz.Rect(sidebar_width + 24, 32, A4.width - 36, A4.height - 40), MAIN_HTML, css=BASE_CSS)
    doc.save(str(path))


# --------------------------------------------------------------------------
# 3. DOCX avec tableaux, français
# --------------------------------------------------------------------------
def make_docx_tables(path: Path) -> None:
    doc = Document()
    doc.styles["Normal"].font.size = Pt(10.5)

    # En-tête : un tableau à 2 colonnes (nom à gauche, coordonnées à droite).
    header = doc.add_table(rows=1, cols=2)
    left, right = header.rows[0].cells
    left.paragraphs[0].add_run("Inès Benali").bold = True
    left.add_paragraph("Cheffe de projet marketing digital")
    right.paragraphs[0].add_run("Nantes, France")
    right.add_paragraph("Tél. : 01 98 76 54 32")
    right.add_paragraph("ines.benali@example.net")

    doc.add_heading("Résumé", level=2)
    doc.add_paragraph(
        "Huit ans d'expérience en marketing digital, dont quatre en pilotage de projets "
        "d'acquisition pour des marques grand public. Orientée résultats et données."
    )

    doc.add_heading("Parcours professionnel", level=2)
    jobs = doc.add_table(rows=1, cols=3)
    jobs.style = "Table Grid"
    for cell, label in zip(jobs.rows[0].cells, ("Période", "Poste et entreprise", "Réalisations")):
        cell.text = label
    rows = [
        (
            "2020 – 2024",
            "Cheffe de projet marketing digital\nMaison Océane (cosmétiques), Nantes",
            "Refonte du site e-commerce (+35 % de conversion). Budget annuel de 600 k€. "
            "Coordination de 3 agences.",
        ),
        (
            "2017 – 2020",
            "Chargée d'acquisition\nVéloVille (mobilité), Rennes",
            "Campagnes Google Ads et Meta Ads. Baisse du coût d'acquisition de 22 %.",
        ),
        (
            "2016 – 2017",
            "Assistante marketing (alternance)\nCoop Atlantique, Saint-Nazaire",
            "Newsletter hebdomadaire envoyée à 80 000 adhérents.",
        ),
    ]
    for period, role, results in rows:
        cells = jobs.add_row().cells
        cells[0].text, cells[1].text, cells[2].text = period, role, results

    doc.add_heading("Formation", level=2)
    studies = doc.add_table(rows=2, cols=2)
    studies.rows[0].cells[0].text = "2015 – 2017"
    studies.rows[0].cells[1].text = "Master Marketing digital — Audencia Business School, Nantes"
    studies.rows[1].cells[0].text = "2012 – 2015"
    studies.rows[1].cells[1].text = "Licence Économie-Gestion — Université de Rennes 1"

    doc.add_heading("Compétences et langues", level=2)
    skills = doc.add_table(rows=3, cols=2)
    skills.style = "Table Grid"
    skills.rows[0].cells[0].text = "Outils"
    skills.rows[0].cells[1].text = "Google Analytics 4, Google Ads, Meta Ads, HubSpot, Figma, Notion"
    skills.rows[1].cells[0].text = "Méthodes"
    skills.rows[1].cells[1].text = "SEO, gestion de projet agile, tests A/B, gestion de budget"
    skills.rows[2].cells[0].text = "Langues"
    skills.rows[2].cells[1].text = "Français (natif), Anglais (C1), Arabe (courant)"

    doc.add_heading("Certifications", level=2)
    doc.add_paragraph("Google Ads Search — Google, 2023")
    doc.add_paragraph("Certification HubSpot Inbound Marketing — HubSpot Academy, 2021")

    doc.save(str(path))


# --------------------------------------------------------------------------
# 4. PDF scanné (image seule), français
# --------------------------------------------------------------------------
SCAN_HTML = """
<p style="text-align:center; font-size:20pt"><b>THOMAS GIRARD</b></p>
<p style="text-align:center">Comptable général</p>
<p style="text-align:center">12 rue des Tilleuls, 33000 Bordeaux — 01 44 55 66 77 — thomas.girard@example.com</p>

<h2>Expérience</h2>
<p><b>Comptable général</b>, Cabinet Durand et Associés, Bordeaux — depuis janvier 2019</p>
<ul>
  <li>Tenue de la comptabilité de 45 clients (TPE et artisans).</li>
  <li>Établissement des bilans et des déclarations de TVA.</li>
</ul>
<p><b>Aide-comptable</b>, Transports Lacombe, Mérignac — septembre 2015 à décembre 2018</p>
<ul>
  <li>Saisie des factures fournisseurs et rapprochements bancaires.</li>
  <li>Suivi des relances clients.</li>
</ul>

<h2>Formation</h2>
<p>DCG (Diplôme de Comptabilité et de Gestion) — Lycée Gustave Eiffel, Bordeaux, 2015</p>
<p>BTS Comptabilité et Gestion — Lycée Gustave Eiffel, Bordeaux, 2013</p>

<h2>Compétences</h2>
<p>Sage 100, Cegid, Excel (tableaux croisés dynamiques), paie, fiscalité des PME</p>

<h2>Langues</h2>
<p>Français : langue maternelle. Anglais : niveau scolaire.</p>
"""

SCAN_CSS = BASE_CSS + "body { font-family: serif; font-size: 11pt; }"


def make_scanned(path: Path) -> None:
    # a) On fabrique une page normale, avec du vrai texte...
    doc, page = _new_page()
    page.insert_htmlbox(fitz.Rect(60, 55, A4.width - 60, A4.height - 55), SCAN_HTML, css=SCAN_CSS)
    # b) ...qu'on transforme en image, légèrement penchée comme un vrai scan...
    pixmap = page.get_pixmap(dpi=200, colorspace=fitz.csGRAY)
    image = Image.frombytes("L", (pixmap.width, pixmap.height), pixmap.samples)
    image = image.rotate(0.7, fillcolor=255, resample=Image.BICUBIC)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=70)
    # c) ...puis on colle cette image, seule, dans un nouveau PDF.
    scanned = fitz.open()
    scanned_page = scanned.new_page(width=A4.width, height=A4.height)
    scanned_page.insert_image(scanned_page.rect, stream=buffer.getvalue())
    scanned.save(str(path))


SAMPLES = {
    "cv_classique_fr.pdf": make_classique,
    "cv_two_columns_en.pdf": make_two_columns,
    "cv_tableaux_fr.docx": make_docx_tables,
    "cv_scanne_fr.pdf": make_scanned,
}


def generate_all(target_dir: Path = SAMPLES_DIR) -> None:
    for filename, make in SAMPLES.items():
        make(target_dir / filename)
        print("créé :", target_dir / filename)


if __name__ == "__main__":
    generate_all()

"""Quatre faux CV DIFFICILES, pour mettre le programme en défaut.

Les cinq premiers faux CV (generate_samples.py) sont courts et propres : le
modèle y obtient 100 sur 100, ce qui n'apprend plus rien. Ceux-ci reprennent
des difficultés qu'on rencontre dans les vrais CV :

1. cv_long_fr.pdf           2 pages, 7 postes sur 25 ans, beaucoup de texte
2. cv_paragraphes_en.docx   pas de puces : des paragraphes ; rubriques aux noms inhabituels
3. cv_design_fr.pdf         colonne latérale sombre, photo, niveaux en pastilles, nom en capitales
4. cv_scan_colonnes_fr.pdf  scan penché, de qualité moyenne, sur deux colonnes

Ici, la BONNE RÉPONSE est écrite d'abord (les dictionnaires ci-dessous), et
le document est fabriqué à partir d'elle. On est donc sûr de ce que le
programme doit retrouver. Les réponses attendues sont enregistrées dans
samples/expected/ par write_expected().

Toutes les personnes, entreprises et coordonnées sont inventées.
"""

import io
import json
from html import escape
from pathlib import Path
from typing import Dict, List, Optional

import fitz
from docx import Document
from docx.shared import Pt
from PIL import Image

from samples.generate_samples import A4, BASE_CSS, SAMPLES_DIR, _new_page, _png, draw_portrait

FRENCH_MONTHS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
                 "septembre", "octobre", "novembre", "décembre"]


def french_date(value: Optional[str]) -> str:
    """ "03/2021" -> "Mars 2021" ; "present" -> "aujourd'hui" ; "2019" -> "2019"."""
    if value == "present":
        return "aujourd'hui"
    if value and "/" in value:
        month, year = value.split("/")
        return f"{FRENCH_MONTHS[int(month) - 1].capitalize()} {year}"
    return value or ""


# ==========================================================================
# 1. CV long : deux pages, longue carrière
# ==========================================================================
LONG_CV = {
    "identity": {"full_name": "Bernard Rousseau", "email": "bernard.rousseau@example.fr", "phone": "01 60 70 80 90",
                 "location": "Orléans (45)", "links": ["linkedin.com/in/bernard-rousseau-faux"]},
    "title": "Directeur des opérations logistiques",
    "summary": "Vingt-cinq ans d'expérience en logistique et transport, dont douze à la direction de sites. "
               "Spécialiste de la mise en service d'entrepôts automatisés et de la réduction des coûts de distribution. "
               "Manager de terrain, habitué aux négociations avec les partenaires sociaux.",
    "experiences": [
        {"job_title": "Directeur des opérations", "company": "Translog Centre", "location": "Orléans",
         "start": "01/2019", "end": "present", "highlights": [
             "Pilotage de 4 entrepôts et de 620 collaborateurs, budget annuel de 48 M€.",
             "Mise en service d'un entrepôt automatisé de 32 000 m² en 14 mois.",
             "Baisse de 11 % du coût par colis expédié en trois ans.",
             "Négociation de l'accord d'entreprise sur le travail de nuit."]},
        {"job_title": "Directeur de site", "company": "Translog Centre", "location": "Saran",
         "start": "03/2014", "end": "12/2018", "highlights": [
             "Direction d'une plateforme de 210 personnes fonctionnant en 3x8.",
             "Taux de service client porté de 94 % à 98,5 %.",
             "Déploiement du système de gestion d'entrepôt Reflex."]},
        {"job_title": "Responsable d'exploitation", "company": "Frigo Express", "location": "Tours",
         "start": "09/2009", "end": "02/2014", "highlights": [
             "Organisation des tournées de 85 véhicules frigorifiques.",
             "Réduction de 18 % des kilomètres parcourus à vide.",
             "Recrutement et formation de 40 conducteurs."]},
        {"job_title": "Responsable méthodes logistiques", "company": "Groupe Valmont Distribution", "location": "Chartres",
         "start": "06/2005", "end": "08/2009", "highlights": [
             "Refonte de l'implantation des stocks de trois entrepôts.",
             "Gain de 22 % de productivité en préparation de commandes.",
             "Animation de chantiers d'amélioration continue (Kaizen)."]},
        {"job_title": "Chef d'équipe réception", "company": "Groupe Valmont Distribution", "location": "Chartres",
         "start": "01/2002", "end": "05/2005", "highlights": [
             "Encadrement de 25 caristes et agents de quai.",
             "Mise en place du contrôle qualité à la réception."]},
        {"job_title": "Agent de planning transport", "company": "Messageries du Val de Loire", "location": "Blois",
         "start": "09/1999", "end": "12/2001", "highlights": [
             "Planification quotidienne de 60 tournées de messagerie.",
             "Suivi des litiges et des retours clients."]},
        {"job_title": "Stagiaire logistique", "company": "Usine Renard Emballages", "location": "Vendôme",
         "start": "02/1999", "end": "07/1999", "highlights": [
             "Étude des flux internes de l'atelier de conditionnement."]},
    ],
    "education": [
        {"degree": "Executive MBA", "school": "ESCP Business School", "location": "Paris", "start": "2012", "end": "2013"},
        {"degree": "Master Logistique et transport", "school": "Université d'Orléans", "location": None, "start": "1997", "end": "1999"},
        {"degree": "Licence Sciences économiques", "school": "Université de Tours", "location": None, "start": "1994", "end": "1997"},
    ],
    "skills": ["Direction de site", "Gestion d'entrepôt (WMS Reflex)", "Transport routier", "Chaîne du froid",
               "Lean management", "Kaizen", "Budget et contrôle de gestion", "Négociation sociale", "SAP",
               "Excel avancé", "Sécurité et prévention", "Conduite du changement"],
    "languages": [{"name": "Français", "level": "langue maternelle"}, {"name": "Anglais", "level": "professionnel"},
                  {"name": "Allemand", "level": "notions"}],
    "certifications": [
        {"name": "Green Belt Lean Six Sigma", "issuer": "AFNOR", "date": "2016"},
        {"name": "Attestation de capacité de transport de marchandises", "issuer": None, "date": "2010"},
        {"name": "CACES R489 catégories 1, 3 et 5", "issuer": None, "date": "2003"},
    ],
}


def make_long(path: Path) -> None:
    cv = LONG_CV
    identity = cv["identity"]
    first_page = [
        f"<h1>{escape(identity['full_name'])}</h1>",
        f"<p><b>{escape(cv['title'])}</b></p>",
        f"<p class='muted'>{escape(identity['location'])} · {identity['phone']} · {identity['email']} · {identity['links'][0]}</p>",
        "<h2>Profil</h2>", f"<p>{escape(cv['summary'])}</p>",
        "<h2>Expériences professionnelles</h2>",
    ]
    second_page: List[str] = []
    for index, job in enumerate(cv["experiences"]):
        block = [
            f"<h3>{escape(job['job_title'])} — {escape(job['company'])}, {escape(job['location'])}</h3>",
            f"<p class='muted'>{french_date(job['start'])} – {french_date(job['end'])}</p>",
            "<ul>" + "".join(f"<li>{escape(line)}</li>" for line in job["highlights"]) + "</ul>",
        ]
        (first_page if index < 4 else second_page).extend(block)  # les 4 premiers postes en page 1
    second_page.append("<h2>Formation</h2>")
    for study in cv["education"]:
        place = f", {study['location']}" if study["location"] else ""
        second_page.append(f"<p><b>{escape(study['degree'])}</b> — {escape(study['school'])}{place}, {study['start']} – {study['end']}</p>")
    second_page.append("<h2>Compétences</h2>")
    second_page.append(f"<p>{escape(', '.join(cv['skills']))}</p>")
    second_page.append("<h2>Langues</h2>")
    second_page.append("<p>" + ", ".join(f"{item['name']} ({item['level']})" for item in cv["languages"]) + "</p>")
    second_page.append("<h2>Certifications</h2>")
    for item in cv["certifications"]:
        issuer = f" — {item['issuer']}" if item["issuer"] else ""
        second_page.append(f"<p>{escape(item['name'])}{issuer}, {item['date']}</p>")

    document = fitz.open()
    for html in ("".join(first_page), "".join(second_page)):
        page = document.new_page(width=A4.width, height=A4.height)
        page.insert_htmlbox(fitz.Rect(50, 45, A4.width - 50, A4.height - 45), html, css=BASE_CSS)
    document.save(str(path))


# ==========================================================================
# 2. DOCX en anglais, sans puces : des paragraphes
# ==========================================================================
PARAGRAPHS_CV = {
    "identity": {"full_name": "Priya Raman", "email": "priya.raman@example.co.uk", "phone": "+44 161 496 0199",
                 "location": "Bristol, UK", "links": []},
    "title": "Product Manager",
    "summary": "Product manager with eight years in B2B software. I like small teams, short release cycles "
               "and decisions backed by customer interviews.",
    "experiences": [
        {"job_title": "Senior Product Manager", "company": "Harbourline Software", "location": "Bristol",
         "start": "2021", "end": "present", "highlights": [
             "I own the roadmap of the invoicing product used by 3,000 small businesses.",
             "Last year we rebuilt the onboarding flow and cut churn in the first month by a third.",
             "I manage two product owners and work daily with a team of twelve engineers."]},
        {"job_title": "Product Manager", "company": "Kestrel Analytics", "location": "London",
         "start": "2018", "end": "2021", "highlights": [
             "I launched the self-service reporting module from the first prototype to general availability.",
             "The module reached 40% of customers within a year."]},
        {"job_title": "Business Analyst", "company": "Northgate Insurance", "location": "Leeds",
         "start": "2016", "end": "2018", "highlights": [
             "I wrote the specifications for the claims handling portal.",
             "I also ran user acceptance testing with the call centre teams."]},
    ],
    "education": [
        {"degree": "MSc Human-Computer Interaction", "school": "University of York", "location": None, "start": "2015", "end": "2016"},
        {"degree": "BA Economics", "school": "University of Warwick", "location": None, "start": "2012", "end": "2015"},
    ],
    "skills": ["Roadmapping", "User interviews", "A/B testing", "SQL", "Jira", "Figma", "Scrum"],
    "languages": [{"name": "English", "level": "native"}, {"name": "Tamil", "level": "fluent"},
                  {"name": "Spanish", "level": "basic"}],
    "certifications": [{"name": "Certified Scrum Product Owner", "issuer": "Scrum Alliance", "date": "2019"}],
}


def make_paragraphs(path: Path) -> None:
    cv = PARAGRAPHS_CV
    identity = cv["identity"]
    document = Document()
    document.styles["Normal"].font.size = Pt(10.5)
    document.add_heading(identity["full_name"], level=0)
    document.add_paragraph(cv["title"])
    document.add_paragraph(f"{identity['location']}  |  {identity['phone']}  |  {identity['email']}")
    document.add_heading("About me", level=1)
    document.add_paragraph(cv["summary"])
    document.add_heading("Career history", level=1)
    for job in cv["experiences"]:
        dates = f"since {job['start']}" if job["end"] == "present" else f"{job['start']} - {job['end']}"
        document.add_paragraph().add_run(f"{job['job_title']}, {job['company']} ({job['location']}), {dates}").bold = True
        document.add_paragraph(" ".join(job["highlights"]))  # un seul paragraphe, sans puce
    document.add_heading("Academic background", level=1)
    for study in cv["education"]:
        document.add_paragraph(f"{study['degree']}, {study['school']}, {study['start']} - {study['end']}")
    document.add_heading("Toolbox", level=1)
    document.add_paragraph(" / ".join(cv["skills"]))
    document.add_heading("Languages spoken", level=1)
    document.add_paragraph("; ".join(f"{item['name']}: {item['level']}" for item in cv["languages"]))
    document.add_heading("Training", level=1)
    item = cv["certifications"][0]
    document.add_paragraph(f"{item['name']} ({item['issuer']}, {item['date']})")
    document.save(str(path))


# ==========================================================================
# 3. PDF « design » : colonne latérale sombre, photo, pastilles de niveau
# ==========================================================================
DESIGN_CV = {
    "identity": {"full_name": "Hugo Fontaine", "email": "hugo.fontaine@example.com", "phone": "01 70 60 50 40",
                 "location": "Lille", "links": ["hugofontaine.example"]},
    "title": "Chef de produit e-commerce",
    "summary": "Chef de produit e-commerce depuis sept ans, passé par le retail et une start-up. "
               "J'aime mesurer avant de décider et livrer petit à petit.",
    "experiences": [
        {"job_title": "Chef de produit e-commerce", "company": "Maison Lestrade", "location": "Lille",
         "start": "01/2021", "end": "present", "highlights": [
             "Refonte du tunnel de commande : +12 % de conversion sur mobile.",
             "Lancement du retrait en magasin dans 45 boutiques.",
             "Priorisation du backlog avec une équipe de 9 développeurs."]},
        {"job_title": "Chef de projet digital", "company": "Bobine", "location": "Roubaix",
         "start": "03/2019", "end": "12/2020", "highlights": [
             "Création de la place de marché de tissus entre particuliers.",
             "Croissance de 0 à 20 000 clients en dix-huit mois."]},
        {"job_title": "Assistant chef de produit", "company": "Nordis", "location": "Villeneuve-d'Ascq",
         "start": "09/2016", "end": "02/2019", "highlights": [
             "Suivi des ventes de la gamme jardin, 1 200 références."]},
    ],
    "education": [
        {"degree": "Master Marketing et vente", "school": "IAE Lille", "location": None, "start": "2014", "end": "2016"},
        {"degree": "Licence Économie et gestion", "school": "Université de Lille", "location": None, "start": "2011", "end": "2014"},
    ],
    "skills": ["Shopify", "Google Analytics 4", "SQL", "Tests A/B", "SEO", "Figma", "Jira"],
    "languages": [{"name": "Français", "level": "langue maternelle"}, {"name": "Anglais", "level": "courant"},
                  {"name": "Néerlandais", "level": "débutant"}],
    "certifications": [],
    "interests": ["Cyclisme sur route", "Photographie argentique"],
}
_SKILL_DOTS = ["●●●●●", "●●●●○", "●●●●○", "●●●○○", "●●●○○", "●●●○○", "●●○○○"]

DESIGN_CSS = BASE_CSS + """
.side { color: #ffffff; font-size: 9pt; }
.side h2 { color: #9fc4e8; font-size: 9.5pt; margin: 12pt 0 3pt 0; }
.side p { margin: 1.5pt 0; }
h1.big { font-size: 24pt; letter-spacing: 1pt; margin: 0; }
.dates { color: #666; font-size: 8.5pt; }
"""


def make_design(path: Path) -> None:
    cv = DESIGN_CV
    identity = cv["identity"]
    document, page = _new_page()
    side_width = 180
    page.draw_rect(fitz.Rect(0, 0, side_width, A4.height), color=None, fill=(0.13, 0.20, 0.29))
    page.insert_image(fitz.Rect(45, 40, 135, 130), stream=_png(draw_portrait(400)))

    # La colonne principale est écrite EN PREMIER dans le fichier : à l'extraction,
    # les coordonnées (colonne latérale) arrivent donc tout à la fin du texte.
    main = [f"<h1 class='big'>{escape(identity['full_name'].upper())}</h1>", f"<p><b>{escape(cv['title'].upper())}</b></p>",
            "<h2>À propos</h2>", f"<p>{escape(cv['summary'])}</p>", "<h2>Parcours</h2>"]
    for job in cv["experiences"]:
        start = job["start"].replace("/", ".")
        end = "à ce jour" if job["end"] == "present" else job["end"].replace("/", ".")
        main.append(f"<p class='dates'>{start} - {end}</p>")
        main.append(f"<h3>{escape(job['job_title'])} | {escape(job['company'])} ({escape(job['location'])})</h3>")
        main.append("<ul>" + "".join(f"<li>{escape(line)}</li>" for line in job["highlights"]) + "</ul>")
    main.append("<h2>Diplômes</h2>")
    for study in cv["education"]:
        main.append(f"<p class='dates'>{study['start']} - {study['end']}</p>")
        main.append(f"<p><b>{escape(study['degree'])}</b>, {escape(study['school'])}</p>")
    page.insert_htmlbox(fitz.Rect(side_width + 25, 40, A4.width - 40, A4.height - 40), "".join(main), css=DESIGN_CSS)

    side = ["<div class='side'>", "<h2>CONTACT</h2>", f"<p>☎ {identity['phone']}</p>", f"<p>✉ {identity['email']}</p>",
            f"<p>⌂ {escape(identity['location'])}</p>", f"<p>{identity['links'][0]}</p>", "<h2>COMPÉTENCES</h2>"]
    side += [f"<p>{escape(skill)} {dots}</p>" for skill, dots in zip(cv["skills"], _SKILL_DOTS)]
    side.append("<h2>LANGUES</h2>")
    side += [f"<p>{item['name']} : {item['level']}</p>" for item in cv["languages"]]
    side += ["<h2>CENTRES D'INTÉRÊT</h2>", "<p>Cyclisme sur route</p>", "<p>Photographie argentique</p>", "</div>"]
    page.insert_htmlbox(fitz.Rect(18, 150, side_width - 12, A4.height - 40), "".join(side), css=DESIGN_CSS)
    document.save(str(path))


# ==========================================================================
# 4. Scan penché, qualité moyenne, deux colonnes
# ==========================================================================
SCAN_COLUMNS_CV = {
    "identity": {"full_name": "Nadia Haddad", "email": "nadia.haddad@example.org", "phone": "01 82 83 84 85",
                 "location": "Marseille", "links": []},
    "title": "Infirmière coordinatrice",
    "summary": "Infirmière diplômée d'État depuis douze ans, coordinatrice en EHPAD depuis 2020.",
    "experiences": [
        {"job_title": "Infirmière coordinatrice", "company": "Résidence Les Oliviers", "location": "Marseille",
         "start": "04/2020", "end": "present", "highlights": [
             "Coordination d'une équipe de 28 soignants pour 92 résidents.",
             "Élaboration des plannings et des projets de soins personnalisés.",
             "Référente pour la prévention des chutes."]},
        {"job_title": "Infirmière en cardiologie", "company": "Hôpital Saint-Lazare", "location": "Aix-en-Provence",
         "start": "09/2013", "end": "03/2020", "highlights": [
             "Soins en unité de soins intensifs cardiologiques, 12 lits.",
             "Encadrement des étudiants infirmiers de troisième année."]},
    ],
    "education": [
        {"degree": "Diplôme universitaire Coordination en gérontologie", "school": "Aix-Marseille Université", "location": None, "start": None, "end": "2019"},
        {"degree": "Diplôme d'État d'infirmier", "school": "IFSI de Marseille", "location": None, "start": None, "end": "2013"},
    ],
    "skills": ["Coordination des soins", "Gérontologie", "Soins intensifs", "Éducation thérapeutique",
               "Logiciel NetSoins", "Gestion des plannings"],
    "languages": [{"name": "Français", "level": "langue maternelle"}, {"name": "Arabe", "level": "courant"},
                  {"name": "Anglais", "level": "scolaire"}],
    "certifications": [{"name": "AFGSU niveau 2", "issuer": None, "date": "2022"}],
}

SCAN_COLUMNS_CSS = BASE_CSS + "body { font-family: serif; font-size: 10.5pt; }"


def make_scan_columns(path: Path) -> None:
    cv = SCAN_COLUMNS_CV
    identity = cv["identity"]
    document, page = _new_page()
    head = (f"<h1>{escape(identity['full_name'])}</h1><p><b>{escape(cv['title'])}</b></p>"
            f"<p>{escape(cv['summary'])}</p>")
    page.insert_htmlbox(fitz.Rect(55, 50, A4.width - 55, 150), head, css=SCAN_COLUMNS_CSS)

    left = ["<h2>Coordonnées</h2>", f"<p>{identity['location']}</p>", f"<p>{identity['phone']}</p>", f"<p>{identity['email']}</p>",
            "<h2>Compétences</h2>"] + [f"<p>{escape(skill)}</p>" for skill in cv["skills"]]
    left += ["<h2>Langues</h2>"] + [f"<p>{item['name']} ({item['level']})</p>" for item in cv["languages"]]
    left += ["<h2>Certification</h2>", f"<p>{cv['certifications'][0]['name']}, {cv['certifications'][0]['date']}</p>"]
    page.insert_htmlbox(fitz.Rect(55, 160, 215, A4.height - 60), "".join(left), css=SCAN_COLUMNS_CSS)

    right = ["<h2>Expérience professionnelle</h2>"]
    for job in cv["experiences"]:
        right.append(f"<h3>{escape(job['job_title'])}</h3>")
        end = "aujourd'hui" if job["end"] == "present" else job["end"]
        right.append(f"<p>{escape(job['company'])}, {escape(job['location'])} — {job['start']} à {end}</p>")
        right.append("<ul>" + "".join(f"<li>{escape(line)}</li>" for line in job["highlights"]) + "</ul>")
    right.append("<h2>Formation</h2>")
    for study in cv["education"]:
        right.append(f"<p><b>{escape(study['degree'])}</b><br>{escape(study['school'])}, {study['end']}</p>")
    page.insert_htmlbox(fitz.Rect(240, 160, A4.width - 55, A4.height - 60), "".join(right), css=SCAN_COLUMNS_CSS)

    # La page devient une image de qualité moyenne, nettement penchée, comme un scan fait à la va-vite.
    pixmap = page.get_pixmap(dpi=150, colorspace=fitz.csGRAY)
    image = Image.frombytes("L", (pixmap.width, pixmap.height), pixmap.samples)
    image = image.rotate(-1.6, fillcolor=255, resample=Image.BICUBIC)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=45)
    scanned = fitz.open()
    scanned_page = scanned.new_page(width=A4.width, height=A4.height)
    scanned_page.insert_image(scanned_page.rect, stream=buffer.getvalue())
    scanned.save(str(path))


# ==========================================================================
HARD_SAMPLES = {
    "cv_long_fr.pdf": make_long,
    "cv_paragraphes_en.docx": make_paragraphs,
    "cv_design_fr.pdf": make_design,
    "cv_scan_colonnes_fr.pdf": make_scan_columns,
}
HARD_ANSWERS: Dict[str, dict] = {
    "cv_long_fr.pdf": LONG_CV,
    "cv_paragraphes_en.docx": PARAGRAPHS_CV,
    "cv_design_fr.pdf": DESIGN_CV,
    "cv_scan_colonnes_fr.pdf": SCAN_COLUMNS_CV,
}


def write_expected(target_dir: Path = SAMPLES_DIR / "expected") -> None:
    """Enregistre la bonne réponse de chaque CV difficile, au format du banc d'essai."""
    from app.schema import CV  # import ici : samples/ doit rester utilisable sans le reste de l'application

    for filename, answer in HARD_ANSWERS.items():
        cv = CV.model_validate(answer)
        (target_dir / f"{Path(filename).stem}.json").write_text(
            json.dumps(cv.model_dump(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    for name, make in HARD_SAMPLES.items():
        make(SAMPLES_DIR / name)
        print("créé :", SAMPLES_DIR / name)
    write_expected()

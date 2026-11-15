"""Tests des corrections faites en Python d'après le texte d'origine."""

from app.fixes import fill_current_jobs
from app.schema import CV

SOURCE = """THOMAS GIRARD
Comptable général
12 rue des Tilleuls, 33000 Bordeaux
Expérience
Comptable général, Cabinet Durand et Associés, Bordeaux - depuis janvier 2019
• Tenue de la comptabilité de 45 clients (TPE et artisans).
Aide-comptable, Transports Lacombe, Mérignac - septembre 2015 à décembre 2018
• Saisie des factures depuis le logiciel Sage."""


def _cv(*jobs) -> CV:
    return CV.model_validate({"identity": {"full_name": "Thomas Girard"}, "experiences": list(jobs)})


def test_job_described_with_depuis_gets_present():
    cv = fill_current_jobs(_cv({"job_title": "Comptable général", "start": "janvier 2019"}), SOURCE)
    assert cv.experiences[0].end == "present"


def test_finished_job_is_left_alone():
    # « depuis » figure dans une puce de ce poste, pas dans sa ligne de dates.
    cv = fill_current_jobs(_cv({"job_title": "Aide-comptable", "start": "09/2015", "end": "12/2018"}), SOURCE)
    assert cv.experiences[0].end == "12/2018"


def test_no_end_and_no_keyword_stays_empty():
    source = "Aide-comptable, Transports Lacombe\n2015\n• Suivi des relances depuis le logiciel Sage."
    cv = fill_current_jobs(_cv({"job_title": "Aide-comptable", "start": "2015"}), source)
    assert cv.experiences[0].end is None


def test_dates_on_the_next_line_are_seen():
    source = "Senior Data Analyst, Brightcart Ltd\nJan 2022 – Present | Manchester\n• Built the dashboard."
    cv = fill_current_jobs(_cv({"job_title": "Senior Data Analyst", "start": "01/2022"}), source)
    assert cv.experiences[0].end == "present"


def test_the_year_must_be_in_the_same_passage():
    # Le mot-clé est là, mais pour une autre année : on ne touche à rien.
    source = "Consultant, Cabinet Exemple - depuis 2023"
    cv = fill_current_jobs(_cv({"job_title": "Consultant", "start": "2019"}), source)
    assert cv.experiences[0].end is None


def test_start_written_with_depuis_by_the_model():
    cv = _cv({"job_title": "Comptable", "start": "depuis janvier 2019", "end": None})
    assert (cv.experiences[0].start, cv.experiences[0].end) == ("01/2019", "present")


# ----------------------------------------------------- coordonnées --------
from app.fixes import fix_contact  # noqa: E402

CONTACT_SOURCE = """Priya Raman
Bristol, UK | +44 161 496 0199 | priya.raman@example.co.uk
33000 Bordeaux, de 2018 - 2021 puis 09/2015 à 12/2018"""


def _person(**identity) -> CV:
    return CV.model_validate({"identity": {"full_name": "Priya Raman", **identity}})


def test_email_with_a_typo_is_replaced_by_the_one_in_the_cv():
    cv = fix_contact(_person(email="pria.raman@example.co.uk"), CONTACT_SOURCE)  # vu avec gemma3:4b
    assert cv.identity.email == "priya.raman@example.co.uk"


def test_missing_email_and_phone_are_filled_when_there_is_only_one_in_the_cv():
    cv = fix_contact(_person(), CONTACT_SOURCE)
    assert cv.identity.email == "priya.raman@example.co.uk"
    assert cv.identity.phone == "+44 161 496 0199"


def test_phone_with_a_wrong_digit_is_replaced():
    cv = fix_contact(_person(phone="+44 161 496 0189"), CONTACT_SOURCE)
    assert cv.identity.phone == "+44 161 496 0199"


def test_correct_values_are_left_alone_and_dates_are_not_phone_numbers():
    cv = fix_contact(_person(email="priya.raman@example.co.uk", phone="+44 161 496 0199"), CONTACT_SOURCE)
    assert (cv.identity.email, cv.identity.phone) == ("priya.raman@example.co.uk", "+44 161 496 0199")
    # Un CV sans téléphone : ni le code postal ni les années ne sont pris pour un numéro.
    assert fix_contact(_person(), "33000 Bordeaux\n2018 - 2021\n09/2015 à 12/2018").identity.phone is None


def test_with_several_emails_only_a_close_one_is_used():
    source = "jean.dupont@example.com\nReferences: marie.curie@example.org"
    assert fix_contact(_person(email="jean.dupond@example.com"), source).identity.email == "jean.dupont@example.com"
    # Rien de ressemblant : on ne choisit pas au hasard entre les deux.
    assert fix_contact(_person(), source).identity.email is None


# ------------------------------------------- intitulé + entreprise --------
from app.fixes import clean_interests, split_job_titles  # noqa: E402


def test_title_that_swallowed_the_company_is_split():
    cv = split_job_titles(_cv({"job_title": "Directeur de site — Translog Centre, Saran"}))  # vu avec gemma3:4b
    job = cv.experiences[0]
    assert (job.job_title, job.company, job.location) == ("Directeur de site", "Translog Centre", "Saran")


def test_title_that_repeats_the_company_is_shortened():
    cv = split_job_titles(_cv({"job_title": "Chef de produit | Maison Lestrade (Lille)", "company": "Maison Lestrade", "location": "Lille"}))
    job = cv.experiences[0]
    assert (job.job_title, job.company, job.location) == ("Chef de produit", "Maison Lestrade", "Lille")


def test_legitimate_titles_are_left_alone():
    # Un simple tiret, ou un séparateur suivi d'autre chose que l'entreprise connue.
    for title, company in [("Responsable marketing - communication", None), ("Directeur — Europe du Sud", "Novalys")]:
        cv = split_job_titles(_cv({"job_title": title, "company": company}))
        assert (cv.experiences[0].job_title, cv.experiences[0].company) == (title, company)


# ----------------------------------------------- centres d'intérêt --------
def _with_interests(*interests, **extra) -> CV:
    return CV.model_validate({"identity": {"full_name": "Jean Dupont"}, "interests": list(interests), **extra})


def test_interests_are_emptied_when_the_cv_has_no_such_section():
    source = "Certifications\nCACES R489 catégories 1, 3 et 5, 2003"
    assert clean_interests(_with_interests("CACES R489 catégories 1, 3 et 5", "2003"), source).interests == []


def test_real_interests_are_kept_but_years_and_duplicates_are_removed():
    source = "Centres d'intérêt\nCyclisme sur route\nPhotographie argentique"
    cv = _with_interests("Cyclisme sur route", "2003", "Figma", "Photographie argentique", skills=["Figma"])
    assert clean_interests(cv, source).interests == ["Cyclisme sur route", "Photographie argentique"]

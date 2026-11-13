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

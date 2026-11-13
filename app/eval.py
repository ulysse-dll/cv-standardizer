"""Banc d'essai : le modèle fait-il du bon travail ? On le MESURE.

    python -m app.eval                       # le modèle du .env, sur les faux CV
    python -m app.eval --model llama3.2:3b   # un autre modèle Ollama, pour comparer
    python -m app.eval --json resultat.json  # garde le détail dans un fichier

Pour chaque faux CV de samples/, on connaît la bonne réponse
(samples/expected/<nom>.json, relue à la main). On fait travailler le modèle,
puis on compare son résultat à cette réponse, rubrique par rubrique. Chaque
rubrique reçoit une note de 0 à 100 ; la note du CV est leur moyenne.

À lancer avant et après tout changement de consigne (prompts.py) ou de modèle :
c'est le seul moyen de savoir si on a amélioré ou cassé quelque chose.
"""

import argparse
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from app.config import ROOT_DIR, Settings, get_settings
from app.coverage import find_missing_lines, find_unsupported_values, normalize
from app.extraction import extract_text
from app.llm import get_provider
from app.llm.base import LLMProvider
from app.pipeline import structure_cv
from app.schema import CV, Experience
from app.timing import StepTimer, setup_logging

SAMPLES_DIR = ROOT_DIR / "samples"
EXPECTED_DIR = SAMPLES_DIR / "expected"
CRITERIA = ["identité", "postes", "dates", "réalisations", "formation", "compétences", "langues", "certifs"]


def overlap(expected: Sequence[Optional[str]], got: Sequence[Optional[str]]) -> float:
    """Part commune de deux listes, de 0 à 1 (1 = identiques, l'ordre ne compte pas).

    On divise par le nombre total de valeurs différentes : un élément oublié
    ET un élément en trop font tous les deux baisser la note.
    """
    wanted = {normalize(value) for value in expected if value}
    found = {normalize(value) for value in got if value}
    if not wanted and not found:
        return 1.0
    return len(wanted & found) / len(wanted | found)


def _same(expected: Optional[str], got: Optional[str]) -> float:
    return 1.0 if normalize(expected) == normalize(got) else 0.0


def _average(values: List[float]) -> float:
    return sum(values) / len(values) if values else 1.0


def score_cv(expected: CV, got: CV) -> Dict[str, float]:
    """Compare le résultat à la bonne réponse. Une note de 0 à 100 par rubrique."""
    # On apparie les postes par leur intitulé (deux postes de même intitulé : dans l'ordre).
    remaining: List[Experience] = list(got.experiences)
    pairs = []
    for job in expected.experiences:
        match = next((other for other in remaining if _same(job.job_title, other.job_title)), None)
        if match is not None:
            remaining.remove(match)
        pairs.append((job, match))
    job_count = max(len(expected.experiences), len(got.experiences))

    scores = {
        "identité": _average([
            _same(expected.identity.full_name, got.identity.full_name),
            _same(expected.identity.email, got.identity.email),
            _same(expected.identity.phone, got.identity.phone),
            _same(expected.title, got.title),
        ]),
        "postes": sum(match is not None for _, match in pairs) / job_count if job_count else 1.0,
        # Pour les dates et les réalisations, un poste introuvable vaut zéro.
        "dates": _average([
            (_same(job.start, match.start) + _same(job.end, match.end)) / 2 if match else 0.0 for job, match in pairs
        ]),
        "réalisations": _average([overlap(job.highlights, match.highlights) if match else 0.0 for job, match in pairs]),
        "formation": overlap([study.degree for study in expected.education], [study.degree for study in got.education]),
        "compétences": overlap(expected.skills, got.skills),
        "langues": overlap([language.name for language in expected.languages], [language.name for language in got.languages]),
        "certifs": overlap([item.name for item in expected.certifications], [item.name for item in got.certifications]),
    }
    return {name: round(100 * value, 1) for name, value in scores.items()}


@dataclass
class Row:
    """Le résultat du banc d'essai pour un CV."""

    filename: str
    scores: Dict[str, float] = field(default_factory=dict)
    invented: int = 0  # valeurs absentes du CV d'origine
    missing: int = 0  # lignes du CV d'origine absentes du résultat
    attempts: int = 0
    seconds: float = 0.0
    error: Optional[str] = None

    @property
    def total(self) -> float:
        return round(sum(self.scores.values()) / len(self.scores), 1) if self.scores else 0.0


def evaluate_file(path: Path, provider: LLMProvider, settings: Settings) -> Row:
    row = Row(filename=path.name)
    expected = CV.model_validate_json((EXPECTED_DIR / f"{path.stem}.json").read_text(encoding="utf-8"))
    started = time.monotonic()
    try:
        text = extract_text(path.read_bytes(), path.name, settings.ocr_languages).text[: settings.max_cv_chars]
        cv, row.attempts = structure_cv(text, provider, StepTimer(path.name), copy_mode=settings.llm_copy_mode)
    except Exception as error:  # un échec compte pour zéro, et on passe au CV suivant
        row.error = str(error)
        row.scores = {name: 0.0 for name in CRITERIA}
    else:
        row.scores = score_cv(expected, cv)
        row.invented = len(find_unsupported_values(text, cv))
        row.missing = len(find_missing_lines(text, cv))
    row.seconds = round(time.monotonic() - started, 1)
    return row


def format_table(rows: List[Row]) -> str:
    header = ["fichier", "note", *CRITERIA, "inventé", "oublié", "essais", "secondes"]
    lines = [header]
    for row in rows:
        lines.append([
            row.filename, f"{row.total:.0f}", *[f"{row.scores[name]:.0f}" for name in CRITERIA],
            str(row.invented), str(row.missing), str(row.attempts), f"{row.seconds:.0f}",
        ])
    lines.append([
        "MOYENNE", f"{_average([row.total for row in rows]):.1f}",
        *[f"{_average([row.scores[name] for row in rows]):.0f}" for name in CRITERIA],
        str(sum(row.invented for row in rows)), str(sum(row.missing for row in rows)), "",
        f"{_average([row.seconds for row in rows]):.0f}",
    ])
    widths = [max(len(line[index]) for line in lines) for index in range(len(header))]
    return "\n".join("  ".join(cell.ljust(width) for cell, width in zip(line, widths)) for line in lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Note le modèle sur les faux CV dont on connaît la bonne réponse.")
    parser.add_argument("files", nargs="*", help="fichiers de samples/ à évaluer (par défaut : tous)")
    parser.add_argument("--model", help="modèle Ollama à essayer à la place de celui du .env")
    parser.add_argument("--copy-mode", choices=["text", "refs"], help="text ou refs (voir refs.py), à la place de celui du .env")
    parser.add_argument("--json", dest="json_path", help="fichier où enregistrer le détail des notes")
    arguments = parser.parse_args()

    setup_logging()
    settings = get_settings()
    if arguments.model:
        settings = settings.model_copy(update={"ollama_model": arguments.model})
    if arguments.copy_mode:
        settings = settings.model_copy(update={"llm_copy_mode": arguments.copy_mode})
    provider = get_provider(settings)

    paths = [Path(name) for name in arguments.files] or sorted(
        path for path in SAMPLES_DIR.iterdir() if (EXPECTED_DIR / f"{path.stem}.json").exists() and path.suffix != ".json"
    )
    rows = []
    for path in paths:
        row = evaluate_file(path, provider, settings)
        rows.append(row)
        print(f"{row.filename} : {row.total:.0f}/100 en {row.seconds:.0f} s" + (f" (ÉCHEC : {row.error})" if row.error else ""), flush=True)

    print(f"\nModèle : {provider.model} ({provider.name}), mode {settings.llm_copy_mode} — notes sur 100")
    print(format_table(rows))
    if arguments.json_path:
        detail = {"model": provider.model, "rows": [{**row.__dict__, "total": row.total} for row in rows]}
        Path(arguments.json_path).write_text(json.dumps(detail, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()

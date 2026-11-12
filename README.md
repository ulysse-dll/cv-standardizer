# CV Standardizer

Transforme des CV de toutes formes (PDF, DOCX, scans) en CV au même format,
**entièrement en local et gratuitement** : un petit modèle de langage tourne
sur ta machine via Ollama. Aucune clé d'API payante, aucun CV envoyé sur
Internet (par défaut).

```
fichier ──► 1. extraction du texte ──► 2. LLM ──► 3. validation ──► 4. génération
            PyMuPDF / python-docx       JSON        Pydantic          HTML ─► PDF
            OCR Tesseract si scanné     forcé       + 1 retry         + export JSON
            (aucun LLM ici)
```

## 1. Installation

### a) Ollama et le modèle

1. Installe Ollama : <https://ollama.com/download>
2. Télécharge le modèle par défaut (3,3 Go) :

   ```sh
   ollama pull gemma3:4b
   ```

### b) Python et les bibliothèques système

Le projet a besoin de Python, plus deux programmes qui ne s'installent pas
avec `pip` : **Tesseract** (OCR des PDF scannés) et **Pango** (utilisé par
WeasyPrint pour fabriquer les PDF).

**Mac Intel** — Homebrew ne fournit plus de paquets précompilés pour Intel.
On passe par micromamba (un seul fichier, sans mot de passe admin) et le
dépôt conda-forge :

```sh
# 1. micromamba
mkdir -p ~/.local/bin
curl -L -o ~/.local/bin/micromamba \
  https://github.com/mamba-org/micromamba-releases/releases/latest/download/micromamba-osx-64
chmod +x ~/.local/bin/micromamba

# 2. l'environnement du projet, dans le dossier env/
cd ~/cv-standardizer
~/.local/bin/micromamba create -y -p ./env -c conda-forge python=3.12 pango tesseract

# 3. le français pour l'OCR (l'anglais est déjà fourni)
curl -L -o env/share/tessdata/fra.traineddata \
  https://github.com/tesseract-ocr/tessdata_fast/raw/main/fra.traineddata

# 4. les bibliothèques Python
env/bin/pip install -r requirements.txt
```

**Mac Apple Silicon** — Homebrew fonctionne :

```sh
brew install python@3.12 pango tesseract tesseract-lang
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Sans Tesseract ni Pango, l'application démarre quand même : seuls les PDF
scannés et l'export PDF sont indisponibles (la page l'indique dans son bandeau).

Dans la suite, les commandes utilisent `env/bin/python`. Si ton environnement
est un venv, remplace `env/bin/` par `.venv/bin/`.

### c) Configuration

```sh
cp .env.example .env
```

Les valeurs par défaut conviennent pour démarrer : tu peux ne rien modifier.

## 2. Lancement

```sh
./run.sh
```

Puis ouvre <http://127.0.0.1:8000>. Dépose un ou plusieurs CV, clique sur
« Standardiser », regarde l'aperçu, télécharge le PDF ou le JSON.

Ollama doit tourner (l'application Ollama ouverte, ou `ollama serve`).

### En ligne de commande

```sh
# un seul CV : la réponse arrive quand il est traité
curl -F "file=@samples/cv_classique_fr.pdf" http://127.0.0.1:8000/api/process

# un lot : on reçoit un identifiant de job, puis on suit l'avancement
curl -F "files=@samples/cv_classique_fr.pdf" -F "files=@samples/cv_tableaux_fr.docx" \
     http://127.0.0.1:8000/api/batch
curl http://127.0.0.1:8000/api/batch/<job_id>
curl -OJ http://127.0.0.1:8000/api/batch/<job_id>/zip
```

La liste complète des routes, testable dans le navigateur : <http://127.0.0.1:8000/docs>

## 3. Choisir le modèle

Le modèle se règle avec `OLLAMA_MODEL` dans `.env`. N'importe quel modèle
Ollama convient ; pense à le télécharger d'abord (`ollama pull <nom>`).

| Modèle | Taille | Pour quoi |
|---|---|---|
| `gemma3:4b` (défaut) | 3,3 Go | Bon compromis vitesse / qualité, à l'aise en français |
| `qwen2.5:7b` | 4,7 Go | Plus fiable sur les CV compliqués, nettement plus lent |
| `llama3.2:3b` | 2,0 Go | Plus rapide, moins précis |

Règle pratique sur CPU : le temps est proportionnel au nombre de tokens
écrits par le modèle. Un CV d'une page, c'est environ 500 tokens lus et 600
écrits.

Mesuré sur un Mac mini Intel i5-8500B (6 cœurs, sans GPU) avec `gemma3:4b` :
environ 8 tokens par seconde, soit **65 à 90 secondes par CV d'une page**.
L'extraction, la validation et le rendu HTML prennent moins de 0,1 seconde :
tout le temps passe dans le LLM.

## 4. Changer de provider

Tout se passe dans `.env`, avec `LLM_PROVIDER`.

| Provider | Les CV quittent la machine ? | Usage |
|---|---|---|
| `ollama` (défaut) | Non | Vrais CV |
| `gemini` | **Oui**, vers Google | Développement, avec de faux CV uniquement |
| `custom` | **Oui**, vers ton URL | Démo, par exemple Ollama sur Colab |

Garde-fou : `gemini` et `custom` refusent de démarrer tant que `.env` ne
contient pas `ALLOW_REMOTE=true`, et la page affiche un bandeau rouge.

**Gemini** (clé gratuite sur <https://aistudio.google.com/apikey>) :

```ini
LLM_PROVIDER=gemini
ALLOW_REMOTE=true
GEMINI_API_KEY=ta_cle
GEMINI_MODEL=gemini-2.5-flash
```

Les modèles du tier gratuit changent : si celui-ci est refusé, prends le nom
d'un modèle « Flash » actuel dans la documentation Google.

**Custom**, pour un serveur Ollama distant (Colab exposé par un tunnel) :

```ini
LLM_PROVIDER=custom
ALLOW_REMOTE=true
CUSTOM_API_STYLE=ollama
CUSTOM_BASE_URL=https://ton-tunnel.example
CUSTOM_MODEL=gemma3:4b
```

Pour tout autre serveur au format OpenAI (LM Studio, vLLM...), mets
`CUSTOM_API_STYLE=openai` et l'URL qui se termine par `/v1`.

Redémarre le serveur après chaque changement du `.env`.

## 5. Mesurer la vitesse

Chaque étape est chronométrée. Les durées apparaissent :

- dans la page web, sous chaque CV ;
- dans le terminal et dans `logs/cv_agent.log` ;
- dans un tableau récapitulatif avec :

  ```sh
  env/bin/python -m app.bench            # les 4 faux CV
  env/bin/python -m app.bench mon_cv.pdf # tes fichiers
  ```

Le premier CV après un démarrage est plus lent : Ollama charge le modèle en
mémoire (il y reste ensuite 30 minutes, réglable avec `OLLAMA_KEEP_ALIVE`).

## 6. Tests

```sh
env/bin/python -m pytest
```

Les tests n'ont pas besoin d'Ollama : le LLM y est remplacé par un faux qui
renvoie des réponses écrites d'avance. Les tests d'OCR et de PDF sont sautés
automatiquement si Tesseract ou Pango manquent.

Pour régénérer les faux CV : `env/bin/python samples/generate_samples.py`

## 7. Le rôle de chaque fichier

| Fichier | Rôle |
|---|---|
| `app/config.py` | Lit `.env` et expose les réglages |
| `app/schema.py` | Le schéma du CV (Pydantic), le nettoyage des valeurs, les dates |
| `app/extraction.py` | Fichier → texte brut (PDF, DOCX, OCR), sans LLM |
| `app/prompts.py` | Les consignes envoyées au modèle |
| `app/llm/base.py` | L'interface commune à tous les providers |
| `app/llm/ollama.py` | L'appel à Ollama, avec le paramètre `format` |
| `app/llm/openai_compat.py` | L'appel au format OpenAI (gemini, custom) |
| `app/llm/__init__.py` | Choisit le provider d'après `.env`, avec le garde-fou |
| `app/pipeline.py` | Enchaîne extraction → LLM → validation → retry → rendu |
| `app/coverage.py` | Repère les lignes du CV d'origine absentes du résultat |
| `app/render.py` | CV validé → HTML (Jinja2) → PDF (WeasyPrint) |
| `app/templates/cv.html` | Le modèle visuel du CV standardisé |
| `app/batch.py` | La file d'attente : traite les CV un par un en arrière-plan |
| `app/main.py` | Les routes HTTP (FastAPI) |
| `app/static/index.html` | La page web |
| `app/timing.py` | Le chronomètre par étape et les logs |
| `app/bench.py` | Mesure de vitesse en ligne de commande |
| `samples/` | Les faux CV et le script qui les fabrique |
| `tests/` | Les tests pytest |

## 8. Vie privée

- Avec `ollama`, rien ne sort de la machine. Le serveur n'écoute que sur
  `127.0.0.1` : il n'est pas joignable depuis le réseau.
- Les fichiers envoyés ne sont jamais écrits sur le disque. Les résultats
  (JSON, HTML, PDF) sont rangés dans `outputs/`, qui contient donc des
  données personnelles : supprime ce dossier quand tu n'en as plus besoin.
- `outputs/`, `logs/` et `.env` sont exclus de git.

## 9. Limites connues

- Un petit modèle peut oublier une ligne ou mal ranger une information :
  relis le résultat avant de t'en servir. Un avertissement « À vérifier »
  signale les lignes du CV d'origine qu'on ne retrouve pas dans le résultat,
  mais ce contrôle est approximatif et ne remplace pas la relecture.
- Le provider `gemini` n'a pas été essayé avec une vraie clé : seul son
  format de requête est couvert par les tests.
- Un CV très long est coupé à `MAX_CV_CHARS` caractères (un avertissement s'affiche).
- Les PDF à colonnes sont lus dans l'ordre où le texte est stocké dans le
  fichier, ce qui convient le plus souvent mais pas toujours.
- Les jobs sont gardés en mémoire : ils disparaissent au redémarrage du
  serveur (les fichiers dans `outputs/` restent).

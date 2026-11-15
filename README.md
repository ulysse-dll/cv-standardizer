# CV Standardizer

Transforme des CV de toutes formes (PDF, DOCX, scans) en CV au même format,
**entièrement en local et gratuitement** : un petit modèle de langage tourne
sur ta machine via Ollama. Aucune clé d'API payante, aucun CV envoyé sur
Internet (par défaut).

```
fichier ──► 1. extraction du texte ──► 2. LLM ──► 3. validation ──► 4. génération
            PyMuPDF / python-docx       JSON        Pydantic          HTML ─► PDF
            OCR si le PDF est scanné    forcé       + 1 retry         + diapo PowerPoint
            (aucun LLM ici)                         + 2 contrôles     + export JSON
```

Chaque CV ressort en trois fichiers : un **PDF** d'une page A4, une
**diapositive PowerPoint** (`.pptx`, une seule diapo 16:9, modifiable) et un
**JSON**.

La diapositive est une **fiche profil** au format des documents
d'entreprise, toujours la même : en haut à gauche la **photo du candidat**
(retrouvée dans son CV ; à défaut, un rond avec ses initiales), son nom et
son titre ; à gauche une colonne grise (coordonnées, langues, formation,
certifications) ; à droite le profil, les compétences et les expériences en
tableau, dates alignées dans leur colonne ; en bas un pied de page
« Profil candidat · Confidentiel ».

Après le passage du modèle, tu peux **corriger le résultat à la main** dans
la page : le PDF et la diapositive sont refaits aussitôt, sans relancer le LLM.

## 1. Installation

Deux choses à faire, une seule fois.

**1. Installe Ollama** : <https://ollama.com/download> (c'est lui qui fait
tourner le modèle de langage).

**2. Lance le script d'installation** :

```sh
cd ~/cv-standardizer
./install.sh
```

Il crée l'environnement Python (`.venv`), installe les bibliothèques, crée le
fichier `.env`, télécharge le modèle par défaut (`gemma3:4b`, 3,3 Go) s'il
manque, puis affiche un diagnostic. Il peut être relancé sans risque.

Le diagnostic se relance à tout moment :

```sh
.venv/bin/python -m app.check
```

Il dit, ligne par ligne, ce qui est prêt et ce qui manque (Ollama lancé ?
modèle téléchargé ? OCR ? export PDF ?), avec la commande à taper pour
corriger.

Sur un Mac, deux fonctions s'appuient sur ce que la machine a déjà :

| Fonction | Premier choix | Sinon |
|---|---|---|
| OCR des PDF scannés | Tesseract, s'il est installé | l'OCR intégré à macOS (framework Vision) |
| Export PDF | WeasyPrint, si la bibliothèque Pango est installée | Chrome, Chromium, Edge ou Brave, lancé sans fenêtre |

Le bandeau en haut de la page indique lequel est utilisé. S'il n'y a ni l'un
ni l'autre, l'application démarre quand même : seuls les PDF scannés ou
l'export PDF sont indisponibles.

<details>
<summary>Installation à la main, sans le script</summary>

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
ollama pull gemma3:4b
```

`requirements.lock` donne les versions exactes avec lesquelles l'application
a été testée (macOS, Python 3.9).
</details>

### Facultatif : Tesseract et Pango

Utile seulement hors Mac, ou si tu préfères ces deux outils.

**Mac Intel** — Homebrew ne fournit plus de paquets précompilés pour Intel.
On passe par micromamba (un seul fichier, sans mot de passe admin) et le
dépôt conda-forge. Ces commandes n'ont pas été exécutées sur la machine de
développement : à vérifier à la première utilisation.

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

Dans la suite, les commandes utilisent `.venv/bin/python`. Si tu as créé
l'environnement micromamba, remplace `.venv/bin/` par `env/bin/`
(`./run.sh` choisit tout seul).

### Configuration

Tout se règle dans le fichier `.env` (créé par `./install.sh` à partir de
`.env.example`). Les valeurs par défaut conviennent pour démarrer : tu peux
ne rien modifier.

## 2. Lancement

```sh
./run.sh
```

Sur Mac, tu peux aussi double-cliquer sur `Lancer.command` dans le Finder :
il démarre le serveur et ouvre la page tout seul.

Puis ouvre <http://127.0.0.1:8000>. Dépose un ou plusieurs CV et clique sur
« Standardiser ». Une barre montre l'avancement de chaque CV. Une fois un CV
prêt, quatre onglets :

- **CV standardisé** : l'aperçu du résultat ;
- **Original** : le PDF que tu as envoyé, pour comparer (il reste dans le
  navigateur, donc l'onglet disparaît si tu recharges la page) ;
- **Texte extrait** : ce que le programme a lu dans le fichier, et que le
  modèle a reçu. Pratique pour savoir si une erreur vient de la lecture ou
  du modèle ;
- **Corriger** : un formulaire pour rectifier le résultat. « Enregistrer et
  régénérer » refait le PDF, la diapositive et le JSON en quelques secondes.

Si une photo a été trouvée dans le CV, elle apparaît en vignette à côté du
nom. Le programme peut se tromper d'image (un logo carré, par exemple) : dans
l'onglet « Corriger », le bouton « Retirer la photo de la diapositive » la
remplace par les initiales.

Sous chaque CV, trois boutons de téléchargement : **PDF**, **PowerPoint**
et **JSON**. « Tout télécharger (ZIP) » regroupe les trois formats de tout
le lot, et « PowerPoint du lot » donne un seul fichier avec une diapositive
par candidat.

Sur Mac, un onglet **Diapositive** montre l'image de la diapositive sans
avoir à la télécharger.

### Lot anonyme

Coche « Lot anonyme » avant de cliquer sur « Standardiser » : les documents
sont produits pour un tri à l'aveugle. Le candidat devient « Candidat 01 »,
sans e-mail, téléphone, adresse, liens ni photo, et son nom est masqué s'il
apparaît dans le résumé ou les réalisations. Les entreprises, écoles et dates
restent : elles peuvent suffire à reconnaître quelqu'un. Le texte d'origine
n'est pas conservé pour ces lots. Le nom du fichier envoyé, lui, reste
affiché dans la page et noté dans `job.json` (pas dans les documents) :
renomme tes fichiers avant l'envoi s'ils contiennent le nom du candidat.

### Photo

La photo trouvée dans le CV apparaît dans la diapositive et dans le PDF. Dans
l'onglet « Corriger », « Changer la photo » (ou « Ajouter une photo ») la
remplace par une image de ton choix, et « Retirer la photo » l'enlève.

### Lots précédents

Les lots sont enregistrés dans `outputs/` et retrouvés après un redémarrage
du serveur : la liste « Lots précédents », sous les CV, permet d'y revenir,
de les corriger encore et de les retélécharger. « Supprimer ce lot » efface
ses fichiers. Les lots de plus de 30 jours sont supprimés automatiquement
(réglable avec `OUTPUT_RETENTION_DAYS`, 0 pour tout garder).

### Couleurs, logo, pied de page

Dans `.env` : `THEME_ACCENT` (couleur principale du PDF et de la
diapositive), `THEME_STRIPE` (le liseré sous la barre du haut),
`THEME_LOGO_PATH` (un logo en haut à droite de la diapositive) et
`THEME_FOOTER` (le texte du pied de page). Redémarre le serveur ensuite.

### Le modèle PowerPoint de ton entreprise

Si ton entreprise a son propre modèle `.pptx` (fond, logo, pied de page,
mentions légales), indique son chemin dans `THEME_TEMPLATE_PATH`. La fiche
est alors dessinée sur la mise en page la plus vide du modèle, à sa taille
(16:9 ou 4:3), et notre barre de couleur, notre logo et notre pied de page
disparaissent au profit de ceux du modèle.

La fiche occupe toujours la même zone : le titre en haut, le contenu entre
22 % et 90 % de la hauteur. Si le modèle a un grand bandeau ou un pied de
page épais, le texte peut les recouvrir. Cette fonction a été essayée avec
un modèle fabriqué pour le test, pas avec un vrai modèle d'entreprise.

Ollama doit tourner (l'application Ollama ouverte, ou `ollama serve`).

Tu peux lancer un gros lot et t'éloigner : tant qu'il reste des CV à
traiter, le serveur empêche le Mac de se mettre en veille (avec `caffeinate`,
un outil fourni avec macOS). L'écran, lui, peut s'éteindre.

### En ligne de commande

```sh
# un seul CV : la réponse arrive quand il est traité
curl -F "file=@samples/cv_classique_fr.pdf" http://127.0.0.1:8000/api/process

# un lot : on reçoit un identifiant de job, puis on suit l'avancement
curl -F "files=@samples/cv_classique_fr.pdf" -F "files=@samples/cv_tableaux_fr.docx" \
     http://127.0.0.1:8000/api/batch
curl http://127.0.0.1:8000/api/batch/<job_id>
curl -OJ http://127.0.0.1:8000/api/batch/<job_id>/zip

# un fichier précis : pdf, pptx ou json (ici ceux du 1er CV, numéro 0)
curl -OJ http://127.0.0.1:8000/api/batch/<job_id>/items/0/pdf
curl -OJ http://127.0.0.1:8000/api/batch/<job_id>/items/0/pptx

# corriger un résultat : on renvoie le JSON modifié
curl -o cv.json http://127.0.0.1:8000/api/batch/<job_id>/items/0/json
curl -X PUT -H "Content-Type: application/json" -d @cv.json \
     http://127.0.0.1:8000/api/batch/<job_id>/items/0
```

La liste complète des routes, testable dans le navigateur : <http://127.0.0.1:8000/docs>

## 3. Choisir le modèle

Le modèle se règle avec `OLLAMA_MODEL` dans `.env`. N'importe quel modèle
Ollama convient ; pense à le télécharger d'abord (`ollama pull <nom>`).

Trois modèles ont été notés avec le banc d'essai (section 6), sur les 5 faux
CV, sur un Mac mini Intel i5-8500B sans carte graphique :

| Modèle | Taille | Note sur 100 | Temps moyen par CV | Ce qu'on observe |
|---|---|---|---|---|
| `gemma3:4b` (défaut) | 3,3 Go | 100 | 55 s | Tout est juste sur les 5 CV |
| `qwen2.5:3b` | 1,9 Go | 86 | 58 s | Oublie des postes entiers sur 2 CV |
| `llama3.2:3b` | 2,0 Go | 85 | 62 s | Oublie des postes et des diplômes sur 3 CV |

Les deux petits modèles ne sont pas plus rapides en pratique et perdent du
contenu : `gemma3:4b` reste le bon choix. Les temps de `gemma3:4b` ont été
pris machine au repos ; ceux des deux autres pendant que d'autres tâches
tournaient, ils sont donc un peu pessimistes. `qwen2.5:7b` (4,7 Go) n'a pas
été noté : attends-toi à nettement plus lent.

Une piste a été essayée puis abandonnée : faire désigner au modèle les
numéros des lignes du CV (pour les réalisations et le résumé) au lieu de les
lui faire recopier. Avec `gemma3:4b`, la note tombe à 36 sur 100 : sur 3 CV
sur 5 le modèle écrit des numéros sans s'arrêter, et sur les autres il perd
des réalisations, sans gagner de temps.

Règle pratique sur CPU : le temps est proportionnel au nombre de tokens
écrits par le modèle. Un CV d'une page, c'est environ 500 tokens lus et 600
écrits.

Mesuré sur un Mac mini Intel i5-8500B (6 cœurs, sans GPU) avec `gemma3:4b` :
environ 8 tokens par seconde, soit **50 à 90 secondes par CV d'une page**
selon ce que la machine fait d'autre.
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
  .venv/bin/python -m app.bench            # les 4 faux CV
  .venv/bin/python -m app.bench mon_cv.pdf # tes fichiers
  ```

Le premier CV après un démarrage est plus lent : Ollama charge le modèle en
mémoire (il y reste ensuite 30 minutes, réglable avec `OLLAMA_KEEP_ALIVE`).

## 6. Tests et banc d'essai

```sh
.venv/bin/python -m pytest
```

Le **banc d'essai** répond à une autre question : le modèle fait-il du bon
travail ? Il fait traiter les faux CV par le vrai modèle et compare chaque
résultat à la bonne réponse (`samples/expected/`), rubrique par rubrique :

```sh
.venv/bin/python -m app.eval                      # le modèle du .env
.venv/bin/python -m app.eval --model llama3.2:3b  # un autre, pour comparer
```

À lancer avant et après tout changement de consigne (`app/prompts.py`) ou de
modèle. Attention : les faux CV sont courts et propres, une note de 100 ne
garantit rien sur de vrais CV.

Les tests n'ont pas besoin d'Ollama : le LLM y est remplacé par un faux qui
renvoie des réponses écrites d'avance. Les tests d'OCR et de PDF sont sautés
automatiquement si la machine n'a aucun moteur pour les faire.

Pour régénérer les faux CV : `.venv/bin/python samples/generate_samples.py`

## 7. Le rôle de chaque fichier

| Fichier | Rôle |
|---|---|
| `app/config.py` | Lit `.env` et expose les réglages |
| `app/schema.py` | Le schéma du CV (Pydantic), le nettoyage des valeurs, les dates |
| `app/extraction.py` | Fichier → texte brut (PDF, DOCX), sans LLM |
| `app/ocr.py` | Image d'une page scannée → texte (Tesseract ou OCR de macOS) |
| `app/prompts.py` | Les consignes envoyées au modèle |
| `app/llm/base.py` | L'interface commune à tous les providers |
| `app/llm/ollama.py` | L'appel à Ollama, avec le paramètre `format` |
| `app/llm/openai_compat.py` | L'appel au format OpenAI (gemini, custom) |
| `app/llm/__init__.py` | Choisit le provider d'après `.env`, avec le garde-fou |
| `app/pipeline.py` | Enchaîne extraction → LLM → validation → retry → rendu |
| `app/coverage.py` | Deux contrôles sans LLM : lignes oubliées, valeurs inventées |
| `app/render.py` | CV validé → HTML (Jinja2) → PDF (WeasyPrint ou navigateur) |
| `app/templates/cv.html` | Le modèle visuel du CV standardisé |
| `app/photo.py` | Retrouve la photo du candidat dans le fichier, sans LLM |
| `app/slides.py` | CV validé + photo → une diapositive PowerPoint (python-pptx) |
| `app/batch.py` | La file d'attente : traite les CV un par un, enregistre les corrections |
| `app/main.py` | Les routes HTTP (FastAPI) |
| `app/static/index.html` | La page web |
| `app/timing.py` | Le chronomètre par étape et les logs |
| `app/fixes.py` | Corrections sans LLM d'après le texte d'origine (poste en cours) |
| `app/anonymize.py` | La version anonyme d'un CV |
| `app/preview.py` | L'image de la diapositive, pour la page (Quick Look, Mac) |
| `app/theme.py` | Couleurs et logo réglables dans `.env` |
| `app/bench.py` | Mesure de vitesse en ligne de commande |
| `app/eval.py` | Banc d'essai : note le modèle contre des réponses attendues |
| `app/check.py` | Diagnostic de l'installation (`python -m app.check`) |
| `install.sh`, `run.sh`, `Lancer.command` | Installer, lancer, lancer d'un double-clic (Mac) |
| `Dockerfile`, `docker-compose.yml` | Déploiement sur un serveur Linux (non essayé) |
| `requirements.txt`, `requirements.lock` | Les bibliothèques ; les versions exactes testées |
| `samples/` | Les faux CV et le script qui les fabrique |
| `tests/` | Les tests pytest |

## 8. Vie privée

- Avec `ollama`, rien ne sort de la machine. Le serveur n'écoute que sur
  `127.0.0.1` : il n'est pas joignable depuis le réseau.
- Les fichiers envoyés ne sont jamais écrits sur le disque. Les résultats
  (JSON, HTML, PDF) sont rangés dans `outputs/`, qui contient donc des
  données personnelles : supprime ce dossier quand tu n'en as plus besoin.
- L'OCR de macOS tourne sur la machine, sans connexion.
- Quand le PDF passe par un navigateur, le CV est écrit le temps de la
  conversion dans un dossier temporaire, supprimé aussitôt. Le navigateur
  est lancé avec un profil vide, et deux réglages lui coupent le réseau :
  la résolution des noms de domaine échoue toujours, et toute connexion est
  dirigée vers un proxy qui n'existe pas. Ce blocage repose sur les options
  du navigateur ; il n'a pas été contrôlé avec un outil d'écoute réseau.
- La photo du candidat et le texte extrait de son CV sont enregistrés dans
  le dossier du lot, avec les résultats. La détection de visage est celle de
  macOS : elle tourne sur la machine.
- Les lots de plus de 30 jours sont supprimés automatiquement
  (`OUTPUT_RETENTION_DAYS`), et « Supprimer ce lot » efface un lot tout de
  suite.
- Un lot anonyme ne garde ni le nom, ni les coordonnées, ni la photo, ni le
  texte d'origine.
- `outputs/`, `logs/` et `.env` sont exclus de git.

## 9. Déployer sur une autre machine

Par défaut l'application n'a **pas de mot de passe** : quiconque peut ouvrir
la page peut envoyer et lire des CV. C'est sans risque tant qu'elle n'écoute
que sur ta machine (`127.0.0.1`, le réglage par défaut).

Avant de l'ouvrir à d'autres postes, définis `APP_PASSWORD` dans `.env` : le
navigateur demandera ce mot de passe (le nom d'utilisateur est libre). C'est
une protection simple : sans HTTPS, le mot de passe circule en clair sur le
réseau. Elle convient à un réseau local de confiance, pas à Internet, où il
faut un accès protégé devant l'application (VPN, ou reverse proxy en HTTPS).

### Sur un autre Mac

```sh
git clone <adresse du dépôt> cv-standardizer   # ou copie du dossier, sans .venv/ ni outputs/
cd cv-standardizer
./install.sh
./run.sh
```

C'est le parcours qui a été essayé de bout en bout (copie neuve du dépôt,
installation, traitement d'un CV).

Pour que d'autres postes du même réseau local y accèdent : définis
`APP_PASSWORD`, lance `HOST=0.0.0.0 ./run.sh`, puis ouvre
`http://<adresse-du-mac>:8000` depuis les autres postes.

### Sur un serveur Linux, avec Docker

```sh
docker compose up --build -d
docker compose exec ollama ollama pull gemma3:4b    # une seule fois
docker compose exec app python -m app.check         # diagnostic
```

Puis <http://127.0.0.1:8000> depuis le serveur. Sous Linux, l'OCR passe par
Tesseract et le PDF par WeasyPrint, installés dans l'image.

**Non essayé** : Docker n'est pas installé sur la machine de développement.
Ni les deux fichiers Docker, ni les chemins Tesseract et WeasyPrint n'ont
tourné une seule fois. Attends-toi à devoir ajuster, et commence par le
diagnostic.

Sans carte graphique, compte sur une vitesse du même ordre que sur un Mac
Intel (une à deux minutes par CV).

## 10. Limites connues

- Un petit modèle peut oublier une ligne, mal ranger une information ou
  ajouter un détail : relis le résultat avant de t'en servir. Deux
  avertissements « À vérifier » aident : l'un signale les lignes du CV
  d'origine absentes du résultat, l'autre les valeurs du résultat absentes
  du CV d'origine. Ces contrôles comparent des mots : ils sont approximatifs
  et ne remplacent pas la relecture. Par exemple, un organisme déduit du nom
  d'une certification (« Microsoft » pour « Microsoft PL-300 ») n'est pas
  signalé.
- La vitesse dépend du processeur : compte environ une minute et demie par
  CV d'une page. La barre de progression est une estimation.
- L'export PDF par le navigateur prend de 1 à 6 secondes selon les moments,
  sans cause identifiée.
- La diapositive n'a qu'une page. Pour un CV long, la police est réduite
  (jusqu'à 9 points), puis le nombre de réalisations par poste (un
  avertissement « Diapositive » le signale). La place prise par le texte est
  estimée, pas mesurée : sur un CV extrême, le texte peut déborder.
- La diapositive a été contrôlée avec l'aperçu de macOS (Quick Look), pas
  dans PowerPoint ni Keynote, absents de la machine de développement.
- L'aperçu de la diapositive dans la page n'existe que sur Mac (il vient de
  Quick Look). Ailleurs, il faut la télécharger.
- La photo est choisie d'après la forme des images (portrait ou carré, ni
  minuscule ni très large) et, sur Mac, d'après la présence d'un visage. Elle
  peut être fausse (logo pris pour une photo) ou manquer (photo de profil,
  très petite, ou dans un format que le programme ne lit pas). On peut la
  retirer ou la remplacer à la main.
- Le poste en cours est reconnu par des mots-clés (« depuis », « aujourd'hui »,
  « present »...) placés sur la ligne du poste ou la suivante. Une autre
  tournure ne sera pas vue.
- Le provider `gemini` n'a pas été essayé avec une vraie clé : seul son
  format de requête est couvert par les tests.
- Un CV très long est coupé à `MAX_CV_CHARS` caractères (un avertissement s'affiche).
- Les PDF à colonnes sont lus dans l'ordre où le texte est stocké dans le
  fichier, ce qui convient le plus souvent mais pas toujours.
- Les jobs sont gardés en mémoire : ils disparaissent au redémarrage du
  serveur (les fichiers dans `outputs/` restent).

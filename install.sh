#!/bin/sh
# Installe l'application sur cette machine (Mac ou Linux).
#
#     ./install.sh
#
# Peut être relancé sans risque : chaque étape vérifie d'abord si elle est
# déjà faite. Ne demande aucun mot de passe administrateur.

set -e  # on s'arrête à la première commande qui échoue
cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"

# ---- 1. Python ---------------------------------------------------------
if ! command -v "$PYTHON" >/dev/null 2>&1; then
    echo "Python 3 est introuvable. Installe-le depuis https://www.python.org/downloads/ puis relance ./install.sh" >&2
    exit 1
fi
if ! "$PYTHON" -c 'import sys; sys.exit(sys.version_info < (3, 9))'; then
    echo "Il faut Python 3.9 ou plus récent (trouvé : $("$PYTHON" --version))." >&2
    exit 1
fi

# ---- 2. Environnement virtuel et bibliothèques -------------------------
# Un "venv" est un dossier (.venv) qui contient les bibliothèques du projet,
# sans toucher au Python du système.
if [ ! -x .venv/bin/python ]; then
    echo "1/4  Création de l'environnement Python (.venv)..."
    "$PYTHON" -m venv .venv
else
    echo "1/4  Environnement Python déjà présent."
fi
echo "2/4  Installation des bibliothèques (quelques minutes la première fois)..."
.venv/bin/python -m pip install --quiet --upgrade pip
.venv/bin/python -m pip install --quiet -r requirements.txt

# ---- 3. Configuration --------------------------------------------------
if [ ! -f .env ]; then
    cp .env.example .env
    echo "3/4  Fichier .env créé (réglages par défaut : tout en local)."
else
    echo "3/4  Fichier .env déjà présent, laissé tel quel."
fi

# ---- 4. Ollama et le modèle --------------------------------------------
PROVIDER="$(grep -E '^LLM_PROVIDER=' .env | cut -d= -f2)"
MODEL="$(grep -E '^OLLAMA_MODEL=' .env | cut -d= -f2)"
MODEL="${MODEL:-gemma3:4b}"
if [ "${PROVIDER:-ollama}" != "ollama" ]; then
    echo "4/4  Provider « $PROVIDER » : pas de modèle local à installer."
elif ! command -v ollama >/dev/null 2>&1; then
    echo "4/4  Ollama n'est pas installé. Télécharge-le sur https://ollama.com/download, puis relance ./install.sh"
elif ollama list 2>/dev/null | awk '{print $1}' | grep -qx "$MODEL"; then
    echo "4/4  Modèle $MODEL déjà téléchargé."
else
    echo "4/4  Téléchargement du modèle $MODEL (plusieurs Go)..."
    ollama pull "$MODEL"
fi

# ---- Bilan -------------------------------------------------------------
echo
.venv/bin/python -m app.check

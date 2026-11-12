#!/bin/sh
# Lance le serveur sur http://127.0.0.1:8000
# 127.0.0.1 = accessible uniquement depuis cette machine, pas depuis le réseau.
#
# Utilise l'environnement conda "env/" s'il existe (il contient Tesseract et
# Pango), sinon le venv ".venv/".

cd "$(dirname "$0")" || exit 1

if [ -x env/bin/python ]; then
    PYTHON=env/bin/python
    # Indique à WeasyPrint où trouver les bibliothèques (Pango...) de l'environnement.
    export DYLD_FALLBACK_LIBRARY_PATH="$PWD/env/lib:${DYLD_FALLBACK_LIBRARY_PATH:-/usr/local/lib:/usr/lib}"
    export TESSDATA_PREFIX="$PWD/env/share/tessdata"
elif [ -x .venv/bin/python ]; then
    PYTHON=.venv/bin/python
else
    echo "Aucun environnement Python trouvé. Voir le README, section Installation." >&2
    exit 1
fi

exec "$PYTHON" -m uvicorn app.main:app --host 127.0.0.1 --port "${PORT:-8000}"

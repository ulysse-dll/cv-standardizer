#!/bin/sh
# Sur Mac : double-clique sur ce fichier pour démarrer l'application.
# Il installe ce qui manque, lance le serveur et ouvre la page dans le navigateur.
# Pour arrêter : ferme la fenêtre du Terminal (ou Ctrl+C).

cd "$(dirname "$0")" || exit 1

if [ ! -x .venv/bin/python ] && [ ! -x env/bin/python ]; then
    ./install.sh || exit 1
fi

PORT="${PORT:-8000}"
# En arrière-plan : on attend que le serveur réponde, puis on ouvre la page.
(
    until curl -s -o /dev/null "http://127.0.0.1:$PORT/health"; do sleep 1; done
    open "http://127.0.0.1:$PORT"
) &

exec ./run.sh

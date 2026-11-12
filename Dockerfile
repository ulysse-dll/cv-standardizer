# Image Docker de l'application, pour un serveur Linux.
#
# ATTENTION : ce fichier n'a pas pu être essayé sur la machine de
# développement (Docker n'y est pas installé). Voir le README, section
# « Déploiement ».
#
#     docker compose up --build          (avec le docker-compose.yml fourni)

FROM python:3.12-slim

# Sous Linux, on installe les deux outils prévus à l'origine :
#   - Tesseract pour l'OCR (avec le français ; l'anglais est fourni d'office)
#   - Pango pour WeasyPrint (export PDF), plus une police de caractères
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        tesseract-ocr tesseract-ocr-fra \
        libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 \
        fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Les bibliothèques d'abord : tant que requirements.txt ne change pas, Docker
# réutilise cette étape au lieu de tout retélécharger.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Dans un conteneur, il faut écouter sur 0.0.0.0 pour être joignable depuis
# l'extérieur du conteneur. C'est docker-compose.yml qui limite ensuite
# l'accès à la machine hôte (127.0.0.1).
ENV HOST=0.0.0.0 PORT=8000
EXPOSE 8000

CMD ["sh", "-c", "python -m uvicorn app.main:app --host \"$HOST\" --port \"$PORT\""]

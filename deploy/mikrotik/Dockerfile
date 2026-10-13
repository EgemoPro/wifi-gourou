# syntax=docker/dockerfile:1
# ─────────────────────────────────────────────────────────────────────────────
#  Image de l'agent WIFIZONE pour container RouterOS (arm64 / amd64)
#  À construire depuis la RACINE du dépôt :
#    docker buildx build --platform linux/arm64 -f deploy/mikrotik/Dockerfile .
#  Voir deploy/mikrotik/README.md
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUTF8=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DATA_DIR=/data \
    LOG_LEVEL=INFO

WORKDIR /app

# --only-binary : échoue vite plutôt que de compiler (pas de Rust/gcc dans l'image)
COPY deploy/mikrotik/requirements-container.txt /tmp/requirements.txt
RUN pip install --only-binary=:all: -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

COPY . /app

# /data = volume persistant (clé USB) : bases SQLite, logs, backups, bons PDF
RUN mkdir -p /data
VOLUME ["/data"]

# 9000 = réception des alertes du routeur, 9001 = API de commande (exposée via Tailscale)
EXPOSE 9000 9001

# Toute la configuration vient des variables d'environnement (SITE_ID, MIKROTIK_*, CENTRAL_*…)
CMD ["python", "main.py"]

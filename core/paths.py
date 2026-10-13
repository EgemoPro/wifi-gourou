"""
core/paths.py — Dossier de données de l'agent.

Par défaut (PC Ubuntu/Windows) les données restent à côté du code, comme avant.
En container (RouterOS, Docker), DATA_DIR pointe vers un volume persistant
(ex. clé USB montée sur /data) : bases SQLite, logs, backups, bons PDF.
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR") or BASE_DIR)

try:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
except OSError:
    # Le message d'erreur utile sera levé plus tard à l'ouverture des bases
    pass

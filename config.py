"""
config.py — Chargement configuration depuis .env
SITE_ID est obligatoire — l'agent refuse de démarrer sans lui.
"""

# ── Vérification version Python minimale ──────────────────────────────────────
import sys

_MIN_PYTHON = (3, 9)
if sys.version_info < _MIN_PYTHON:
    print(
        f"[ERREUR] Python 3.9+ requis (version actuelle: "
        f"{sys.version_info.major}.{sys.version_info.minor})"
    )
    print("         Mettez à jour Python ou installez une version plus récente.")
    sys.exit(1)

import os
import logging
from pathlib import Path
from dotenv import load_dotenv

env_path = Path(os.getenv("ENV_PATH", Path(__file__).parent / ".env"))
load_dotenv(dotenv_path=env_path)

logger = logging.getLogger("config")


def _require(key: str) -> str:
    """Lit une variable obligatoire — arrête l'agent si absente."""
    val = os.getenv(key)
    if not val:
        print(f"[ERREUR] Variable obligatoire manquante dans .env : {key}")
        print(f"         Fichier .env lu : {env_path}")
        sys.exit(1)
    return val


def _int(key: str, default: int) -> int:
    return int(os.getenv(key, default))


# ── Constantes nommées ─────────────────────────────────────────────────────
DEFAULT_BACKUP_HOUR = 2
DEFAULT_QUEUE_FLUSH_INTERVAL = 60


CONFIG: dict = {

    # ── Identité — OBLIGATOIRE ────────────────────────────────────────────────
    "site_id":   _require("SITE_ID"),
    "site_name": _require("SITE_NAME"),

    # ── MikroTik SSH — OBLIGATOIRE ─────────────────────────────────────────────
    "mikrotik_host":        _require("MIKROTIK_HOST"),
    "mikrotik_port":        _int("MIKROTIK_PORT",     8728),    # Port API (archivé)
    "mikrotik_ssh_port":    _int("MIKROTIK_SSH_PORT", 22),      # Port SSH
    "mikrotik_rest_port":   _int("MIKROTIK_REST_PORT", 8080),  # Port REST API
    "mikrotik_user":        os.getenv("MIKROTIK_USER",     "admin"),
    "mikrotik_password":    _require("MIKROTIK_PASSWORD"),
    "mikrotik_ros_version": _int("MIKROTIK_ROS_VERSION", 7),
    "ssh_timeout":          _int("SSH_TIMEOUT",          15),    # Timeout SSH (s)

    # ── PC Central — OBLIGATOIRE ──────────────────────────────────────────────
    "central_host":    _require("CENTRAL_HOST"),
    "central_port":    _int("CENTRAL_PORT", 5678),
    "central_api_key": os.getenv("CENTRAL_API_KEY", ""),

    # ── Ports de l'agent ─────────────────────────────────────────────────────
    "alert_port":   _int("ALERT_PORT",   9000),
    "command_port": _int("COMMAND_PORT", 9001),

    # ── IP Tailscale de cet agent (pour s'enregistrer) ────────────────────────
    # Laisser vide → l'agent détecte automatiquement son IP Tailscale
    "agent_tailscale_ip": os.getenv("AGENT_TAILSCALE_IP", ""),

    # ── Intervalles (secondes) ────────────────────────────────────────────────
    "intervals": {
        "metrics":          _int("INTERVAL_METRICS",    300),
        "clients":          _int("INTERVAL_CLIENTS",    60),
        "bandwidth_check":  _int("INTERVAL_BANDWIDTH",  120),
        "offline_check":    _int("INTERVAL_OFFLINE",    120),
        "user_bloat_check": _int("INTERVAL_USER_BLOAT", 3600),
        "scheduler_check":  _int("INTERVAL_SCHEDULERS", 3600),
        "backup_hour":      _int("BACKUP_HOUR",         DEFAULT_BACKUP_HOUR),
        "register_retry":   _int("REGISTER_RETRY",      60),
        "queue_flush":      _int("INTERVAL_QUEUE_FLUSH", DEFAULT_QUEUE_FLUSH_INTERVAL),
    },

    # ── Seuils ────────────────────────────────────────────────────────────────
    "thresholds": {
        "cpu_alert_percent":       _int("THRESHOLD_CPU",                80),
        "cpu_alert_cycles":        _int("THRESHOLD_CPU_CYCLES",         2),
        "bandwidth_suspect_mb":    _int("THRESHOLD_BANDWIDTH_MB",       500),
        "max_users_warning":       _int("THRESHOLD_MAX_USERS",          200),
        "max_schedulers_warning":  _int("THRESHOLD_MAX_SCHEDULERS",     20),
        "offline_retries":         _int("THRESHOLD_OFFLINE_RETRIES",    3),
    },
}

# CENTRAL_API_KEY est obligatoire — refus de démarrer sans elle
if not CONFIG["central_api_key"]:
    raise ValueError(
        "CENTRAL_API_KEY is required but not set in .env or environment"
    )

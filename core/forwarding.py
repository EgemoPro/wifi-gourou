"""
core/forwarding.py — Envoi vers PC central + queue durable pour mode offline

Encapsule Queue (core/queue.py) + HTTP POST avec backoff exponentiel.
Remplace l'ancien forwarder.py avec une API plus propre.

Usage :
    forwarder = Forwarder(CONFIG)
    forwarder.send_metrics(data)
    forwarder.send_alert(alert)
    stats = forwarder.stats()
    forwarder.cleanup()
"""
import json
import time
import random
import logging
from typing import Any, Optional

import requests

from core.queue import Queue

logger = logging.getLogger("forwarder")

# ── Chemins webhook n8n (port 5678) ───────────────────────────────────────────
# Format n8n v3+: /webhook/{webhookId}
# L'webhook INGEST unique (ingest-metrics) route par champ "mode":
#   mode=metrics → Insert metrics (site_metrics)
#   mode=alert   → Insert alert (alerts)
#   fallback     → metrics
WEBHOOK_PATHS: dict[str, str] = {
    "METRICS":     "/webhook/ingest-metrics",
    "CLIENTS":     "/webhook/ingest-metrics",
    "ALERT":       "/webhook/ingest-metrics",
    "CMD_RESULT":  "/webhook/ingest-metrics",
    "BACKUP":      "/webhook/ingest-metrics",
    "DIAGNOSTICS": "/webhook/ingest-metrics",
    "REGISTER":    "/webhook/register",
}

MODE_MAP: dict[str, str] = {
    "METRICS": "metrics",
    "CLIENTS": "clients",
    "ALERT": "alert",
    "CMD_RESULT": "cmd_result",
    "BACKUP": "backup",
    "DIAGNOSTICS": "diagnostics",
}

# Délais de reconnexion vers le PC central (secondes)
CENTRAL_RETRY_DELAYS = [10, 30, 60, 120, 300]

# Timeout HTTP par défaut (secondes)
HTTP_TIMEOUT = 10

# Taille maximale d'un payload (10 Mo)
MAX_PAYLOAD_SIZE = 10 * 1024 * 1024


class Forwarder:
    """
    Envoi vers PC central avec queue durable pour mode offline.

    Wraps Queue (core/queue.py) + HTTP POST logic with exponential backoff.
    Les messages sont d'abord tentés en HTTP ; si le central est injoignable,
    ils sont mis en queue (durable_queue table) pour envoi ultérieur.

    Usage :
        forwarder = Forwarder(CONFIG)
        forwarder.send_metrics(metrics_data)
        forwarder.send_alert(alert_data)
    """

    def __init__(self, config: dict):
        self.config = config
        self.queue = Queue()

    # ── HTTP avec backoff exponentiel ─────────────────────────────────────────

    def _http_post(self, path: str, payload: dict[str, Any],
                   timeout: int = HTTP_TIMEOUT) -> dict[str, Any]:
        """
        POST vers le PC central (n8n webhook) avec backoff exponentiel.
        Lève une exception si tous les essais échouent.
        """
        conf = self.config
        url = f"http://{conf['central_host']}:{conf['central_port']}{path}"
        headers = {
            "Content-Type": "application/json",
            "X-API-Key":    conf.get("central_api_key", ""),
            "X-Site-ID":    conf["site_id"],
        }
        last_error: Optional[str] = None

        for attempt, delay in enumerate(CENTRAL_RETRY_DELAYS, start=1):
            try:
                r = requests.post(url, json=payload, headers=headers, timeout=timeout)
                r.raise_for_status()
                # Certains webhooks n8n retournent 200 OK sans body → r.json() échouerait
                try:
                    return r.json()
                except (json.JSONDecodeError, ValueError):
                    return {"status": "ok", "detail": "empty response"}
            except requests.exceptions.HTTPError as e:
                # 4xx/5xx → pas la peine de retenter
                raise RuntimeError(f"HTTP {e.response.status_code} : {e}")
            except (requests.exceptions.ConnectionError,
                    requests.exceptions.Timeout) as e:
                last_error = str(e)
                if attempt < len(CENTRAL_RETRY_DELAYS):
                    jitter = delay * 0.2 * random.uniform(-1, 1)
                    wait = max(1, delay + jitter)
                    logger.warning(
                        f"Central injoignable ({e}) — "
                        f"tentative {attempt}/{len(CENTRAL_RETRY_DELAYS)} "
                        f"dans {wait:.0f}s"
                    )
                    time.sleep(wait)

        raise ConnectionError(
            f"PC Central injoignable après {len(CENTRAL_RETRY_DELAYS)} "
            f"tentatives : {last_error}"
        )

    # ── Envoi principal ───────────────────────────────────────────────────────

    def _flush_send_fn(self, msg_type: str, payload: dict[str, Any]) -> bool:
        """Callback pour Queue.flush() — retourne True/False."""
        path = WEBHOOK_PATHS.get(msg_type, "/webhook/ingest-metrics")
        mode = MODE_MAP.get(msg_type, "metrics")
        payload_with_mode = {"mode": mode, **payload}
        try:
            self._http_post(path, payload_with_mode)
            return True
        except Exception as e:
            logger.debug(f"Flush HTTP fail ({msg_type}): {e}")
            return False

    def _send_or_queue(self, msg_type: str, data: dict[str, Any],
                       priority: int = 0) -> None:
        """
        Tente l'envoi avec backoff.
        Si échec → met en queue durable.
        Si succès → flush automatique de la queue.
        priority=1 pour les alertes (passent en tête de queue).
        """
        path = WEBHOOK_PATHS.get(msg_type, "/webhook/ingest-metrics")
        mode = MODE_MAP.get(msg_type, "metrics")
        payload_with_mode = {"mode": mode, **data}
        try:
            self._http_post(path, payload_with_mode)
            logger.debug(f"Envoyé : {msg_type}")
            # On a réussi → tenter de vider la queue
            self.queue.flush(self._flush_send_fn)
        except Exception as e:
            logger.warning(f"Mise en queue ({msg_type}) : {e}")
            self.queue.push(msg_type, data, priority=priority)

    # ── Helpers par type ──────────────────────────────────────────────────────

    def send_metrics(self, data: dict[str, Any]) -> None:
        """Envoie les métriques système."""
        self._send_or_queue("METRICS", data)

    def send_clients(self, data: dict[str, Any]) -> None:
        """Envoie la liste des clients actifs."""
        self._send_or_queue("CLIENTS", data)

    def send_alert(self, data: dict[str, Any], priority: int = 1) -> None:
        """Envoie une alerte (priorité haute)."""
        self._send_or_queue("ALERT", data, priority=priority)

    def send_command_result(self, data: dict[str, Any]) -> None:
        """Envoie le résultat d'une commande."""
        self._send_or_queue("CMD_RESULT", data)

    def send_backup_result(self, data: dict[str, Any]) -> None:
        """Envoie le résultat d'un backup."""
        self._send_or_queue("BACKUP", data)

    def send_diagnostics(self, data: dict[str, Any]) -> None:
        """Envoie les diagnostics."""
        self._send_or_queue("DIAGNOSTICS", data)

    def register_site(self, agent_url: str) -> None:
        """
        Enregistre ce site auprès du PC central au démarrage.
        Retry toutes les 60s si le central est injoignable.
        """
        conf = self.config
        payload = {
            "site_id":       conf["site_id"],
            "site_name":     conf["site_name"],
            "agent_url":     agent_url,
            "mikrotik_host": conf["mikrotik_host"],
            "active":        True,
        }
        retry_delay = conf["intervals"].get("register_retry", 60)

        while True:
            try:
                self._http_post(WEBHOOK_PATHS["REGISTER"], payload,
                                timeout=HTTP_TIMEOUT)
                logger.info(f"✅ Site enregistré : {conf['site_id']} → {agent_url}")
                return
            except Exception as e:
                logger.warning(
                    f"Enregistrement échoué ({e}) — "
                    f"nouvelle tentative dans {retry_delay}s"
                )
                time.sleep(retry_delay)

    # ── Délégation à Queue ─────────────────────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        """Statistiques de la queue durable."""
        return self.queue.stats()

    def cleanup(self) -> dict[str, int]:
        """Nettoie les messages anciens de la queue durable."""
        return self.queue.cleanup()

    def pending_count(self) -> int:
        """Retourne le nombre de messages en attente (rapide)."""
        return self.queue.pending_count()

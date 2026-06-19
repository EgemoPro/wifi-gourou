#!/usr/bin/env python3
"""
main.py — Agent local WIFIZONE
Tourne sur le PC Ubuntu de chaque site.

Nouvelle architecture (v2) :
  - Moteur SSH + scripts déterministes (.rsc) au lieu de RouterOS API
  - Registre d'actions via config/commands.json
  - Pipeline générique : lookup → validation → exécution → retour structuré

Usage :
  ENV_PATH=/opt/wifizone-agent/.env python main.py
"""

import os
import json
import uuid
import socket
import asyncio
import contextlib
import logging
import hmac
import functools
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any

import uvicorn
import requests as http_requests
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from fastapi import FastAPI, BackgroundTasks, HTTPException, Request, Query
from fastapi.responses import FileResponse

from config      import CONFIG
from models      import MikroTikRawAlert, CommandRequest, ActionRequest, AlertData
from core.ssh    import SSHPool
from core.executor import execute_action
from core.registry import list_actions, lookup, resolve_name, get_capabilities
from core.storage import Storage
from core.queue   import Queue
from workers.metrics import (
    collect_metrics, collect_clients,
    check_bandwidth_abuse, check_router_online,
    check_user_bloat, check_scheduler_bloat,
)
from core.forwarding import Forwarder

# ── Logging ───────────────────────────────────────────────────────────────────
Path("logs").mkdir(exist_ok=True)
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)-8s] %(name)s — %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(
            f"logs/{CONFIG['site_id'].lower()}.log"
        ),
    ]
)
logger = logging.getLogger("main")

# ── État partagé ──────────────────────────────────────────────────────────────
shared_state: Dict[str, Any] = {
    "offline_count":   0,
    "last_seen":       None,
    "cpu_alert_count": 0,
    "latest_metrics":  None,
    "agent_url":       "",
    "version":         "2.0",
}

# ── Ressources globales ───────────────────────────────────────────────────────
ssh_pool:       Optional[SSHPool] = None
forwarder:      Optional[Forwarder] = None
storage:        Optional[Storage] = None
durable_queue:  Optional[Queue] = None


# ── Helper auth ─────────────────────────────────────────────────────────────────

def _check_api_key(request: Request):
    """Vérifie l'API key pour les endpoints protégés."""
    api_key = request.headers.get("X-API-Key", "")
    key = CONFIG.get("central_api_key", "")
    if not hmac.compare_digest(api_key, key):
        raise HTTPException(status_code=401, detail="Unauthorized")


# ── Détection IP Tailscale ────────────────────────────────────────────────────

def detect_agent_url() -> str:
    manual_ip = CONFIG.get("agent_tailscale_ip", "").strip()
    if manual_ip:
        return f"http://{manual_ip}:{CONFIG['command_port']}"
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect((CONFIG["central_host"], 80))
        ip = s.getsockname()[0]
        s.close()
        return f"http://{ip}:{CONFIG['command_port']}"
    except Exception:
        return f"http://127.0.0.1:{CONFIG['command_port']}"


# ── Helper décorateur pour les boucles ─────────────────────────────────────────

def _loop_error_handler(loop_name: str):
    """Décorateur pour standardiser la gestion d'erreurs dans les boucles asyncio."""
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"{loop_name} : {e}", exc_info=True)
                if storage:
                    try:
                        storage.push_event(CONFIG["site_id"], "error",
                                           f"{loop_name} : {str(e)[:200]}")
                    except Exception:
                        pass
        return wrapper
    return decorator


# ── Boucles de collecte (SSH-based) ───────────────────────────────────────────

# TODO: apply @_loop_error_handler
async def loop_metrics():
    interval = CONFIG["intervals"]["metrics"]
    while True:
        await asyncio.sleep(interval)
        try:
            ssh = ssh_pool.get_client()
            metrics = collect_metrics(ssh, CONFIG)
            if not metrics:
                continue

            shared_state["latest_metrics"] = metrics
            cpu       = metrics.cpu_load or 0
            threshold = CONFIG["thresholds"]["cpu_alert_percent"]
            cycles    = CONFIG["thresholds"]["cpu_alert_cycles"]

            if cpu > threshold:
                shared_state["cpu_alert_count"] += 1
                if shared_state["cpu_alert_count"] >= cycles:
                    alert = AlertData(
                        site_id    = CONFIG["site_id"],
                        site_name  = CONFIG["site_name"],
                        timestamp  = datetime.now(timezone.utc).isoformat(),
                        alert_type = "CPU_HIGH",
                        message    = (
                            f"⚠️ Alerte {CONFIG['site_name']}\n"
                            f"CPU : {cpu}% · Uptime : {metrics.uptime}\n"
                            f"Clients : {metrics.active_users}"
                        ),
                        data = {"cpu": cpu, "uptime": metrics.uptime,
                                "clients_count": metrics.active_users},
                    )
                    await asyncio.to_thread(forwarder.send_alert, alert.model_dump())
                    if storage:
                        storage.push_event(
                            CONFIG["site_id"], "alert",
                            f"CPU {cpu}% dépasse seuil {threshold}%",
                            data={"cpu": cpu, "threshold": threshold},
                        )
                    shared_state["cpu_alert_count"] = 0
            else:
                shared_state["cpu_alert_count"] = 0

            await asyncio.to_thread(forwarder.send_metrics, metrics.model_dump())

            # Cache local
            if storage:
                try:
                    storage.save_metrics(CONFIG["site_id"], "system", metrics.model_dump())
                except Exception as e:
                    logger.debug(f"Storage save_metrics error: {e}")
        except Exception as e:
            logger.error(f"loop_metrics : {e}")
            if storage:
                try:
                    storage.push_event(CONFIG["site_id"], "error",
                                       f"loop_metrics : {str(e)[:200]}")
                except Exception as _e:
                    logger.debug(f"Storage error: {_e}")


# TODO: apply @_loop_error_handler
async def loop_clients():
    interval = CONFIG["intervals"]["clients"]
    while True:
        await asyncio.sleep(interval)
        try:
            ssh = ssh_pool.get_client()
            clients = collect_clients(ssh, CONFIG)
            if clients:
                await asyncio.to_thread(forwarder.send_clients, clients.model_dump())
                if storage:
                    try:
                        storage.save_metrics(CONFIG["site_id"], "clients",
                                             clients.model_dump())
                    except Exception as _e:
                        logger.debug(f"Storage error: {_e}")
        except Exception as e:
            logger.error(f"loop_clients : {e}")
            if storage:
                try:
                    storage.push_event(CONFIG["site_id"], "error",
                                       f"loop_clients : {str(e)[:200]}")
                except Exception as _e:
                    logger.debug(f"Storage error: {_e}")


# TODO: apply @_loop_error_handler
async def loop_bandwidth():
    interval = CONFIG["intervals"]["bandwidth_check"]
    while True:
        await asyncio.sleep(interval)
        try:
            ssh = ssh_pool.get_client()
            alert = check_bandwidth_abuse(ssh, CONFIG)
            if alert:
                await asyncio.to_thread(forwarder.send_alert, alert.model_dump())
        except Exception as e:
            logger.error(f"loop_bandwidth : {e}")


# TODO: apply @_loop_error_handler
async def loop_offline():
    interval = CONFIG["intervals"]["offline_check"]
    while True:
        await asyncio.sleep(interval)
        try:
            alert = check_router_online(CONFIG, shared_state)
            if alert:
                await asyncio.to_thread(forwarder.send_alert, alert.model_dump())
        except Exception as e:
            logger.error(f"loop_bandwidth : {e}")
            if storage:
                storage.push_event(CONFIG["site_id"], "error",
                                   f"loop_bandwidth : {str(e)[:200]}")


# TODO: apply @_loop_error_handler
async def loop_offline():
    interval = CONFIG["intervals"]["offline_check"]
    while True:
        await asyncio.sleep(interval)
        try:
            alert = check_router_online(CONFIG, shared_state)
            if alert:
                await asyncio.to_thread(forwarder.send_alert, alert.model_dump())
        except Exception as e:
            logger.error(f"loop_offline : {e}")
            if storage:
                storage.push_event(CONFIG["site_id"], "error",
                                   f"loop_offline : {str(e)[:200]}")


# TODO: apply @_loop_error_handler
async def loop_diagnostics():
    interval = CONFIG["intervals"]["user_bloat_check"]
    while True:
        await asyncio.sleep(interval)
        try:
            ssh = ssh_pool.get_client()
            bloat = check_user_bloat(ssh, CONFIG)
            sched = check_scheduler_bloat(ssh, CONFIG)

            await asyncio.to_thread(forwarder.send_diagnostics, {
                "site_id":    CONFIG["site_id"],
                "timestamp":  datetime.now(timezone.utc).isoformat(),
                "user_bloat": bloat.model_dump() if bloat else {},
                "schedulers": sched.model_dump() if sched else {},
            })

            if bloat and bloat.alert:
                await asyncio.to_thread(forwarder.send_alert, AlertData(
                    site_id=CONFIG["site_id"], site_name=CONFIG["site_name"],
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    alert_type="USER_BLOAT",
                    message=f"⚠️ {CONFIG['site_name']} — {bloat.total_users} comptes",
                    data=bloat.model_dump(),
                ).model_dump())
            if sched and sched.alert:
                await asyncio.to_thread(forwarder.send_alert, AlertData(
                    site_id=CONFIG["site_id"], site_name=CONFIG["site_name"],
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    alert_type="SCHEDULER_BLOAT",
                    message=f"⚠️ {CONFIG['site_name']} — {sched.count} schedulers",
                    data=sched.model_dump(),
                ).model_dump())
        except Exception as e:
            logger.error(f"loop_diagnostics : {e}")
            if storage:
                storage.push_event(CONFIG["site_id"], "error",
                                   f"loop_diagnostics : {str(e)[:200]}")


# TODO: apply @_loop_error_handler
async def loop_queue_flush():
    """
    Vide périodiquement la durable queue.
    Tente d'envoyer chaque message au PC central via HTTP POST.
    """
    interval = CONFIG["intervals"].get("queue_flush", 60)
    while True:
        await asyncio.sleep(interval)
        try:
            if not durable_queue:
                continue

            def send_fn(msg_type: str, payload: dict) -> bool:
                url = f"http://{CONFIG['central_host']}:{CONFIG['central_port']}/api/v1/{msg_type.lower()}"
                headers = {
                    "X-API-Key": CONFIG.get("central_api_key", ""),
                    "Content-Type": "application/json",
                }
                try:
                    resp = http_requests.post(url, json=payload, headers=headers, timeout=15)
                    return 200 <= resp.status_code < 300
                except Exception as e:
                    logger.debug(f"Queue flush HTTP fail ({msg_type}): {e}")
                    return False

            report = durable_queue.flush(send_fn, max_messages=25)
            if report["sent"] > 0 or report["failed"] > 0:
                logger.info(
                    f"Queue flush: {report['sent']} envoyés, "
                    f"{report['failed']} échoués"
                )
        except Exception as e:
            logger.error(f"loop_queue_flush : {e}")


# TODO: apply @_loop_error_handler
async def loop_maintenance():
    """Nettoyage quotidien : queue forwarder + storage + durable queue."""
    while True:
        await asyncio.sleep(86400 + random.randint(-3600, 3600))  # 24h ± 1h jitter
        try:
            if forwarder:
                forwarder.cleanup()
        except Exception as e:
            logger.error(f"loop_maintenance (queue) : {e}")

        try:
            if storage:
                cleaned = storage.cleanup()
                if sum(cleaned.values()) > 0:
                    logger.info(f"Storage cleanup: {sum(cleaned.values())} lignes supprimées")
        except Exception as e:
            logger.error(f"loop_maintenance (storage) : {e}")

        try:
            if durable_queue:
                dq_cleaned = durable_queue.cleanup()
                if sum(dq_cleaned.values()) > 0:
                    logger.info(f"Durable queue cleanup: {sum(dq_cleaned.values())} supprimés")
        except Exception as e:
            logger.error(f"loop_maintenance (queue) : {e}")


# TODO: apply @_loop_error_handler
async def loop_backup():
    backup_hour = CONFIG["intervals"].get("backup_hour", 2)
    last_backup_date = None
    while True:
        now  = datetime.now()
        date = now.date()
        if now.hour == backup_hour and last_backup_date != date:
            try:
                logger.info(f"[BACKUP] Démarrage backup quotidien — {date}")
                result = execute_action(
                    ssh_pool=ssh_pool, config=CONFIG,
                    action_name="router.backup", params={},
                )
                await asyncio.to_thread(forwarder.send_backup_result, {
                    "site_id": CONFIG["site_id"],
                    "command": "backup_config",
                    "status": "ok" if result.get("status") == "success" else "error",
                    "result": result.get("output", result),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
                last_backup_date = date
            except Exception as e:
                logger.error(f"loop_backup : {e}")
            await asyncio.sleep(70)
        else:
            # Calculer le temps jusqu'à la prochaine heure cible
            next_run = now.replace(hour=backup_hour, minute=0, second=0, microsecond=0)
            if now.hour >= backup_hour:
                from datetime import timedelta
                next_run += timedelta(days=1)
            sleep_secs = (next_run - now).total_seconds()
            await asyncio.sleep(max(30, min(sleep_secs, 3600)))


# ── App 1 : Alertes RouterOS natifs (port 9000) ───────────────────────────────

alert_app = FastAPI(title="WIFIZONE Alert Receiver")

@alert_app.post("/alert")
async def receive_mikrotik_alert(raw: MikroTikRawAlert,
                                  background_tasks: BackgroundTasks,
                                  request: Request):
    # Vérification X-API-Key
    api_key = request.headers.get("X-API-Key", "")
    if not hmac.compare_digest(api_key, CONFIG["central_api_key"]):
        raise HTTPException(status_code=401, detail="Unauthorized")

    alert = AlertData(
        site_id    = CONFIG["site_id"],
        site_name  = CONFIG["site_name"],
        timestamp  = datetime.now(timezone.utc).isoformat(),
        alert_type = raw.type,
        message    = f"[RouterOS] {raw.type} : {raw.value}",
        data       = {"raw_type": raw.type, "raw_value": raw.value},
    )
    background_tasks.add_task(forwarder.send_alert, alert.model_dump())

    # Log dans storage
    if storage:
        try:
            storage.push_event(
                CONFIG["site_id"], "alert",
                f"[RouterOS] {raw.type} : {raw.value[:100]}",
                data={"raw_type": raw.type, "raw_value": raw.value},
            )
        except Exception as _e:
            logger.debug(f"Storage error: {_e}")

    return {"status": "received"}


# ── App 2 : Commandes PC central (port 9001) ──────────────────────────────────

@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    await _startup_logic()
    yield
    if forwarder:
        forwarder.queue.close()
    if storage:
        storage.close()
    if durable_queue:
        durable_queue.close()

command_app = FastAPI(title="WIFIZONE Command Center", lifespan=lifespan)

limiter = Limiter(key_func=get_remote_address)
command_app.state.limiter = limiter
command_app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# ── Endpoints Santé ────────────────────────────────────────────────────────────

@limiter.limit("100/minute")
@command_app.get("/health")
async def health(request: Request):
    _check_api_key(request)
    fwd_q = forwarder.stats() if forwarder else {}
    dq_stats = durable_queue.stats() if durable_queue else {}
    st_stats = storage.stats() if storage else {}
    m = shared_state.get("latest_metrics")
    return {
        "status":         "ok",
        "version":        shared_state.get("version", "2.0"),
        "site_id":        CONFIG["site_id"],
        "site_name":      CONFIG["site_name"],
        "agent_url":      shared_state.get("agent_url", ""),
        "timestamp":      datetime.now(timezone.utc).isoformat(),
        "mikrotik_host":  CONFIG["mikrotik_host"],
        "queue": {
            "forwarder": fwd_q,
            "durable": {
                "pending": dq_stats.get("pending", 0),
                "retrying": dq_stats.get("retrying", 0),
                "dead": dq_stats.get("dead", 0),
            },
        },
        "storage": {
            "commands": st_stats.get("commands", {}),
            "metrics": st_stats.get("metrics", {}),
            "events": st_stats.get("events", {}),
        },
        "latest_cpu":     m.cpu_load     if m else None,
        "latest_clients": m.active_users if m else None,
    }


@limiter.limit("100/minute")
@command_app.get("/metrics")
async def get_metrics(request: Request):
    _check_api_key(request)
    m = shared_state.get("latest_metrics")
    if not m:
        raise HTTPException(503, "Métriques pas encore disponibles")
    return m.model_dump()


@limiter.limit("100/minute")
@command_app.get("/queue")
async def get_queue(request: Request):
    """Stats de la queue forwarder."""
    _check_api_key(request)
    return forwarder.stats()


@limiter.limit("100/minute")
@command_app.get("/queue/durable")
async def get_durable_queue(
    request: Request,
    status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
):
    """Inspecte la durable queue (enhanced retry + TTL)."""
    _check_api_key(request)
    if not durable_queue:
        raise HTTPException(503, "Durable queue pas encore initialisée")
    return {
        "stats": durable_queue.stats(),
        "messages": durable_queue.get_messages(status=status, limit=limit),
    }


# ── Catalogue d'actions (nouveau) ──────────────────────────────────────────────

@limiter.limit("100/minute")
@command_app.get("/actions")
async def get_actions(request: Request):
    """
    Expose le catalogue simplifié des actions disponibles (protégé).
    """
    _check_api_key(request)
    return {
        "site_id": CONFIG["site_id"],
        "version": shared_state.get("version", "2.0"),
        "actions": list_actions(),
    }


@limiter.limit("100/minute")
@command_app.get("/capabilities")
async def get_capabilities_endpoint(request: Request):
    """
    Catalogue découverte complet — toutes les actions avec metadata.
    Accessible sans clé API pour permettre à n8n de découvrir
    les capacités de l'agent automatiquement.
    """
    return {
        "site_id": CONFIG["site_id"],
        "version": shared_state.get("version", "2.0"),
        "capabilities": get_capabilities(),
    }


# ── Endpoints Storage / Historique ────────────────────────────────────────────

@limiter.limit("100/minute")
@command_app.get("/commands")
async def get_commands(
    request: Request,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    status: str | None = Query(None),
    action: str | None = Query(None),
):
    """Historique des actions exécutées."""
    _check_api_key(request)
    if not storage:
        raise HTTPException(503, "Storage pas encore initialisé")
    return {
        "site_id": CONFIG["site_id"],
        "total": storage.count_commands(status=status),
        "commands": storage.get_commands(
            limit=limit, offset=offset, status=status, action=action,
        ),
    }


@limiter.limit("100/minute")
@command_app.get("/events")
async def get_events(
    request: Request,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    event_type: str | None = Query(None),
    since: str | None = Query(None),
):
    """Journal des événements (erreurs, alertes, info)."""
    _check_api_key(request)
    if not storage:
        raise HTTPException(503, "Storage pas encore initialisé")
    return {
        "site_id": CONFIG["site_id"],
        "total": storage.count_events(),
        "events": storage.get_events(
            limit=limit, offset=offset, event_type=event_type, since=since,
        ),
    }


@limiter.limit("100/minute")
@command_app.get("/storage")
async def get_storage_stats(request: Request):
    """Statistiques du stockage local."""
    _check_api_key(request)
    if not storage:
        raise HTTPException(503, "Storage pas encore initialisé")
    return {
        "site_id": CONFIG["site_id"],
        "stats": storage.stats(),
    }


# ── Point d'entrée unifié pour les actions (nouveau) ───────────────────────────

@limiter.limit("10/second")
@command_app.post("/action")
async def receive_action(cmd: ActionRequest, request: Request):
    """
    Nouveau endpoint unifié.
    Reçoit {action, payload, mode} et exécute via le pipeline générique.
    """
    # Vérification X-API-Key
    api_key = request.headers.get("X-API-Key", "")
    if not hmac.compare_digest(api_key, CONFIG["central_api_key"]):
        raise HTTPException(status_code=401, detail="Unauthorized")

    action = cmd.action
    payload = cmd.payload or {}
    if cmd.mode:
        payload["mode"] = cmd.mode

    logger.info(f"Action reçue : {action} (command_id={cmd.command_id})")

    # Exécution via le pipeline (déduplication + auto-save dans executor)
    result = execute_action(
        ssh_pool=ssh_pool,
        config=CONFIG,
        action_name=action,
        params=payload,
        command_id=cmd.command_id,
        storage=storage,
    )

    cmd_id = result.get("id", uuid.uuid4().hex[:12])
    cmd_status = result.get("status", "error")

    # Log via forwarder (n8n)
    await asyncio.to_thread(forwarder.send_command_result, {
        "site_id": CONFIG["site_id"],
        "command": action,
        "status": "ok" if cmd_status == "success" else "error",
        "result": result,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })

    # Push vers durable queue pour retry tracking amélioré
    if durable_queue and cmd_status != "success":
        durable_queue.push(
            "CMD_RESULT", {
                "cmd_id": cmd_id,
                "site_id": CONFIG["site_id"],
                "action": action,
                "result": result,
            },
            priority=1,
        )

    return result


# ── Point d'entrée rétro-compatible (ancien format) ────────────────────────────

@limiter.limit("10/second")
@command_app.post("/command")
async def receive_command(cmd: CommandRequest, request: Request):
    """
    Ancien endpoint rétro-compatible.
    Reçoit {command, params} — résout via les alias du registre.
    """
    api_key = request.headers.get("X-API-Key", "")
    if not hmac.compare_digest(api_key, CONFIG["central_api_key"]):
        raise HTTPException(status_code=401, detail="Unauthorized")

    logger.info(f"Commande legacy reçue : {cmd.command}")
    start_time = datetime.now(timezone.utc)

    # Résoudre l'ancien nom via les alias
    resolved = resolve_name(cmd.command)
    actual_action = resolved or cmd.command

    result = execute_action(
        ssh_pool=ssh_pool,
        config=CONFIG,
        action_name=actual_action,
        params=cmd.params,
    )

    elapsed_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)
    cmd_status = result.get("status", "error")

    # Formater comme l'ancien CommandResult
    legacy = {
        "site_id": CONFIG["site_id"],
        "command": cmd.command,
        "status": "ok" if result.get("status") == "success" else "error",
        "result": result.get("output", result),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    await asyncio.to_thread(forwarder.send_command_result, legacy)

    # Log dans storage local
    if storage:
        try:
            storage.save_command(
                command_id=f"legacy-{uuid.uuid4().hex[:12]}",
                site_id=CONFIG["site_id"],
                action=actual_action,
                status=cmd_status,
                payload=cmd.params,
                output=result,
                execution_time_ms=elapsed_ms,
                error_message=result.get("error") if cmd_status != "success" else None,
            )
        except Exception as e:
            logger.warning(f"Storage save_command (legacy) error: {e}")

    return legacy


# ── Téléchargement de fichiers ─────────────────────────────────────────────────

@limiter.limit("100/minute")
@command_app.get("/download/{filename:path}")
async def download_file(filename: str, request: Request):
    """Sert un fichier généré par l'agent (PDF, backup, etc.)."""
    _check_api_key(request)
    from core.executor import BACKUP_DIR, VOUCHER_DIR

    allowed_dirs = [VOUCHER_DIR, BACKUP_DIR]
    for d in allowed_dirs:
        filepath = Path(d) / filename
        filepath = filepath.resolve()
        if any(str(filepath).startswith(str(Path(ad).resolve())) for ad in allowed_dirs):
            if filepath.is_file():
                ext = filepath.suffix.lower()
                media_types = {
                    '.pdf': 'application/pdf',
                    '.backup': 'application/octet-stream',
                    '.zip': 'application/zip',
                    '.txt': 'text/plain',
                    '.rsc': 'text/plain',
                }
                media_type = media_types.get(ext, 'application/octet-stream')
                return FileResponse(str(filepath), media_type=media_type, filename=filename)

    raise HTTPException(status_code=404, detail="Fichier introuvable")


# ── Startup ───────────────────────────────────────────────────────────────────

def _print_banner():
    logger.info("=" * 55)
    logger.info(f"  WIFIZONE Agent v2 — {CONFIG['site_id']} ({CONFIG['site_name']})")
    logger.info("  Moteur : SSH + scripts déterministes (.rsc)")
    logger.info("=" * 55)


async def _init_storage_and_queue():
    global forwarder, storage, durable_queue
    forwarder = Forwarder(CONFIG)

    try:
        storage = Storage()
        logger.info("Storage initialisé (agent.db)")
    except Exception as e:
        logger.warning(f"⚠️ Storage non disponible : {e}")

    try:
        durable_queue = Queue()
        logger.info("Durable queue initialisée (queue.db → durable_queue)")
    except Exception as e:
        logger.warning(f"⚠️ Durable queue non disponible : {e}")


async def _init_ssh_and_test():
    global ssh_pool
    ssh_pool = SSHPool(CONFIG)

    # Test connexion SSH au démarrage
    try:
        ssh = ssh_pool.get_client()
        ident = ssh.execute("/system identity print", timeout=10)
        if ident.get("exit_code") == 0:
            logger.info(f"✅ SSH connecté — {ident.get('stdout', '').strip()[:50]}")
        else:
            logger.warning(f"⚠️ SSH réponse anormale : {ident.get('stderr')}")
    except Exception as e:
        logger.warning(f"⚠️ SSH non disponible au démarrage : {e}")
        logger.warning("   Les boucles de collecte tenteront de se reconnecter.")

    agent_url = detect_agent_url()
    shared_state["agent_url"] = agent_url
    logger.info(f"URL agent : {agent_url}")

    loop = asyncio.get_running_loop()
    loop.run_in_executor(None, forwarder.register_site, agent_url)


async def _first_collect():
    try:
        ssh = ssh_pool.get_client()
        metrics = collect_metrics(ssh, CONFIG)
        if metrics:
            shared_state["latest_metrics"] = metrics
            await asyncio.to_thread(forwarder.send_metrics, metrics.model_dump())
            if storage:
                storage.save_metrics(CONFIG["site_id"], "system", metrics.model_dump())
            logger.info(f"Collecte initiale OK — CPU={metrics.cpu_load}%")
    except Exception as e:
        logger.warning(f"Collecte initiale échouée : {e}")


def _start_loops():
    asyncio.create_task(loop_metrics())
    asyncio.create_task(loop_clients())
    asyncio.create_task(loop_queue_flush())
    asyncio.create_task(loop_maintenance())
    asyncio.create_task(loop_bandwidth())
    asyncio.create_task(loop_offline())
    asyncio.create_task(loop_diagnostics())
    # Désactivé : backup géré par n8n WF-BACKUP
    # asyncio.create_task(loop_backup())
    logger.info("✅ Toutes les boucles démarrées")


async def _startup_logic():
    global ssh_pool, forwarder, storage, durable_queue
    _print_banner()
    await _init_storage_and_queue()
    await _init_ssh_and_test()
    await _first_collect()
    _start_loops()


# ── Lancement des 2 serveurs ──────────────────────────────────────────────────

async def start_servers():
    Path("logs").mkdir(exist_ok=True)
    await asyncio.gather(
        uvicorn.Server(uvicorn.Config(
            alert_app,   host="0.0.0.0",
            port=CONFIG["alert_port"],   log_level="warning"
        )).serve(),
        uvicorn.Server(uvicorn.Config(
            command_app, host="0.0.0.0",
            port=CONFIG["command_port"], log_level="warning"
        )).serve(),
    )

if __name__ == "__main__":
    asyncio.run(start_servers())

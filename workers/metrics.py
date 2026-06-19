"""
workers/metrics.py — Collecte passive via SSH

Remplace collector.py avec le nouveau moteur SSH.
Interface identique pour backward compat.

Fonctions :
  collect_metrics(ssh, config)   → MetricsData | None
  collect_clients(ssh, config)   → ClientsData | None
  check_bandwidth_abuse(ssh, config) → AlertData | None
  check_router_online(config, state) → AlertData | None (ping)
  check_user_bloat(ssh, config)  → UserBloatData
  check_scheduler_bloat(ssh, config) → SchedulerData
"""
import re
import subprocess
import logging
from typing import Optional

from core.ssh import SSHClient, parse_routeros_output
from core.utils import now_iso, parse_bytes as _parse_bytes
from models import (
    MetricsData, ClientsData, HotspotClient,
    AlertData, UserBloatData, SchedulerData,
)

logger = logging.getLogger("metrics")


# ── Parse helpers ──────────────────────────────────────────────────────────────


def _parse_uptime_seconds(uptime: str) -> int:
    """Parse un uptime RouterOS (ex: '2d14h32m10s') en secondes."""
    total = 0
    m = re.match(r"(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?", uptime)
    if m:
        d, h, mi, s = (int(x) if x else 0 for x in m.groups())
        total = d * 86400 + h * 3600 + mi * 60 + s
    return total


# ── F01: Métriques système ─────────────────────────────────────────────────────


def collect_metrics(ssh: SSHClient, config: dict) -> Optional[MetricsData]:
    """
    Collecte les métriques via SSH direct (pas de upload/import).
    Plus rapide et moins intrusif pour les lectures fréquentes.
    """
    try:
        # Commande RouterOS directe
        result = ssh.execute("/system resource print", timeout=15)
        if result.get("exit_code", -1) != 0:
            logger.warning(f"Échec /system resource print : {result.get('stderr')}")
            return None

        parsed_list = parse_routeros_output(result.get("stdout", ""))
        system_data = parsed_list[0] if parsed_list else {}

        # Température (optionnel)
        temperature = None
        try:
            temp_result = ssh.execute("/system health print", timeout=10)
            if temp_result.get("exit_code") == 0:
                health_list = parse_routeros_output(temp_result.get("stdout", ""))
                health = health_list[0] if health_list else {}
                if health.get("temperature"):
                    temperature = float(health["temperature"])
        except Exception:
            pass

        # Comptage des clients actifs
        hotspot_count = 0
        ppp_count = 0
        try:
            hs = ssh.execute("/ip hotspot active print count-only", timeout=10)
            hotspot_count = int(hs.get("stdout", "0").strip() or "0")
        except Exception:
            pass
        try:
            ppp = ssh.execute("/ppp active print count-only", timeout=10)
            ppp_count = int(ppp.get("stdout", "0").strip() or "0")
        except Exception:
            pass

        cpu = float(str(system_data.get("cpu_load", "0")).replace("%", ""))
        free_mem = _parse_bytes(system_data.get("free_memory", "0"))
        total_mem = _parse_bytes(system_data.get("total_memory", "0"))

        return MetricsData(
            site_id=config["site_id"],
            site_name=config["site_name"],
            timestamp=now_iso(),
            cpu_load=cpu,
            memory_free=free_mem,
            memory_total=total_mem,
            uptime=system_data.get("uptime"),
            ros_version=system_data.get("version"),
            board_name=system_data.get("board_name"),
            active_users=hotspot_count + ppp_count,
            temperature=temperature,
        )

    except Exception as e:
        logger.error(f"[F01] collect_metrics: {e}")
        return None


# ── F02: Clients actifs ────────────────────────────────────────────────────────


def collect_clients(ssh: SSHClient, config: dict) -> Optional[ClientsData]:
    """
    Liste les clients hotspot actifs via SSH direct.
    """
    try:
        result = ssh.execute(
            "/ip hotspot active print detail", timeout=15
        )
        if result.get("exit_code", -1) != 0:
            logger.warning(f"Échec /ip hotspot active print : {result.get('stderr')}")
            return None

        stdout = result.get("stdout", "")
        clients = []
        current: dict = {}

        for line in stdout.splitlines():
            line = line.strip()
            if not line:
                if current.get("user"):
                    clients.append(HotspotClient(
                        user=current["user"],
                        ip=current.get("address"),
                        mac=current.get("mac-address"),
                        uptime=current.get("uptime"),
                        bytes_in=int(current.get("bytes-in", 0)),
                        bytes_out=int(current.get("bytes-out", 0)),
                        profile=current.get("profile"),
                        client_type="hotspot",
                    ))
                current = {}
                continue
            if ":" in line:
                key, _, val = line.partition(":")
                current[key.strip()] = val.strip()

        # Dernier élément
        if current.get("user"):
            clients.append(HotspotClient(
                user=current["user"],
                ip=current.get("address"),
                mac=current.get("mac-address"),
                uptime=current.get("uptime"),
                bytes_in=int(current.get("bytes-in", 0)),
                bytes_out=int(current.get("bytes-out", 0)),
                profile=current.get("profile"),
                client_type="hotspot",
            ))

        return ClientsData(
            site_id=config["site_id"],
            site_name=config["site_name"],
            timestamp=now_iso(),
            count=len(clients),
            clients=clients,
        )

    except Exception as e:
        logger.error(f"[F02] collect_clients: {e}")
        return None


# ── F04: Bande passante suspecte ────────────────────────────────────────────────


def check_bandwidth_abuse(ssh: SSHClient, config: dict) -> Optional[AlertData]:
    """
    Détecte les clients avec une consommation anormale.
    Seuil configurable via THRESHOLD_BANDWIDTH_MB.
    """
    threshold = config["thresholds"]["bandwidth_suspect_mb"]
    try:
        result = ssh.execute(
            "/ip hotspot active print detail", timeout=15
        )
        if result.get("exit_code", -1) != 0:
            return None

        stdout = result.get("stdout", "")
        suspects = []
        current: dict = {}

        for line in stdout.splitlines():
            line = line.strip()
            if not line:
                if current.get("user"):
                    total_bytes = int(current.get("bytes-in", 0)) + \
                                  int(current.get("bytes-out", 0))
                    total_mb = total_bytes / (1024 * 1024)
                    if total_mb > threshold:
                        suspects.append({
                            "user": current["user"],
                            "ip": current.get("address", "?"),
                            "total_mb": round(total_mb, 1),
                        })
                current = {}
                continue
            if ":" in line:
                key, _, val = line.partition(":")
                current[key.strip()] = val.strip()

        if not suspects:
            return None

        return AlertData(
            site_id=config["site_id"],
            site_name=config["site_name"],
            timestamp=now_iso(),
            alert_type="SUSPECT_BW",
            message=f"⚠️ {len(suspects)} suspect(s) — {config['site_name']}",
            data={"suspects": suspects, "threshold_mb": threshold},
        )

    except Exception as e:
        logger.error(f"[F04] check_bandwidth_abuse: {e}")
        return None


# ── F09: Routeur offline ───────────────────────────────────────────────────────


def check_router_online(config: dict, state: dict) -> Optional[AlertData]:
    """
    Vérifie la connectivité du routeur via ping.
    Même logique que l'ancien collector.py — ne change pas.
    """
    host = config["mikrotik_host"]
    retries = config["thresholds"]["offline_retries"]

    try:
        result = subprocess.run(
            ["ping", "-c", "1", "-W", "2", host],
            capture_output=True, timeout=5,
        )
        if result.returncode == 0:
            state["offline_count"] = 0
            state["last_seen"] = now_iso()
            return None

        state["offline_count"] = state.get("offline_count", 0) + 1
        if state["offline_count"] >= retries:
            state["offline_count"] = 0
            return AlertData(
                site_id=config["site_id"],
                site_name=config["site_name"],
                timestamp=now_iso(),
                alert_type="ROUTER_OFFLINE",
                message=f"🚨 {config['site_name']} OFFLINE",
                data={
                    "last_seen": state.get("last_seen"),
                    "host": host,
                },
            )
        return None

    except Exception as e:
        logger.error(f"[F09] check_router_online: {e}")
        return None


# ── F10: User bloat ────────────────────────────────────────────────────────────


def check_user_bloat(ssh: SSHClient, config: dict) -> Optional[UserBloatData]:
    """
    Analyse la base d'utilisateurs hotspot :
    - Nombre total
    - Comptes désactivés
    - Jamais utilisés (0 bytes, pas connectés)
    """
    try:
        result = ssh.execute(
            "/ip hotspot user print detail", timeout=15
        )
        if result.get("exit_code", -1) != 0:
            return None

        stdout = result.get("stdout", "")
        users = []
        current: dict = {}

        for line in stdout.splitlines():
            line = line.strip()
            if not line:
                if current.get("name"):
                    users.append(current)
                current = {}
                continue
            if ":" in line:
                key, _, val = line.partition(":")
                current[key.strip()] = val.strip()

        if current.get("name"):
            users.append(current)

        # Récupérer les utilisateurs actuellement connectés
        active_result = ssh.execute("/ip hotspot active print detail", timeout=10)
        active_users = set()
        for line in active_result.get("stdout", "").splitlines():
            if "user:" in line:
                active_users.add(line.split(":", 1)[1].strip())

        disabled = [u for u in users if u.get("disabled") == "yes" or u.get("disabled") == "true"]
        never = []
        for u in users:
            is_active = u.get("name") in active_users
            bytes_in = int(u.get("bytes-in", 0))
            if bytes_in == 0 and not is_active:
                never.append(u)

        return UserBloatData(
            site_id=config["site_id"],
            site_name=config["site_name"],
            timestamp=now_iso(),
            total_users=len(users),
            disabled=len(disabled),
            never_used=len(never),
            alert=len(users) > config["thresholds"]["max_users_warning"],
        )

    except Exception as e:
        logger.error(f"[F10] check_user_bloat: {e}")
        return None


# ── F11: Scheduler bloat ─────────────────────────────────────────────────────


def check_scheduler_bloat(ssh: SSHClient, config: dict) -> Optional[SchedulerData]:
    """
    Liste les scripts planifiés et alerte si trop nombreux.
    """
    try:
        result = ssh.execute(
            "/system scheduler print detail", timeout=15
        )
        if result.get("exit_code", -1) != 0:
            return None

        stdout = result.get("stdout", "")
        schedulers = []
        current: dict = {}

        for line in stdout.splitlines():
            line = line.strip()
            if not line:
                if current.get("name"):
                    schedulers.append({
                        "name": current["name"],
                        "interval": current.get("interval", ""),
                        "runs": current.get("run-count", "0"),
                        "disabled": current.get("disabled", "no"),
                    })
                current = {}
                continue
            if ":" in line:
                key, _, val = line.partition(":")
                current[key.strip()] = val.strip()

        if current.get("name"):
            schedulers.append({
                "name": current["name"],
                "interval": current.get("interval", ""),
                "runs": current.get("run-count", "0"),
                "disabled": current.get("disabled", "no"),
            })

        return SchedulerData(
            site_id=config["site_id"],
            site_name=config["site_name"],
            timestamp=now_iso(),
            count=len(schedulers),
            alert=len(schedulers) > config["thresholds"]["max_schedulers_warning"],
            schedulers=schedulers,
        )

    except Exception as e:
        logger.error(f"[F11] check_scheduler_bloat: {e}")
        return None

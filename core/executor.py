"""
core/executor.py — Pipeline d'exécution générique

Point d'entrée unique pour toutes les actions :

  1. Reçoit (action_name, params)
  2. Résout via registry (supports alias)
  3. Valide les paramètres
  4. Exécute :
       - Type "routeros" → SSH upload + /import du script .rsc
       - Type "python"   → handler Python
  5. Parse la sortie
  6. Retourne réponse standardisée

Backward compatibility :
  Les anciens noms (create_user, reboot_router) sont résolus
  via les alias dans commands.json vers les nouveaux noms canoniques.
"""
import os
import re
import random
import string
import logging
import time
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import requests
from requests.auth import HTTPBasicAuth

from core.ssh import SSHPool, SSHClient
from core.registry import lookup, resolve_name, get_script_path
from core.validator import validate_action, validate_params, ValidationError
from core.utils import now_iso, parse_bytes
from core.storage import Storage

logger = logging.getLogger("executor")

# Répertoires de sortie
BASE_DIR = Path(__file__).parent.parent
BACKUP_DIR = BASE_DIR / "backups"
VOUCHER_DIR = BASE_DIR / "vouchers"
os.makedirs(BACKUP_DIR, exist_ok=True)
os.makedirs(VOUCHER_DIR, exist_ok=True)


# ── Helpers ────────────────────────────────────────────────────────────────────


def generate_id() -> str:
    """ID unique pour chaque commande exécutée."""
    ts = datetime.now().strftime("%y%m%d%H%M%S")
    rand = random.choices(string.ascii_lowercase + string.digits, k=6)
    return f"cmd_{ts}_{''.join(rand)}"


def _parse_data_limit(v: Any) -> int:
    """Parse une limite de données (ex: '2GB', '500M') en bytes."""
    if not v:
        return 0
    v = str(v).strip().upper()
    try:
        if v.endswith("GB"):
            return int(float(v[:-2]) * 1024**3)
        if v.endswith("G"):
            return int(float(v[:-1]) * 1024**3)
        if v.endswith("MB"):
            return int(float(v[:-2]) * 1024**2)
        if v.endswith("M"):
            return int(float(v[:-1]) * 1024**2)
        if v.endswith("KB"):
            return int(float(v[:-2]) * 1024)
        if v.endswith("K"):
            return int(float(v[:-1]) * 1024)
        return int(v)
    except (ValueError, TypeError):
        return 0


def _parse_time_limit(v: Any) -> int:
    """Parse une limite de temps (ex: '1h', '30m', '1h30m', '24h') en secondes."""
    if not v:
        return 0
    v = str(v).strip().lower()
    total = 0
    # Pattern: (Xd)?(Xh)?(Xm)?(Xs)?  ex: "1d6h" → 108000, "1h30m" → 5400
    match = re.match(r"^(?:(\d+)\s*d)?\s*(?:(\d+)\s*h)?\s*(?:(\d+)\s*m)?\s*(?:(\d+)\s*s)?$", v)
    if match:
        days = int(match.group(1)) if match.group(1) else 0
        hours = int(match.group(2)) if match.group(2) else 0
        minutes = int(match.group(3)) if match.group(3) else 0
        seconds = int(match.group(4)) if match.group(4) else 0
        total = days * 86400 + hours * 3600 + minutes * 60 + seconds
    else:
        # Fallback: tenter de parser comme nombre brut (secondes)
        try:
            total = int(v)
        except (ValueError, TypeError):
            logger.warning(f"Impossible de parser time_limit: '{v}'")
            return 0
    return total


def _sanitize_ros_param(value: str | int, max_len: int = 50) -> str:
    """Échappe un paramètre pour une commande RouterOS (interpolation sécurisée)."""
    s = str(value).strip()
    # RouterOS utilise " pour les strings — on échappe les " internes
    s = s.replace('"', '\\"')
    # On limite la longueur pour éviter les attaques par buffer overflow
    return s[:max_len]


def _make_code(length: int = 8, charset: str = "ABCD") -> str:
    """Génère un code aléatoire pour voucher."""
    pools = {
        "abcd": string.ascii_lowercase,
        "ABCD": string.ascii_uppercase,
        "aBcD": string.ascii_letters,
        "1234": string.digits,
        "aB12": string.ascii_letters + string.digits,
    }
    chars = pools.get(charset, string.ascii_uppercase)
    return "".join(random.choices(chars, k=length))


def _parse_rsc_output(stdout: str) -> dict[str, Any]:
    """
    Parse la sortie d'un script .rsc.

    Nouveau format (recommandé) :
        === STATUS ===
        status=ok

        === DATA ===
        username=test
        profile=default

        === END ===

    Ancien format (rétrocompatible) :
        === CUSTOM_SECTION ===
        cle=valeur
        → result["custom_section_cle"] = "valeur"

    Aucune section :
        → détection par mots-clés (fallback)

    STATUS/DATA/END → pas de préfixe (cle→root).
    Autres sections → préfixé (section_cle→root).
    """
    result: dict[str, Any] = {}
    current_section = None
    lines = stdout.strip().splitlines()
    seen_end = False

    for line in lines:
        line = line.strip()
        if not line or seen_end:
            continue

        # Marqueur de section
        if line.startswith("===") and line.endswith("==="):
            section_name = line.strip("= ").lower().replace(" ", "_")
            current_section = section_name
            if section_name == "end":
                seen_end = True
            continue

        # Ligne clé=valeur
        if "=" not in line:
            continue

        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip()

        # STATUS, DATA, pas de section → root (pas de préfixe)
        if current_section in ("status", "data", "end", None):
            result[key] = val
        else:
            # Autres sections → préfixé pour rétrocompatibilité
            result[f"{current_section}_{key}"] = val

    # Statut implicite (fallback détection par mots-clés)
    if "status" not in result:
        from_exec = [kw for kw in stdout.split() if kw.isupper() and "_" in kw]
        success_kw = {"USER_CREATED", "USER_DELETED", "USER_DISABLED",
                       "USER_ENABLED", "USER_KICKED", "MAC_BLOCKED",
                       "MAC_UNBLOCKED", "PROFILE_CREATED", "REBOOT_INITIATED"}
        error_kw = {"ERROR", "NOT_FOUND", "ALREADY_EXISTS"}

        matched = [kw for kw in from_exec if kw in success_kw or kw in error_kw]
        if matched:
            result["status"] = matched[0].lower()
        elif any(kw in stdout for kw in ["not found", "already exists"]):
            result["status"] = "error"
        else:
            result["status"] = "completed"

    return result


# ── Réponse standardisée ──────────────────────────────────────────────────────


def make_response(
    command_id: str,
    action: str,
    site_id: str,
    status: str,
    output: Any = None,
    error: Optional[dict] = None,
    execution_time_ms: Optional[int] = None,
) -> dict[str, Any]:
    """Construit une réponse standardisée."""
    response: dict[str, Any] = {
        "id": command_id,
        "action": action,
        "site_id": site_id,
        "status": status,
        "timestamp": now_iso(),
    }
    if output is not None:
        response["output"] = output
    if execution_time_ms is not None:
        response["execution_time_ms"] = execution_time_ms
    if error:
        response["error"] = error
    return response


# ── Point d'entrée principal ──────────────────────────────────────────────────


def execute_action(
    ssh_pool: SSHPool,
    config: dict,
    action_name: str,
    params: dict[str, Any],
    command_id: Optional[str] = None,
    storage: Optional[Storage] = None,
) -> dict[str, Any]:
    """
    Pipeline principal d'exécution :

    1. Résout l'action (nom canonique + alias)
    2. Valide l'action existe
    3. Valide les paramètres
    4. Exécute (SSH script ou Python handler)
    5. Retourne réponse standardisée

    Paramètres :
        ssh_pool : Pool de connexions SSH
        config   : Configuration agent (.env)
        action_name : Nom de l'action (ex: "hotspot.create_user")
        params   : Dict des paramètres
        command_id : ID optionnel (généré automatiquement si vide)
        storage  : Storage optionnel pour déduplication + audit

    Retourne :
        Dict standardisé {id, action, site_id, status, output/error, execution_time_ms}
    """
    cmd_id = command_id or generate_id()
    site_id = config.get("site_id", "unknown")
    start_time = time.time()

    # Déduplication : si command_id fourni et déjà traité → retour sans exécuter
    if storage and command_id:
        existing = storage.get_command(command_id)
        if existing:
            logger.info(f"[{cmd_id}] Déduplication — résultat existant retourné")
            db_status = existing.get("status", "unknown")
            resp_status = "success" if db_status == "success" else "failed"
            db_output = existing.get("output")
            # L'output est stocké en JSON string — le décoder si possible
            if isinstance(db_output, str):
                try:
                    db_output = json.loads(db_output)
                except (json.JSONDecodeError, TypeError):
                    pass
            return make_response(
                command_id=cmd_id,
                action=existing.get("action", action_name),
                site_id=existing.get("site_id", site_id),
                status=resp_status,
                output=db_output,
                execution_time_ms=0,  # 0 = pas d'exécution (cache hit)
            )

    try:
        # 1. Extraire le mode (preview) des paramètres AVANT validation
        #    car "mode" n'est pas un paramètre défini dans l'action
        mode = params.get("mode", "execute")
        # Crée une copie du dict params sans le mode (ne pas muter l'original)
        working_params = {k: v for k, v in params.items() if k != "mode"}

        # 2. Valider l'action
        action_def = validate_action(action_name)
        canonical = resolve_name(action_name) or action_name

        # 3. Valider les paramètres (sans "mode")
        validated_params = validate_params(working_params, action_def)
        logger.info(
            f"[{cmd_id}] {canonical} "
            f"params={{{', '.join(validated_params.keys())}}}"
        )

        # 4. Mode preview (dry-run) — ne nécessite pas SSH
        if mode == "preview":
            return _preview_action(action_def, validated_params, cmd_id, canonical, site_id)

        # 5. Exécuter selon le type
        action_type = action_def.get("type", "routeros")

        # Vérifier que le pool SSH est disponible
        if ssh_pool is None:
            raise RuntimeError("SSHPool non initialisé — impossible d'exécuter des actions")

        ssh = ssh_pool.get_client()

        if action_type == "routeros":
            output = _execute_routeros_script(ssh, action_def, validated_params)
        elif action_type == "python":
            output = _execute_python_handler(ssh, config, action_def["handler"], validated_params)
        else:
            raise ValueError(f"Type d'action inconnu : {action_type}")

        elapsed_ms = int((time.time() - start_time) * 1000)

        resp = make_response(
            command_id=cmd_id,
            action=canonical,
            site_id=site_id,
            status="success",
            output=output,
            execution_time_ms=elapsed_ms,
        )
        _save_execution(storage, cmd_id, site_id, canonical, resp, validated_params)

        # ── Post-hook : création de profil → auto-setup on-login + cleanup ──
        if canonical == "profile.create" and output and isinstance(output, dict):
            profile_name = validated_params.get("profileName", "")
            if profile_name and output.get("status") != "error":
                try:
                    _handler_setup_profile(ssh, config, {"profile": profile_name})
                    logger.info(f"[auto_hook] ✅ On-login + cleanup auto-injectés sur '{profile_name}'")
                except Exception as hook_err:
                    logger.warning(f"[auto_hook] ⚠️ Setup auto échoué pour '{profile_name}': {hook_err}")

        return resp

    except ValidationError as e:
        elapsed_ms = int((time.time() - start_time) * 1000)
        logger.warning(f"[{cmd_id}] Validation error: {e}")
        resp = make_response(
            command_id=cmd_id,
            action=action_name,
            site_id=site_id,
            status="failed",
            error={"type": "VALIDATION_ERROR", "message": str(e), "field": e.field},
            execution_time_ms=elapsed_ms,
        )
        _save_execution(storage, cmd_id, site_id, action_name, resp, working_params)
        return resp

    except ConnectionError as e:
        elapsed_ms = int((time.time() - start_time) * 1000)
        logger.error(f"[{cmd_id}] SSH error: {e}")
        resp = make_response(
            command_id=cmd_id,
            action=action_name,
            site_id=site_id,
            status="failed",
            error={"type": "SSH_ERROR", "message": str(e)},
            execution_time_ms=elapsed_ms,
        )
        _save_execution(storage, cmd_id, site_id, action_name, resp, working_params)
        return resp

    except Exception as e:
        elapsed_ms = int((time.time() - start_time) * 1000)
        logger.error(f"[{cmd_id}] Execution error: {e}", exc_info=True)
        resp = make_response(
            command_id=cmd_id,
            action=action_name,
            site_id=site_id,
            status="failed",
            error={"type": "EXECUTION_ERROR", "message": str(e)},
            execution_time_ms=elapsed_ms,
        )
        _save_execution(storage, cmd_id, site_id, action_name, resp, working_params)
        return resp


# ── Auto-save helper ────────────────────────────────────────────────────────────


def _save_execution(
    storage: Optional[Storage],
    cmd_id: str,
    site_id: str,
    action: str,
    response: dict[str, Any],
    params: dict[str, Any],
) -> None:
    """Sauvegarde le résultat d'exécution dans le storage si disponible."""
    if not storage:
        return
    try:
        resp_status = response.get("status", "unknown")
        error_data = response.get("error") if resp_status != "success" else None
        storage.save_command(
            command_id=cmd_id,
            site_id=site_id,
            action=action,
            status=resp_status,
            payload=params,
            output=response.get("output"),
            execution_time_ms=response.get("execution_time_ms"),
            error_type=error_data.get("type") if isinstance(error_data, dict) else None,
            error_message=error_data.get("message") if isinstance(error_data, dict) else None,
        )
    except Exception as e:
        logger.warning(f"[{cmd_id}] Storage save error: {e}")


# ── Mode Preview ───────────────────────────────────────────────────────────────


def _preview_action(
    action_def: dict,
    params: dict,
    cmd_id: str,
    canonical: str,
    site_id: str,
) -> dict[str, Any]:
    """Génère un aperçu de la commande sans l'exécuter."""
    script_rel = action_def.get("script", "")
    script_path = get_script_path(action_def)

    content = ""
    if script_path and script_path.is_file():
        raw = script_path.read_text(encoding="utf-8")
        header = "\n".join(
            f':local {k} "{str(v).replace(chr(34), chr(92)+chr(34))}"'
            for k, v in params.items()
        )
        content = header + "\n\n" + raw

    return make_response(
        command_id=cmd_id,
        action=canonical,
        site_id=site_id,
        status="preview",
        output={
            "script": script_rel,
            "params": params,
            "generated": content,
            "note": "Aperçu uniquement — exécutez sans mode=preview pour appliquer",
        },
        execution_time_ms=0,
    )


# ── Exécution RouterOS (SSH + /import) ─────────────────────────────────────────


def _execute_routeros_script(
    ssh: SSHClient,
    action_def: dict,
    params: dict,
) -> dict[str, Any]:
    """
    Exécute une action de type 'routeros' :
    1. Charge le fichier .rsc
    2. Injecte les paramètres
    3. Upload + /import
    4. Parse la sortie
    """
    script_path = get_script_path(action_def)
    if not script_path or not script_path.is_file():
        raise FileNotFoundError(
            f"Script introuvable : {script_path}"
        )

    timeout = action_def.get("timeout", 30)

    # Exécuter via ssh (injection + upload + import)
    ssh_result = ssh.execute_script_from_file(
        local_path=script_path,
        params=params,
        timeout=timeout,
        cleanup=True,
    )

    if ssh_result.get("exit_code", -1) == -1:
        raise ConnectionError(
            f"Échec SSH : {ssh_result.get('stderr', 'unknown error')}"
        )

    # Parser la sortie
    stdout = ssh_result.get("stdout", "")
    stderr = ssh_result.get("stderr", "")

    parsed = _parse_rsc_output(stdout)

    # Si le script a renvoyé une erreur
    if parsed.get("status") in ("error", "not_found", "already_exists") or \
       any(kw in stdout.upper() for kw in ["ERROR", "NOT_FOUND", "ALREADY"]):
        if "error" not in parsed:
            # Extraire le message d'erreur
            error_lines = [l for l in stdout.splitlines()
                          if "error" in l.lower() or "not" in l.lower()]
            parsed["error"] = error_lines[0] if error_lines else stderr[:200]

    return parsed


# ── Exécution Python (logique métier) ──────────────────────────────────────────


def _execute_python_handler(
    ssh: SSHClient,
    config: dict,
    handler_name: str,
    params: dict,
) -> Any:
    """
    Exécute un handler Python (logique métier complexe).
    Le handler reçoit (ssh, config, params) et retourne un dict.
    """
    handlers = {
        "generate_vouchers": _handler_generate_vouchers,
        "update_profile": _handler_update_profile,
        "backup_router": _handler_backup_router,
        "export_pdf": _handler_export_pdf,
        "setup_profile": _handler_setup_profile,
    }

    handler = handlers.get(handler_name)
    if handler is None:
        raise ValueError(f"Handler Python inconnu : {handler_name}")

    # TODO: wrap in asyncio.wait_for — l'appel handler est bloquant sans timeout
    return handler(ssh, config, params)


# ── Handlers Python ────────────────────────────────────────────────────────────


def _handler_generate_vouchers(
    ssh: SSHClient,
    config: dict,
    params: dict,
) -> dict[str, Any]:
    """
    Génère des codes vouchers hotspot.
    Utilise SSH (méthode designée) pour la création des users.
    """
    qty = min(int(params.get("qty", 1)), 99)
    profile = params.get("profile", "default")
    mode = params.get("user_mode", "voucher")
    length = int(params.get("name_length", 8))
    charset = params.get("charset", "ABCD")
    lot_id = datetime.now(timezone.utc).strftime('%d%m%Y')
    # Attention: commands.json définit "default": "" pour comment
    # donc params.get("comment") retourne "" même si non fourni par l'appelant
    # On utilise "or" pour capturer la chaîne vide
    comment = params.get("comment") or f"vc:{profile}:{lot_id}"

    # Récupérer la liste des users existants via SSH
    result = ssh.execute("/ip hotspot/user print detail", timeout=15)
    existing = set()
    for line in result.get("stdout", "").splitlines():
        if "name=" in line:
            for part in line.split():
                if part.startswith("name="):
                    existing.add(part.split("=", 1)[1].strip('"'))
                    break

    # Parser les limites pour RouterOS (accepte "1h", "30m", "500MB", "2GB", etc.)
    raw_data_limit = params.get("data_limit", "")
    raw_time_limit = params.get("time_limit", "")
    if raw_data_limit:
        data_limit_bytes = str(_parse_data_limit(raw_data_limit))
    else:
        data_limit_bytes = ""
    if raw_time_limit:
        time_limit_seconds = str(_parse_time_limit(raw_time_limit))
    else:
        time_limit_seconds = ""

    created = []
    for _ in range(qty):
        for _ in range(20):
            code = _make_code(length, charset)
            if code not in existing:
                break
        pwd = code if mode == "voucher" else _make_code(6, "aB12")

        # Créer l'utilisateur via SSH (méthode designée)
        ssh.execute_script_from_file(
            local_path=BASE_DIR / "scripts" / "routeros" / "hotspot" / "add_user.rsc",
            params={
                "username": code,
                "password": pwd,
                "profile": profile,
                "comment": comment,
                "data_limit": data_limit_bytes,
                "time_limit": time_limit_seconds,
            },
            timeout=30,
        )
        existing.add(code)
        created.append({
            "name": code,
            "password": pwd,
            "profile": profile,
            "user_mode": mode,
            "time_limit": raw_time_limit,
            "data_limit": raw_data_limit,
            "price": params.get("price", ""),
            "login_url": params.get("login_url", ""),
            "comment": comment,
            "generated_at": datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M"),
        })

    return {
        "status": "ok",
        "created": len(created),
        "profile": profile,
        "vouchers": created,
    }


def _handler_update_profile(
    ssh: SSHClient,
    config: dict,
    params: dict,
) -> dict[str, Any]:
    """
    Met à jour un profil hotspot existant.
    Logique identique à l'ancien executor._update_profile.
    """
    name = _sanitize_ros_param(params["name"])

    # Vérifier l'existence du profil
    check = ssh.execute(
        f'/ip hotspot user/profile print where name="{name}"', timeout=10
    )
    if not check.get("stdout", "").strip():
        return {"status": "not_found", "profile": name}

    # Construire la commande set
    set_parts = [f'name="{name}"']
    if "rate_limit" in params:
        rl = _sanitize_ros_param(params["rate_limit"])
        set_parts.append(f'rate-limit="{rl}"')
    if "session_timeout" in params and params["session_timeout"]:
        st = _sanitize_ros_param(params["session_timeout"])
        set_parts.append(f'session-timeout="{st}"')
    if "idle_timeout" in params and params["idle_timeout"]:
        it = _sanitize_ros_param(params["idle_timeout"])
        set_parts.append(f'idle-timeout="{it}"')
    if "shared_users" in params:
        su = _sanitize_ros_param(params["shared_users"])
        set_parts.append(f"shared-users={su}")
    if "data_limit" in params and params["data_limit"]:
        lb = _parse_data_limit(params["data_limit"])
        set_parts.append(f"limit-bytes-total={lb}")

    cmd = "/ip hotspot user/profile set " + " ".join(set_parts)
    ssh.execute(cmd, timeout=10)

    return {"status": "updated", "profile": name}


def _handler_backup_router(
    ssh: SSHClient,
    config: dict,
    params: dict,
) -> dict[str, Any]:
    """
    Backup config MikroTik :
    1. Exécute /system backup save
    2. SFTP download
    3. Retourne infos
    """
    site_id = config.get("site_id", "unknown").lower()
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    backup_name = f"{site_id}-{date_str}"
    remote_file = f"{backup_name}.backup"
    local_path = BACKUP_DIR / remote_file

    try:
        # 1. Créer le backup côté MikroTik
        result = ssh.execute(
            f'/system backup save name="{backup_name}"',
            timeout=60,
        )
        if result.get("exit_code", 0) != 0:
            raise RuntimeError(
                f"Backup failed: {result.get('stderr', result.get('stdout'))[:200]}"
            )

        # Attendre que le fichier soit écrit
        time.sleep(5)

        # 2. Télécharger via SFTP
        ssh.download_file(remote_file, local_path)

        return {
            "status": "ok",
            "filename": remote_file,
            "size_kb": local_path.stat().st_size // 1024,
        }

    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "filename": remote_file,
        }


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  SETUP PROFILE : On-login + Scheduler cleanup via REST API                  ║
# ╚══════════════════════════════════════════════════════════════════════════════╝


REST_PORT_DEFAULT = 8080


def _rest_api_call(
    config: dict, method: str, path: str, data: dict | None = None,
    timeout: int = 10,
) -> dict | list | None:
    """
    Appelle l'API REST MikroTik.
    Gère les réponses vides (DELETE retourne 204 No Content).
    """
    host = config.get("mikrotik_host", "127.0.0.1")
    port = config.get("mikrotik_rest_port", REST_PORT_DEFAULT)
    user = config.get("mikrotik_user", "admin")
    password = config.get("mikrotik_password", "")
    url = f"http://{host}:{port}/rest/{path.lstrip('/')}"
    auth = HTTPBasicAuth(user, password)

    resp = requests.request(method.upper(), url, json=data, auth=auth, timeout=timeout)
    resp.raise_for_status()

    # 204 No Content → pas de body JSON
    if resp.status_code == 204 or not resp.text.strip():
        return None
    try:
        return resp.json()
    except json.JSONDecodeError:
        return None


def _rest_api_get(
    config: dict, path: str, timeout: int = 10
) -> list | dict | None:
    """GET vers l'API REST MikroTik."""
    return _rest_api_call(config, "GET", path, timeout=timeout)


def _rest_api_patch(
    config: dict, path: str, data: dict, timeout: int = 10
) -> dict | list | None:
    """PATCH vers l'API REST MikroTik (mise à jour)."""
    return _rest_api_call(config, "PATCH", path, data=data, timeout=timeout)


def _rest_api_post(
    config: dict, path: str, data: dict, timeout: int = 10
) -> dict | list | None:
    """POST vers l'API REST MikroTik (création)."""
    return _rest_api_call(config, "POST", path, data=data, timeout=timeout)


def _rest_api_delete(
    config: dict, path: str, timeout: int = 10
) -> dict | list | None:
    """DELETE vers l'API REST MikroTik."""
    return _rest_api_call(config, "DELETE", path, timeout=timeout)


def _generate_onlogin_script(validity: str, lock_mac: bool = False) -> str:
    """
    Génère le on-login script RouterOS pour un hotspot profile.
    RouterOS v7.10+ utilise le format ISO pour les dates (YYYY-MM-DD).

    Se déclenche à chaque connexion utilisateur :
    - Vérifie que c'est un voucher (commentaire commence par "vc")
    - Calcule la date d'expiration via scheduler temporaire
    - Stocke l'expiration en format ISO dans le commentaire du user
    - Optionnel : verrouille le MAC address à la 1ère connexion
    """
    lines = [
        '{',
        '  :local c [/ip hotspot user get [find where name="$user"] comment];',
        '  :local u [:pick $c 0 2];',
        '  :if ($u = "vc") do={',
        '    :local d [/system clock get date];',
        f'    /system scheduler add name="$user" start-date=$d interval="{validity}";',
        '    :delay 5s;',
        '    :local e [/system scheduler get [find name="$user"] next-run];',
        # ISO format: "YYYY-MM-DD HH:MM:SS" = 19 chars → garder "YYYY-MM-DD HH:MM"
        '    :if ([:len $e] = 19) do={ :set e [:pick $e 0 16]; }',
        '    /ip hotspot user set comment="$e" [find where name="$user"];',
        '    :delay 3s;',
        '    /system scheduler remove [find name="$user"];',
    ]
    if lock_mac:
        lines.append('    :local mac "$mac-address";')
        lines.append('    /ip hotspot user set mac-address=$mac [find where name="$user"];')
    lines.append('  }')
    lines.append('}')
    # Marqueur WIFIZONE pour détection auto-init
    lines.append('# WIFIZONE on-login v2')
    return "\n".join(lines)


def _generate_cleanup_script(profile_name: str) -> str:
    """
    Génère le script de nettoyage pour le scheduler.
    Format ISO YYYY-MM-DD (RouterOS v7.10+).
    Parcourt tous les users du profile et supprime ceux dont
    la date d'expiration (dans le commentaire) est dépassée.

    Comparaison multi-niveaux : année → mois → jour → heure → minute.
    Chaque niveau utilise [:tonum] pour éviter l'erreur RouterOS
    "cannot compare if string is less than string".
    Les conditions sont indépendantes (pas de else, juste des if qui
    vérifient le niveau précédent).
    """
    return (
        ':local dNow [/system clock get date];\n'
        ':local tNow [/system clock get time];\n'
        # ISO format: dNow="2026-07-17", tNow="09:07:18"
        ':local yNow [:tonum [:pick $dNow 0 4]];\n'
        ':local mNow [:tonum [:pick $dNow 5 7]];\n'
        ':local dDay [:tonum [:pick $dNow 8 10]];\n'
        ':local hNow [:tonum [:pick $tNow 0 2]];\n'
        ':local minNow [:tonum [:pick $tNow 3 5]];\n'
        f':foreach i in=[/ip hotspot user find where profile="{profile_name}"] do={{\n'
        '  :local c [/ip hotspot user get $i comment];\n'
        '  :local n [/ip hotspot user get $i name];\n'
        '  :if ([:len $c] > 10) do={\n'
        # Guard: ISO date a "-" à l'index 4 (ex: "2026-07-17 ...")
        '    :if ([:pick $c 4 5] != "-") do={ :put ("SKIP $n (no date)"); } else={\n'
        '    :local eYear  [:tonum [:pick $c 0 4]];\n'
        '    :local eMonth [:tonum [:pick $c 5 7]];\n'
        '    :local eDay   [:tonum [:pick $c 8 10]];\n'
        '    :local eHour  [:tonum [:pick $c 11 13]];\n'
        '    :local eMin   [:tonum [:pick $c 14 16]];\n'
        # Année inférieure → expiré
        '      :if ($eYear < $yNow) do={\n'
        '        /ip hotspot user remove $i;\n'
        '        /ip hotspot active remove [find user=$n];\n'
        '        :put ("REMOVED $n (year)");\n'
        '      }\n'
        # Même année, mois inférieur → expiré
        '      :if ($eYear = $yNow and $eMonth < $mNow) do={\n'
        '        /ip hotspot user remove $i;\n'
        '        /ip hotspot active remove [find user=$n];\n'
        '        :put ("REMOVED $n (month)");\n'
        '      }\n'
        # Même année+même mois, jour inférieur → expiré
        '      :if ($eYear = $yNow and $eMonth = $mNow and $eDay < $dDay) do={\n'
        '        /ip hotspot user remove $i;\n'
        '        /ip hotspot active remove [find user=$n];\n'
        '        :put ("REMOVED $n (day)");\n'
        '      }\n'
        # Même année+même mois+même jour, heure inférieure → expiré
        '      :if ($eYear = $yNow and $eMonth = $mNow and $eDay = $dDay and $eHour < $hNow) do={\n'
        '        /ip hotspot user remove $i;\n'
        '        /ip hotspot active remove [find user=$n];\n'
        '        :put ("REMOVED $n (hour)");\n'
        '      }\n'
        # Même année+même mois+même jour+même heure, minute inférieure → expiré
        '      :if ($eYear = $yNow and $eMonth = $mNow and $eDay = $dDay and $eHour = $hNow and $eMin < $minNow) do={\n'
        '        /ip hotspot user remove $i;\n'
        '        /ip hotspot active remove [find user=$n];\n'
        '        :put ("REMOVED $n (min)");\n'
        '      }\n'
        '    }\n'
        '  }\n'
        '}\n'
    )


def _handler_setup_profile(
    ssh: SSHClient,
    config: dict,
    params: dict,
) -> dict[str, Any]:
    """
    Configure le on-login script + scheduler cleanup pour un hotspot profile.
    Utilise l'API REST MikroTik (port 8080 par défaut) pour éviter
    les problèmes de quoting SSH avec les longs scripts contenant {} et $.

    Paramètres :
        profile   (str, obligatoire) — Nom du profile hotspot
        validity  (str, optionnel)   — Période de validité (ex: "1h", "1d", "7d")
        lock_mac  (str, optionnel)   — "yes" pour verrouiller le MAC address

    Retourne :
        {"status": "ok", "profile": "...", "on_login_length": N, ...}
    """
    profile = params["profile"]
    validity = params.get("validity", "1h")
    lock_mac = params.get("lock_mac", "").lower() in ("yes", "true", "1")

    # 1. Vérifier que le profile existe
    profile_data = _rest_api_get(config, f"ip/hotspot/user/profile/{profile}")
    if profile_data is None:
        return {"status": "not_found", "profile": profile, "detail": "Aucune donnée retournée par l'API REST"}
    if isinstance(profile_data, list) and not profile_data:
        return {"status": "not_found", "profile": profile}

    # 2. Injecter le on-login script
    login_script = _generate_onlogin_script(validity, lock_mac)
    _rest_api_patch(config, f"ip/hotspot/user/profile/{profile}", {"on-login": login_script})
    logger.info(f"[setup_profile] On-login injecté ({len(login_script)} chars) → {profile}")

    # 3. Créer/mettre à jour le scheduler cleanup
    cleanup_name = f"wf-cleanup-{profile}"
    cleanup_script = _generate_cleanup_script(profile)

    # Supprimer l'ancien scheduler s'il existe
    try:
        schedulers = _rest_api_get(config, "system/scheduler")
        if schedulers and isinstance(schedulers, list):
            for sched in schedulers:
                if sched.get("name") == cleanup_name:
                    sched_id = sched.get(".id", "")
                    if sched_id:
                        _rest_api_delete(config, f"system/scheduler/{sched_id}")
                        logger.info(f"[setup_profile] Ancien scheduler supprimé : {cleanup_name}")
    except requests.HTTPError:
        pass  # Pas de scheduler existant

    # Créer le nouveau scheduler
    # RouterOS REST API v7: POST /rest/{path}/add pour créer
    _rest_api_call(config, "POST", "system/scheduler/add", {
        "name": cleanup_name,
        "start-time": "00:03:00",
        "interval": "00:03:00",
        "on-event": cleanup_script,
        "comment": f"WIFIZONE cleanup {profile}",
        "disabled": "no",
    })
    logger.info(f"[setup_profile] Scheduler créé : {cleanup_name} (interval 3min)")

    return {
        "status": "ok",
        "profile": profile,
        "validity": validity,
        "lock_mac": lock_mac,
        "on_login_length": len(login_script),
        "cleanup_scheduler": cleanup_name,
    }


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  AUTO-INIT : Initialisation auto du routeur au démarrage agent             ║
# ║  S'exécute après la connexion SSH, avant la première collecte              ║
# ╚══════════════════════════════════════════════════════════════════════════════╝


def auto_init_router(ssh: SSHClient, config: dict) -> dict[str, Any]:
    """
    Auto-initialisation du routeur MikroTik au démarrage de l'agent.
    Idempotent — ne fait que ce qui manque, ne casse rien.

    1. Active l'API REST (port 8080) si pas déjà
    2. Scanne tous les profils hotspot existants
    3. Injecte on-login sur les profils qui n'en ont pas
    4. Crée les schedulers cleanup manquants

    Retourne un rapport de ce qui a été fait.
    """
    report: dict[str, Any] = {
        "rest_api": {"status": "unknown", "detail": ""},
        "profiles_scanned": 0,
        "on_login_injected": [],
        "cleanup_created": [],
        "errors": [],
    }

    # ── 1. Vérifier/activer REST API ──────────────────────────────────────
    rest_port = config.get("mikrotik_rest_port", REST_PORT_DEFAULT)
    try:
        _rest_api_get(config, "system/identity", timeout=5)
        report["rest_api"] = {"status": "already_enabled", "port": rest_port}
    except Exception:
        logger.info("[auto_init] API REST inactive — activation via SSH...")
        try:
            result = ssh.execute(
                f"/ip service set www-ssl disabled=no port={rest_port}",
                timeout=10,
            )
            if result.get("exit_code") == 0:
                report["rest_api"] = {"status": "enabled", "port": rest_port}
                logger.info(f"[auto_init] ✅ API REST activée (port {rest_port})")
            else:
                report["rest_api"] = {"status": "failed", "detail": result.get("stderr", "")}
                report["errors"].append(f"REST API activation failed: {result.get('stderr')}")
                logger.warning(f"[auto_init] ⚠️ Impossible d'activer REST API")
                return report  # Sans REST API, on ne peut pas continuer
        except Exception as e:
            report["rest_api"] = {"status": "failed", "detail": str(e)}
            report["errors"].append(f"REST API exception: {e}")
            logger.warning(f"[auto_init] ⚠️ Exception activation REST API: {e}")
            return report

    # Petite pause pour que REST API soit prête
    import time as _time
    _time.sleep(1)

    # ── 2. Lister les profils hotspot ───────────────────────────────────────
    try:
        profiles = _rest_api_get(config, "ip/hotspot/user/profile")
        if not profiles or not isinstance(profiles, list):
            report["profiles_scanned"] = 0
            logger.info("[auto_init] Aucun profil hotspot trouvé.")
            return report
    except Exception as e:
        report["errors"].append(f"Impossible de lister les profils: {e}")
        logger.warning(f"[auto_init] ⚠️ Échec liste profils: {e}")
        return report

    report["profiles_scanned"] = len(profiles)
    logger.info(f"[auto_init] {len(profiles)} profils hotspot trouvés")

    # ── 3. Injecter on-login + créer cleanup pour chaque profil ────────────
    for profile in profiles:
        pname = profile.get("name", "")
        if not pname:
            continue

        on_login = profile.get("on-login", "")

        # Vérifier si le profil a déjà un on-login WIFIZONE à jour
        if on_login and "# WIFIZONE on-login v2" in on_login:
            logger.debug(f"[auto_init] Profil '{pname}' a déjà on-login WIFIZONE ✅")
        else:
            if on_login:
                logger.info(f"[auto_init] Profil '{pname}' — remplace ancien on-login ({len(on_login)} chars)")
            # Injecter on-login par défaut
            try:
                login_script = _generate_onlogin_script("1h", lock_mac=False)
                _rest_api_patch(config, f"ip/hotspot/user/profile/{pname}", {"on-login": login_script})
                report["on_login_injected"].append(pname)
                logger.info(f"[auto_init] ✅ On-login injecté sur '{pname}' ({len(login_script)} chars)")
            except Exception as e:
                report["errors"].append(f"on-login '{pname}': {e}")
                logger.warning(f"[auto_init] ⚠️ Échec on-login '{pname}': {e}")

        # Vérifier si le scheduler cleanup existe déjà
        cleanup_name = f"wf-cleanup-{pname}"
        scheduler_exists = False
        try:
            schedulers = _rest_api_get(config, "system/scheduler")
            if schedulers and isinstance(schedulers, list):
                for s in schedulers:
                    if s.get("name") == cleanup_name:
                        scheduler_exists = True
                        break
        except Exception:
            pass

        if scheduler_exists:
            logger.debug(f"[auto_init] Scheduler '{cleanup_name}' existe déjà ✅")
        else:
            # Créer le scheduler cleanup
            try:
                cleanup_script = _generate_cleanup_script(pname)
                _rest_api_call(config, "POST", "system/scheduler/add", {
                    "name": cleanup_name,
                    "start-time": "00:03:00",
                    "interval": "00:03:00",
                    "on-event": cleanup_script,
                    "comment": f"WIFIZONE cleanup {pname}",
                    "disabled": "no",
                })
                report["cleanup_created"].append(pname)
                logger.info(f"[auto_init] ✅ Scheduler '{cleanup_name}' créé (interval 3min)")
            except Exception as e:
                report["errors"].append(f"scheduler '{cleanup_name}': {e}")
                logger.warning(f"[auto_init] ⚠️ Échec scheduler '{cleanup_name}': {e}")

    # Rapport final
    logger.info(
        f"[auto_init] ✅ Terminé — "
        f"{len(report['on_login_injected'])} on-login, "
        f"{len(report['cleanup_created'])} cleanups, "
        f"{len(report['errors'])} erreurs"
    )
    return report


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  BACKWARD COMPATIBILITY : Ancienne interface execute_command()              ║
# ║  Utilisée par main.py et les boucles de collecte existantes                ║
# ╚══════════════════════════════════════════════════════════════════════════════╝


def _handler_export_pdf(
    ssh: SSHClient,
    config: dict,
    params: dict,
) -> dict[str, Any]:
    """
    Exporte une liste de vouchers vers un fichier PDF.

    Paramètres :
        params["vouchers"] : liste de dicts (name, password, profile, time_limit,
                              price, login_url, comment, generated_at, etc.)
        params["filename"] : nom de fichier optionnel

    Retourne :
        {"status": "ok", "filename": "...", "path": "...", "count": N}
    """
    vouchers = params.get("vouchers", [])
    if not vouchers:
        return {"status": "error", "error": "Aucun voucher à exporter"}

    if isinstance(vouchers, str):
        try:
            vouchers = json.loads(vouchers)
        except (json.JSONDecodeError, TypeError):
            return {"status": "error", "error": "Paramètre 'vouchers' invalide : JSON string attendu"}

    if not isinstance(vouchers, list):
        return {"status": "error", "error": "Paramètre 'vouchers' doit être une liste"}

    # Générer le nom de fichier
    filename = params.get("filename", "").strip()
    if not filename:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        site = config.get("site_id", "unknown").lower()
        filename = f"tickets_{site}_{ts}.pdf"

    # S'assurer que l'extension est .pdf
    if not filename.lower().endswith(".pdf"):
        filename += ".pdf"

    output_path = str(VOUCHER_DIR / filename)

    try:
        # Appel à voucher_pdf.generate_voucher_pdf()
        from voucher_pdf import generate_voucher_pdf
        generate_voucher_pdf(
            vouchers=vouchers,
            config=config,
            output_path=output_path,
        )
        logger.info(f"PDF généré : {output_path} ({len(vouchers)} tickets)")

        return {
            "status": "ok",
            "filename": filename,
            "path": output_path,
            "count": len(vouchers),
        }
    except Exception as e:
        logger.error(f"Erreur génération PDF : {e}", exc_info=True)
        return {
            "status": "error",
            "error": f"Erreur génération PDF : {str(e)}",
        }


def execute_command(
    ssh_pool: SSHPool,
    config: dict,
    command: str,
    params: dict[str, Any],
) -> dict[str, Any]:
    """
    Point d'entrée rétro-compatible.

    Remplace l'ancien executor.execute_command(pool, config, command, params).
    Résout les anciens noms de commande via les alias du registre.
    Retourne le format CommandResult compatible avec l'ancien système.
    """
    # Résoudre l'ancien nom de commande via les alias
    resolved = resolve_name(command)
    if resolved is None:
        # Essayer directement comme action
        resolved = command

    result = execute_action(
        ssh_pool=ssh_pool,
        config=config,
        action_name=resolved,
        params=params,
    )

    # Formater comme l'ancien CommandResult pour backward compat
    return {
        "site_id": config.get("site_id", "unknown"),
        "command": command,
        "status": "ok" if result.get("status") == "success" else "error",
        "result": result.get("output", result),
        "timestamp": now_iso(),
    }

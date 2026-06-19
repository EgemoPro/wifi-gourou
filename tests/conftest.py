"""
conftest.py — Fixtures partagées pour tous les tests wifizone-agent
Sans connexion réelle à un MikroTik.
"""
import sys
import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

# ── Shim pour les modules qui dépendent de config globale ────────────────


@pytest.fixture(autouse=True)
def _reset_registry():
    """Reset le cache du registre avant chaque test."""
    from core.registry import _registry, _actions, _alias_map

    _registry = None
    _actions = {}
    _alias_map = {}
    yield
    _registry = None
    _actions = {}
    _alias_map = {}


# ── Fausse config ────────────────────────────────────────────────────────


@pytest.fixture
def fake_config() -> dict[str, Any]:
    """Configuration agent factice pour les tests."""
    return {
        "site_id": "site_a",
        "site_name": "Site Alpha",
        "mikrotik_host": "192.168.88.1",
        "mikrotik_port": 8728,
        "mikrotik_ssh_port": 22,
        "mikrotik_user": "admin",
        "mikrotik_password": "test_pass",
        "central_host": "central.example.com",
        "central_port": 5678,
        "central_api_key": "test-api-key",
        "ssh_timeout": 15,
        "alert_port": 9000,
        "command_port": 9001,
        "intervals": {},
        "thresholds": {
            "cpu_alert_percent": 80,
            "cpu_alert_cycles": 2,
            "bandwidth_suspect_mb": 500,
            "max_users_warning": 200,
            "max_schedulers_warning": 20,
            "offline_retries": 3,
        },
    }


@pytest.fixture
def fake_commands_json(tmp_path: Path) -> Path:
    """Crée un fichier commands.json temporaire pour les tests."""
    data = {
        "meta": {"version": "2.0"},
        "actions": {
            "hotspot.create_user": {
                "type": "routeros",
                "script": "hotspot/add_user.rsc",
                "timeout": 15,
                "description": "Crée un utilisateur hotspot",
                "params": [
                    {"name": "username", "required": True, "type": "string",
                     "max_length": 32},
                    {"name": "password", "required": True, "type": "string",
                     "max_length": 64},
                    {"name": "profile", "required": False, "type": "string",
                     "default": "default"},
                ],
                "danger": "low",
                "alias": ["create_user"],
            },
            "hotspot.vouchers": {
                "type": "python",
                "handler": "generate_vouchers",
                "description": "Génère des vouchers",
                "params": [
                    {"name": "qty", "required": False, "type": "int",
                     "default": 1, "min": 1, "max": 99},
                    {"name": "profile", "required": False, "type": "string",
                     "default": "default"},
                    {"name": "name_length", "required": False, "type": "int",
                     "default": 8},
                ],
                "danger": "low",
                "alias": ["generate_vouchers"],
            },
            "router.reboot": {
                "type": "routeros",
                "script": "system/reboot.rsc",
                "timeout": 30,
                "description": "Redémarre le routeur",
                "params": [
                    {"name": "confirm", "required": True, "type": "bool"},
                ],
                "danger": "high",
                "alias": ["reboot_router"],
            },
            "router.backup": {
                "type": "python",
                "handler": "backup_router",
                "description": "Backup config",
                "params": [],
                "danger": "low",
                "alias": ["backup_config"],
            },
            "profile.update": {
                "type": "python",
                "handler": "update_profile",
                "description": "Update hotspot profile",
                "params": [
                    {"name": "name", "required": True, "type": "string",
                     "max_length": 32},
                    {"name": "rate_limit", "required": False, "type": "string"},
                    {"name": "shared_users", "required": False, "type": "int"},
                    {"name": "session_timeout", "required": False, "type": "string"},
                    {"name": "data_limit", "required": False, "type": "string"},
                ],
                "danger": "medium",
                "alias": ["update_profile"],
            },
            "router.health": {
                "type": "routeros",
                "script": "diagnostics/health.rsc",
                "timeout": 10,
                "description": "Santé du routeur",
                "params": [],
                "danger": "low",
            },
            "hotspot.block_mac": {
                "type": "routeros",
                "script": "network/block_mac.rsc",
                "timeout": 10,
                "description": "Bloque une MAC",
                "params": [
                    {"name": "mac", "required": True, "type": "string",
                     "pattern":
                     "^([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}$"},
                ],
                "danger": "medium",
                "alias": ["block_mac"],
            },
            "unknown_type_action": {
                "type": "invalid_type",
                "script": "nonexistent.rsc",
                "timeout": 10,
                "description": "Test",
                "params": [],
                "danger": "low",
            },
        },
    }
    commands_file = tmp_path / "config" / "commands.json"
    commands_file.parent.mkdir(parents=True)
    commands_file.write_text(json.dumps(data, indent=2))

    # Créer un script .rsc factice pour les tests
    scripts_dir = tmp_path / "scripts" / "routeros"
    scripts_dir.mkdir(parents=True)

    (scripts_dir / "hotspot").mkdir(exist_ok=True)
    add_user_script = scripts_dir / "hotspot" / "add_user.rsc"
    add_user_script.write_text(
        '/ip hotspot user add name=$username password=$password '
        'profile=$profile\n'
        ':put "USER_CREATED"\n'
    )

    (scripts_dir / "system").mkdir(exist_ok=True)
    reboot_script = scripts_dir / "system" / "reboot.rsc"
    reboot_script.write_text('/system reboot\n:put "REBOOT_INITIATED"\n')

    (scripts_dir / "diagnostics").mkdir(exist_ok=True)
    health_script = scripts_dir / "diagnostics" / "health.rsc"
    health_script.write_text(
        '/system resource print\n:put "=== HEALTH ===\n'
        'cpu-load=25\nuptime=1d2h3m"'
    )

    (scripts_dir / "network").mkdir(exist_ok=True)
    block_mac_script = scripts_dir / "network" / "block_mac.rsc"
    block_mac_script.write_text(
        '/ip firewall address-list add address=$mac list=blocked\n'
        ':put "MAC_BLOCKED"\n'
    )

    return commands_file


# ── Mock Paramiko ────────────────────────────────────────────────────────


@pytest.fixture
def mock_paramiko(mocker):
    """Mock complet de paramiko.SSHClient.

    Retourne un dict avec:
      - mock_client: le mock du client SSH
      - mock_transport: le mock du transport
      - mock_sftp: le mock du client SFTP
      - mock_stdout: le mock du channel stdout
      - mock_stderr: le mock du channel stderr
    """
    mock_transport = mocker.MagicMock()
    mock_transport.is_active.return_value = True

    mock_stdout = mocker.MagicMock()
    mock_stdout.channel.recv_exit_status.return_value = 0
    mock_stdout.read.return_value = b"mocked stdout output"

    mock_stderr = mocker.MagicMock()
    mock_stderr.read.return_value = b""

    mock_client = mocker.MagicMock()
    mock_client.get_transport.return_value = mock_transport
    mock_client.exec_command.return_value = (
        mocker.MagicMock(), mock_stdout, mock_stderr,
    )

    mock_sftp = mocker.MagicMock()
    mock_sftp.sock = mocker.MagicMock()  # non-None → connected
    mock_client.open_sftp.return_value = mock_sftp

    # Patch paramiko.SSHClient class (appelée dans SSHClient.connect)
    mocker.patch("core.ssh.paramiko.SSHClient", return_value=mock_client)
    mocker.patch("core.ssh.paramiko.AutoAddPolicy")
    mocker.patch("core.ssh.paramiko.SFTPClient")

    return {
        "client": mock_client,
        "transport": mock_transport,
        "sftp": mock_sftp,
        "stdout": mock_stdout,
        "stderr": mock_stderr,
    }


@pytest.fixture
def mock_ssh_client(mock_paramiko) -> Any:
    """Crée une instance SSHClient avec paramiko mocké."""
    from core.ssh import SSHClient

    client = SSHClient(host="192.168.88.1", username="admin",
                       password="test")
    return client


@pytest.fixture
def mock_ssh_pool(mock_paramiko, fake_config) -> Any:
    """Crée un SSHPool avec paramiko mocké."""
    from core.ssh import SSHPool

    pool = SSHPool(fake_config)
    return pool


# ── Fixtures pour executor ───────────────────────────────────────────────


@pytest.fixture
def patched_executor_registry(mocker, fake_commands_json: Path):
    """Patche les chemins du registry pour utiliser le commands.json
    temporaire et le répertoire scripts factice."""
    scripts_dir = fake_commands_json.parent.parent / "scripts"
    mocker.patch("core.registry.REGISTRY_PATH", fake_commands_json)
    mocker.patch("core.registry.SCRIPTS_DIR", scripts_dir)
    mocker.patch("core.registry._registry", None)
    mocker.patch("core.registry._actions", {})
    mocker.patch("core.registry._alias_map", {})

    return fake_commands_json


@pytest.fixture
def setup_executor(mocker, patched_executor_registry, mock_paramiko,
                   fake_config):
    """Configure l'environnement complet pour exécuter execute_action.

    Patche les constantes de répertoire dans executor.py.
    """
    base_dir = patched_executor_registry.parent.parent
    mocker.patch("core.executor.BASE_DIR", base_dir)
    mocker.patch("core.executor.BACKUP_DIR", base_dir / "backups")
    mocker.patch("core.executor.VOUCHER_DIR", base_dir / "vouchers")
    (base_dir / "backups").mkdir(exist_ok=True)
    (base_dir / "vouchers").mkdir(exist_ok=True)

    from core.ssh import SSHPool

    pool = SSHPool(fake_config)
    return pool, fake_config

"""Tests pour core/executor.py — pipeline complet avec SSH mocké."""
import json
from pathlib import Path

import pytest

from core.registry import _registry, _actions, _alias_map


# ═════════════════════════════════════════════════════════════════════════
# _parse_rsc_output()
# ═════════════════════════════════════════════════════════════════════════


class TestParseRscOutput:
    """Tests unitaires pour _parse_rsc_output()."""

    def test_empty_stdout(self):
        from core.executor import _parse_rsc_output
        result = _parse_rsc_output("")
        assert result["status"] == "completed"

    def test_key_value_pairs(self):
        from core.executor import _parse_rsc_output
        result = _parse_rsc_output("cpu-load=25\nuptime=1d2h3m")
        assert result["cpu-load"] == "25"
        assert result["uptime"] == "1d2h3m"

    def test_section_markers(self):
        from core.executor import _parse_rsc_output
        stdout = "=== HEALTH ===\ncpu-load=25\n=== END ==="
        result = _parse_rsc_output(stdout)
        assert result["health_cpu-load"] == "25"

    def test_status_success_keyword(self):
        from core.executor import _parse_rsc_output
        result = _parse_rsc_output("USER_CREATED")
        assert result["status"] == "user_created"

    def test_status_error_keyword(self):
        from core.executor import _parse_rsc_output
        result = _parse_rsc_output("ERROR: already exists")
        assert result["status"] == "error"

    def test_status_completed_by_default(self):
        from core.executor import _parse_rsc_output
        result = _parse_rsc_output("some random output\nwith=values")
        assert result["status"] == "completed"

    def test_blank_lines_skipped(self):
        from core.executor import _parse_rsc_output
        result = _parse_rsc_output("\n\n\nkey=val\n\n")
        assert result["key"] == "val"

    def test_lines_without_equals_skipped(self):
        from core.executor import _parse_rsc_output
        result = _parse_rsc_output("info line\nkey=val\nanother line")
        assert result["key"] == "val"


# ═════════════════════════════════════════════════════════════════════════
# _parse_data_limit()
# ═════════════════════════════════════════════════════════════════════════


class TestParseDataLimit:
    def test_none(self):
        from core.executor import _parse_data_limit
        assert _parse_data_limit(None) == 0
        assert _parse_data_limit("") == 0

    def test_bytes(self):
        from core.executor import _parse_data_limit
        assert _parse_data_limit("500") == 500

    def test_kilobytes(self):
        from core.executor import _parse_data_limit
        assert _parse_data_limit("1K") == 1024
        assert _parse_data_limit("2KB") == 2048

    def test_megabytes(self):
        from core.executor import _parse_data_limit
        assert _parse_data_limit("1M") == 1024 ** 2
        assert _parse_data_limit("2MB") == 2 * 1024 ** 2

    def test_gigabytes(self):
        from core.executor import _parse_data_limit
        assert _parse_data_limit("1G") == 1024 ** 3
        assert _parse_data_limit("2GB") == 2 * 1024 ** 3

    def test_invalid_value(self):
        from core.executor import _parse_data_limit
        assert _parse_data_limit("invalid") == 0


# ═════════════════════════════════════════════════════════════════════════
# _sanitize_ros_param()
# ═════════════════════════════════════════════════════════════════════════


class TestSanitizeRosParam:
    def test_escapes_quotes(self):
        from core.executor import _sanitize_ros_param
        assert _sanitize_ros_param('test"value') == 'test\\"value'

    def test_truncates_long(self):
        from core.executor import _sanitize_ros_param
        long_val = "a" * 100
        assert len(_sanitize_ros_param(long_val)) == 50

    def test_strips_whitespace(self):
        from core.executor import _sanitize_ros_param
        assert _sanitize_ros_param("  hello  ") == "hello"

    def test_integer_input(self):
        from core.executor import _sanitize_ros_param
        assert _sanitize_ros_param(42) == "42"

    def test_empty_string(self):
        from core.executor import _sanitize_ros_param
        assert _sanitize_ros_param("") == ""


# ═════════════════════════════════════════════════════════════════════════
# make_response()
# ═════════════════════════════════════════════════════════════════════════


class TestMakeResponse:
    def test_basic_response(self):
        from core.executor import make_response
        resp = make_response(
            command_id="cmd_123", action="hotspot.create_user",
            site_id="site_a", status="success",
        )
        assert resp["id"] == "cmd_123"
        assert resp["action"] == "hotspot.create_user"
        assert resp["site_id"] == "site_a"
        assert resp["status"] == "success"
        assert "timestamp" in resp

    def test_with_output(self):
        from core.executor import make_response
        resp = make_response(
            command_id="cmd_1", action="test", site_id="s1",
            status="success", output={"key": "val"},
        )
        assert resp["output"] == {"key": "val"}

    def test_with_error(self):
        from core.executor import make_response
        resp = make_response(
            command_id="cmd_1", action="test", site_id="s1",
            status="failed",
            error={"type": "TEST_ERROR", "message": "test"},
        )
        assert resp["error"]["type"] == "TEST_ERROR"

    def test_with_execution_time(self):
        from core.executor import make_response
        resp = make_response(
            command_id="cmd_1", action="test", site_id="s1",
            status="success", execution_time_ms=1234,
        )
        assert resp["execution_time_ms"] == 1234


# ═════════════════════════════════════════════════════════════════════════
# _preview_action()
# ═════════════════════════════════════════════════════════════════════════


class TestPreviewAction:
    def test_preview_returns_generated_script(
            self, setup_executor, patched_executor_registry):
        """mode=preview → script généré sans exécution SSH."""
        from core.executor import execute_action
        from core.ssh import SSHPool

        pool, config = setup_executor
        # Créer un pool factice avec mock_paramiko intégré
        result = execute_action(
            ssh_pool=pool,
            config=config,
            action_name="hotspot.create_user",
            params={"username": "test", "password": "secret",
                    "mode": "preview"},
        )
        assert result["status"] == "preview"
        assert "output" in result
        assert "generated" in result["output"]
        assert ":local username" in result["output"]["generated"]
        assert ":local password" in result["output"]["generated"]

    def test_preview_routeros_only(self, setup_executor):
        """mode=preview fonctionne même si ssh_pool est None."""
        from core.executor import execute_action
        result = execute_action(
            ssh_pool=None,
            config={"site_id": "test"},
            action_name="router.health",
            params={"mode": "preview"},
        )
        assert result["status"] == "preview"


# ═════════════════════════════════════════════════════════════════════════
# execute_action() — RouterOS type
# ═════════════════════════════════════════════════════════════════════════


class TestExecuteActionRouterOS:
    def test_execute_routeros_success(
            self, setup_executor, mock_paramiko):
        """Pipeline complet routeros → réponse success."""
        from core.executor import execute_action

        # Simuler une sortie RouterOS avec des clé=valeur
        mock_paramiko["stdout"].read.return_value = (
            b"status=success\ncpu-load=25\nuptime=1d2h3m"
        )

        pool, config = setup_executor
        result = execute_action(
            ssh_pool=pool,
            config=config,
            action_name="hotspot.create_user",
            params={"username": "testuser", "password": "test123"},
        )
        assert result["status"] == "success"
        assert result["action"] == "hotspot.create_user"
        assert "output" in result
        assert "execution_time_ms" in result
        assert result["output"].get("status") == "success"

    def test_execute_routeros_via_alias(
            self, setup_executor, mock_paramiko):
        """Les alias sont résolus (create_user → hotspot.create_user)."""
        from core.executor import execute_action

        mock_paramiko["stdout"].read.return_value = b"status=ok"

        pool, config = setup_executor
        result = execute_action(
            ssh_pool=pool, config=config,
            action_name="create_user",
            params={"username": "u", "password": "p"},
        )
        assert result["status"] in ("success", "failed")
        # L'action canonique doit apparaître
        assert result["action"] == "hotspot.create_user"

    def test_execute_routeros_no_params(
            self, setup_executor, mock_paramiko):
        """Action sans paramètres (router.health)."""
        from core.executor import execute_action

        mock_paramiko["stdout"].read.return_value = (
            b"health=ok\nuptime=10d"
        )

        pool, config = setup_executor
        result = execute_action(
            ssh_pool=pool, config=config,
            action_name="router.health",
            params={},
        )
        assert result["status"] == "success"

    def test_execute_routeros_nonzero_exit(
            self, setup_executor, mock_paramiko):
        """exit_code == -1 (SSH error) → status=failed, SSH_ERROR."""
        from core.executor import execute_action

        # exit_code = -1 → ConnectionError dans _execute_routeros_script
        mock_paramiko["stdout"].channel.recv_exit_status.return_value = -1
        mock_paramiko["stderr"].read.return_value = b"connection error"

        pool, config = setup_executor
        result = execute_action(
            ssh_pool=pool, config=config,
            action_name="router.health",
            params={},
        )
        assert result["status"] == "failed"
        assert result["error"]["type"] == "SSH_ERROR"


# ═════════════════════════════════════════════════════════════════════════
# execute_action() — Validation errors
# ═════════════════════════════════════════════════════════════════════════


class TestExecuteActionValidation:
    def test_invalid_action_name(self, setup_executor):
        """Action inconnue → status=failed, VALIDATION_ERROR."""
        from core.executor import execute_action
        pool, config = setup_executor
        result = execute_action(
            ssh_pool=pool, config=config,
            action_name="nonexistent.action",
            params={},
        )
        assert result["status"] == "failed"
        assert result["error"]["type"] == "VALIDATION_ERROR"

    def test_missing_required_param(
            self, setup_executor):
        """Paramètre requis manquant → status=failed."""
        from core.executor import execute_action
        pool, config = setup_executor
        result = execute_action(
            ssh_pool=pool, config=config,
            action_name="hotspot.create_user",
            params={"username": "test"},  # password manquant
        )
        assert result["status"] == "failed"
        assert result["error"]["type"] == "VALIDATION_ERROR"

    def test_invalid_param_type(self, setup_executor):
        """Paramètre string où int est attendu → status=failed."""
        from core.executor import execute_action
        pool, config = setup_executor
        result = execute_action(
            ssh_pool=pool, config=config,
            action_name="hotspot.vouchers",
            params={"qty": "not_a_number"},
        )
        assert result["status"] == "failed"
        assert result["error"]["type"] == "VALIDATION_ERROR"

    def test_unknown_type_action(self, setup_executor, mock_paramiko):
        """Type d'action inconnu → status=failed."""
        from core.executor import execute_action
        pool, config = setup_executor
        result = execute_action(
            ssh_pool=pool, config=config,
            action_name="unknown_type_action",
            params={},
        )
        assert result["status"] == "failed"
        assert "type d'action inconnu" in result["error"]["message"].lower()


# ═════════════════════════════════════════════════════════════════════════
# execute_action() — Python handlers
# ═════════════════════════════════════════════════════════════════════════


class TestExecuteActionPython:
    def test_generate_vouchers(
            self, setup_executor, mock_paramiko):
        """Handler generate_vouchers retourne des codes."""
        from core.executor import execute_action

        # Mock de ssh.execute() pour le print detail (vérif collision)
        mock_paramiko["stdout"].read.return_value = b""

        pool, config = setup_executor
        result = execute_action(
            ssh_pool=pool, config=config,
            action_name="hotspot.vouchers",
            params={"qty": 2, "profile": "default"},
        )
        assert result["status"] == "success"
        assert result["output"]["created"] == 2
        assert len(result["output"]["vouchers"]) == 2

    def test_generate_vouchers_with_custom_params(
            self, setup_executor, mock_paramiko):
        """Vouchers avec paramètres personnalisés."""
        from core.executor import execute_action

        mock_paramiko["stdout"].read.return_value = b""

        pool, config = setup_executor
        result = execute_action(
            ssh_pool=pool, config=config,
            action_name="hotspot.vouchers",
            params={"qty": 1, "profile": "premium",
                    "name_length": 10, "charset": "1234"},
        )
        assert result["status"] == "success"
        voucher = result["output"]["vouchers"][0]
        assert len(voucher["name"]) == 10
        assert voucher["profile"] == "premium"

    def test_generate_vouchers_collision_handling(
            self, setup_executor, mock_paramiko):
        """Collision de noms gérée (max 20 tentatives)."""
        from core.executor import execute_action
        # Simuler un user existant
        mock_paramiko["stdout"].read.return_value = (
            b'name="testuser"\n'
        )

        pool, config = setup_executor
        result = execute_action(
            ssh_pool=pool, config=config,
            action_name="hotspot.vouchers",
            params={"qty": 1, "profile": "default"},
        )
        assert result["status"] == "success"

    def test_backup_router(
            self, setup_executor, mock_paramiko, tmp_path):
        """Handler backup_router sauvegarde la config."""
        from core.executor import execute_action
        import core.executor as executor_mod

        # Rediriger le répertoire backup
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir(exist_ok=True)
        executor_mod.BACKUP_DIR = backup_dir

        mock_paramiko["stdout"].channel.recv_exit_status.return_value = 0
        mock_paramiko["stdout"].read.return_value = b"Saving..."
        # Créer un faux fichier de backup pour download_file
        (backup_dir / "site_a-2026-06-16.backup").write_text("dummy")

        pool, config = setup_executor
        result = execute_action(
            ssh_pool=pool, config=config,
            action_name="router.backup",
            params={},
        )
        assert result["status"] == "success"
        # Restaurer le répertoire original
        executor_mod.BACKUP_DIR = (
            Path(__file__).parent.parent / "backups"
        )

    def test_unknown_handler(self, setup_executor):
        """Handler inconnu dans l'action → réponse failed."""
        from core.executor import execute_action
        # Créer une action avec un handler inexistant dans commands.json
        # On utilise directement _execute_python_handler
        from core.executor import _execute_python_handler
        from core.ssh import SSHPool

        pool, config = setup_executor
        with pytest.raises(ValueError, match="inconnu"):
            _execute_python_handler(
                ssh=pool.get_client(),
                config=config,
                handler_name="nonexistent_handler",
                params={},
            )


# ═════════════════════════════════════════════════════════════════════════
# execute_action() — SSH errors
# ═════════════════════════════════════════════════════════════════════════


class TestExecuteActionSSHErrors:
    def test_ssh_pool_none_for_routeros(self, setup_executor):
        """ssh_pool=None pour action routeros → SSH_ERROR."""
        from core.executor import execute_action
        result = execute_action(
            ssh_pool=None,
            config={"site_id": "test"},
            action_name="router.health",
            params={},
        )
        assert result["status"] == "failed"
        assert result["error"]["type"] in ("EXECUTION_ERROR", "SSH_ERROR")

    def test_ssh_connection_error(
            self, setup_executor, mock_paramiko, mocker):
        """Erreur de connexion SSH → réponse structurée."""
        from core.executor import execute_action

        # Accélérer les time.sleep dans les retries SSH
        mocker.patch("core.ssh.time.sleep")

        # Faire échouer la connexion SSH
        mock_paramiko["client"].connect.side_effect = \
            OSError("SSH refused")

        pool, config = setup_executor
        # Réinitialiser le pool pour forcer une nouvelle connexion
        pool._client = None
        pool._last_error = None

        result = execute_action(
            ssh_pool=pool, config=config,
            action_name="router.health",
            params={},
        )
        # ConnectionError → SSH_ERROR
        assert result["status"] == "failed"
        assert result["error"]["type"] in ("SSH_ERROR", "EXECUTION_ERROR")


# ═════════════════════════════════════════════════════════════════════════
# _execute_routeros_script()
# ═════════════════════════════════════════════════════════════════════════


class TestExecuteRouterosScript:
    def test_script_not_found(
            self, setup_executor, patched_executor_registry, mocker):
        """Script .rsc manquant → FileNotFoundError."""
        from core.executor import _execute_routeros_script

        # Créer une action factice avec un script inexistant
        action_def = {
            "type": "routeros",
            "script": "nonexistent/script.rsc",
            "timeout": 10,
        }

        pool, config = setup_executor
        ssh = pool.get_client()
        with pytest.raises(FileNotFoundError):
            _execute_routeros_script(ssh, action_def,
                                     {"username": "test"})


# ═════════════════════════════════════════════════════════════════════════
# execute_command() — backward compatibility
# ═════════════════════════════════════════════════════════════════════════


class TestExecuteCommandBackwardCompat:
    def test_execute_command_resolves_alias(
            self, setup_executor, mock_paramiko):
        """execute_command() résout les anciens noms via alias."""
        from core.executor import execute_command

        mock_paramiko["stdout"].read.return_value = (
            b"status=success\ncpu-load=10"
        )

        pool, config = setup_executor
        result = execute_command(
            ssh_pool=pool, config=config,
            command="create_user",  # ancien nom → alias dans commands.json
            params={"username": "test", "password": "secret"},
        )
        assert result["status"] in ("ok", "error")
        assert "command" in result
        assert "result" in result
        assert "timestamp" in result

    def test_execute_command_unknown_falls_through(
            self, setup_executor, mock_paramiko):
        """Commande inconnue → tentative directe (échoue)."""
        from core.executor import execute_command

        pool, config = setup_executor
        result = execute_command(
            ssh_pool=pool, config=config,
            command="some_unknown_command",
            params={},
        )
        # Le format retourné est toujours valide
        assert "status" in result
        assert "command" in result


# ═════════════════════════════════════════════════════════════════════════
# _handler_update_profile()
# ═════════════════════════════════════════════════════════════════════════


class TestHandlerUpdateProfile:
    def test_profile_not_found(self, setup_executor, mock_paramiko):
        """Profil inexistant → status=not_found."""
        from core.executor import _handler_update_profile

        mock_paramiko["stdout"].read.return_value = b""  # stdout vide

        pool, config = setup_executor
        ssh = pool.get_client()
        result = _handler_update_profile(
            ssh=ssh, config=config,
            params={"name": "nonexistent_profile"},
        )
        assert result["status"] == "not_found"

    def test_profile_updated(self, setup_executor, mock_paramiko):
        """Profil existant → mis à jour."""
        from core.executor import _handler_update_profile

        mock_paramiko["stdout"].read.return_value = b"name=test_profile"

        pool, config = setup_executor
        ssh = pool.get_client()
        result = _handler_update_profile(
            ssh=ssh, config=config,
            params={
                "name": "test_profile",
                "rate_limit": "2M/2M",
                "shared_users": 3,
                "session_timeout": "30m",
                "data_limit": "500M",
            },
        )
        assert result["status"] == "updated"
        assert result["profile"] == "test_profile"


# ═════════════════════════════════════════════════════════════════════════
# generate_id()
# ═════════════════════════════════════════════════════════════════════════


class TestGenerateId:
    def test_generate_id_format(self):
        from core.executor import generate_id
        cmd_id = generate_id()
        assert cmd_id.startswith("cmd_")
        assert len(cmd_id) > 10

    def test_generate_id_unique(self):
        from core.executor import generate_id
        ids = {generate_id() for _ in range(100)}
        assert len(ids) == 100  # tous uniques


# ═════════════════════════════════════════════════════════════════════════
# _make_code()
# ═════════════════════════════════════════════════════════════════════════


class TestMakeCode:
    def test_default_length_and_charset(self):
        from core.executor import _make_code
        code = _make_code()
        assert len(code) == 8
        assert code.isupper()

    def test_custom_length(self):
        from core.executor import _make_code
        code = _make_code(length=12)
        assert len(code) == 12

    def test_digit_charset(self):
        from core.executor import _make_code
        code = _make_code(length=6, charset="1234")
        assert code.isdigit()

    def test_alphanumeric_charset(self):
        from core.executor import _make_code
        code = _make_code(length=100, charset="aB12")
        assert len(code) == 100
        assert code.isalnum()
        assert any(c.isdigit() for c in code)
        assert any(c.isalpha() for c in code)

    def test_unknown_charset_falls_back(self):
        from core.executor import _make_code
        code = _make_code(charset="unknown")
        assert len(code) == 8


# ═════════════════════════════════════════════════════════════════════════
# execute_action() — update_profile handler
# ═════════════════════════════════════════════════════════════════════════


class TestExecuteActionUpdateProfile:
    """Tests update_profile via le pipeline execute_action."""

    def test_update_profile_success(
            self, setup_executor, mock_paramiko):
        """update_profile avec params valides → output.status=updated."""
        from core.executor import execute_action

        mock_paramiko["stdout"].read.return_value = b"name=test_profile"

        pool, config = setup_executor
        result = execute_action(
            ssh_pool=pool, config=config,
            action_name="profile.update",
            params={"name": "test_profile", "rate_limit": "2M/2M"},
        )
        assert result["status"] == "success"
        assert result["output"]["status"] == "updated"
        assert result["output"]["profile"] == "test_profile"
        assert result["action"] == "profile.update"

    def test_update_profile_missing_name(
            self, setup_executor):
        """Paramètre 'name' manquant → VALIDATION_ERROR."""
        from core.executor import execute_action

        pool, config = setup_executor
        result = execute_action(
            ssh_pool=pool, config=config,
            action_name="profile.update",
            params={"rate_limit": "2M/2M"},
        )
        assert result["status"] == "failed"
        assert result["error"]["type"] == "VALIDATION_ERROR"
        assert "name" in result["error"]["message"]

    def test_update_profile_via_alias(
            self, setup_executor, mock_paramiko):
        """Alias 'update_profile' résolu vers 'profile.update'."""
        from core.executor import execute_action

        mock_paramiko["stdout"].read.return_value = b"name=test_profile"

        pool, config = setup_executor
        result = execute_action(
            ssh_pool=pool, config=config,
            action_name="update_profile",
            params={"name": "test_profile"},
        )
        assert result["status"] == "success"
        assert result["action"] == "profile.update"
        assert result["output"]["status"] == "updated"


# ═════════════════════════════════════════════════════════════════════════
# execute_action() — backup_router handler
# ═════════════════════════════════════════════════════════════════════════


class TestExecuteActionBackupRouter:
    """Tests backup_router via le pipeline execute_action."""

    def test_backup_router_success(
            self, setup_executor, mock_paramiko, tmp_path, mocker):
        """Backup réussi → réponse structurée complète."""
        from core.executor import execute_action
        import core.executor as executor_mod
        from pathlib import Path

        # Éviter le time.sleep réel
        mocker.patch("core.executor.time.sleep")

        backup_dir = tmp_path / "backups"
        backup_dir.mkdir(exist_ok=True)
        executor_mod.BACKUP_DIR = backup_dir

        mock_paramiko["stdout"].channel.recv_exit_status.return_value = 0
        mock_paramiko["stdout"].read.return_value = b"Saving..."
        (backup_dir / "site_a-2026-06-16.backup").write_text("dummy")

        pool, config = setup_executor
        result = execute_action(
            ssh_pool=pool, config=config,
            action_name="router.backup",
            params={},
        )
        assert result["status"] == "success"
        assert result["output"]["status"] == "ok"
        assert result["output"]["filename"] == "site_a-2026-06-16.backup"
        assert isinstance(result["output"]["size_kb"], int)

        executor_mod.BACKUP_DIR = (
            Path(__file__).parent.parent / "backups"
        )

    def test_backup_router_sftp_failure(
            self, setup_executor, mock_paramiko, tmp_path, mocker):
        """Échec SFTP download → output.status=error."""
        from core.executor import execute_action
        import core.executor as executor_mod
        from pathlib import Path

        mocker.patch("core.executor.time.sleep")

        backup_dir = tmp_path / "backups"
        backup_dir.mkdir(exist_ok=True)
        executor_mod.BACKUP_DIR = backup_dir

        mock_paramiko["stdout"].channel.recv_exit_status.return_value = 0
        mock_paramiko["stdout"].read.return_value = b"Saving..."

        # Simuler un échec SFTP download
        mock_paramiko["sftp"].get.side_effect = OSError("SFTP connection refused")

        pool, config = setup_executor
        result = execute_action(
            ssh_pool=pool, config=config,
            action_name="router.backup",
            params={},
        )
        # Handler catch l'exception → top-level success avec output.status=error
        assert result["status"] == "success"
        assert result["output"]["status"] == "error"
        assert "error" in result["output"]

        executor_mod.BACKUP_DIR = (
            Path(__file__).parent.parent / "backups"
        )


# ═════════════════════════════════════════════════════════════════════════
# execute_action() — Error conditions
# ═════════════════════════════════════════════════════════════════════════


class TestExecuteActionErrorConditions:
    """Tests d'erreurs via execute_action (chemins non testés ailleurs)."""

    def test_backup_router_ssh_command_failure(
            self, setup_executor, mock_paramiko, tmp_path, mocker):
        """Commande SSH exit_code != 0 → handler catch → output.status=error."""
        from core.executor import execute_action
        import core.executor as executor_mod
        from pathlib import Path

        mocker.patch("core.executor.time.sleep")

        backup_dir = tmp_path / "backups"
        backup_dir.mkdir(exist_ok=True)
        executor_mod.BACKUP_DIR = backup_dir

        # SSH commande exit_code != 0 → handler catch RuntimeError en interne
        mock_paramiko["stdout"].channel.recv_exit_status.return_value = 1
        mock_paramiko["stdout"].read.return_value = b"backup error"
        mock_paramiko["stderr"].read.return_value = b"disk full"

        pool, config = setup_executor
        result = execute_action(
            ssh_pool=pool, config=config,
            action_name="router.backup",
            params={},
        )
        # Handler catch l'erreur → top-level success, output.status=error
        assert result["status"] == "success"
        assert result["output"]["status"] == "error"
        assert "backup failed" in result["output"]["error"].lower()

        executor_mod.BACKUP_DIR = (
            Path(__file__).parent.parent / "backups"
        )

    def test_script_not_found_via_execute_action(
            self, setup_executor, mocker):
        """Script .rsc manquant → EXECUTION_ERROR dans execute_action."""
        from core.executor import execute_action

        # Patcher get_script_path pour simuler un script manquant
        mocker.patch("core.executor.get_script_path", return_value=None)

        pool, config = setup_executor
        result = execute_action(
            ssh_pool=pool, config=config,
            action_name="hotspot.create_user",
            params={"username": "test", "password": "secret"},
        )
        assert result["status"] == "failed"
        assert result["error"]["type"] == "EXECUTION_ERROR"

    def test_param_exceeds_max_length(
            self, setup_executor):
        """Paramètre username dépasse max_length=32 → VALIDATION_ERROR."""
        from core.executor import execute_action

        pool, config = setup_executor
        result = execute_action(
            ssh_pool=pool, config=config,
            action_name="hotspot.create_user",
            params={
                "username": "a" * 100,
                "password": "secret",
            },
        )
        assert result["status"] == "failed"
        assert result["error"]["type"] == "VALIDATION_ERROR"
        assert "username" in result["error"]["message"]

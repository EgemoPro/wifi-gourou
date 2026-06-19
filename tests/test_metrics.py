"""Tests pour workers/metrics.py — collecte lecture seule (F01-F11)

Toutes les fonctions testées ne font QUE lire des données via SSH
ou ping. Aucune écriture sur le MikroTik.
"""
import subprocess
from unittest.mock import MagicMock

import pytest

from core.utils import now_iso


# ═════════════════════════════════════════════════════════════════════════
# _parse_uptime_seconds()
# ═════════════════════════════════════════════════════════════════════════


class TestParseUptimeSeconds:
    """_parse_uptime_seconds — pure function, pas de mock nécessaire."""

    def test_full_uptime(self):
        from workers.metrics import _parse_uptime_seconds
        assert _parse_uptime_seconds("2d14h32m10s") == 2*86400 + 14*3600 + 32*60 + 10

    def test_days_only(self):
        from workers.metrics import _parse_uptime_seconds
        assert _parse_uptime_seconds("5d") == 5 * 86400

    def test_hours_minutes(self):
        from workers.metrics import _parse_uptime_seconds
        assert _parse_uptime_seconds("3h45m") == 3*3600 + 45*60

    def test_minutes_seconds(self):
        from workers.metrics import _parse_uptime_seconds
        assert _parse_uptime_seconds("30m15s") == 30*60 + 15

    def test_seconds_only(self):
        from workers.metrics import _parse_uptime_seconds
        assert _parse_uptime_seconds("45s") == 45

    def test_empty_string(self):
        from workers.metrics import _parse_uptime_seconds
        assert _parse_uptime_seconds("") == 0

    def test_invalid_format(self):
        from workers.metrics import _parse_uptime_seconds
        assert _parse_uptime_seconds("not-a-uptime") == 0


# ═════════════════════════════════════════════════════════════════════════
# F01: collect_metrics()
# ═════════════════════════════════════════════════════════════════════════


class TestCollectMetrics:
    """collect_metrics() — /system resource print + /system health print
    + /ip hotspot active print count-only + /ppp active print count-only."""

    RSC_PRINT_OUTPUT = """cpu-load: 25
free-memory: 536870912
total-memory: 1073741824
uptime: 14d3h27m12s
version: 7.14.3
board-name: CCR1036-8G-2S+
"""

    HEALTH_PRINT_OUTPUT = """temperature: 45.5
voltage: 12.0
"""

    def test_collect_metrics_full(
            self, mock_ssh_client, fake_config, mock_paramiko):
        """collect_metrics() retourne MetricsData avec toutes les valeurs."""
        from workers.metrics import collect_metrics

        # Simuler une sortie RouterOS réaliste pour chaque commande
        def mock_exec(command, timeout=30):
            mock_out = MagicMock()
            mock_err = MagicMock()
            mock_err.read.return_value = b""

            if "/system resource print" in command:
                mock_out.read.return_value = self.RSC_PRINT_OUTPUT.encode()
                mock_out.channel.recv_exit_status.return_value = 0
            elif "/system health print" in command:
                mock_out.read.return_value = self.HEALTH_PRINT_OUTPUT.encode()
                mock_out.channel.recv_exit_status.return_value = 0
            elif "hotspot" in command and "count-only" in command:
                mock_out.read.return_value = b"3"
                mock_out.channel.recv_exit_status.return_value = 0
            elif "ppp" in command and "count-only" in command:
                mock_out.read.return_value = b"2"
                mock_out.channel.recv_exit_status.return_value = 0
            else:
                mock_out.read.return_value = b""
                mock_out.channel.recv_exit_status.return_value = 0

            return (MagicMock(), mock_out, mock_err)

        mock_paramiko["client"].exec_command.side_effect = mock_exec

        metrics = collect_metrics(mock_ssh_client, fake_config)
        assert metrics is not None
        assert metrics.site_id == "site_a"
        assert metrics.cpu_load == 25.0
        assert metrics.memory_free == 536870912
        assert metrics.memory_total == 1073741824
        assert metrics.uptime == "14d3h27m12s"
        assert metrics.ros_version == "7.14.3"
        assert metrics.board_name == "CCR1036-8G-2S+"
        assert metrics.active_users == 5  # hotspot(3) + ppp(2)
        assert metrics.temperature == 45.5

    def test_collect_metrics_no_temperature(
            self, mock_ssh_client, fake_config, mock_paramiko):
        """Quand /system health print échoue, temperature=None."""
        from workers.metrics import collect_metrics

        def mock_exec(command, timeout=30):
            mock_out = MagicMock()
            mock_err = MagicMock()
            mock_err.read.return_value = b""

            if "/system resource print" in command:
                mock_out.read.return_value = self.RSC_PRINT_OUTPUT.encode()
                mock_out.channel.recv_exit_status.return_value = 0
            elif "/system health print" in command:
                raise OSError("health not supported")
            elif "hotspot" in command and "count-only" in command:
                mock_out.read.return_value = b"2"
                mock_out.channel.recv_exit_status.return_value = 0
            elif "ppp" in command and "count-only" in command:
                mock_out.read.return_value = b"1"
                mock_out.channel.recv_exit_status.return_value = 0
            else:
                mock_out.read.return_value = b""
                mock_out.channel.recv_exit_status.return_value = 0

            return (MagicMock(), mock_out, mock_err)

        mock_paramiko["client"].exec_command.side_effect = mock_exec

        metrics = collect_metrics(mock_ssh_client, fake_config)
        assert metrics is not None
        assert metrics.temperature is None
        assert metrics.active_users == 3

    def test_collect_metrics_ssh_failure(
            self, mock_ssh_client, fake_config, mock_paramiko):
        """Quand /system resource print échoue → None."""
        from workers.metrics import collect_metrics

        mock_paramiko["stdout"].channel.recv_exit_status.return_value = 1
        mock_paramiko["stderr"].read.return_value = b"timeout"

        metrics = collect_metrics(mock_ssh_client, fake_config)
        assert metrics is None

    def test_collect_metrics_exception_handled(
            self, mock_ssh_client, fake_config, mock_paramiko):
        """Exception inattendue → None (pas de crash)."""
        from workers.metrics import collect_metrics

        mock_paramiko["client"].exec_command.side_effect = \
            RuntimeError("connection lost")

        metrics = collect_metrics(mock_ssh_client, fake_config)
        assert metrics is None

    def test_collect_metrics_zero_users(
            self, mock_ssh_client, fake_config, mock_paramiko):
        """Aucun utilisateur actif → active_users=0."""
        from workers.metrics import collect_metrics

        def mock_exec(command, timeout=30):
            mock_out = MagicMock()
            mock_err = MagicMock()
            mock_err.read.return_value = b""

            if "/system resource print" in command:
                mock_out.read.return_value = self.RSC_PRINT_OUTPUT.encode()
                mock_out.channel.recv_exit_status.return_value = 0
            elif "/system health print" in command:
                mock_out.read.return_value = b"temperature: 30.0"
                mock_out.channel.recv_exit_status.return_value = 0
            elif "print count-only" in command:
                mock_out.read.return_value = b"0"
                mock_out.channel.recv_exit_status.return_value = 0
            else:
                mock_out.read.return_value = b""
                mock_out.channel.recv_exit_status.return_value = 0

            return (MagicMock(), mock_out, mock_err)

        mock_paramiko["client"].exec_command.side_effect = mock_exec

        metrics = collect_metrics(mock_ssh_client, fake_config)
        assert metrics is not None
        assert metrics.active_users == 0


# ═════════════════════════════════════════════════════════════════════════
# F02: collect_clients()
# ═════════════════════════════════════════════════════════════════════════


class TestCollectClients:
    """collect_clients() — /ip hotspot active print detail."""

    CLIENTS_OUTPUT = """user: alice
address: 10.5.0.100
mac-address: AA:BB:CC:DD:EE:01
uptime: 1h23m45s
bytes-in: 1048576
bytes-out: 524288
profile: 1M

user: bob
address: 10.5.0.101
mac-address: AA:BB:CC:DD:EE:02
uptime: 30m10s
bytes-in: 2097152
bytes-out: 1048576
profile: 2M
"""

    def test_collect_clients_returns_list(
            self, mock_ssh_client, fake_config, mock_paramiko):
        """collect_clients() retourne ClientsData avec 2 clients."""
        from workers.metrics import collect_clients

        mock_paramiko["stdout"].read.return_value = \
            self.CLIENTS_OUTPUT.encode()
        mock_paramiko["stdout"].channel.recv_exit_status.return_value = 0

        clients_data = collect_clients(mock_ssh_client, fake_config)
        assert clients_data is not None
        assert clients_data.count == 2
        assert len(clients_data.clients) == 2

        alice = clients_data.clients[0]
        assert alice.user == "alice"
        assert alice.ip == "10.5.0.100"
        assert alice.mac == "AA:BB:CC:DD:EE:01"
        assert alice.bytes_in == 1048576
        assert alice.bytes_out == 524288
        assert alice.profile == "1M"
        assert alice.client_type == "hotspot"

        bob = clients_data.clients[1]
        assert bob.user == "bob"
        assert bob.ip == "10.5.0.101"

    def test_collect_clients_no_clients(
            self, mock_ssh_client, fake_config, mock_paramiko):
        """Aucun client actif → count=0."""
        from workers.metrics import collect_clients

        mock_paramiko["stdout"].read.return_value = b""
        mock_paramiko["stdout"].channel.recv_exit_status.return_value = 0

        clients_data = collect_clients(mock_ssh_client, fake_config)
        assert clients_data is not None
        assert clients_data.count == 0
        assert clients_data.clients == []

    def test_collect_clients_ssh_failure(
            self, mock_ssh_client, fake_config, mock_paramiko):
        """Échec SSH → None."""
        from workers.metrics import collect_clients

        mock_paramiko["stdout"].channel.recv_exit_status.return_value = 1
        mock_paramiko["stderr"].read.return_value = b"error"

        clients_data = collect_clients(mock_ssh_client, fake_config)
        assert clients_data is None


# ═════════════════════════════════════════════════════════════════════════
# F04: check_bandwidth_abuse()
# ═════════════════════════════════════════════════════════════════════════


class TestCheckBandwidthAbuse:
    """check_bandwidth_abuse() — /ip hotspot active print detail."""

    BANDWIDTH_OUTPUT = """user: heavy_user
address: 10.5.0.200
bytes-in: 1073741824
bytes-out: 536870912

user: light_user
address: 10.5.0.201
bytes-in: 1048576
bytes-out: 524288
"""

    BANDWIDTH_LOW_OUTPUT = """user: normal_user
address: 10.5.0.202
bytes-in: 1048576
bytes-out: 524288
"""

    def test_suspect_detected(self, mock_ssh_client, fake_config,
                              mock_paramiko):
        """Client avec consommation > seuil → alerte SUSPECT_BW."""
        from workers.metrics import check_bandwidth_abuse

        fake_config["thresholds"]["bandwidth_suspect_mb"] = 500

        mock_paramiko["stdout"].read.return_value = \
            self.BANDWIDTH_OUTPUT.encode()
        mock_paramiko["stdout"].channel.recv_exit_status.return_value = 0

        alert = check_bandwidth_abuse(mock_ssh_client, fake_config)
        assert alert is not None
        assert alert.alert_type == "SUSPECT_BW"
        assert len(alert.data["suspects"]) == 1
        assert alert.data["suspects"][0]["user"] == "heavy_user"

    def test_no_suspect(self, mock_ssh_client, fake_config,
                        mock_paramiko):
        """Tous les clients sous le seuil → pas d'alerte."""
        from workers.metrics import check_bandwidth_abuse

        fake_config["thresholds"]["bandwidth_suspect_mb"] = 5000

        mock_paramiko["stdout"].read.return_value = \
            self.BANDWIDTH_LOW_OUTPUT.encode()
        mock_paramiko["stdout"].channel.recv_exit_status.return_value = 0

        alert = check_bandwidth_abuse(mock_ssh_client, fake_config)
        assert alert is None

    def test_empty_clients(self, mock_ssh_client, fake_config,
                           mock_paramiko):
        """Aucun client → pas d'alerte."""
        from workers.metrics import check_bandwidth_abuse

        mock_paramiko["stdout"].read.return_value = b""
        mock_paramiko["stdout"].channel.recv_exit_status.return_value = 0

        alert = check_bandwidth_abuse(mock_ssh_client, fake_config)
        assert alert is None

    def test_ssh_failure(self, mock_ssh_client, fake_config,
                         mock_paramiko):
        """Échec SSH → None."""
        from workers.metrics import check_bandwidth_abuse

        mock_paramiko["stdout"].channel.recv_exit_status.return_value = 1

        alert = check_bandwidth_abuse(mock_ssh_client, fake_config)
        assert alert is None


# ═════════════════════════════════════════════════════════════════════════
# F09: check_router_online()
# ═════════════════════════════════════════════════════════════════════════


class TestCheckRouterOnline:
    """check_router_online() — ping (subprocess)."""

    def test_router_online(self, mocker):
        """Ping réussi → pas d'alerte, offline_count=0."""
        from workers.metrics import check_router_online

        mock_run = mocker.patch("workers.metrics.subprocess.run")
        mock_run.return_value.returncode = 0

        state = {"offline_count": 2}
        alert = check_router_online(
            {"mikrotik_host": "192.168.88.1",
             "thresholds": {"offline_retries": 3}},
            state,
        )
        assert alert is None
        assert state["offline_count"] == 0
        assert "last_seen" in state

    def test_router_offline_below_threshold(self, mocker):
        """Ping échoue mais retries pas atteint → pas d'alerte."""
        from workers.metrics import check_router_online

        mock_run = mocker.patch("workers.metrics.subprocess.run")
        mock_run.return_value.returncode = 1

        state = {"offline_count": 1}
        alert = check_router_online(
            {"mikrotik_host": "192.168.88.1",
             "thresholds": {"offline_retries": 3}},
            state,
        )
        assert alert is None
        assert state["offline_count"] == 2

    def test_router_offline_alert(self, mocker):
        """Ping échoue + retries atteint → alerte ROUTER_OFFLINE."""
        from workers.metrics import check_router_online

        mock_run = mocker.patch("workers.metrics.subprocess.run")
        mock_run.return_value.returncode = 1

        state = {"offline_count": 2, "last_seen": "2026-06-16T00:00:00"}
        alert = check_router_online(
            {"mikrotik_host": "192.168.88.1",
             "thresholds": {"offline_retries": 3},
             "site_id": "site_a", "site_name": "Site Alpha"},
            state,
        )
        assert alert is not None
        assert alert.alert_type == "ROUTER_OFFLINE"
        assert "site_a" in alert.site_id
        # offline_count reset after alert
        assert state["offline_count"] == 0

    def test_router_online_first_call(self, mocker):
        """Premier appel sans state existant."""
        from workers.metrics import check_router_online

        mock_run = mocker.patch("workers.metrics.subprocess.run")
        mock_run.return_value.returncode = 1

        state: dict = {}
        alert = check_router_online(
            {"mikrotik_host": "192.168.88.1",
             "thresholds": {"offline_retries": 3}},
            state,
        )
        assert alert is None
        assert state["offline_count"] == 1

    def test_exception_handled(self, mocker):
        """subprocess.run échoue → None."""
        from workers.metrics import check_router_online

        mocker.patch("workers.metrics.subprocess.run",
                     side_effect=OSError("ping not found"))

        alert = check_router_online(
            {"mikrotik_host": "192.168.88.1",
             "thresholds": {"offline_retries": 3}},
            {},
        )
        assert alert is None


# ═════════════════════════════════════════════════════════════════════════
# F10: check_user_bloat()
# ═════════════════════════════════════════════════════════════════════════


class TestCheckUserBlot:
    """check_user_bloat() — /ip hotspot user print detail
    + /ip hotspot active print detail."""

    USERS_OUTPUT = """name: alice
disabled: no
bytes-in: 1048576

name: bob
disabled: yes
bytes-in: 0

name: charlie
disabled: no
bytes-in: 0
"""

    ACTIVE_OUTPUT = """user: alice
address: 10.5.0.100
"""

    def test_user_bloat_analysis(
            self, mock_ssh_client, fake_config, mock_paramiko):
        """Analyse correcte des utilisateurs (total, disabled, never)."""
        from workers.metrics import check_user_bloat

        def mock_exec(command, timeout=30):
            mock_out = MagicMock()
            mock_err = MagicMock()
            mock_err.read.return_value = b""

            if "hotspot user print" in command:
                mock_out.read.return_value = self.USERS_OUTPUT.encode()
            elif "hotspot active print" in command:
                mock_out.read.return_value = self.ACTIVE_OUTPUT.encode()
            else:
                mock_out.read.return_value = b""
            mock_out.channel.recv_exit_status.return_value = 0

            return (MagicMock(), mock_out, mock_err)

        mock_paramiko["client"].exec_command.side_effect = mock_exec

        result = check_user_bloat(mock_ssh_client, fake_config)
        assert result is not None
        assert result.total_users == 3
        assert result.disabled == 1  # bob
        # bob + charlie = never used (both have 0 bytes, not in active list)
        assert result.never_used == 2

    def test_user_bloat_no_users(
            self, mock_ssh_client, fake_config, mock_paramiko):
        """Aucun utilisateur → 0 partout."""
        from workers.metrics import check_user_bloat

        mock_paramiko["stdout"].read.return_value = b""
        mock_paramiko["stdout"].channel.recv_exit_status.return_value = 0

        result = check_user_bloat(mock_ssh_client, fake_config)
        assert result is not None
        assert result.total_users == 0
        assert result.disabled == 0
        assert result.never_used == 0

    def test_user_bloat_ssh_failure(
            self, mock_ssh_client, fake_config, mock_paramiko):
        """Échec SSH → None."""
        from workers.metrics import check_user_bloat

        mock_paramiko["stdout"].channel.recv_exit_status.return_value = 1

        result = check_user_bloat(mock_ssh_client, fake_config)
        assert result is None


# ═════════════════════════════════════════════════════════════════════════
# F11: check_scheduler_bloat()
# ═════════════════════════════════════════════════════════════════════════


class TestCheckSchedulerBlot:
    """check_scheduler_bloat() — /system scheduler print detail."""

    SCHEDULERS_OUTPUT = """name: daily_backup
interval: 24:00:00
run-count: 15
disabled: no

name: check_online
interval: 00:05:00
run-count: 1200
disabled: no

name: old_cleanup
interval: 01:00:00
run-count: 0
disabled: yes
"""

    def test_returns_schedulers(
            self, mock_ssh_client, fake_config, mock_paramiko):
        """Retourne SchedulerData avec la liste des schedulers."""
        from workers.metrics import check_scheduler_bloat

        mock_paramiko["stdout"].read.return_value = \
            self.SCHEDULERS_OUTPUT.encode()
        mock_paramiko["stdout"].channel.recv_exit_status.return_value = 0

        result = check_scheduler_bloat(mock_ssh_client, fake_config)
        assert result is not None
        assert result.count == 3
        assert len(result.schedulers) == 3
        assert result.schedulers[0]["name"] == "daily_backup"
        assert result.schedulers[2]["disabled"] == "yes"

    def test_alert_on_too_many_schedulers(
            self, mock_ssh_client, fake_config, mock_paramiko):
        """Nombre > threshold → alert=True."""
        from workers.metrics import check_scheduler_bloat

        fake_config["thresholds"]["max_schedulers_warning"] = 2

        mock_paramiko["stdout"].read.return_value = \
            self.SCHEDULERS_OUTPUT.encode()
        mock_paramiko["stdout"].channel.recv_exit_status.return_value = 0

        result = check_scheduler_bloat(mock_ssh_client, fake_config)
        assert result is not None
        assert result.alert is True

    def test_no_alert_when_below_threshold(
            self, mock_ssh_client, fake_config, mock_paramiko):
        """Nombre ≤ threshold → alert=False."""
        from workers.metrics import check_scheduler_bloat

        fake_config["thresholds"]["max_schedulers_warning"] = 5

        mock_paramiko["stdout"].read.return_value = \
            self.SCHEDULERS_OUTPUT.encode()
        mock_paramiko["stdout"].channel.recv_exit_status.return_value = 0

        result = check_scheduler_bloat(mock_ssh_client, fake_config)
        assert result is not None
        assert result.alert is False

    def test_no_schedulers(
            self, mock_ssh_client, fake_config, mock_paramiko):
        """Aucun scheduler → count=0."""
        from workers.metrics import check_scheduler_bloat

        mock_paramiko["stdout"].read.return_value = b""
        mock_paramiko["stdout"].channel.recv_exit_status.return_value = 0

        result = check_scheduler_bloat(mock_ssh_client, fake_config)
        assert result is not None
        assert result.count == 0

    def test_ssh_failure(
            self, mock_ssh_client, fake_config, mock_paramiko):
        """Échec SSH → None."""
        from workers.metrics import check_scheduler_bloat

        mock_paramiko["stdout"].channel.recv_exit_status.return_value = 1

        result = check_scheduler_bloat(mock_ssh_client, fake_config)
        assert result is None


# ═════════════════════════════════════════════════════════════════════════
# Vérification rapide : toutes les fonctions gèrent l'absence de SSH
# ═════════════════════════════════════════════════════════════════════════


class TestAllHandlersHandleNoSSH:
    """Les 6 fonctions de lecture retournent None silencieusement
    si SSH est indisponible (pas de crash)."""

    @pytest.mark.parametrize("func_name,config_key", [
        ("collect_metrics", None),
        ("collect_clients", None),
        ("check_bandwidth_abuse", None),
        ("check_user_bloat", None),
        ("check_scheduler_bloat", None),
    ])
    def test_all_return_none_on_ssh_failure(
            self, func_name, config_key, mock_ssh_client,
            fake_config, mock_paramiko):
        """Chaque fonction retourne None quand SSH échoue."""
        import workers.metrics as M

        mock_paramiko["client"].exec_command.side_effect = \
            RuntimeError("SSH down")
        mock_paramiko["stdout"].channel.recv_exit_status.return_value = -1

        func = getattr(M, func_name)
        result = func(mock_ssh_client, fake_config)
        assert result is None, f"{func_name} devrait retourner None"

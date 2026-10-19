"""
Tests : confirmation obligatoire des actions dangereuses + rétention des fichiers.

Volontairement indépendants des mocks SSH/paramiko : ils utilisent le VRAI
config/commands.json (une régression sur un niveau `danger` est ainsi détectée)
et des doubles minimaux écrits ici.
"""
import os
import time
from pathlib import Path

import pytest

from core import executor as ex
from core.executor import execute_action, _handler_backup_router, _cleanup_router_backups
from core.retention import purge_directory, run_retention
from core.validator import (
    ConfirmationRequired, check_confirmation, is_truthy, requires_confirmation,
)

DAY = 86400


# ═════════════════════════════════════════════════════════════════════════════
# Outils
# ═════════════════════════════════════════════════════════════════════════════

def make_file(directory: Path, name: str, age_days: float = 0, size: int = 10) -> Path:
    p = directory / name
    p.write_bytes(b"x" * size)
    t = time.time() - age_days * DAY
    os.utime(p, (t, t))
    return p


class FakePool:
    """Pool SSH factice : enregistre si on a tenté de se connecter."""
    def __init__(self):
        self.get_client_calls = 0

    def get_client(self):
        self.get_client_calls += 1
        return object()


class FakeStorage:
    def __init__(self):
        self.saved = []

    def get_command(self, command_id):
        return None

    def save_command(self, **kwargs):
        self.saved.append(kwargs)


@pytest.fixture
def runner(monkeypatch):
    """Remplace l'exécution RouterOS réelle ; renvoie la liste des appels."""
    calls = []

    def fake_run(ssh, action_def, params):
        calls.append({"script": action_def.get("script"), "params": dict(params)})
        return {"ran": True}

    monkeypatch.setattr(ex, "_execute_routeros_script", fake_run)
    return calls


CONFIG = {"site_id": "SITE_T"}


# ═════════════════════════════════════════════════════════════════════════════
# validator : fonctions pures
# ═════════════════════════════════════════════════════════════════════════════

class TestConfirmationHelpers:
    @pytest.mark.parametrize("value,expected", [
        (True, True), ("true", True), ("TRUE", True), (" yes ", True), ("1", True),
        (1, True), ("on", True),
        (False, False), ("false", False), ("0", False), ("", False), (None, False),
        (0, False), (2, False), ("oui", False), ([], False),
    ])
    def test_is_truthy(self, value, expected):
        assert is_truthy(value) is expected

    def test_default_levels_only_high(self):
        assert requires_confirmation({"danger": "high"}) is True
        assert requires_confirmation({"danger": "medium"}) is False
        assert requires_confirmation({"danger": "low"}) is False
        assert requires_confirmation({}) is False

    def test_custom_levels(self):
        assert requires_confirmation({"danger": "medium"}, ("medium", "high")) is True
        assert requires_confirmation({"danger": "high"}, ()) is False

    def test_check_raises_only_when_needed(self):
        with pytest.raises(ConfirmationRequired) as e:
            check_confirmation({"name": "profile.delete", "danger": "high"}, False)
        assert e.value.danger == "high" and "profile.delete" in str(e.value)
        check_confirmation({"name": "x", "danger": "high"}, True)       # confirmé
        check_confirmation({"name": "x", "danger": "low"}, False)       # pas dangereux


# ═════════════════════════════════════════════════════════════════════════════
# Pipeline execute_action (vrai registre)
# ═════════════════════════════════════════════════════════════════════════════

class TestConfirmationInPipeline:
    def test_real_registry_marks_expected_actions_high(self):
        from core.registry import lookup
        assert lookup("profile.delete")["danger"] == "high"
        assert lookup("router.reboot")["danger"] == "high"

    def test_high_danger_refused_without_confirm(self, runner):
        pool = FakePool()
        r = execute_action(pool, CONFIG, "profile.delete", {"profileName": "p1"})
        assert r["status"] == "failed"
        assert r["error"]["type"] == "CONFIRMATION_REQUIRED"
        assert r["error"]["danger"] == "high"
        assert runner == []                      # rien exécuté
        assert pool.get_client_calls == 0        # aucune connexion SSH tentée

    @pytest.mark.parametrize("value", [False, "false", "0", "", None, "non"])
    def test_falsy_confirm_still_refused(self, runner, value):
        r = execute_action(FakePool(), CONFIG, "profile.delete",
                           {"profileName": "p1", "confirm": value})
        assert r["error"]["type"] == "CONFIRMATION_REQUIRED"
        assert runner == []

    @pytest.mark.parametrize("value", [True, "true", "1", "yes"])
    def test_confirm_allows_execution(self, runner, value):
        r = execute_action(FakePool(), CONFIG, "profile.delete",
                           {"profileName": "p1", "confirm": value})
        assert r["status"] == "success"
        assert len(runner) == 1

    def test_confirm_not_forwarded_to_script_when_not_declared(self, runner):
        execute_action(FakePool(), CONFIG, "profile.delete",
                       {"profileName": "p1", "confirm": True})
        assert runner[0]["params"] == {"profileName": "p1"}

    def test_reboot_declares_confirm_and_is_checked_before_the_script(self, runner):
        r = execute_action(FakePool(), CONFIG, "router.reboot", {"confirm": False})
        assert r["error"]["type"] == "CONFIRMATION_REQUIRED"
        assert runner == []
        r = execute_action(FakePool(), CONFIG, "router.reboot", {"confirm": True})
        assert r["status"] == "success"
        assert runner[0]["params"] == {"confirm": True}      # déclaré : transmis au .rsc

    def test_reboot_missing_confirm_is_a_validation_error(self, runner):
        r = execute_action(FakePool(), CONFIG, "router.reboot", {})
        assert r["error"]["type"] == "VALIDATION_ERROR"

    def test_low_and_medium_not_blocked_by_default(self, runner):
        assert execute_action(FakePool(), CONFIG, "hotspot.list_active", {})["status"] == "success"
        r = execute_action(FakePool(), CONFIG, "hotspot.delete_user", {"username": "bob"})
        assert r["status"] == "success"              # medium : libre par défaut

    def test_medium_can_be_made_mandatory_by_config(self, runner):
        cfg = {**CONFIG, "confirm_danger_levels": ("medium", "high")}
        r = execute_action(FakePool(), cfg, "hotspot.delete_user", {"username": "bob"})
        assert r["error"]["type"] == "CONFIRMATION_REQUIRED"
        r = execute_action(FakePool(), cfg, "hotspot.delete_user",
                           {"username": "bob", "confirm": True})
        assert r["status"] == "success"

    def test_confirmation_can_be_disabled_by_config(self, runner):
        cfg = {**CONFIG, "confirm_danger_levels": ()}
        r = execute_action(FakePool(), cfg, "profile.delete", {"profileName": "p1"})
        assert r["status"] == "success"

    def test_preview_is_allowed_without_confirm_and_says_so(self, runner):
        r = execute_action(FakePool(), CONFIG, "profile.delete",
                           {"profileName": "p1", "mode": "preview"})
        assert r["status"] == "preview"
        assert r["output"]["requires_confirmation"] is True
        assert runner == []
        r = execute_action(FakePool(), CONFIG, "hotspot.list_active", {"mode": "preview"})
        assert r["output"]["requires_confirmation"] is False

    def test_refusal_is_not_persisted_so_command_id_dedup_does_not_replay_it(self, runner):
        store = FakeStorage()
        r1 = execute_action(FakePool(), CONFIG, "profile.delete", {"profileName": "p1"},
                            command_id="cmd-1", storage=store)
        assert r1["error"]["type"] == "CONFIRMATION_REQUIRED"
        assert store.saved == []                     # refus non enregistré
        r2 = execute_action(FakePool(), CONFIG, "profile.delete",
                            {"profileName": "p1", "confirm": True},
                            command_id="cmd-1", storage=store)
        assert r2["status"] == "success"             # même command_id, maintenant confirmé
        assert len(store.saved) == 1


# ═════════════════════════════════════════════════════════════════════════════
# retention.purge_directory
# ═════════════════════════════════════════════════════════════════════════════

class TestPurgeDirectory:
    def test_deletes_files_older_than_max_age(self, tmp_path):
        make_file(tmp_path, "old.backup", age_days=40)
        make_file(tmp_path, "new.backup", age_days=1)
        r = purge_directory(tmp_path, patterns=("*.backup",), max_age_days=30)
        assert r["deleted"] == 1 and r["kept"] == 1
        assert not (tmp_path / "old.backup").exists() and (tmp_path / "new.backup").exists()

    def test_keep_min_protects_newest_even_if_old(self, tmp_path):
        for i, age in enumerate((90, 80, 70, 60)):
            make_file(tmp_path, f"b{i}.backup", age_days=age)
        r = purge_directory(tmp_path, patterns=("*.backup",), max_age_days=30, keep_min=2)
        assert r["deleted"] == 2
        # b3 (60 j) et b2 (70 j) sont les plus récents : protégés
        assert sorted(p.name for p in tmp_path.iterdir()) == ["b2.backup", "b3.backup"]

    def test_size_cap_removes_oldest_first(self, tmp_path):
        mb = 1024 * 1024
        make_file(tmp_path, "a.backup", age_days=3, size=mb)
        make_file(tmp_path, "b.backup", age_days=2, size=mb)
        make_file(tmp_path, "c.backup", age_days=1, size=mb)
        r = purge_directory(tmp_path, patterns=("*.backup",), max_total_mb=2)
        assert r["deleted"] == 1 and r["freed_bytes"] == mb
        assert not (tmp_path / "a.backup").exists()          # le plus ancien
        assert (tmp_path / "b.backup").exists() and (tmp_path / "c.backup").exists()

    def test_size_cap_never_deletes_protected_files(self, tmp_path):
        mb = 1024 * 1024
        make_file(tmp_path, "a.backup", age_days=3, size=mb)
        make_file(tmp_path, "b.backup", age_days=1, size=mb)
        purge_directory(tmp_path, patterns=("*.backup",), max_total_mb=0.1, keep_min=1)
        assert [p.name for p in tmp_path.iterdir()] == ["b.backup"]

    def test_zero_disables_each_criterion(self, tmp_path):
        make_file(tmp_path, "old.backup", age_days=999, size=5 * 1024 * 1024)
        r = purge_directory(tmp_path, patterns=("*.backup",), max_age_days=0, max_total_mb=0)
        assert r["deleted"] == 0 and (tmp_path / "old.backup").exists()

    def test_only_matching_regular_files_are_touched(self, tmp_path):
        make_file(tmp_path, "old.pdf", age_days=99)
        make_file(tmp_path, "notes.txt", age_days=99)
        (tmp_path / "subdir.backup").mkdir()                  # dossier au nom piège
        target = make_file(tmp_path, "real.dat", age_days=99)
        link = tmp_path / "link.backup"
        link.symlink_to(target)
        r = purge_directory(tmp_path, patterns=("*.backup",), max_age_days=1)
        assert r["deleted"] == 0
        assert (tmp_path / "notes.txt").exists() and (tmp_path / "old.pdf").exists()
        assert (tmp_path / "subdir.backup").is_dir() and link.is_symlink() and target.exists()

    def test_dry_run_deletes_nothing_but_reports(self, tmp_path):
        make_file(tmp_path, "old.backup", age_days=99)
        r = purge_directory(tmp_path, patterns=("*.backup",), max_age_days=1, dry_run=True)
        assert r["deleted"] == 1 and (tmp_path / "old.backup").exists()

    def test_missing_directory_is_harmless(self, tmp_path):
        r = purge_directory(tmp_path / "absent", max_age_days=1)
        assert r["deleted"] == 0 and r["errors"] == 0

    def test_age_and_size_combined(self, tmp_path):
        mb = 1024 * 1024
        make_file(tmp_path, "ancien.backup", age_days=50, size=mb)
        make_file(tmp_path, "m1.backup", age_days=5, size=mb)
        make_file(tmp_path, "m2.backup", age_days=4, size=mb)
        make_file(tmp_path, "m3.backup", age_days=3, size=mb)
        purge_directory(tmp_path, patterns=("*.backup",), max_age_days=30, max_total_mb=2)
        assert sorted(p.name for p in tmp_path.iterdir()) == ["m2.backup", "m3.backup"]


class TestRunRetention:
    def test_applies_config_to_backups_and_vouchers(self, tmp_path):
        b, v = tmp_path / "backups", tmp_path / "vouchers"
        b.mkdir(); v.mkdir()
        make_file(b, "s-old.backup", age_days=60)
        make_file(b, "s-new.backup", age_days=1)
        make_file(v, "t-old.pdf", age_days=60)
        make_file(v, "t-new.pdf", age_days=1)
        cfg = {"retention": {"backup": {"max_age_days": 30, "max_total_mb": 0, "keep_min": 1},
                             "voucher": {"max_age_days": 30, "max_total_mb": 0, "keep_min": 0}}}
        out = run_retention(cfg, b, v)
        assert out["backups"]["deleted"] == 1 and out["vouchers"]["deleted"] == 1
        assert [p.name for p in b.iterdir()] == ["s-new.backup"]
        assert [p.name for p in v.iterdir()] == ["t-new.pdf"]

    def test_defaults_when_config_has_no_retention(self, tmp_path):
        b, v = tmp_path / "b", tmp_path / "v"
        b.mkdir(); v.mkdir()
        make_file(b, "x-1.backup", age_days=400)             # défaut keep_min=3 : protégé
        out = run_retention({}, b, v)
        assert out["backups"]["deleted"] == 0 and (b / "x-1.backup").exists()

    def test_never_raises(self, tmp_path):
        out = run_retention({"retention": {"backup": {"max_age_days": "pas-un-nombre"}}},
                            tmp_path, tmp_path)
        assert "error" in out or "backups" in out            # pas d'exception


# ═════════════════════════════════════════════════════════════════════════════
# Backup : ménage côté routeur + local
# ═════════════════════════════════════════════════════════════════════════════

class FakeSSH:
    def __init__(self, content=b"BACKUP-DATA", fail_remove=False):
        self.commands = []
        self.content = content
        self.fail_remove = fail_remove

    def execute(self, command, timeout=30):
        self.commands.append(command)
        if self.fail_remove and command.startswith("/file remove"):
            raise RuntimeError("ssh coupé")
        return {"stdout": "", "stderr": "", "exit_code": 0}

    def download_file(self, remote_path, local_path):
        Path(local_path).write_bytes(self.content)
        return Path(local_path)


@pytest.fixture
def backup_env(tmp_path, monkeypatch):
    b, v = tmp_path / "backups", tmp_path / "vouchers"
    b.mkdir(); v.mkdir()
    monkeypatch.setattr(ex, "BACKUP_DIR", b)
    monkeypatch.setattr(ex, "VOUCHER_DIR", v)
    monkeypatch.setattr(ex.time, "sleep", lambda s: None)   # le handler attend 5 s
    return b, v


def _cfg(**over):
    cfg = {"site_id": "SITE_A",
           "retention": {"backup": {"max_age_days": 30, "max_total_mb": 0, "keep_min": 1},
                         "voucher": {}, "router_keep_only_latest": True}}
    cfg.update(over)
    return cfg


class TestBackupCleanup:
    def test_removes_older_router_backups_but_keeps_todays(self, backup_env):
        ssh = FakeSSH()
        out = _handler_backup_router(ssh, _cfg(), {})
        assert out["status"] == "ok"
        remove = [c for c in ssh.commands if c.startswith("/file remove")]
        assert len(remove) == 1
        assert 'type="backup"' in remove[0] and 'name~"^site_a-"' in remove[0]
        assert f'name!="{out["filename"]}"' in remove[0]
        assert out["router_cleanup"]["status"] == "ok"

    def test_router_cleanup_runs_after_the_download(self, backup_env):
        ssh = FakeSSH()
        _handler_backup_router(ssh, _cfg(), {})
        kinds = [c.split()[0] + " " + c.split()[1] for c in ssh.commands]
        assert kinds == ["/system backup", "/file remove"]

    def test_empty_download_keeps_everything_on_the_router(self, backup_env):
        ssh = FakeSSH(content=b"")
        out = _handler_backup_router(ssh, _cfg(), {})
        assert out["status"] == "error"
        assert not [c for c in ssh.commands if c.startswith("/file remove")]

    def test_can_be_disabled(self, backup_env):
        ssh = FakeSSH()
        cfg = _cfg()
        cfg["retention"]["router_keep_only_latest"] = False
        out = _handler_backup_router(ssh, cfg, {})
        assert out["status"] == "ok" and "router_cleanup" not in out
        assert not [c for c in ssh.commands if c.startswith("/file remove")]

    def test_cleanup_failure_does_not_fail_the_backup(self, backup_env):
        out = _handler_backup_router(FakeSSH(fail_remove=True), _cfg(), {})
        assert out["status"] == "ok"
        assert out["router_cleanup"]["status"] == "error"

    def test_unsafe_site_id_skips_router_cleanup(self):
        ssh = FakeSSH()
        res = _cleanup_router_backups(ssh, 'site"; /system reset-configuration; "', "x.backup")
        assert res["status"] == "skipped" and ssh.commands == []

    def test_local_old_backups_are_purged_after_a_new_one(self, backup_env):
        b, _ = backup_env
        make_file(b, "site_a-2020-01-01.backup", age_days=400)
        out = _handler_backup_router(FakeSSH(), _cfg(), {})
        assert not (b / "site_a-2020-01-01.backup").exists()
        assert (b / out["filename"]).exists()
        assert out["local_retention"]["backups"]["deleted"] == 1

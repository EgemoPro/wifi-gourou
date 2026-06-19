"""Tests pour core/storage.py — sans MikroTik."""
import sys
import json
import uuid
from datetime import datetime, timezone, timedelta

sys.path.insert(0, ".")

from core.storage import Storage


class TestStorage:
    def setup_method(self):
        self.store = Storage(":memory:")

    def teardown_method(self):
        self.store.close()

    # ── Commands ──────────────────────────────────────────────────────────

    def test_save_and_get_command(self):
        cid = uuid.uuid4().hex[:12]
        self.store.save_command(
            command_id=cid, site_id="SITE_A", action="test.ping",
            status="success", payload={"host": "10.0.0.1"}, output="pong",
            execution_time_ms=42,
        )
        cmd = self.store.get_command(cid)
        assert cmd is not None
        assert cmd["action"] == "test.ping"
        assert cmd["status"] == "success"

    def test_get_commands_with_filters(self):
        self.store.save_command(
            command_id="a", site_id="SITE_A", action="test.a", status="success"
        )
        self.store.save_command(
            command_id="b", site_id="SITE_B", action="test.b", status="failed"
        )
        cmds = self.store.get_commands(status="failed")
        assert len(cmds) == 1
        assert cmds[0]["id"] == "b"

        cmds_a = self.store.get_commands(site_id="SITE_A")
        assert len(cmds_a) == 1

    def test_count_commands(self):
        self.store.save_command(command_id="c1", site_id="S", action="x", status="success")
        self.store.save_command(command_id="c2", site_id="S", action="x", status="failed")
        assert self.store.count_commands() == 2
        assert self.store.count_commands(status="success") == 1
        assert self.store.count_commands(status="failed") == 1

    # ── Metrics ───────────────────────────────────────────────────────────

    def test_save_and_get_latest_metrics(self):
        self.store.save_metrics("SITE_A", "system", {"cpu": 42, "mem": 60})
        self.store.save_metrics("SITE_A", "system", {"cpu": 45, "mem": 62})
        latest = self.store.get_latest_metrics("SITE_A", "system")
        assert latest is not None
        assert latest["data"]["cpu"] == 45

    def test_get_metrics_history(self):
        self.store.save_metrics("SITE_A", "system", {"cpu": 10})
        self.store.save_metrics("SITE_A", "system", {"cpu": 20})
        history = self.store.get_metrics_history("SITE_A", "system", limit=10)
        assert len(history) == 2

    def test_get_metrics_history_with_since(self):
        self.store.save_metrics("SITE_A", "system", {"cpu": 30})
        cutoff = datetime.now(timezone.utc).isoformat()
        self.store.save_metrics("SITE_A", "system", {"cpu": 40})
        history = self.store.get_metrics_history("SITE_A", "system", since=cutoff)
        assert len(history) == 1
        assert history[0]["data"]["cpu"] == 40

    # ── Events ────────────────────────────────────────────────────────────

    def test_push_and_get_events(self):
        self.store.push_event("SITE_A", "error", "Test error", {"code": 500})
        self.store.push_event("SITE_A", "info", "Test info")
        events = self.store.get_events(limit=10)
        assert len(events) == 2
        assert events[0]["event_type"] == "info"  # plus récent en premier

    def test_get_events_filter_by_type(self):
        self.store.push_event("SITE_A", "error", "Err 1")
        self.store.push_event("SITE_A", "info", "Info 1")
        self.store.push_event("SITE_B", "error", "Err 2")
        errors = self.store.get_events(event_type="error", limit=10)
        assert len(errors) == 2
        site_b = self.store.get_events(site_id="SITE_B", limit=10)
        assert len(site_b) == 1

    def test_count_events(self):
        self.store.push_event("S", "info", "Info")
        self.store.push_event("S", "error", "Err")
        self.store.push_event("S", "warning", "Warn")
        assert self.store.count_events() == 3
        assert self.store.count_events(event_type="error") == 1

    # ── Cleanup ───────────────────────────────────────────────────────────

    def test_cleanup_removes_old_commands(self):
        self.store.save_command(
            command_id="old", site_id="S", action="x", status="success",
        )
        # Forcer une date ancienne
        old_date = (datetime.now(timezone.utc) - timedelta(days=200)).isoformat()
        self.store.conn.execute(
            "UPDATE commands SET created_at=? WHERE id='old'", (old_date,)
        )
        self.store.conn.commit()
        result = self.store.cleanup()
        assert result.get("commands", 0) >= 1
        assert self.store.get_command("old") is None

    def test_stats(self):
        self.store.save_command(command_id="s1", site_id="S", action="x", status="success")
        self.store.save_metrics("S", "system", {"cpu": 50})
        self.store.push_event("S", "info", "Test")
        stats = self.store.stats()
        assert stats["commands"]["total"] >= 1
        assert stats["metrics"]["total"] >= 1
        assert stats["events"]["total"] >= 1

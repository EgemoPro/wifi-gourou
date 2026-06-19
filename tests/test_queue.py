"""Tests pour core/queue.py — sans MikroTik."""
import sys
import time
import json

sys.path.insert(0, ".")  # noqa: E402
from core.queue import Queue, MESSAGE_CONFIG


class TestQueue:
    def setup_method(self):
        self.q = Queue(":memory:")

    def teardown_method(self):
        self.q.close()

    # ── Push ──────────────────────────────────────────────────────────────

    def test_push_returns_id(self):
        msg_id = self.q.push("METRICS", {"cpu": 50})
        assert isinstance(msg_id, int)
        assert msg_id > 0

    def test_push_with_type_config(self):
        cfg = MESSAGE_CONFIG["ALERT"]
        msg_id = self.q.push("ALERT", {"level": "warning"})
        msgs = self.q.get_messages()
        m = next(m for m in msgs if m["id"] == msg_id)
        assert m["max_retries"] == cfg["max_retries"]
        assert m["priority"] == cfg["priority"]

    def test_push_overrides_defaults(self):
        msg_id = self.q.push("METRICS", {"cpu": 50}, priority=5, max_retries=2)
        msgs = self.q.get_messages()
        m = next(m for m in msgs if m["id"] == msg_id)
        assert m["priority"] == 5
        assert m["max_retries"] == 2

    # ── Flush ─────────────────────────────────────────────────────────────

    def test_flush_success(self):
        self.q.push("TEST", {"data": 1})
        self.q.push("TEST", {"data": 2})

        def send_ok(_type, _payload):
            return True

        report = self.q.flush(send_ok)
        assert report["sent"] == 2
        assert report["failed"] == 0
        assert report["status"] == "ok"

    def test_flush_failure_triggers_retry(self):
        self.q.push("TEST", {"data": 1}, max_retries=3)

        call_count = 0

        def send_fail(_type, _payload):
            nonlocal call_count
            call_count += 1
            return False

        report = self.q.flush(send_fail)
        assert report["failed"] >= 1
        # Message should be in retrying state
        msgs = self.q.get_messages(status="retrying")
        assert len(msgs) >= 1
        assert msgs[0]["retries"] == 1
        assert msgs[0]["next_retry_at"] is not None

    def test_dead_letter_via_direct_insert(self):
        """Vérifie que _mark_dead fonctionne avec une insertion directe."""
        # Insérer un message directement à max_retries-1 avec retry status
        import json
        from datetime import datetime, timezone
        self.q.conn.execute(
            """INSERT INTO durable_queue
               (msg_type, payload, priority, status, retries, max_retries,
                created_at, next_retry_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            ("TEST", json.dumps({"data": 1}), 0,
             "retrying", 2, 2,
             datetime.now(timezone.utc).isoformat(),
             "2000-01-01T00:00:00"),
        )
        self.q.conn.commit()

        def send_fail(_type, _payload):
            return False

        self.q.flush(send_fail)
        dead = self.q.get_messages(status="dead")
        assert len(dead) >= 1

    def test_flush_empty_queue(self):
        report = self.q.flush(lambda t, p: True)
        assert report["total"] == 0
        assert report["status"] == "idle"

    def test_flush_callback_exception(self):
        self.q.push("TEST", {"data": 1})

        def send_exc(_type, _payload):
            raise RuntimeError("Connection refused")

        report = self.q.flush(send_exc)
        assert report["failed"] >= 1

    # ── Stats ─────────────────────────────────────────────────────────────

    def test_stats_empty(self):
        s = self.q.stats()
        assert s["total"] == 0
        assert s["pending"] == 0

    def test_stats_counts(self):
        self.q.push("METRICS", {"cpu": 1})
        self.q.push("ALERT", {"msg": "test"}, priority=1)
        s = self.q.stats()
        assert s["total"] == 2
        assert s["pending"] == 2
        assert "METRICS" in s["by_type"]
        assert s["by_type"]["ALERT"]["pending"] == 1

    # ── Reset ─────────────────────────────────────────────────────────────

    def test_reset_retrying_to_pending(self):
        self.q.push("TEST", {"data": 1})

        def send_fail(_t, _p):
            return False

        self.q.flush(send_fail)
        reset_count = self.q.reset()
        assert reset_count > 0
        pending = self.q.get_messages(status="pending")
        assert len(pending) > 0

    # ── Cleanup ───────────────────────────────────────────────────────────

    def test_cleanup_removes_delivered(self):
        self.q.push("TEST", {"data": 1})
        self.q.flush(lambda t, p: True)

        # Forcer la date de delivery dans le passé
        self.q.conn.execute(
            "UPDATE durable_queue SET delivered_at='2000-01-01T00:00:00'"
        )
        self.q.conn.commit()

        result = self.q.cleanup()
        assert result.get("delivered", 0) > 0

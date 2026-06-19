"""
core/queue.py — File d'attente durable pour mode offline

Extension de la queue existante dans forwarder.py avec :
  - Statut par message (pending, delivered, failed, expired)
  - TTL / expiration automatique
  - Max retries configurable par type de message
  - Backoff exponentiel entre retries
  - Dead letter queue
  - Flush via callback (découplé HTTP)
  - Statistiques détaillées

Utilise queue.db (compatibilité forwarder) mais table distincte.

Usage :
  q = Queue()
  q.push("METRICS", data, priority=1)
  q.flush(send_callback)           # callback(msg_type, payload) → True/False
  stats = q.stats()
  q.cleanup()
"""
import json
import time
import logging
import sqlite3
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger("queue")

DB_PATH = Path(__file__).parent.parent / "queue.db"
LOCK = threading.Lock()

# --- Constantes par défaut ---
DEFAULT_MAX_RETRIES = 5
DEFAULT_TTL_HOURS = 48  # 48h avant expiration
FLUSH_BATCH_SIZE = 25  # Nombre max de messages par flush
RETRY_DELAYS_SECONDS = [30, 60, 120, 300, 600]  # Backoff progressif

# Types de messages avec configuration spécifique
MESSAGE_CONFIG: dict[str, dict[str, Any]] = {
    "METRICS":     {"max_retries": 5, "ttl_hours": 24, "priority": 0},
    "CLIENTS":     {"max_retries": 5, "ttl_hours": 12, "priority": 0},
    "ALERT":       {"max_retries": 10, "ttl_hours": 72, "priority": 1},
    "CMD_RESULT":  {"max_retries": 5, "ttl_hours": 48, "priority": 0},
    "BACKUP":      {"max_retries": 3, "ttl_hours": 168, "priority": 0},
    "DIAGNOSTICS": {"max_retries": 3, "ttl_hours": 24, "priority": 0},
    "REGISTER":    {"max_retries": 10, "ttl_hours": 72, "priority": 2},
}

# Valeurs par défaut si type non listé ci-dessus
DEFAULT_MSG_CONFIG = {"max_retries": 5, "ttl_hours": 48, "priority": 0}


class Queue:
    """File d'attente durable et thread-safe."""

    def __init__(self, db_path: str | Path = DB_PATH):
        self.db_path = Path(db_path)
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._init_table()

    # ── Initialisation ──────────────────────────────────────────────────────────

    def _init_table(self):
        """Crée la table durable_queue si elle n'existe pas."""
        with LOCK:
            self.conn.executescript("""
                CREATE TABLE IF NOT EXISTS durable_queue (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    msg_type    TEXT    NOT NULL,
                    payload     TEXT    NOT NULL,
                    priority    INTEGER DEFAULT 0,
                    status      TEXT    NOT NULL DEFAULT 'pending',
                    retries     INTEGER DEFAULT 0,
                    max_retries INTEGER DEFAULT 5,
                    created_at  TEXT    NOT NULL,
                    expires_at  TEXT,
                    last_error  TEXT,
                    next_retry_at TEXT,
                    delivered_at TEXT,
                    dead_letter_at TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_dq_status
                    ON durable_queue(status);
                CREATE INDEX IF NOT EXISTS idx_dq_priority
                    ON durable_queue(priority DESC, created_at ASC);
                CREATE INDEX IF NOT EXISTS idx_dq_retry
                    ON durable_queue(next_retry_at);
                CREATE INDEX IF NOT EXISTS idx_dq_expires
                    ON durable_queue(expires_at);
            """)
            self.conn.commit()

    # ── Push : ajouter un message ──────────────────────────────────────────────

    def push(
        self,
        msg_type: str,
        payload: dict[str, Any],
        priority: int | None = None,
        ttl_hours: int | None = None,
        max_retries: int | None = None,
    ) -> int:
        """
        Ajoute un message dans la file.

        Retourne l'ID du message inséré.
        Les paramètres priority/ttl_hours/max_retries surchargent la config par type.
        """
        now = datetime.now(timezone.utc)

        # Config du type de message
        cfg = MESSAGE_CONFIG.get(msg_type, DEFAULT_MSG_CONFIG)

        actual_priority = priority if priority is not None else cfg["priority"]
        actual_ttl = ttl_hours if ttl_hours is not None else cfg["ttl_hours"]
        actual_max_retries = max_retries if max_retries is not None else cfg["max_retries"]

        expires_at = (now + timedelta(hours=actual_ttl)).isoformat()

        with LOCK:
            cursor = self.conn.execute(
                """INSERT INTO durable_queue
                   (msg_type, payload, priority, status, max_retries,
                    created_at, expires_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (
                    msg_type,
                    json.dumps(payload, default=str),
                    actual_priority,
                    "pending",
                    actual_max_retries,
                    now.isoformat(),
                    expires_at,
                ),
            )
            self.conn.commit()
            msg_id = cursor.lastrowid

        logger.debug(
            f"Queue push #{msg_id} : {msg_type} "
            f"(prio={actual_priority}, ttl={actual_ttl}h, "
            f"max_retry={actual_max_retries})"
        )
        return msg_id

    # ── Flush : envoyer les messages en attente ────────────────────────────────

    def flush(
        self,
        send_fn: Callable[[str, dict[str, Any]], bool],
        max_messages: int = FLUSH_BATCH_SIZE,
    ) -> dict[str, Any]:
        """
        Tente d'envoyer tous les messages en attente (status=pending)
        via send_fn(msg_type, payload) → True si succès, False si échec.

        Les messages expired sont marqués comme tels.
        Les messages qui dépassent max_retries passent en dead letter.

        Retourne un rapport {sent, failed, expired, total, errors}.
        """
        report: dict[str, Any] = {
            "sent": 0,
            "failed": 0,
            "expired": 0,
            "dead": 0,
            "total": 0,
            "errors": [],
        }

        # 1. Expirer les messages TTL dépassés
        now = datetime.now(timezone.utc)
        with LOCK:
            expired = self.conn.execute(
                """UPDATE durable_queue SET status='expired'
                   WHERE status='pending' AND expires_at IS NOT NULL
                   AND expires_at < ?""",
                (now.isoformat(),),
            ).rowcount
            self.conn.commit()
        if expired:
            logger.info(f"Queue: {expired} message(s) expirés")
            report["expired"] = expired

        # 2. Récupérer les messages pending ou retry
        with LOCK:
            pending = self.conn.execute(
                """SELECT id, msg_type, payload, retries, max_retries, created_at
                   FROM durable_queue
                   WHERE status='pending'
                      OR (status='retrying' AND next_retry_at IS NOT NULL
                          AND next_retry_at <= ?)
                   ORDER BY priority DESC, created_at ASC
                   LIMIT ?""",
                (now.isoformat(), max_messages),
            ).fetchall()

        if not pending:
            report["total"] = 0
            report["status"] = "idle"
            return report

        report["total"] = len(pending)

        for row in pending:
            msg_id, msg_type, payload_str, retries, max_retries, created_at = row

            try:
                payload = json.loads(payload_str)
            except json.JSONDecodeError:
                payload = {"_raw": payload_str}

            # Vérifier expiration
            if self._is_expired(msg_id):
                report["expired"] += 1
                continue

            # Vérifier si le message est en dead letter (trop de retries)
            if retries >= max_retries:
                self._mark_dead(msg_id, "Max retries atteint")
                report["dead"] += 1
                continue

            # Envoyer via le callback
            error_msg = None
            try:
                success = send_fn(msg_type, payload)
            except Exception as e:
                success = False
                error_msg = str(e)[:500]
                logger.warning(f"Queue flush callback error #{msg_id}: {error_msg}")

            if success:
                self._mark_delivered(msg_id)
                report["sent"] += 1
            else:
                self._mark_retry(msg_id, error_msg or "send_fn returned False")
                report["failed"] += 1
                report["errors"].append(f"#{msg_id} ({msg_type}): retry {retries+1}/{max_retries}")

        logger.info(
            f"Queue flush: {report['sent']} envoyés, "
            f"{report['failed']} échoués, "
            f"{report['expired']} expirés, "
            f"{report['dead']} dead letter"
        )
        report["status"] = "ok" if report["sent"] > 0 else "partial"
        return report

    # ── États internes ─────────────────────────────────────────────────────────

    def _mark_delivered(self, msg_id: int) -> None:
        """Marque un message comme délivré."""
        now = datetime.now(timezone.utc).isoformat()
        with LOCK:
            self.conn.execute(
                "UPDATE durable_queue SET status='delivered', delivered_at=?, "
                "last_error=NULL, next_retry_at=NULL WHERE id=?",
                (now, msg_id),
            )
            self.conn.commit()

    def _mark_retry(self, msg_id: int, error: str) -> None:
        """Incrémente le compteur de retry et planifie la prochaine tentative."""
        with LOCK:
            row = self.conn.execute(
                "SELECT retries, max_retries FROM durable_queue WHERE id=?",
                (msg_id,),
            ).fetchone()
            if not row:
                return

            retries, max_retries = row
            new_retries = retries + 1

            if new_retries >= max_retries:
                self._mark_dead(msg_id, error)
                return

            # Backoff exponentiel
            delay_idx = min(new_retries - 1, len(RETRY_DELAYS_SECONDS) - 1)
            delay = RETRY_DELAYS_SECONDS[delay_idx]
            next_retry = (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat()

            self.conn.execute(
                """UPDATE durable_queue SET
                    status='retrying', retries=?, last_error=?, next_retry_at=?
                   WHERE id=?""",
                (new_retries, error[:500], next_retry, msg_id),
            )
            self.conn.commit()

    def _mark_dead(self, msg_id: int, reason: str) -> None:
        """Marque un message comme dead letter."""
        now = datetime.now(timezone.utc).isoformat()
        with LOCK:
            self.conn.execute(
                "UPDATE durable_queue SET status='dead', dead_letter_at=?, "
                "last_error=? WHERE id=?",
                (now, reason[:500], msg_id),
            )
            self.conn.commit()
        logger.warning(f"Queue dead letter #{msg_id}: {reason[:100]}")

    def _is_expired(self, msg_id: int) -> bool:
        """Vérifie si un message a dépassé son TTL."""
        now = datetime.now(timezone.utc).isoformat()
        with LOCK:
            row = self.conn.execute(
                "SELECT id FROM durable_queue WHERE id=? AND "
                "expires_at IS NOT NULL AND expires_at < ?",
                (msg_id, now),
            ).fetchone()
        if row:
            with LOCK:
                self.conn.execute(
                    "UPDATE durable_queue SET status='expired' WHERE id=?",
                    (msg_id,),
                )
                self.conn.commit()
            return True
        return False

    # ── Stats ──────────────────────────────────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        """Statistiques détaillées de la file."""
        with LOCK:
            total = self.conn.execute(
                "SELECT COUNT(*) FROM durable_queue"
            ).fetchone()[0]
            pending = self.conn.execute(
                "SELECT COUNT(*) FROM durable_queue WHERE status='pending'"
            ).fetchone()[0]
            retrying = self.conn.execute(
                "SELECT COUNT(*) FROM durable_queue WHERE status='retrying'"
            ).fetchone()[0]
            delivered = self.conn.execute(
                "SELECT COUNT(*) FROM durable_queue WHERE status='delivered'"
            ).fetchone()[0]
            failed = self.conn.execute(
                "SELECT COUNT(*) FROM durable_queue WHERE status='failed'"
            ).fetchone()[0]
            expired = self.conn.execute(
                "SELECT COUNT(*) FROM durable_queue WHERE status='expired'"
            ).fetchone()[0]
            dead = self.conn.execute(
                "SELECT COUNT(*) FROM durable_queue WHERE status='dead'"
            ).fetchone()[0]

            # Stats par type
            by_type = {}
            for row in self.conn.execute(
                "SELECT msg_type, status, COUNT(*) as cnt "
                "FROM durable_queue GROUP BY msg_type, status"
            ).fetchall():
                mt = row[0]
                if mt not in by_type:
                    by_type[mt] = {}
                by_type[mt][row[1]] = row[2]

            db_size = self.db_path.stat().st_size if self.db_path.is_file() else 0

        return {
            "db_size_kb": db_size // 1024,
            "total": total,
            "pending": pending,
            "retrying": retrying,
            "delivered": delivered,
            "failed": failed,
            "expired": expired,
            "dead": dead,
            "by_type": by_type,
        }

    def pending_count(self) -> int:
        """Retourne le nombre de messages en attente (rapide)."""
        with LOCK:
            return self.conn.execute(
                "SELECT COUNT(*) FROM durable_queue WHERE status IN ('pending','retrying')"
            ).fetchone()[0]

    # ── Récupération de messages pour inspection ──────────────────────────────

    def get_messages(
        self,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Récupère les messages de la file avec filtre optionnel."""
        query = "SELECT * FROM durable_queue"
        params: list[Any] = []
        if status:
            query += " WHERE status = ?"
            params.append(status)
        query += " ORDER BY priority DESC, created_at ASC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        with LOCK:
            rows = self.conn.execute(query, params).fetchall()
        return [
            {
                "id": r[0],
                "msg_type": r[1],
                "payload": json.loads(r[2]) if r[2] else {},
                "priority": r[3],
                "status": r[4],
                "retries": r[5],
                "max_retries": r[6],
                "created_at": r[7],
                "expires_at": r[8],
                "last_error": r[9],
                "next_retry_at": r[10],
                "delivered_at": r[11],
                "dead_letter_at": r[12],
            }
            for r in rows
        ]

    # ── Nettoyage ─────────────────────────────────────────────────────────────

    def cleanup(self) -> dict[str, int]:
        """
        Supprime les messages délivrés et dead de plus de 7 jours.
        Supprime les messages expirés.
        """
        now = datetime.now(timezone.utc)
        cutoff = (now - timedelta(days=7)).isoformat()
        results: dict[str, int] = {}

        with LOCK:
            # Messages delivered
            deleted = self.conn.execute(
                "DELETE FROM durable_queue WHERE status='delivered' AND delivered_at < ?",
                (cutoff,),
            ).rowcount
            results["delivered"] = deleted

            # Dead letter
            deleted = self.conn.execute(
                "DELETE FROM durable_queue WHERE status='dead' AND dead_letter_at < ?",
                (cutoff,),
            ).rowcount
            results["dead"] = deleted

            # Expired
            deleted = self.conn.execute(
                "DELETE FROM durable_queue WHERE status='expired'"
            ).rowcount
            results["expired"] = deleted

            if sum(results.values()) > 0:
                self.conn.execute("PRAGMA optimize")
                self.conn.commit()
                logger.info(
                    f"Queue cleanup: {sum(results.values())} message(s) supprimés"
                )

        return results

    # ── Reset for testing ─────────────────────────────────────────────────────

    def reset(self) -> int:
        """Remet tous les messages non-délivrés en pending."""
        with LOCK:
            count = self.conn.execute(
                "UPDATE durable_queue SET status='pending', retries=0, "
                "last_error=NULL, next_retry_at=NULL "
                "WHERE status IN ('retrying', 'dead')"
            ).rowcount
            self.conn.commit()
        if count:
            logger.info(f"Queue reset: {count} message(s) remis en pending")
        return count

    # ── Fermeture ─────────────────────────────────────────────────────────────

    def close(self):
        """Ferme la connexion SQLite."""
        try:
            self.conn.close()
            logger.debug("Queue fermée")
        except Exception as e:
            logger.warning(f"Erreur fermeture queue : {e}")

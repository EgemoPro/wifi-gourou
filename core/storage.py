"""
core/storage.py — Persistance SQLite structurée

3 tables dans un même fichier agent.db :
  commands   → Historique des actions exécutées
  metrics    → Cache local des métriques collectées
  events     → Journal d'événements (errors, warnings, info)

Usage :
  store = Storage()
  store.save_command(...)
  store.push_event("error", "SSH connection refused")
  latest = store.get_latest_metrics()
  store.close()
"""
import json
import sqlite3
import logging
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("storage")

DB_PATH = Path(__file__).parent.parent / "agent.db"
LOCK = threading.Lock()

# Rétention (jours)
COMMANDS_RETENTION_DAYS = 90
METRICS_RETENTION_DAYS = 30
EVENTS_RETENTION_DAYS = 60

# Nombre maximum de lignes par table
MAX_COMMANDS = 10_000
MAX_EVENTS = 5_000
MAX_METRICS = 50_000


class Storage:
    """Stockage local structuré — thread-safe."""

    def __init__(self, db_path: str | Path = DB_PATH):
        self.db_path = Path(db_path)
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")  # Meilleures performances écriture
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._init_tables()

    # ── Initialisation ──────────────────────────────────────────────────────────

    def _init_tables(self):
        with LOCK:
            self.conn.executescript("""
                CREATE TABLE IF NOT EXISTS commands (
                    id              TEXT PRIMARY KEY,
                    site_id         TEXT NOT NULL,
                    action          TEXT NOT NULL,
                    action_version  TEXT DEFAULT '1.0',
                    payload         TEXT,
                    status          TEXT NOT NULL DEFAULT 'pending',
                    output          TEXT,
                    execution_time_ms INTEGER,
                    error_type      TEXT,
                    error_message   TEXT,
                    created_at      TEXT NOT NULL,
                    executed_at     TEXT
                );

                CREATE TABLE IF NOT EXISTS metrics (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    site_id     TEXT NOT NULL,
                    metric_type TEXT NOT NULL,
                    data        TEXT NOT NULL,
                    created_at  TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS events (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    site_id     TEXT NOT NULL,
                    event_type  TEXT NOT NULL,
                    message     TEXT NOT NULL,
                    data        TEXT,
                    created_at  TEXT NOT NULL
                );

                -- Index pour requêtes fréquentes
                CREATE INDEX IF NOT EXISTS idx_commands_site    ON commands(site_id);
                CREATE INDEX IF NOT EXISTS idx_commands_action  ON commands(action);
                CREATE INDEX IF NOT EXISTS idx_commands_status  ON commands(status);
                CREATE INDEX IF NOT EXISTS idx_commands_created ON commands(created_at DESC);

                CREATE INDEX IF NOT EXISTS idx_metrics_site     ON metrics(site_id);
                CREATE INDEX IF NOT EXISTS idx_metrics_type     ON metrics(metric_type);
                CREATE INDEX IF NOT EXISTS idx_metrics_created  ON metrics(created_at DESC);

                CREATE INDEX IF NOT EXISTS idx_events_site      ON events(site_id);
                CREATE INDEX IF NOT EXISTS idx_events_type      ON events(event_type);
                CREATE INDEX IF NOT EXISTS idx_events_created   ON events(created_at DESC);
            """)
            self.conn.commit()

    # ── Commands (historique des actions) ─────────────────────────────────────

    def save_command(
        self,
        command_id: str,
        site_id: str,
        action: str,
        status: str,
        payload: dict | None = None,
        output: Any = None,
        execution_time_ms: int | None = None,
        error_type: str | None = None,
        error_message: str | None = None,
        action_version: str = "1.0",
    ) -> None:
        """Enregistre une action exécutée dans l'historique."""
        now = datetime.now(timezone.utc).isoformat()
        with LOCK:
            self.conn.execute(
                """INSERT OR REPLACE INTO commands
                   (id, site_id, action, action_version, payload, status,
                    output, execution_time_ms, error_type, error_message,
                    created_at, executed_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    command_id, site_id, action, action_version,
                    json.dumps(payload) if payload else None,
                    status,
                    json.dumps(output) if output and not isinstance(output, str) else (
                        str(output)[:2000] if output else None
                    ),
                    execution_time_ms,
                    error_type,
                    error_message,
                    now, now,
                ),
            )
            self.conn.commit()

    def get_commands(
        self,
        limit: int = 50,
        offset: int = 0,
        status: str | None = None,
        action: str | None = None,
        site_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Récupère l'historique des commandes avec filtres optionnels."""
        where = []
        params: list[Any] = []
        if status:
            where.append("status = ?")
            params.append(status)
        if action:
            where.append("action = ?")
            params.append(action)
        if site_id:
            where.append("site_id = ?")
            params.append(site_id)

        query = "SELECT * FROM commands"
        if where:
            query += " WHERE " + " AND ".join(where)
        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        with LOCK:
            rows = self.conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def get_command(self, command_id: str) -> dict | None:
        """Récupère une commande par son ID."""
        with LOCK:
            row = self.conn.execute(
                "SELECT * FROM commands WHERE id = ?", (command_id,)
            ).fetchone()
        return dict(row) if row else None

    def count_commands(self, status: str | None = None) -> int:
        """Compte les commandes (optionnellement par statut)."""
        if status:
            with LOCK:
                return self.conn.execute(
                    "SELECT COUNT(*) FROM commands WHERE status = ?", (status,)
                ).fetchone()[0]
        else:
            with LOCK:
                return self.conn.execute("SELECT COUNT(*) FROM commands").fetchone()[0]

    # ── Metrics (cache local) ─────────────────────────────────────────────────

    def save_metrics(self, site_id: str, metric_type: str, data: dict) -> None:
        """Stocke un snapshot de métriques."""
        now = datetime.now(timezone.utc).isoformat()
        with LOCK:
            self.conn.execute(
                "INSERT INTO metrics (site_id, metric_type, data, created_at) VALUES (?,?,?,?)",
                (site_id, metric_type, json.dumps(data, default=str), now),
            )
            self.conn.commit()

    def get_latest_metrics(
        self, site_id: str | None = None, metric_type: str | None = None
    ) -> dict | None:
        """Récupère le snapshot le plus récent."""
        where = []
        params: list[Any] = []
        if site_id:
            where.append("site_id = ?")
            params.append(site_id)
        if metric_type:
            where.append("metric_type = ?")
            params.append(metric_type)

        query = "SELECT * FROM metrics"
        if where:
            query += " WHERE " + " AND ".join(where)
        query += " ORDER BY created_at DESC LIMIT 1"

        with LOCK:
            row = self.conn.execute(query, params).fetchone()
        if not row:
            return None
        result = dict(row)
        try:
            result["data"] = json.loads(result["data"])
        except (json.JSONDecodeError, TypeError):
            pass
        return result

    def get_metrics_history(
        self,
        site_id: str,
        metric_type: str,
        limit: int = 100,
        since: str | None = None,
    ) -> list[dict[str, Any]]:
        """Récupère l'historique des métriques."""
        params: list[Any] = [site_id, metric_type]
        query = "SELECT * FROM metrics WHERE site_id = ? AND metric_type = ?"
        if since:
            query += " AND created_at >= ?"
            params.append(since)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        with LOCK:
            rows = self.conn.execute(query, params).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            try:
                d["data"] = json.loads(d["data"])
            except (json.JSONDecodeError, TypeError):
                pass
            results.append(d)
        return results

    # ── Events (journal) ──────────────────────────────────────────────────────

    def push_event(
        self,
        site_id: str,
        event_type: str,
        message: str,
        data: dict | None = None,
    ) -> None:
        """Ajoute un événement au journal."""
        now = datetime.now(timezone.utc).isoformat()
        with LOCK:
            self.conn.execute(
                "INSERT INTO events (site_id, event_type, message, data, created_at) "
                "VALUES (?,?,?,?,?)",
                (site_id, event_type, message,
                 json.dumps(data) if data else None, now),
            )
            self.conn.commit()

    def get_events(
        self,
        limit: int = 50,
        offset: int = 0,
        event_type: str | None = None,
        site_id: str | None = None,
        since: str | None = None,
    ) -> list[dict[str, Any]]:
        """Récupère les événements avec filtres optionnels."""
        where = []
        params: list[Any] = []
        if event_type:
            where.append("event_type = ?")
            params.append(event_type)
        if site_id:
            where.append("site_id = ?")
            params.append(site_id)
        if since:
            where.append("created_at >= ?")
            params.append(since)

        query = "SELECT * FROM events"
        if where:
            query += " WHERE " + " AND ".join(where)
        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        with LOCK:
            rows = self.conn.execute(query, params).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            try:
                if d.get("data"):
                    d["data"] = json.loads(d["data"])
            except (json.JSONDecodeError, TypeError):
                pass
            results.append(d)
        return results

    def count_events(self, event_type: str | None = None) -> int:
        """Compte les événements (optionnellement par type)."""
        if event_type:
            with LOCK:
                return self.conn.execute(
                    "SELECT COUNT(*) FROM events WHERE event_type = ?", (event_type,)
                ).fetchone()[0]
        else:
            with LOCK:
                return self.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]

    # ── Maintenance ───────────────────────────────────────────────────────────

    def cleanup(self) -> dict[str, int]:
        """Supprime les données de plus de N jours et vide les tables trop grandes."""
        now = datetime.now(timezone.utc)
        results: dict[str, int] = {}

        with LOCK:
            # Commands anciennes
            cutoff = (now - timedelta(days=COMMANDS_RETENTION_DAYS)).isoformat()
            deleted = self.conn.execute(
                "DELETE FROM commands WHERE created_at < ?", (cutoff,)
            ).rowcount
            if deleted:
                logger.info(f"Storage cleanup: {deleted} anciennes commandes supprimées")
            results["commands"] = deleted

            # Metrics anciennes
            cutoff = (now - timedelta(days=METRICS_RETENTION_DAYS)).isoformat()
            deleted = self.conn.execute(
                "DELETE FROM metrics WHERE created_at < ?", (cutoff,)
            ).rowcount
            if deleted:
                logger.info(f"Storage cleanup: {deleted} anciennes métriques supprimées")
            results["metrics"] = deleted

            # Events anciens
            cutoff = (now - timedelta(days=EVENTS_RETENTION_DAYS)).isoformat()
            deleted = self.conn.execute(
                "DELETE FROM events WHERE created_at < ?", (cutoff,)
            ).rowcount
            if deleted:
                logger.info(f"Storage cleanup: {deleted} anciens événements supprimés")
            results["events"] = deleted

            # Nettoyer si trop de lignes
            for table, max_rows in [
                ("commands", MAX_COMMANDS),
                ("events", MAX_EVENTS),
                ("metrics", MAX_METRICS),
            ]:
                count = self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                if count > max_rows:
                    excess = count - max_rows
                    self.conn.execute(
                        f"DELETE FROM {table} WHERE id IN "
                        f"(SELECT id FROM {table} ORDER BY created_at ASC LIMIT ?)",
                        (excess,),
                    )
                    logger.info(
                        f"Storage cleanup: {excess} lignes supprimées de {table}"
                    )

            self.conn.commit()
            self.conn.execute("PRAGMA optimize")
            self.conn.commit()

        return results

    # ── Stats ─────────────────────────────────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        """Statistiques sur le stockage local."""
        with LOCK:
            commands_total = self.conn.execute(
                "SELECT COUNT(*) FROM commands"
            ).fetchone()[0]
            commands_ok = self.conn.execute(
                "SELECT COUNT(*) FROM commands WHERE status = 'success'"
            ).fetchone()[0]
            commands_failed = self.conn.execute(
                "SELECT COUNT(*) FROM commands WHERE status = 'failed'"
            ).fetchone()[0]
            metrics_total = self.conn.execute(
                "SELECT COUNT(*) FROM metrics"
            ).fetchone()[0]
            events_total = self.conn.execute(
                "SELECT COUNT(*) FROM events"
            ).fetchone()[0]
            events_errors = self.conn.execute(
                "SELECT COUNT(*) FROM events WHERE event_type = 'error'"
            ).fetchone()[0]

            # Taille du fichier
            db_size = self.db_path.stat().st_size if self.db_path.is_file() else 0

        return {
            "db_size_kb": db_size // 1024,
            "commands": {
                "total": commands_total,
                "success": commands_ok,
                "failed": commands_failed,
            },
            "metrics": {"total": metrics_total},
            "events": {"total": events_total, "errors": events_errors},
        }

    # ── Fermeture ─────────────────────────────────────────────────────────────

    def close(self):
        """Ferme la connexion SQLite."""
        try:
            self.conn.close()
            logger.debug("Storage fermé")
        except Exception as e:
            logger.warning(f"Erreur fermeture storage : {e}")

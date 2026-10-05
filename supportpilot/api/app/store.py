"""SQLite store for local dev. In AWS, swap this class for DynamoDB/RDS with the same methods."""
import os
import sqlite3
import threading
from datetime import datetime, timezone

UPDATABLE = {"status", "category", "priority", "needs_refund", "draft_reply", "confidence"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TicketStore:
    def __init__(self, path: str | None = None) -> None:
        self._lock = threading.Lock()
        self._db = sqlite3.connect(
            path or os.getenv("DB_PATH", "supportpilot.db"), check_same_thread=False
        )
        self._db.row_factory = sqlite3.Row
        self._db.execute(
            """CREATE TABLE IF NOT EXISTS tickets (
                ticket_id TEXT PRIMARY KEY,
                customer_id TEXT NOT NULL,
                customer_email TEXT,
                subject TEXT NOT NULL,
                body TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'queued',
                category TEXT, priority TEXT, needs_refund INTEGER,
                draft_reply TEXT, confidence REAL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"""
        )
        self._db.commit()

    @staticmethod
    def _row(row: sqlite3.Row | None) -> dict | None:
        if row is None:
            return None
        d = dict(row)
        if d["needs_refund"] is not None:
            d["needs_refund"] = bool(d["needs_refund"])
        return d

    def create(self, ticket_id: str, data: dict) -> dict:
        now = _now()
        with self._lock:
            self._db.execute(
                "INSERT INTO tickets (ticket_id, customer_id, customer_email, subject, body,"
                " created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                (ticket_id, data["customer_id"], data.get("customer_email"),
                 data["subject"], data["body"], now, now),
            )
            self._db.commit()
        return self.get(ticket_id)  # type: ignore[return-value]

    def get(self, ticket_id: str) -> dict | None:
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM tickets WHERE ticket_id = ?", (ticket_id,)
            ).fetchone()
        return self._row(row)

    def update(self, ticket_id: str, fields: dict) -> dict | None:
        fields = {k: v for k, v in fields.items() if k in UPDATABLE}
        if fields:
            sets = ", ".join(f"{k} = ?" for k in fields)
            with self._lock:
                self._db.execute(
                    f"UPDATE tickets SET {sets}, updated_at = ? WHERE ticket_id = ?",
                    (*fields.values(), _now(), ticket_id),
                )
                self._db.commit()
        return self.get(ticket_id)

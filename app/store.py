from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.models import CVEventIn


UTC = timezone.utc


def utcnow() -> datetime:
    return datetime.now(UTC)


class EventStore:
    def __init__(self, db_path: str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        with self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id TEXT PRIMARY KEY,
                    vendor TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    camera_id TEXT NOT NULL,
                    camera_name TEXT NOT NULL,
                    zone_id TEXT NOT NULL,
                    timestamp_utc TEXT NOT NULL,
                    confidence REAL,
                    media_url TEXT,
                    raw_payload_json TEXT NOT NULL,
                    received_at_utc TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    reason TEXT
                );

                CREATE TABLE IF NOT EXISTS alerts (
                    id TEXT PRIMARY KEY,
                    event_id TEXT,
                    channel TEXT NOT NULL,
                    destination TEXT,
                    sent_at_utc TEXT NOT NULL,
                    status TEXT NOT NULL,
                    error TEXT,
                    message_json TEXT,
                    FOREIGN KEY(event_id) REFERENCES events(id)
                );

                CREATE TABLE IF NOT EXISTS dedupe_state (
                    dedupe_key TEXT PRIMARY KEY,
                    last_sent_at_utc TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS camera_heartbeat (
                    camera_id TEXT PRIMARY KEY,
                    last_seen_utc TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS health_alert_state (
                    camera_id TEXT PRIMARY KEY,
                    last_alert_at_utc TEXT NOT NULL
                );
                """
            )

    def save_event(self, event: CVEventIn, decision: str, reason: str | None) -> str:
        event_id = str(uuid.uuid4())
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO events (
                    id, vendor, event_type, camera_id, camera_name, zone_id,
                    timestamp_utc, confidence, media_url, raw_payload_json,
                    received_at_utc, decision, reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    event.vendor.value,
                    event.event_type.value,
                    event.camera_id,
                    event.camera_name,
                    event.zone_id,
                    event.timestamp_utc.astimezone(UTC).isoformat(),
                    event.confidence,
                    event.media_url,
                    json.dumps(event.raw_payload, ensure_ascii=True),
                    utcnow().isoformat(),
                    decision,
                    reason,
                ),
            )
        return event_id

    def update_event_decision(self, event_id: str, decision: str, reason: str | None) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE events SET decision = ?, reason = ? WHERE id = ?",
                (decision, reason, event_id),
            )

    def save_alert(
        self,
        event_id: str | None,
        channel: str,
        destination: str | None,
        status: str,
        message_payload: dict,
        error: str | None = None,
    ) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO alerts (
                    id, event_id, channel, destination, sent_at_utc,
                    status, error, message_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    event_id,
                    channel,
                    destination,
                    utcnow().isoformat(),
                    status,
                    error,
                    json.dumps(message_payload, ensure_ascii=True),
                ),
            )

    def get_last_sent_at(self, dedupe_key: str) -> datetime | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT last_sent_at_utc FROM dedupe_state WHERE dedupe_key = ?",
                (dedupe_key,),
            ).fetchone()

        if row is None:
            return None
        return datetime.fromisoformat(row["last_sent_at_utc"])

    def set_last_sent_at(self, dedupe_key: str, when: datetime) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO dedupe_state (dedupe_key, last_sent_at_utc)
                VALUES (?, ?)
                ON CONFLICT(dedupe_key)
                DO UPDATE SET last_sent_at_utc = excluded.last_sent_at_utc
                """,
                (dedupe_key, when.astimezone(UTC).isoformat()),
            )

    def upsert_camera_heartbeat(self, camera_id: str, seen_at: datetime) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO camera_heartbeat (camera_id, last_seen_utc)
                VALUES (?, ?)
                ON CONFLICT(camera_id)
                DO UPDATE SET last_seen_utc = excluded.last_seen_utc
                """,
                (camera_id, seen_at.astimezone(UTC).isoformat()),
            )

    def get_stale_cameras(self, threshold_seconds: int, now: datetime | None = None) -> list[tuple[str, datetime]]:
        now = now or utcnow()
        stale_before = now - timedelta(seconds=threshold_seconds)

        with self._lock:
            rows = self._conn.execute(
                "SELECT camera_id, last_seen_utc FROM camera_heartbeat WHERE last_seen_utc < ?",
                (stale_before.isoformat(),),
            ).fetchall()

        return [(row["camera_id"], datetime.fromisoformat(row["last_seen_utc"])) for row in rows]

    def get_last_health_alert_at(self, camera_id: str) -> datetime | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT last_alert_at_utc FROM health_alert_state WHERE camera_id = ?",
                (camera_id,),
            ).fetchone()
        if row is None:
            return None
        return datetime.fromisoformat(row["last_alert_at_utc"])

    def set_last_health_alert_at(self, camera_id: str, when: datetime) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO health_alert_state (camera_id, last_alert_at_utc)
                VALUES (?, ?)
                ON CONFLICT(camera_id)
                DO UPDATE SET last_alert_at_utc = excluded.last_alert_at_utc
                """,
                (camera_id, when.astimezone(UTC).isoformat()),
            )

    def cleanup_old_records(self, retention_days: int) -> None:
        cutoff = utcnow() - timedelta(days=retention_days)
        cutoff_iso = cutoff.isoformat()
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM alerts WHERE sent_at_utc < ?", (cutoff_iso,))
            self._conn.execute("DELETE FROM events WHERE received_at_utc < ?", (cutoff_iso,))
            self._conn.execute("DELETE FROM dedupe_state WHERE last_sent_at_utc < ?", (cutoff_iso,))

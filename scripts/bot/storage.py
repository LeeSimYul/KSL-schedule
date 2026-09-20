# -*- coding: utf-8 -*-

"""
Persistence for RSVPs, reminder subscriptions and posted message IDs.

SQLite rather than a JSON file because reminders are read and written on a one minute
loop while buttons are writing concurrently, and "who is coming to class" is not
something we want to lose to a half-written file. The whole database is a few tables and
stays comfortably small - one row per person per class.
"""

import dataclasses
import datetime
import pathlib
import sqlite3


SCHEMA = """
CREATE TABLE IF NOT EXISTS rsvps (
    occurrence_key  TEXT    NOT NULL,
    user_id         INTEGER NOT NULL,
    lane            TEXT    NOT NULL,
    event_key       TEXT    NOT NULL,
    starts_at       INTEGER NOT NULL,
    status          TEXT    NOT NULL,
    created_at      INTEGER NOT NULL,
    PRIMARY KEY (occurrence_key, user_id)
);

CREATE TABLE IF NOT EXISTS reminders (
    occurrence_key  TEXT    NOT NULL,
    user_id         INTEGER NOT NULL,
    lane            TEXT    NOT NULL,
    event_key       TEXT    NOT NULL,
    starts_at       INTEGER NOT NULL,
    lead_minutes    INTEGER NOT NULL,
    sent_at         INTEGER,
    PRIMARY KEY (occurrence_key, user_id)
);

CREATE INDEX IF NOT EXISTS reminders_pending
    ON reminders (starts_at) WHERE sent_at IS NULL;

CREATE TABLE IF NOT EXISTS schedule_messages (
    lane        TEXT    PRIMARY KEY,
    channel_id  INTEGER NOT NULL,
    message_id  INTEGER NOT NULL
);
"""


@dataclasses.dataclass(frozen=True)
class PendingReminder:
    occurrence_key: str
    user_id: int
    lane: str
    event_key: str
    starts_at: datetime.datetime


class Storage:
    """A thin, synchronous wrapper around the bot's SQLite database."""

    def __init__(self, path: pathlib.Path):
        path.parent.mkdir(parents=True, exist_ok=True)

        self.connection = sqlite3.connect(path, isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        # WAL keeps the one minute reminder sweep from blocking a button press.
        self.connection.execute("PRAGMA journal_mode = WAL")
        self.connection.executescript(SCHEMA)

    def close(self) -> None:
        self.connection.close()

    # --- RSVP -------------------------------------------------------------------------

    def set_rsvp(
        self,
        occurrence_key: str,
        user_id: int,
        lane: str,
        event_key: str,
        starts_at: datetime.datetime,
        status: str,
    ) -> None:
        self.connection.execute(
            """
            INSERT INTO rsvps (occurrence_key, user_id, lane, event_key, starts_at, status, created_at)
                 VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (occurrence_key, user_id) DO UPDATE SET status = excluded.status
            """,
            (occurrence_key, user_id, lane, event_key, int(starts_at.timestamp()), status,
             int(datetime.datetime.now(datetime.timezone.utc).timestamp())),
        )

    def clear_rsvp(self, occurrence_key: str, user_id: int) -> None:
        self.connection.execute(
            "DELETE FROM rsvps WHERE occurrence_key = ? AND user_id = ?",
            (occurrence_key, user_id),
        )

    def get_rsvp(self, occurrence_key: str, user_id: int) -> str | None:
        row = self.connection.execute(
            "SELECT status FROM rsvps WHERE occurrence_key = ? AND user_id = ?",
            (occurrence_key, user_id),
        ).fetchone()

        return row["status"] if row else None

    def count_rsvps(self, occurrence_key: str, status: str = "going") -> int:
        row = self.connection.execute(
            "SELECT COUNT(*) AS total FROM rsvps WHERE occurrence_key = ? AND status = ?",
            (occurrence_key, status),
        ).fetchone()

        return int(row["total"])

    def list_attendees(self, occurrence_key: str, status: str = "going") -> list[int]:
        rows = self.connection.execute(
            "SELECT user_id FROM rsvps WHERE occurrence_key = ? AND status = ? ORDER BY created_at",
            (occurrence_key, status),
        ).fetchall()

        return [int(row["user_id"]) for row in rows]

    # --- Reminders --------------------------------------------------------------------

    def add_reminder(
        self,
        occurrence_key: str,
        user_id: int,
        lane: str,
        event_key: str,
        starts_at: datetime.datetime,
        lead_minutes: int,
    ) -> None:
        self.connection.execute(
            """
            INSERT INTO reminders (occurrence_key, user_id, lane, event_key, starts_at, lead_minutes, sent_at)
                 VALUES (?, ?, ?, ?, ?, ?, NULL)
            ON CONFLICT (occurrence_key, user_id) DO UPDATE SET lead_minutes = excluded.lead_minutes
            """,
            (occurrence_key, user_id, lane, event_key, int(starts_at.timestamp()), lead_minutes),
        )

    def remove_reminder(self, occurrence_key: str, user_id: int) -> None:
        self.connection.execute(
            "DELETE FROM reminders WHERE occurrence_key = ? AND user_id = ?",
            (occurrence_key, user_id),
        )

    def has_reminder(self, occurrence_key: str, user_id: int) -> bool:
        row = self.connection.execute(
            "SELECT 1 FROM reminders WHERE occurrence_key = ? AND user_id = ? AND sent_at IS NULL",
            (occurrence_key, user_id),
        ).fetchone()

        return row is not None

    def due_reminders(
        self,
        now: datetime.datetime,
        grace_minutes: int,
    ) -> list[PendingReminder]:
        """
        Reminders whose lead time has arrived but whose event has not long since passed.

        The grace window is what stops a bot that was offline from carpet-bombing people
        with reminders for classes that already happened.
        """
        now_unix = int(now.timestamp())
        earliest = now_unix - (grace_minutes * 60)

        rows = self.connection.execute(
            """
            SELECT occurrence_key, user_id, lane, event_key, starts_at
              FROM reminders
             WHERE sent_at IS NULL
               AND starts_at - (lead_minutes * 60) <= ?
               AND starts_at >= ?
             ORDER BY starts_at
            """,
            (now_unix, earliest),
        ).fetchall()

        return [
            PendingReminder(
                occurrence_key=row["occurrence_key"],
                user_id=int(row["user_id"]),
                lane=row["lane"],
                event_key=row["event_key"],
                starts_at=datetime.datetime.fromtimestamp(row["starts_at"], datetime.timezone.utc),
            )
            for row in rows
        ]

    def mark_reminder_sent(self, occurrence_key: str, user_id: int, now: datetime.datetime) -> None:
        self.connection.execute(
            "UPDATE reminders SET sent_at = ? WHERE occurrence_key = ? AND user_id = ?",
            (int(now.timestamp()), occurrence_key, user_id),
        )

    def purge_expired(self, now: datetime.datetime, keep_days: int = 14) -> int:
        """Drop rows for events that finished a while ago, so the database stays small."""
        cutoff = int((now - datetime.timedelta(days=keep_days)).timestamp())

        cursor = self.connection.execute("DELETE FROM reminders WHERE starts_at < ?", (cutoff,))
        removed = cursor.rowcount or 0
        cursor = self.connection.execute("DELETE FROM rsvps WHERE starts_at < ?", (cutoff,))

        return removed + (cursor.rowcount or 0)

    # --- Posted messages ----------------------------------------------------------------

    def get_schedule_message(self, lane: str) -> tuple[int, int] | None:
        row = self.connection.execute(
            "SELECT channel_id, message_id FROM schedule_messages WHERE lane = ?",
            (lane,),
        ).fetchone()

        if row is None:
            return None

        return int(row["channel_id"]), int(row["message_id"])

    def set_schedule_message(self, lane: str, channel_id: int, message_id: int) -> None:
        self.connection.execute(
            """
            INSERT INTO schedule_messages (lane, channel_id, message_id)
                 VALUES (?, ?, ?)
            ON CONFLICT (lane) DO UPDATE SET channel_id = excluded.channel_id,
                                             message_id = excluded.message_id
            """,
            (lane, channel_id, message_id),
        )

    def forget_schedule_message(self, lane: str) -> None:
        self.connection.execute("DELETE FROM schedule_messages WHERE lane = ?", (lane,))

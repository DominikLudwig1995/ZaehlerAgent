"""History of the readings: a small SQLite database (or memory when no data directory is set)."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

SCHEMA = """
create table if not exists readings (
    id integer primary key autoincrement,
    ts real not null,
    meter text not null,
    status text not null,
    reason text not null default '',
    digits text not null default '',
    value real,
    confidence real,
    agreement real,
    cost real not null default 0,
    samples text not null default '[]',
    models text not null default '[]',
    device_reading text not null default ''
);
create index if not exists readings_meter_ts on readings (meter, ts);
"""


class History:
    def __init__(self, data_dir: str = "", keep_days: int = 30) -> None:
        if data_dir:
            Path(data_dir).mkdir(parents=True, exist_ok=True)
            path = str(Path(data_dir) / "history.db")
        else:
            path = ":memory:"
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self.keep_days = keep_days
        with self._lock:
            self._db.executescript(SCHEMA)
        self.purge()

    def add(self, meter: str, detail: dict, value: float | None, cost: float = 0.0) -> None:
        with self._lock:
            self._db.execute(
                "insert into readings (ts, meter, status, reason, digits, value, confidence, agreement, cost,"
                " samples, models, device_reading) values (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    time.time(),
                    meter,
                    detail.get("status", ""),
                    detail.get("reason", "") or detail.get("detail", ""),
                    detail.get("digits", ""),
                    value,
                    detail.get("confidence"),
                    detail.get("agreement"),
                    cost,
                    json.dumps(detail.get("samples", [])),
                    json.dumps(detail.get("models", [])),
                    detail.get("device_reading", ""),
                ),
            )
            self._db.commit()

    def recent(self, meter: str | None = None, limit: int = 50) -> list[dict]:
        sql, args = "select * from readings", []
        if meter:
            sql, args = sql + " where meter = ?", [meter]
        with self._lock:
            rows = self._db.execute(sql + " order by ts desc limit ?", [*args, limit]).fetchall()
        return [self._row(r) for r in rows]

    def series(self, meter: str, hours: int = 72) -> list[list[float]]:
        """[[timestamp, value], ...] of the values that were published, oldest first."""
        since = time.time() - hours * 3600
        with self._lock:
            rows = self._db.execute(
                "select ts, value from readings where meter = ? and ts >= ? and value is not null"
                " and status in ('accepted', 'unchanged') order by ts",
                (meter, since),
            ).fetchall()
        return [[r["ts"], r["value"]] for r in rows]

    def cost_since(self, since: float) -> float:
        with self._lock:
            row = self._db.execute(
                "select coalesce(sum(cost), 0) c from readings where ts >= ?", (since,)
            ).fetchone()
        return float(row["c"])

    def purge(self) -> None:
        with self._lock:
            self._db.execute(
                "delete from readings where ts < ?", (time.time() - self.keep_days * 86400,)
            )
            self._db.commit()

    @staticmethod
    def _row(r: sqlite3.Row) -> dict:
        d = dict(r)
        d["samples"] = json.loads(d["samples"])
        d["models"] = json.loads(d["models"])
        return d

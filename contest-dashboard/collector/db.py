"""
SQLite schema and data-access layer. WAL mode enabled for concurrent reads
during WebSocket pushes without blocking UDP writes.

All writes go through upsert/soft-delete so edits and deletes from N1MM
stay in sync with the local truth (§4 — treat ingest as upsert/delete stream).
"""

import sqlite3
import json
import logging
from contextlib import contextmanager
from typing import Optional
from pathlib import Path

from config import DB_PATH

log = logging.getLogger(__name__)


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection):
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


SCHEMA = """
CREATE TABLE IF NOT EXISTS contests (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    contest_type    TEXT NOT NULL,
    year            INTEGER NOT NULL,
    location        TEXT,
    status          TEXT NOT NULL DEFAULT 'draft'  -- draft / live / complete
        CHECK(status IN ('draft','live','complete')),
    started_at      TEXT,    -- when capture was armed (UTC ISO)
    completed_at    TEXT,    -- when capture was closed (UTC ISO)
    start_utc       TEXT,    -- scheduled contest window start
    end_utc         TEXT,    -- scheduled contest window end
    station_callsign TEXT,
    category        TEXT,
    notes           TEXT,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS contacts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    contest_id      INTEGER NOT NULL REFERENCES contests(id),
    n1mm_id         TEXT NOT NULL,
    operator        TEXT,
    call            TEXT,
    band            TEXT,
    mode            TEXT,
    rx_freq         TEXT,
    tx_freq         TEXT,
    points          INTEGER DEFAULT 0,
    station_name    TEXT,
    radio_nr        INTEGER,
    is_original     INTEGER DEFAULT 1,
    qso_utc         TEXT,
    is_mult1        INTEGER DEFAULT 0,
    is_mult2        INTEGER DEFAULT 0,
    is_mult3        INTEGER DEFAULT 0,
    is_run_qso      INTEGER,   -- NULL if packet doesn't carry it
    deleted         INTEGER NOT NULL DEFAULT 0,
    created_utc     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_utc     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    UNIQUE(contest_id, n1mm_id)
);

CREATE TABLE IF NOT EXISTS score_snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    contest_id      INTEGER NOT NULL REFERENCES contests(id),
    snapshot_utc    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    total_qsos      INTEGER,
    total_points    INTEGER,
    total_mults     INTEGER,
    score           INTEGER,
    band_breakdown  TEXT   -- JSON: {"20m": {"qsos": 42, ...}, ...}
);

CREATE TABLE IF NOT EXISTS stations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    contest_id      INTEGER NOT NULL REFERENCES contests(id),
    position_label  TEXT NOT NULL,
    station_name    TEXT NOT NULL,   -- maps to NetBiosName from packets
    UNIQUE(contest_id, station_name)
);

CREATE TABLE IF NOT EXISTS config_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    contest_id      INTEGER NOT NULL REFERENCES contests(id),
    station_id      INTEGER REFERENCES stations(id),
    effective_utc   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    rig             TEXT,
    antenna         TEXT,
    bands           TEXT,   -- comma-separated
    note            TEXT
);

CREATE TABLE IF NOT EXISTS mirror_queue (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    operation       TEXT NOT NULL,  -- upsert_contact / delete_contact / upsert_score / upsert_contest
    payload         TEXT NOT NULL,  -- JSON
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    attempts        INTEGER NOT NULL DEFAULT 0,
    last_error      TEXT
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_contacts_contest ON contacts(contest_id);
CREATE INDEX IF NOT EXISTS idx_contacts_band ON contacts(contest_id, band);
CREATE INDEX IF NOT EXISTS idx_contacts_operator ON contacts(contest_id, operator);
CREATE INDEX IF NOT EXISTS idx_contacts_time ON contacts(contest_id, qso_utc);
CREATE INDEX IF NOT EXISTS idx_contacts_station ON contacts(contest_id, station_name);
CREATE INDEX IF NOT EXISTS idx_score_contest ON score_snapshots(contest_id, snapshot_utc);
"""


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()
    log.info("Database schema initialized at %s", DB_PATH)


# ── Contests ───────────────────────────────────────────────────────────────

def get_live_contest(conn: sqlite3.Connection) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM contests WHERE status='live' LIMIT 1"
    ).fetchone()


def get_contest(conn: sqlite3.Connection, contest_id: int) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM contests WHERE id=?", (contest_id,)).fetchone()


def list_contests(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM contests ORDER BY started_at DESC"
    ).fetchall()


def create_contest(conn: sqlite3.Connection, **fields) -> int:
    cols = ", ".join(fields.keys())
    placeholders = ", ".join("?" * len(fields))
    cur = conn.execute(
        f"INSERT INTO contests ({cols}) VALUES ({placeholders})",
        list(fields.values()),
    )
    conn.commit()
    return cur.lastrowid


def set_contest_status(conn: sqlite3.Connection, contest_id: int, status: str, **extra) -> None:
    sets = ["status=?"]
    vals = [status]
    if status == "live":
        sets.append("started_at=strftime('%Y-%m-%dT%H:%M:%SZ','now')")
    elif status == "complete":
        sets.append("completed_at=strftime('%Y-%m-%dT%H:%M:%SZ','now')")
    for k, v in extra.items():
        sets.append(f"{k}=?")
        vals.append(v)
    vals.append(contest_id)
    conn.execute(f"UPDATE contests SET {', '.join(sets)} WHERE id=?", vals)
    conn.commit()


# ── Contacts ───────────────────────────────────────────────────────────────

def upsert_contact(conn: sqlite3.Connection, contest_id: int, data: dict) -> None:
    conn.execute("""
        INSERT INTO contacts
            (contest_id, n1mm_id, operator, call, band, mode, rx_freq, tx_freq,
             points, station_name, radio_nr, is_original, qso_utc,
             is_mult1, is_mult2, is_mult3, is_run_qso, deleted, updated_utc)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,strftime('%Y-%m-%dT%H:%M:%SZ','now'))
        ON CONFLICT(contest_id, n1mm_id) DO UPDATE SET
            operator=excluded.operator,
            call=excluded.call,
            band=excluded.band,
            mode=excluded.mode,
            rx_freq=excluded.rx_freq,
            tx_freq=excluded.tx_freq,
            points=excluded.points,
            station_name=excluded.station_name,
            radio_nr=excluded.radio_nr,
            is_original=excluded.is_original,
            qso_utc=excluded.qso_utc,
            is_mult1=excluded.is_mult1,
            is_mult2=excluded.is_mult2,
            is_mult3=excluded.is_mult3,
            is_run_qso=excluded.is_run_qso,
            deleted=0,
            updated_utc=strftime('%Y-%m-%dT%H:%M:%SZ','now')
    """, (
        contest_id,
        data.get("n1mm_id"),
        data.get("operator"),
        data.get("call"),
        data.get("band"),
        data.get("mode"),
        data.get("rx_freq"),
        data.get("tx_freq"),
        data.get("points", 0),
        data.get("station_name"),
        data.get("radio_nr"),
        data.get("is_original", 1),
        data.get("qso_utc"),
        data.get("is_mult1", 0),
        data.get("is_mult2", 0),
        data.get("is_mult3", 0),
        data.get("is_run_qso"),
    ))


def soft_delete_contact(conn: sqlite3.Connection, contest_id: int, n1mm_id: str) -> None:
    conn.execute("""
        UPDATE contacts SET deleted=1, updated_utc=strftime('%Y-%m-%dT%H:%M:%SZ','now')
        WHERE contest_id=? AND n1mm_id=?
    """, (contest_id, n1mm_id))


# ── Stats queries ──────────────────────────────────────────────────────────

def get_live_stats(conn: sqlite3.Connection, contest_id: int) -> dict:
    """Aggregate live stats from contacts table for dashboard."""
    base = "FROM contacts WHERE contest_id=? AND deleted=0"

    total = conn.execute(f"SELECT COUNT(*) as n {base}", (contest_id,)).fetchone()["n"]

    bands = conn.execute(f"""
        SELECT band, COUNT(*) as qsos, SUM(points) as pts
        {base} GROUP BY band ORDER BY band
    """, (contest_id,)).fetchall()

    operators = conn.execute(f"""
        SELECT operator, COUNT(*) as qsos,
               GROUP_CONCAT(DISTINCT band) as bands_active
        {base} AND operator IS NOT NULL
        GROUP BY operator ORDER BY qsos DESC
    """, (contest_id,)).fetchall()

    stations = conn.execute(f"""
        SELECT station_name, radio_nr, COUNT(*) as qsos,
               MAX(qso_utc) as last_qso,
               MAX(band) as last_band,
               MAX(mode) as last_mode
        {base} AND station_name IS NOT NULL
        GROUP BY station_name, radio_nr ORDER BY station_name, radio_nr
    """, (contest_id,)).fetchall()

    # Per-operator per-band
    op_band = conn.execute(f"""
        SELECT operator, band, COUNT(*) as qsos
        {base} AND operator IS NOT NULL
        GROUP BY operator, band
    """, (contest_id,)).fetchall()

    # Rate: QSOs in last 60 minutes and last 10 QSOs time span
    rate_1h = conn.execute(f"""
        SELECT COUNT(*) as n {base}
        AND qso_utc >= strftime('%Y-%m-%dT%H:%M:%SZ', 'now', '-1 hour')
    """, (contest_id,)).fetchone()["n"]

    recent = conn.execute(f"""
        SELECT call, operator, band, mode, qso_utc
        {base} ORDER BY qso_utc DESC LIMIT 20
    """, (contest_id,)).fetchall()

    # Mode distribution
    modes = conn.execute(f"""
        SELECT mode, COUNT(*) as qsos
        {base} AND mode IS NOT NULL AND mode != ''
        GROUP BY mode ORDER BY qsos DESC
    """, (contest_id,)).fetchall()

    # QSOs per UTC hour (last 24 hours, for rate chart)
    hourly = conn.execute(f"""
        SELECT strftime('%H', qso_utc) as hour, COUNT(*) as qsos
        {base}
        AND qso_utc >= strftime('%Y-%m-%dT%H:%M:%SZ', 'now', '-24 hours')
        GROUP BY hour ORDER BY hour
    """, (contest_id,)).fetchall()

    return {
        "total_qsos": total,
        "rate_1h":    rate_1h,
        "bands":      [dict(r) for r in bands],
        "operators":  [dict(r) for r in operators],
        "stations":   [dict(r) for r in stations],
        "op_band":    [dict(r) for r in op_band],
        "recent":     [dict(r) for r in recent],
        "modes":      [dict(r) for r in modes],
        "hourly":     [dict(r) for r in hourly],
    }


# ── Score snapshots ────────────────────────────────────────────────────────

def upsert_score_snapshot(conn: sqlite3.Connection, contest_id: int, data: dict) -> None:
    conn.execute("""
        INSERT INTO score_snapshots
            (contest_id, total_qsos, total_points, total_mults, score, band_breakdown)
        VALUES (?,?,?,?,?,?)
    """, (
        contest_id,
        data.get("total_qsos"),
        data.get("total_points"),
        data.get("total_mults"),
        data.get("score"),
        json.dumps(data.get("band_breakdown", {})),
    ))


def get_latest_score(conn: sqlite3.Connection, contest_id: int) -> Optional[sqlite3.Row]:
    return conn.execute("""
        SELECT * FROM score_snapshots WHERE contest_id=?
        ORDER BY snapshot_utc DESC LIMIT 1
    """, (contest_id,)).fetchone()


# ── Stations & config ──────────────────────────────────────────────────────

def upsert_station(conn: sqlite3.Connection, contest_id: int,
                   station_name: str, position_label: str) -> int:
    conn.execute("""
        INSERT INTO stations (contest_id, station_name, position_label)
        VALUES (?,?,?)
        ON CONFLICT(contest_id, station_name) DO UPDATE SET position_label=excluded.position_label
    """, (contest_id, station_name, position_label))
    row = conn.execute(
        "SELECT id FROM stations WHERE contest_id=? AND station_name=?",
        (contest_id, station_name)
    ).fetchone()
    return row["id"]


def add_config_event(conn: sqlite3.Connection, contest_id: int,
                     station_id: Optional[int], **fields) -> None:
    cols = ["contest_id", "station_id"] + list(fields.keys())
    vals = [contest_id, station_id] + list(fields.values())
    placeholders = ", ".join("?" * len(vals))
    conn.execute(
        f"INSERT INTO config_events ({', '.join(cols)}) VALUES ({placeholders})",
        vals,
    )


def get_station_configs(conn: sqlite3.Connection, contest_id: int) -> list[sqlite3.Row]:
    return conn.execute("""
        SELECT ce.*, s.position_label, s.station_name
        FROM config_events ce
        JOIN stations s ON s.id = ce.station_id
        WHERE ce.contest_id=? ORDER BY ce.effective_utc
    """, (contest_id,)).fetchall()


# ── Mirror queue ───────────────────────────────────────────────────────────

def enqueue_mirror(conn: sqlite3.Connection, operation: str, payload: dict) -> None:
    conn.execute(
        "INSERT INTO mirror_queue (operation, payload) VALUES (?,?)",
        (operation, json.dumps(payload)),
    )


def get_pending_mirror(conn: sqlite3.Connection, limit: int = 50) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM mirror_queue ORDER BY id LIMIT ?", (limit,)
    ).fetchall()


def ack_mirror(conn: sqlite3.Connection, row_id: int) -> None:
    conn.execute("DELETE FROM mirror_queue WHERE id=?", (row_id,))


def fail_mirror(conn: sqlite3.Connection, row_id: int, error: str) -> None:
    conn.execute("""
        UPDATE mirror_queue SET attempts=attempts+1, last_error=? WHERE id=?
    """, (error, row_id))

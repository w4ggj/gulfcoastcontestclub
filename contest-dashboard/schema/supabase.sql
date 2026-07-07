-- GCCC Contest Dashboard — Supabase (Postgres) schema
-- Mirrors the SQLite schema in collector/db.py.
-- Run this in the Supabase SQL editor once to set up the project.

-- ── Tables ─────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS contests (
    id               SERIAL PRIMARY KEY,
    name             TEXT NOT NULL,
    contest_type     TEXT NOT NULL,
    year             INTEGER NOT NULL,
    location         TEXT,
    status           TEXT NOT NULL DEFAULT 'draft'
        CHECK(status IN ('draft','live','complete')),
    started_at       TIMESTAMPTZ,
    completed_at     TIMESTAMPTZ,
    start_utc        TIMESTAMPTZ,
    end_utc          TIMESTAMPTZ,
    station_callsign TEXT,
    category         TEXT,
    notes            TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS contacts (
    id           SERIAL PRIMARY KEY,
    contest_id   INTEGER NOT NULL REFERENCES contests(id),
    n1mm_id      TEXT NOT NULL,
    operator     TEXT,
    call         TEXT,
    band         TEXT,
    mode         TEXT,
    rx_freq      TEXT,
    tx_freq      TEXT,
    points       INTEGER DEFAULT 0,
    station_name TEXT,
    radio_nr     INTEGER,
    is_original  BOOLEAN DEFAULT TRUE,
    qso_utc      TIMESTAMPTZ,
    is_mult1     BOOLEAN DEFAULT FALSE,
    is_mult2     BOOLEAN DEFAULT FALSE,
    is_mult3     BOOLEAN DEFAULT FALSE,
    is_run_qso   BOOLEAN,
    deleted      BOOLEAN NOT NULL DEFAULT FALSE,
    created_utc  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_utc  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(contest_id, n1mm_id)
);

CREATE TABLE IF NOT EXISTS score_snapshots (
    id             SERIAL PRIMARY KEY,
    contest_id     INTEGER NOT NULL REFERENCES contests(id),
    snapshot_utc   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    total_qsos     INTEGER,
    total_points   INTEGER,
    total_mults    INTEGER,
    score          INTEGER,
    band_breakdown JSONB
);

CREATE TABLE IF NOT EXISTS stations (
    id             SERIAL PRIMARY KEY,
    contest_id     INTEGER NOT NULL REFERENCES contests(id),
    position_label TEXT NOT NULL,
    station_name   TEXT NOT NULL,
    UNIQUE(contest_id, station_name)
);

CREATE TABLE IF NOT EXISTS config_events (
    id            SERIAL PRIMARY KEY,
    contest_id    INTEGER NOT NULL REFERENCES contests(id),
    station_id    INTEGER REFERENCES stations(id),
    effective_utc TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    rig           TEXT,
    antenna       TEXT,
    bands         TEXT,
    note          TEXT
);

-- ── Indexes ─────────────────────────────────────────────────────────────────

CREATE INDEX IF NOT EXISTS idx_contacts_contest  ON contacts(contest_id);
CREATE INDEX IF NOT EXISTS idx_contacts_band     ON contacts(contest_id, band);
CREATE INDEX IF NOT EXISTS idx_contacts_operator ON contacts(contest_id, operator);
CREATE INDEX IF NOT EXISTS idx_contacts_time     ON contacts(contest_id, qso_utc);
CREATE INDEX IF NOT EXISTS idx_contacts_station  ON contacts(contest_id, station_name);
CREATE INDEX IF NOT EXISTS idx_score_contest     ON score_snapshots(contest_id, snapshot_utc);

-- ── Row-Level Security ───────────────────────────────────────────────────────
-- All tables: service-role key (used by the Pi collector) bypasses RLS.
-- Authenticated users (Supabase Auth) can read everything.
-- Adjust when opening public read-only access.

ALTER TABLE contests       ENABLE ROW LEVEL SECURITY;
ALTER TABLE contacts       ENABLE ROW LEVEL SECURITY;
ALTER TABLE score_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE stations       ENABLE ROW LEVEL SECURITY;
ALTER TABLE config_events  ENABLE ROW LEVEL SECURITY;

-- Allow authenticated users to read all rows
CREATE POLICY "auth read contests"        ON contests        FOR SELECT USING (auth.role() = 'authenticated');
CREATE POLICY "auth read contacts"        ON contacts        FOR SELECT USING (auth.role() = 'authenticated');
CREATE POLICY "auth read score_snapshots" ON score_snapshots FOR SELECT USING (auth.role() = 'authenticated');
CREATE POLICY "auth read stations"        ON stations        FOR SELECT USING (auth.role() = 'authenticated');
CREATE POLICY "auth read config_events"   ON config_events   FOR SELECT USING (auth.role() = 'authenticated');

-- Service-role (used by the Pi) has superuser-equivalent access — no extra policies needed.

-- ── Realtime ─────────────────────────────────────────────────────────────────
-- Enable realtime for the tables the remote dashboard subscribes to.
-- Run in Supabase dashboard: Database → Replication → enable for these tables,
-- or use the SQL API:

ALTER PUBLICATION supabase_realtime ADD TABLE contacts;
ALTER PUBLICATION supabase_realtime ADD TABLE score_snapshots;
ALTER PUBLICATION supabase_realtime ADD TABLE contests;

#!/usr/bin/env python3
"""
Export all contacts for a contest from the DB to an ADIF file.

Usage (run on the Pi):
    python3 tools/export_adif.py --db /home/pi/gccc_contest.db \
        --contest-id 4 --output combined.adi
"""

import argparse
import sqlite3
from pathlib import Path
from datetime import datetime


BAND_TO_FREQ = {
    "160M": "1.850", "80M": "3.525", "40M": "7.050",
    "20M": "14.085", "15M": "21.085", "10M": "28.085",
    "6M": "50.310", "2M": "144.140",
}


def adif_field(tag: str, value: str) -> str:
    return f"<{tag}:{len(value)}>{value}"


def get_conn(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def export(db_path: str, contest_id: int, station_call: str, output: str):
    conn = get_conn(db_path)

    contest = conn.execute(
        "SELECT * FROM contests WHERE id=?", (contest_id,)
    ).fetchone()
    if not contest:
        raise SystemExit(f"Contest id={contest_id} not found")

    contacts = conn.execute("""
        SELECT operator, call, band, mode, qso_utc, points, rx_freq, tx_freq
        FROM contacts
        WHERE contest_id=? AND deleted=0
        ORDER BY qso_utc
    """, (contest_id,)).fetchall()

    now = datetime.utcnow().strftime("%Y%m%d %H%M%S")
    lines = []
    lines.append(f"ADIF export from GCCC Contest Dashboard")
    lines.append(f"Contest: {contest['name']} (id={contest_id})")
    lines.append(f"Station: {station_call.upper()}")
    lines.append(f"Exported: {now} UTC")
    lines.append(f"<ADIF_VER:5>3.1.4")
    lines.append(f"<PROGRAMID:21>GCCC Contest Dashboard")
    lines.append(f"<EOH>")
    lines.append("")

    qso_count = 0
    for c in contacts:
        call    = (c["call"] or "").upper().strip()
        if not call:
            continue

        band    = (c["band"] or "20M").upper()
        mode    = (c["mode"] or "RTTY").upper()
        op      = (c["operator"] or station_call).upper()
        qso_utc = c["qso_utc"] or ""

        # Frequency: prefer stored rx_freq, fall back to band default
        freq = ""
        if c["rx_freq"]:
            try:
                freq = f"{float(c['rx_freq']) / 1000:.3f}"  # Hz → MHz
            except (ValueError, TypeError):
                pass
        if not freq:
            freq = BAND_TO_FREQ.get(band, "14.085")

        # Parse UTC datetime
        try:
            dt = datetime.fromisoformat(qso_utc.replace("Z", "+00:00"))
            qso_date = dt.strftime("%Y%m%d")
            qso_time = dt.strftime("%H%M%S")
        except Exception:
            qso_date = "20260101"
            qso_time = "000000"

        # ADIF mode: RTTY → RTTY, others pass through
        adif_mode = mode
        submode = ""
        if mode in ("RTTY", "FSK"):
            adif_mode = "RTTY"
        elif mode in ("FT8", "FT4", "JS8"):
            adif_mode = "MFSK"
            submode = mode

        record_parts = [
            adif_field("CALL", call),
            adif_field("QSO_DATE", qso_date),
            adif_field("TIME_ON", qso_time),
            adif_field("BAND", band),
            adif_field("FREQ", freq),
            adif_field("MODE", adif_mode),
            adif_field("STATION_CALLSIGN", station_call.upper()),
            adif_field("OPERATOR", op),
            adif_field("CONTEST_ID", contest["name"]),
        ]
        if submode:
            record_parts.append(adif_field("SUBMODE", submode))
        if c["points"]:
            record_parts.append(adif_field("POINTS", str(c["points"])))

        record_parts.append("<EOR>")
        lines.append(" ".join(record_parts))
        qso_count += 1

    Path(output).write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"Wrote {output}")
    print(f"  Contest:  {contest['name']}")
    print(f"  Station:  {station_call.upper()}")
    print(f"  QSOs:     {qso_count}")


def main():
    parser = argparse.ArgumentParser(description="Export contest QSOs to ADIF")
    parser.add_argument("--db", default="/home/pi/gccc_contest.db",
                        help="Path to SQLite DB (default: /home/pi/gccc_contest.db)")
    parser.add_argument("--contest-id", type=int, default=4,
                        help="Contest ID (default: 4)")
    parser.add_argument("--callsign", default="W4GGJ",
                        help="Station callsign")
    parser.add_argument("--output", default="combined.adi",
                        help="Output ADIF file (default: combined.adi)")
    args = parser.parse_args()
    export(args.db, args.contest_id, args.callsign, args.output)


if __name__ == "__main__":
    main()

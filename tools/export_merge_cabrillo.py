#!/usr/bin/env python3
"""
Export all contacts for a contest from the DB and write a merged Cabrillo file.

Usage (run on the Pi):
    python3 tools/export_merge_cabrillo.py --db /home/pi/gccc_contest.db \
        --contest-id 4 --callsign W4GGJ --output combined.log

Reads contacts + imported_log_scores to build an accurate combined Cabrillo.
"""

import argparse
import sqlite3
from pathlib import Path


BAND_TO_FREQ = {
    "160M": "1800", "80M": "3500", "40M": "7000",
    "20M": "14000", "15M": "21000", "10M": "28000",
    "6M": "50000", "2M": "144000",
}


def get_conn(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def export(db_path: str, contest_id: int, callsign: str, output: str):
    conn = get_conn(db_path)

    contest = conn.execute(
        "SELECT * FROM contests WHERE id=?", (contest_id,)
    ).fetchone()
    if not contest:
        raise SystemExit(f"Contest id={contest_id} not found")

    contacts = conn.execute("""
        SELECT operator, call, band, mode, qso_utc, points
        FROM contacts
        WHERE contest_id=? AND deleted=0
        ORDER BY qso_utc
    """, (contest_id,)).fetchall()

    # Claimed scores per operator
    claimed_rows = conn.execute("""
        SELECT operator, claimed_score FROM imported_log_scores
        WHERE contest_id=?
    """, (contest_id,)).fetchall()
    claimed_map = {r["operator"].upper(): r["claimed_score"] for r in claimed_rows}

    # Also get N1MM live score for the station callsign
    score_row = conn.execute("""
        SELECT score FROM score_snapshots WHERE contest_id=?
        ORDER BY snapshot_utc DESC LIMIT 1
    """, (contest_id,)).fetchone()
    n1mm_score = score_row["score"] if score_row else 0

    operators = sorted(set(r["operator"].upper() for r in contacts if r["operator"]))
    total_claimed = sum(claimed_map.get(op, 0) for op in operators)
    if not total_claimed and n1mm_score:
        total_claimed = n1mm_score

    lines = []
    lines.append("START-OF-LOG: 3.0")
    lines.append(f"CALLSIGN: {callsign.upper()}")
    lines.append(f"CONTEST: {contest['name']}")
    lines.append(f"OPERATORS: {' '.join(operators)}")
    lines.append(f"CLAIMED-SCORE: {total_claimed}")
    lines.append(f"CREATED-BY: export_merge_cabrillo.py")
    lines.append(f"SOAPBOX: Exported from GCCC contest dashboard, contest id={contest_id}")
    lines.append("")

    qso_count = 0
    for c in contacts:
        op       = (c["operator"] or callsign).upper()
        call     = (c["call"] or "UNKNOWN").upper()
        band     = (c["band"] or "20M").upper()
        mode     = (c["mode"] or "RTTY").upper()
        qso_utc  = c["qso_utc"] or "2026-01-01T00:00:00Z"
        freq     = BAND_TO_FREQ.get(band, "14000")

        # Parse UTC to date/time fields
        try:
            date_part = qso_utc[:10]          # 2026-09-27
            time_part = qso_utc[11:16].replace(":", "")  # 1453
        except Exception:
            date_part = "2026-01-01"
            time_part = "0000"

        # Cabrillo QSO format (CQ WW RTTY):
        # QSO: freq mode date time mycall snt-rst snt-exch hiscall rcvd-rst rcvd-exch
        # We don't have exchange data in the DB so use placeholders
        line = (f"QSO: {freq:>5} {mode:<5} {date_part} {time_part} "
                f"{callsign.upper():<13} 599 00 "
                f"{call:<13} 599 00 0")
        lines.append(line)
        qso_count += 1

    lines.append("")
    lines.append("END-OF-LOG:")

    Path(output).write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"Wrote {output}")
    print(f"  Contest:       {contest['name']}")
    print(f"  Callsign:      {callsign.upper()}")
    print(f"  Operators:     {' '.join(operators)}")
    print(f"  QSOs:          {qso_count}")
    print(f"  Claimed score: {total_claimed:,}")


def main():
    parser = argparse.ArgumentParser(description="Export contest QSOs to Cabrillo")
    parser.add_argument("--db", default="/home/pi/gccc_contest.db",
                        help="Path to SQLite DB")
    parser.add_argument("--contest-id", type=int, default=4,
                        help="Contest ID (default: 4)")
    parser.add_argument("--callsign", default="W4GGJ",
                        help="Station callsign for the combined log")
    parser.add_argument("--output", default="combined.log",
                        help="Output Cabrillo file")
    args = parser.parse_args()
    export(args.db, args.contest_id, args.callsign, args.output)


if __name__ == "__main__":
    main()

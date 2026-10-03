#!/usr/bin/env python3
"""Import QSOs from an ADIF file into the contest database.

Usage:
    python3 import_adif.py W4GGJ.adi <contest_id>

If contest_id is omitted, the script prints available contests and exits.
"""

import re
import sys
import sqlite3
import hashlib
from datetime import datetime, timezone

DB_PATH = "/home/pi/gulfcoastcontestclub/gccc_contest.db"


def parse_adif(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()

    # skip header (everything before <EOH>)
    eoh = text.upper().find("<EOH>")
    if eoh >= 0:
        text = text[eoh + 5:]

    records = []
    for raw in re.split(r"<EOR>", text, flags=re.IGNORECASE):
        raw = raw.strip()
        if not raw:
            continue
        fields = {}
        for m in re.finditer(r"<([^:>]+)(?::\d+(?::[^>]*)?)?>([^<]*)", raw):
            key = m.group(1).upper()
            val = m.group(2).strip()
            fields[key] = val
        if fields:
            records.append(fields)
    return records


def band_from_freq(freq_str):
    try:
        mhz = float(freq_str)
    except (ValueError, TypeError):
        return None
    if 1.8 <= mhz < 2.0:   return "160M"
    if 3.5 <= mhz < 4.0:   return "80M"
    if 7.0 <= mhz < 7.3:   return "40M"
    if 10.1 <= mhz < 10.15: return "30M"
    if 14.0 <= mhz < 14.35: return "20M"
    if 18.068 <= mhz < 18.168: return "17M"
    if 21.0 <= mhz < 21.45: return "15M"
    if 24.89 <= mhz < 24.99: return "12M"
    if 28.0 <= mhz < 29.7:  return "10M"
    if 50.0 <= mhz < 54.0:  return "6M"
    return None


def qso_to_row(r, contest_id):
    call = r.get("CALL", "").upper().strip()
    if not call:
        return None

    date_s = r.get("QSO_DATE", "")
    time_s = r.get("TIME_ON", "")
    if len(date_s) == 8 and len(time_s) >= 6:
        try:
            qso_utc = datetime.strptime(date_s + time_s[:6], "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            qso_utc = None
    else:
        qso_utc = None

    band = r.get("BAND", "").upper() or band_from_freq(r.get("FREQ")) or ""
    mode = r.get("MODE", "").upper()
    operator = r.get("OPERATOR", r.get("STATION_CALLSIGN", "")).upper()
    rx_freq = r.get("FREQ_RX") or r.get("FREQ") or None
    tx_freq = r.get("FREQ") or None
    try:
        points = int(r.get("APP_N1MM_POINTS", 0) or 0)
    except ValueError:
        points = 0
    is_mult1 = 1 if r.get("APP_N1MM_MULT1", "0") == "1" else 0
    is_mult2 = 1 if r.get("APP_N1MM_MULT2", "0") == "1" else 0
    is_mult3 = 1 if r.get("APP_N1MM_MULT3", "0") == "1" else 0
    is_run_qso = 1 if r.get("APP_N1MM_ISRUNQSO", "0") == "1" else 0
    station_name = r.get("APP_N1MM_NETBIOSNAME", "")
    radio_nr = int(r.get("APP_N1MM_RADIO_NR", 1) or 1)
    is_original = 1 if r.get("APP_N1MM_ISORIGINAL", "True") == "True" else 0

    # use N1MM UUID if present, else generate one from key fields
    n1mm_id = r.get("APP_N1MM_ID", "")
    if not n1mm_id:
        key = f"{call}|{qso_utc}|{band}|{mode}|{operator}"
        n1mm_id = hashlib.md5(key.encode()).hexdigest()

    return {
        "n1mm_id": n1mm_id,
        "call": call,
        "band": band,
        "mode": mode,
        "operator": operator,
        "rx_freq": rx_freq,
        "tx_freq": tx_freq,
        "points": points,
        "station_name": station_name,
        "radio_nr": radio_nr,
        "is_original": is_original,
        "qso_utc": qso_utc,
        "is_mult1": is_mult1,
        "is_mult2": is_mult2,
        "is_mult3": is_mult3,
        "is_run_qso": is_run_qso,
    }


def list_contests(conn):
    rows = conn.execute("SELECT id, name, status FROM contests ORDER BY id DESC LIMIT 10").fetchall()
    print("Available contests:")
    for r in rows:
        print(f"  id={r[0]}  status={r[2]}  name={r[1]}")


def import_qsos(conn, contest_id, records):
    inserted = updated = skipped = 0
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for r in records:
        row = qso_to_row(r, contest_id)
        if not row:
            skipped += 1
            continue
        cur = conn.execute(
            "SELECT rowid FROM contacts WHERE contest_id=? AND n1mm_id=?",
            (contest_id, row["n1mm_id"])
        )
        exists = cur.fetchone()
        if exists:
            conn.execute("""
                UPDATE contacts SET
                    call=?, band=?, mode=?, operator=?, rx_freq=?, tx_freq=?,
                    points=?, station_name=?, radio_nr=?, is_original=?,
                    qso_utc=?, is_mult1=?, is_mult2=?, is_mult3=?, is_run_qso=?,
                    deleted=0, updated_utc=?
                WHERE contest_id=? AND n1mm_id=?
            """, (row["call"], row["band"], row["mode"], row["operator"],
                  row["rx_freq"], row["tx_freq"], row["points"], row["station_name"],
                  row["radio_nr"], row["is_original"], row["qso_utc"],
                  row["is_mult1"], row["is_mult2"], row["is_mult3"], row["is_run_qso"],
                  now, contest_id, row["n1mm_id"]))
            updated += 1
        else:
            conn.execute("""
                INSERT INTO contacts
                    (contest_id, n1mm_id, operator, call, band, mode,
                     rx_freq, tx_freq, points, station_name, radio_nr, is_original,
                     qso_utc, is_mult1, is_mult2, is_mult3, is_run_qso, deleted, updated_utc)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,?)
            """, (contest_id, row["n1mm_id"], row["operator"], row["call"],
                  row["band"], row["mode"], row["rx_freq"], row["tx_freq"],
                  row["points"], row["station_name"], row["radio_nr"], row["is_original"],
                  row["qso_utc"], row["is_mult1"], row["is_mult2"], row["is_mult3"],
                  row["is_run_qso"], now))
            inserted += 1

    conn.commit()
    print(f"Done: {inserted} inserted, {updated} updated, {skipped} skipped")
    total = conn.execute("SELECT COUNT(*) FROM contacts WHERE contest_id=? AND deleted=0", (contest_id,)).fetchone()[0]
    print(f"Total contacts in contest {contest_id}: {total}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    adif_path = sys.argv[1]
    conn = sqlite3.connect(DB_PATH)

    if len(sys.argv) < 3:
        list_contests(conn)
        conn.close()
        sys.exit(0)

    contest_id = int(sys.argv[2])
    row = conn.execute("SELECT id, name FROM contests WHERE id=?", (contest_id,)).fetchone()
    if not row:
        print(f"Contest id {contest_id} not found.")
        list_contests(conn)
        conn.close()
        sys.exit(1)

    print(f"Importing into contest: [{row[0]}] {row[1]}")
    records = parse_adif(adif_path)
    print(f"Parsed {len(records)} QSO records from {adif_path}")
    import_qsos(conn, contest_id, records)
    conn.close()


if __name__ == "__main__":
    main()

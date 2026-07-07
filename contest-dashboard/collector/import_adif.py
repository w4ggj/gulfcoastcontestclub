"""
import_adif.py — load an ADIF file into the contest dashboard database.

Usage:
    python import_adif.py path/to/file.adi [--contest-id N]

A live (or specified) contest must already exist. Create one in the admin UI first.
"""
import argparse
import hashlib
import re
import sys

import db


def parse_adif(text: str) -> list[dict]:
    # strip header (everything before <EOH>)
    eoh = text.upper().find("<EOH>")
    if eoh != -1:
        text = text[eoh + 5:]

    records = []
    for block in re.split(r"<EOR>", text, flags=re.IGNORECASE):
        block = block.strip()
        if not block:
            continue
        fields = {}
        for m in re.finditer(r"<(\w+)(?::\d+(?::\w)?)?>([^<]*)", block, re.IGNORECASE):
            fields[m.group(1).upper()] = m.group(2).strip()
        if fields:
            records.append(fields)
    return records


BAND_MAP = {
    "160m": "160", "80m": "80", "60m": "60", "40m": "40",
    "30m": "30", "20m": "20", "17m": "17", "15m": "15",
    "12m": "12", "10m": "10", "6m": "6", "2m": "2",
}


def normalize_band(raw: str) -> str:
    return BAND_MAP.get(raw.lower(), raw.upper())


def adif_to_contact(rec: dict, contest_id: int) -> dict | None:
    call = rec.get("CALL", "").strip()
    date = rec.get("QSO_DATE", "").strip()
    time = rec.get("TIME_ON", "").strip()
    band_raw = rec.get("BAND", "").strip()
    if not (call and date and time and band_raw):
        return None

    station = rec.get("STATION_CALLSIGN", rec.get("OPERATOR", "UNKNOWN"))
    operator = rec.get("OPERATOR", station)
    band = normalize_band(band_raw)
    mode = rec.get("MODE", "").upper()

    uid = f"{call}:{date}:{time}:{band}:{station}"
    n1mm_id = "adif:" + hashlib.md5(uid.encode()).hexdigest()[:16]

    # build ISO-ish timestamp from ADIF date+time
    ts = f"{date[:4]}-{date[4:6]}-{date[6:8]}T{time[:2]}:{time[2:4]}:{time[4:6]}Z"

    return {
        "contest_id": contest_id,
        "n1mm_id": n1mm_id,
        "callsign": call,
        "band": band,
        "mode": mode,
        "operator": operator,
        "station": station,
        "timestamp": ts,
        "rst_sent": rec.get("RST_SENT", ""),
        "rst_rcvd": rec.get("RST_RCVD", ""),
        "comment": rec.get("COMMENT", rec.get("NOTES", "")),
        "freq": rec.get("FREQ", ""),
        "tx_pwr": rec.get("TX_PWR", ""),
        "gridsquare": rec.get("GRIDSQUARE", ""),
        "raw_data": str(rec),
        "deleted": 0,
        "is_original": 1,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("adif_file")
    ap.add_argument("--contest-id", type=int, default=None)
    args = ap.parse_args()

    con = db.get_conn()

    if args.contest_id:
        row = con.execute(
            "SELECT id, name FROM contests WHERE id=?", (args.contest_id,)
        ).fetchone()
        if not row:
            print(f"Error: contest id {args.contest_id} not found.")
            sys.exit(1)
        contest_id, contest_name = row
    else:
        row = con.execute(
            "SELECT id, name FROM contests WHERE status='live' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if not row:
            print("Error: no live contest found. Create one in the admin UI or pass --contest-id.")
            sys.exit(1)
        contest_id, contest_name = row

    print(f"Importing into contest #{contest_id}: {contest_name}")

    with open(args.adif_file, encoding="utf-8", errors="replace") as f:
        text = f.read()

    records = parse_adif(text)
    print(f"Parsed {len(records)} QSO records")

    inserted = skipped = errors = 0
    for rec in records:
        contact = adif_to_contact(rec, contest_id)
        if contact is None:
            skipped += 1
            continue
        try:
            db.upsert_contact(con, contact)
            inserted += 1
        except Exception as e:
            print(f"  Error inserting {rec.get('CALL')}: {e}")
            errors += 1

    con.close()
    print(f"Done: {inserted} inserted/updated, {skipped} skipped, {errors} errors")


if __name__ == "__main__":
    main()

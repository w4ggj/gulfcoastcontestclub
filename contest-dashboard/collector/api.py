"""
FastAPI application: REST endpoints + WebSocket broadcaster.

Data-source abstraction: the frontend JavaScript checks for a `?source=local`
parameter (or defaults to local). The same static HTML is deployed both on
the Pi (reads this local API) and on Render (reads Supabase directly via JS).
This file is only the local half.
"""

import asyncio
import json
import logging
from typing import Optional

import hashlib
import re
from datetime import datetime, timezone

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, HTMLResponse
from pydantic import BaseModel

import db
import mirror
from config import DEFAULT_ROTATION_SECONDS

log = logging.getLogger(__name__)

app = FastAPI(title="GCCC Contest Dashboard", docs_url="/api/docs")

# Shared connection — set in main.py before serving
_conn = None
_ws_clients: set[WebSocket] = set()


def set_conn(conn):
    global _conn
    _conn = conn


def get_conn():
    if _conn is None:
        raise RuntimeError("DB not initialised")
    return _conn


# ── WebSocket broadcast ────────────────────────────────────────────────────

async def broadcast(event: dict) -> None:
    """Push an event to all connected dashboard WebSocket clients."""
    msg = json.dumps(event)
    dead: set[WebSocket] = set()
    for ws in _ws_clients:
        try:
            await ws.send_text(msg)
        except Exception:
            dead.add(ws)
    _ws_clients.difference_update(dead)


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    _ws_clients.add(ws)
    log.info("WS client connected (%d total)", len(_ws_clients))
    try:
        # Send current state immediately on connect
        conn = get_conn()
        contest = db.get_live_contest(conn)
        if contest:
            stats = db.get_live_stats(conn, contest["id"])
            score = db.get_latest_score(conn, contest["id"])
            await ws.send_text(json.dumps({
                "type":    "snapshot",
                "contest": dict(contest),
                "stats":   stats,
                "score":   dict(score) if score else None,
            }))
        else:
            await ws.send_text(json.dumps({"type": "no_live_contest"}))

        # Keep connection alive
        while True:
            await ws.receive_text()   # ping/pong or client messages
    except WebSocketDisconnect:
        pass
    finally:
        _ws_clients.discard(ws)
        log.info("WS client disconnected (%d total)", len(_ws_clients))


# ── REST: read endpoints ───────────────────────────────────────────────────

@app.get("/api/contests")
def list_contests():
    return [dict(r) for r in db.list_contests(get_conn())]


@app.get("/api/contests/live")
def live_contest():
    c = db.get_live_contest(get_conn())
    if c is None:
        raise HTTPException(404, "No live contest")
    conn = get_conn()
    stats = db.get_live_stats(conn, c["id"])
    score_row = db.get_latest_score(conn, c["id"])
    score = dict(score_row) if score_row else None
    if score and score.get("band_breakdown"):
        score["band_breakdown"] = json.loads(score["band_breakdown"])
    return {"contest": dict(c), "stats": stats, "score": score}


@app.get("/api/contests/{contest_id}/contacts")
def get_contest_contacts(contest_id: int):
    conn = get_conn()
    rows = conn.execute(
        "SELECT call, band, operator, mode, qso_utc FROM contacts "
        "WHERE contest_id=? AND deleted=0 ORDER BY qso_utc",
        (contest_id,)
    ).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/contests/{contest_id}")
def get_contest(contest_id: int):
    conn = get_conn()
    c = db.get_contest(conn, contest_id)
    if c is None:
        raise HTTPException(404, "Contest not found")
    stats = db.get_live_stats(conn, contest_id)
    score_row = db.get_latest_score(conn, contest_id)
    score = dict(score_row) if score_row else None
    if score and score.get("band_breakdown"):
        score["band_breakdown"] = json.loads(score["band_breakdown"])
    stations = db.get_station_configs(conn, contest_id)
    return {
        "contest":  dict(c),
        "stats":    stats,
        "score":    score,
        "stations": [dict(s) for s in stations],
    }


@app.get("/api/config")
def get_config():
    return {"rotation_seconds": DEFAULT_ROTATION_SECONDS}


# ── REST: lifecycle controls ───────────────────────────────────────────────

class ContestCreate(BaseModel):
    name: str
    contest_type: str
    year: int
    location: Optional[str] = None
    station_callsign: Optional[str] = None
    category: Optional[str] = None
    start_utc: Optional[str] = None
    end_utc: Optional[str] = None
    notes: Optional[str] = None


@app.post("/api/contests", status_code=201)
def create_contest(body: ContestCreate):
    conn = get_conn()
    cid = db.create_contest(conn, **body.model_dump(exclude_none=True))
    return {"id": cid}


@app.post("/api/contests/{contest_id}/start")
async def start_contest(contest_id: int):
    conn = get_conn()
    live = conn.execute(
        "SELECT * FROM contests WHERE status='live' LIMIT 1"
    ).fetchone()
    if live and live["id"] != contest_id:
        raise HTTPException(409, f"Contest {live['id']} is already live; complete it first")
    c = db.get_contest(conn, contest_id)
    if c is None:
        raise HTTPException(404, "Contest not found")
    if c["status"] == "complete":
        raise HTTPException(409, "Contest is already complete")
    db.set_contest_status(conn, contest_id, "live")
    await broadcast({"type": "contest_started", "contest_id": contest_id})
    return {"status": "live"}


@app.post("/api/contests/{contest_id}/complete")
async def complete_contest(contest_id: int):
    conn = get_conn()
    c = db.get_contest(conn, contest_id)
    if c is None:
        raise HTTPException(404, "Contest not found")
    db.set_contest_status(conn, contest_id, "complete")
    await broadcast({"type": "contest_completed", "contest_id": contest_id})
    # Trigger final sync reconciliation (non-blocking)
    reconcile = await mirror.drain_and_reconcile(conn)
    return {"status": "complete", "reconciliation": reconcile}


# ── REST: station config ───────────────────────────────────────────────────

class StationSetup(BaseModel):
    station_name: str    # must match NetBiosName from packets
    position_label: str
    rig: Optional[str] = None
    antenna: Optional[str] = None
    bands: Optional[str] = None
    note: Optional[str] = None


@app.post("/api/contests/{contest_id}/stations", status_code=201)
def add_station(contest_id: int, body: StationSetup):
    conn = get_conn()
    sid = db.upsert_station(conn, contest_id, body.station_name, body.position_label)
    db.add_config_event(conn, contest_id, sid,
                        rig=body.rig, antenna=body.antenna,
                        bands=body.bands, note=body.note)
    conn.commit()
    return {"station_id": sid}


# ── ADIF Import ───────────────────────────────────────────────────────────

def _parse_adif_records(text: str):
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
            fields[m.group(1).upper()] = m.group(2).strip()
        if fields:
            records.append(fields)
    return records


def _band_from_freq(freq_str):
    try:
        mhz = float(freq_str)
    except (ValueError, TypeError):
        return None
    if 1.8 <= mhz < 2.0:        return "160M"
    if 3.5 <= mhz < 4.0:        return "80M"
    if 7.0 <= mhz < 7.3:        return "40M"
    if 10.1 <= mhz < 10.15:     return "30M"
    if 14.0 <= mhz < 14.35:     return "20M"
    if 18.068 <= mhz < 18.168:  return "17M"
    if 21.0 <= mhz < 21.45:     return "15M"
    if 24.89 <= mhz < 24.99:    return "12M"
    if 28.0 <= mhz < 29.7:      return "10M"
    if 50.0 <= mhz < 54.0:      return "6M"
    return None


def _adif_record_to_row(r):
    call = r.get("CALL", "").upper().strip()
    if not call:
        return None
    date_s = r.get("QSO_DATE", "")
    time_s = r.get("TIME_ON", "")
    qso_utc = None
    if len(date_s) == 8 and len(time_s) >= 6:
        try:
            qso_utc = datetime.strptime(date_s + time_s[:6], "%Y%m%d%H%M%S").replace(
                tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            pass
    band = r.get("BAND", "").upper() or _band_from_freq(r.get("FREQ")) or ""
    mode = r.get("MODE", "").upper()
    operator = r.get("OPERATOR", r.get("STATION_CALLSIGN", "")).upper()
    rx_freq = r.get("FREQ_RX") or r.get("FREQ")
    tx_freq = r.get("FREQ")
    try:
        points = int(r.get("APP_N1MM_POINTS", 0) or 0)
    except ValueError:
        points = 0
    is_mult1 = 1 if r.get("APP_N1MM_MULT1") == "1" else 0
    is_mult2 = 1 if r.get("APP_N1MM_MULT2") == "1" else 0
    is_mult3 = 1 if r.get("APP_N1MM_MULT3") == "1" else 0
    is_run_qso = 1 if r.get("APP_N1MM_ISRUNQSO") == "1" else 0
    station_name = r.get("APP_N1MM_NETBIOSNAME", "")
    try:
        radio_nr = int(r.get("APP_N1MM_RADIO_NR", 1) or 1)
    except ValueError:
        radio_nr = 1
    is_original = 1 if r.get("APP_N1MM_ISORIGINAL", "True") == "True" else 0
    n1mm_id = r.get("APP_N1MM_ID") or hashlib.md5(
        f"{call}|{qso_utc}|{band}|{mode}|{operator}".encode()).hexdigest()
    return dict(n1mm_id=n1mm_id, call=call, band=band, mode=mode,
                operator=operator, rx_freq=rx_freq, tx_freq=tx_freq,
                points=points, station_name=station_name, radio_nr=radio_nr,
                is_original=is_original, qso_utc=qso_utc,
                is_mult1=is_mult1, is_mult2=is_mult2, is_mult3=is_mult3,
                is_run_qso=is_run_qso)


@app.post("/api/contests/{contest_id}/import_adif")
async def import_adif(contest_id: int, file: UploadFile = File(...)):
    conn = get_conn()
    contest = conn.execute("SELECT id, name FROM contests WHERE id=?", (contest_id,)).fetchone()
    if not contest:
        raise HTTPException(status_code=404, detail="Contest not found")
    content = await file.read()
    text = content.decode("utf-8", errors="replace")
    records = _parse_adif_records(text)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    inserted = updated = skipped = 0
    for r in records:
        row = _adif_record_to_row(r)
        if not row:
            skipped += 1
            continue
        exists = conn.execute(
            "SELECT rowid FROM contacts WHERE contest_id=? AND n1mm_id=?",
            (contest_id, row["n1mm_id"])
        ).fetchone()
        if exists:
            conn.execute("""
                UPDATE contacts SET call=?,band=?,mode=?,operator=?,rx_freq=?,tx_freq=?,
                points=?,station_name=?,radio_nr=?,is_original=?,qso_utc=?,
                is_mult1=?,is_mult2=?,is_mult3=?,is_run_qso=?,deleted=0,updated_utc=?
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
                    (contest_id,n1mm_id,operator,call,band,mode,rx_freq,tx_freq,
                     points,station_name,radio_nr,is_original,qso_utc,
                     is_mult1,is_mult2,is_mult3,is_run_qso,deleted,updated_utc)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,?)
            """, (contest_id, row["n1mm_id"], row["operator"], row["call"],
                  row["band"], row["mode"], row["rx_freq"], row["tx_freq"],
                  row["points"], row["station_name"], row["radio_nr"], row["is_original"],
                  row["qso_utc"], row["is_mult1"], row["is_mult2"], row["is_mult3"],
                  row["is_run_qso"], now))
            inserted += 1
    conn.commit()
    total = conn.execute(
        "SELECT COUNT(*) FROM contacts WHERE contest_id=? AND deleted=0", (contest_id,)
    ).fetchone()[0]
    await broadcast({"type": "reload_stats", "contest_id": contest_id})
    return {"inserted": inserted, "updated": updated, "skipped": skipped, "total": total}


@app.get("/api/contests/{contest_id}/import_adif", response_class=HTMLResponse)
def import_adif_form(contest_id: int):
    conn = get_conn()
    contest = conn.execute("SELECT id, name FROM contests WHERE id=?", (contest_id,)).fetchone()
    if not contest:
        raise HTTPException(status_code=404, detail="Contest not found")
    name = contest[1]
    return f"""<!doctype html><html><head><meta charset=utf-8>
<title>Import ADIF – {name}</title>
<style>body{{font-family:sans-serif;max-width:480px;margin:60px auto;padding:0 1rem}}
h2{{margin-bottom:0.3em}}p{{color:#555;font-size:.9em}}
input[type=file]{{display:block;margin:1rem 0}}
button{{padding:.5rem 1.4rem;font-size:1rem;cursor:pointer}}
#result{{margin-top:1rem;padding:.8rem;border-radius:4px;display:none}}
.ok{{background:#d4edda;color:#155724}}.err{{background:#f8d7da;color:#721c24}}</style>
</head><body>
<h2>Import ADIF into contest</h2>
<p><strong>{name}</strong></p>
<p>Select your <code>.adi</code> or <code>.adif</code> file exported from N1MM.</p>
<form id=f>
  <input type=file id=file accept=".adi,.adif" required>
  <button type=submit>Upload &amp; Import</button>
</form>
<div id=result></div>
<script>
document.getElementById('f').onsubmit=async e=>{{
  e.preventDefault();
  const fd=new FormData();fd.append('file',document.getElementById('file').files[0]);
  const r=document.getElementById('result');r.style.display='block';
  r.className='';r.textContent='Importing…';
  try{{
    const res=await fetch('/api/contests/{contest_id}/import_adif',{{method:'POST',body:fd}});
    const j=await res.json();
    if(res.ok){{r.className='ok';r.textContent=`Done! Inserted: ${{j.inserted}}, Updated: ${{j.updated}}, Skipped: ${{j.skipped}}. Total QSOs in contest: ${{j.total}}`;}}
    else{{r.className='err';r.textContent='Error: '+JSON.stringify(j);}}
  }}catch(err){{r.className='err';r.textContent='Error: '+err;}}
}};
</script></body></html>"""


# ── Static files (frontend) ────────────────────────────────────────────────
# Mounted last so /api routes take precedence

import pathlib
_frontend = pathlib.Path(__file__).parent.parent / "frontend"
if _frontend.exists():
    app.mount("/", StaticFiles(directory=str(_frontend), html=True), name="frontend")

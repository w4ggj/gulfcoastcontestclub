"""
FastAPI application: REST endpoints + WebSocket broadcaster.

Data-source abstraction: the frontend JavaScript checks for a `?source=local`
parameter (or defaults to local). The same static HTML is deployed both on
the Pi (reads this local API) and on Render (reads Supabase directly via JS).
This file is only the local half.
"""

import asyncio
import hmac
import json
import logging
import secrets
from typing import Optional

import hashlib
import re
from datetime import datetime, timezone

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, UploadFile, File, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import db
import mirror
from config import DEFAULT_ROTATION_SECONDS, ADMIN_PASSWORD

log = logging.getLogger(__name__)

app = FastAPI(title="GCCC Contest Dashboard", docs_url="/api/docs")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

# ── Auth ──────────────────────────────────────────────────────────────────
_active_tokens: set[str] = set()
_bearer = HTTPBearer(auto_error=False)


def _require_admin(creds: HTTPAuthorizationCredentials = Depends(_bearer)):
    """Dependency: reject requests without a valid admin token."""
    if creds is None or creds.credentials not in _active_tokens:
        raise HTTPException(401, "Not authenticated")


class LoginBody(BaseModel):
    password: str


@app.post("/api/auth/login")
def login(body: LoginBody):
    if not ADMIN_PASSWORD:
        raise HTTPException(503, "ADMIN_PASSWORD not configured on the server")
    if not hmac.compare_digest(body.password, ADMIN_PASSWORD):
        raise HTTPException(403, "Wrong password")
    token = secrets.token_hex(32)
    _active_tokens.add(token)
    return {"token": token}


@app.post("/api/auth/logout")
def logout(creds: HTTPAuthorizationCredentials = Depends(_bearer)):
    if creds and creds.credentials in _active_tokens:
        _active_tokens.discard(creds.credentials)
    return {"ok": True}


@app.get("/api/auth/check")
def auth_check(creds: HTTPAuthorizationCredentials = Depends(_bearer)):
    """Frontend calls this on load to see if its stored token is still valid."""
    if creds and creds.credentials in _active_tokens:
        return {"authenticated": True}
    return JSONResponse({"authenticated": False}, status_code=401)

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


def _build_combined_score(conn, contest_id: int, n1mm_score_row) -> dict:
    """Build a combined score: N1MM live score + Cabrillo claimed scores."""
    # Live N1MM score (single active station)
    n1mm_total = 0
    if n1mm_score_row:
        sc = dict(n1mm_score_row)
        n1mm_total = sc.get("score") or 0

    # Claimed scores from imported Cabrillo logs
    imported_row = conn.execute(
        "SELECT SUM(claimed_score) as total FROM imported_log_scores WHERE contest_id=?",
        (contest_id,)
    ).fetchone()
    imported_total = (imported_row["total"] or 0) if imported_row else 0

    # Per-operator breakdown for tooltip/detail
    imported_ops = conn.execute(
        "SELECT operator, claimed_score FROM imported_log_scores WHERE contest_id=? ORDER BY claimed_score DESC",
        (contest_id,)
    ).fetchall()

    return {
        "score":          n1mm_total + imported_total,
        "n1mm_score":     n1mm_total,
        "imported_score": imported_total,
        "imported_ops":   [dict(r) for r in imported_ops],
    }


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
            combined_score = _build_combined_score(conn, contest["id"], score)
            await ws.send_text(json.dumps({
                "type":           "snapshot",
                "contest":        dict(contest),
                "stats":          stats,
                "score":          dict(score) if score else None,
                "combined_score": combined_score,
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
        "SELECT call, band, operator, mode, qso_utc, points, is_mult1, station_name, radio_nr FROM contacts "
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
    combined_score = _build_combined_score(conn, contest_id, score)
    return {
        "contest":        dict(c),
        "stats":          stats,
        "score":          score,
        "combined_score": combined_score,
        "stations":       [dict(s) for s in stations],
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


@app.post("/api/contests", status_code=201, dependencies=[Depends(_require_admin)])
def create_contest(body: ContestCreate):
    conn = get_conn()
    cid = db.create_contest(conn, **body.model_dump(exclude_none=True))
    return {"id": cid}


class ContestUpdate(BaseModel):
    name: Optional[str] = None
    contest_type: Optional[str] = None
    year: Optional[int] = None
    location: Optional[str] = None
    station_callsign: Optional[str] = None
    category: Optional[str] = None
    start_utc: Optional[str] = None
    end_utc: Optional[str] = None
    notes: Optional[str] = None


@app.put("/api/contests/{contest_id}", dependencies=[Depends(_require_admin)])
def update_contest(contest_id: int, body: ContestUpdate):
    conn = get_conn()
    c = db.get_contest(conn, contest_id)
    if c is None:
        raise HTTPException(404, "Contest not found")
    fields = body.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(400, "No fields to update")
    db.update_contest(conn, contest_id, **fields)
    return {"ok": True}


@app.delete("/api/contests/{contest_id}", dependencies=[Depends(_require_admin)])
def delete_contest(contest_id: int):
    conn = get_conn()
    c = db.get_contest(conn, contest_id)
    if c is None:
        raise HTTPException(404, "Contest not found")
    if c["status"] == "live":
        raise HTTPException(409, "Cannot delete a live contest — complete it first")
    db.delete_contest(conn, contest_id)
    return {"ok": True}


@app.post("/api/contests/{contest_id}/start", dependencies=[Depends(_require_admin)])
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


@app.post("/api/contests/{contest_id}/complete", dependencies=[Depends(_require_admin)])
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


@app.post("/api/contests/{contest_id}/stations", status_code=201, dependencies=[Depends(_require_admin)])
def add_station(contest_id: int, body: StationSetup):
    conn = get_conn()
    sid = db.upsert_station(conn, contest_id, body.station_name, body.position_label)
    db.add_config_event(conn, contest_id, sid,
                        rig=body.rig, antenna=body.antenna,
                        bands=body.bands, note=body.note)
    conn.commit()
    return {"station_id": sid}


# ── CQ WW Scoring helpers ─────────────────────────────────────────────────

# Prefix → continent (2-char codes: NA SA EU AF AS OC AN)
_PFX_CONTINENT = {
    # North America — USA
    'W':'NA','K':'NA','N':'NA','AA':'NA','AB':'NA','AC':'NA','AD':'NA','AE':'NA',
    'AF':'NA','AG':'NA','AI':'NA','AJ':'NA','AK':'NA',
    'WA':'NA','WB':'NA','WC':'NA','WD':'NA','WE':'NA','WF':'NA','WG':'NA',
    'WH':'NA','WI':'NA','WJ':'NA','WK':'NA','WL':'NA','WM':'NA','WN':'NA',
    'WO':'NA','WP':'NA','WQ':'NA','WR':'NA','WS':'NA','WT':'NA','WU':'NA',
    'WV':'NA','WW':'NA','WX':'NA','WY':'NA','WZ':'NA',
    'KA':'NA','KB':'NA','KC':'NA','KD':'NA','KE':'NA','KF':'NA','KG':'NA',
    'KH':'NA','KI':'NA','KJ':'NA','KK':'NA','KL':'NA','KM':'NA','KN':'NA',
    'KO':'NA','KP':'NA','KQ':'NA','KR':'NA','KS':'NA','KT':'NA','KU':'NA',
    'KV':'NA','KW':'NA','KX':'NA','KY':'NA','KZ':'NA',
    'NA':'NA','NB':'NA','NC':'NA','ND':'NA','NE':'NA','NF':'NA','NG':'NA',
    'NH':'NA','NI':'NA','NJ':'NA','NK':'NA','NL':'NA','NM':'NA','NN':'NA',
    'NO':'NA','NP':'NA','NQ':'NA','NR':'NA','NS':'NA','NT':'NA','NU':'NA',
    'NV':'NA','NW':'NA','NX':'NA','NY':'NA','NZ':'NA',
    # Canada
    'VE':'NA','VA':'NA','VY':'NA','VO':'NA','VB':'NA',
    # Mexico & C. America
    'XE':'NA','XF':'NA','TI':'NA','HP':'NA','TG':'NA','HQ':'NA','YS':'NA',
    # Caribbean
    'CO':'NA','CM':'NA','HH':'NA','HI':'NA','VP9':'NA','ZF':'NA',
    '8P':'NA','J3':'NA','J7':'NA','J8':'NA','J6':'NA','V4':'NA','V3':'NA',
    'KP4':'NA','KP2':'NA','NP2':'NA','NP3':'NA','NP4':'NA',
    'VP2E':'NA','VP2M':'NA','VP2V':'NA','VP5':'NA',
    'P4':'NA','PJ2':'NA','PJ4':'NA','6Y':'NA',
    # South America
    'PY':'SA','PP':'SA','PQ':'SA','PR':'SA','PS':'SA','PT':'SA','PU':'SA',
    'PV':'SA','PW':'SA','PX':'SA',
    'LU':'SA','LS':'SA','LT':'SA','LV':'SA','LW':'SA',
    'CE':'SA','OA':'SA','HC':'SA','HK':'SA','YV':'SA','4M':'SA',
    'ZP':'SA','CX':'SA','CP':'SA','FY':'SA',
    # Europe
    'G':'EU','M':'EU','GX':'EU','GI':'EU','MI':'EU','GW':'EU','MW':'EU',
    'GM':'EU','MM':'EU','GD':'EU','GJ':'EU','GU':'EU','EI':'EU',
    'DL':'EU','DM':'EU','DN':'EU','DP':'EU','DQ':'EU','DR':'EU',
    'DA':'EU','DB':'EU','DC':'EU','DD':'EU','DE':'EU','DF':'EU',
    'DG':'EU','DH':'EU','DI':'EU','DJ':'EU','DK':'EU',
    'F':'EU','I':'EU','IS':'EU','IT9':'EU',
    'EA':'EU','EB':'EU','EC':'EU','ED':'EU','EE':'EU','EF':'EU','EG':'EU','EH':'EU',
    'EA8':'EU','EA9':'EU','CT':'EU','CR':'EU','CR3':'EU','CU':'EU','CT3':'EU',
    'PA':'EU','PD':'EU','PE':'EU','PH':'EU','PI':'EU',
    'SM':'EU','SA':'EU','SB':'EU','SC':'EU','SD':'EU','SE':'EU',
    'SF':'EU','SG':'EU','SH':'EU','SI':'EU','SJ':'EU','SK':'EU','SL':'EU',
    'OH':'EU','OG':'EU','OF':'EU','OI':'EU','OJ':'EU',
    'OY':'EU','TF':'EU',
    'LA':'EU','LB':'EU','LC':'EU',
    'OZ':'EU','OV':'EU','OW':'EU','OU':'EU','OX':'EU',
    'SP':'EU','SN':'EU','SO':'EU','SQ':'EU','SR':'EU','HF':'EU',
    'OK':'EU','OL':'EU','OM':'EU',
    'HA':'EU','HG':'EU',
    'YO':'EU','YP':'EU','YQ':'EU','YR':'EU',
    'LZ':'EU','SV':'EU','SX':'EU','J4':'EU','SV5':'EU','SV9':'EU',
    'OE':'EU','HB9':'EU','HB0':'EU',
    'ON':'EU','OO':'EU','OP':'EU','OR':'EU','OS':'EU','LX':'EU',
    'TK':'EU','9H':'EU','3A':'EU','T7':'EU','ZB':'EU','C3':'EU',
    'YU':'EU','YT':'EU','S5':'EU','E7':'EU','9A':'EU',
    'Z3':'EU','ZA':'EU','4O':'EU','Z6':'EU',
    'YL':'EU','LY':'EU','ES':'EU',
    'TA':'EU','TC':'EU','5B':'EU','P3':'EU',
    'UR':'EU','US':'EU','UT':'EU','UU':'EU','UV':'EU','UW':'EU',
    'UX':'EU','UY':'EU','UZ':'EU','EM':'EU','EN':'EU','EO':'EU',
    'EW':'EU','EU':'EU',
    'UA':'EU','RA':'EU','RB':'EU','RC':'EU','RD':'EU','RE':'EU','RF':'EU',
    'RG':'EU','RH':'EU','RI':'EU','RJ':'EU','RK':'EU','RL':'EU','RM':'EU',
    'RN':'EU','RO':'EU','RP':'EU','RQ':'EU','RS':'EU','RT':'EU','RU':'EU',
    'RV':'EU','RW':'EU','RX':'EU','RY':'EU','RZ':'EU',
    'OD':'AS','4X':'AS','4Z':'AS','JY':'AS','YK':'AS',
    '4L':'AS','EK':'AS','4J':'AS','4K':'AS','EP':'AS','EQ':'AS',
    'A4':'AS','A7':'AS','A6':'AS','9K':'AS','YI':'AS','HZ':'AS','7Z':'AS',
    'UN':'AS','UK':'AS','EY':'AS',
    'UA9':'AS','UA0':'AS',
    'JA':'AS','JB':'AS','JE':'AS','JF':'AS','JG':'AS','JH':'AS','JI':'AS',
    'JJ':'AS','JK':'AS','JL':'AS','JM':'AS','JN':'AS','JO':'AS','JP':'AS',
    'JQ':'AS','JR':'AS','JS':'AS','JD':'AS',
    '7J':'AS','7K':'AS','7L':'AS','7M':'AS','7N':'AS',
    '8J':'AS','8K':'AS','8L':'AS','8M':'AS','8N':'AS',
    'HL':'AS','DS':'AS','DT':'AS',
    'BY':'AS','BA':'AS','BD':'AS','BG':'AS','BH':'AS','BI':'AS',
    'BJ':'AS','BL':'AS','BT':'AS','BV':'AS','BU':'AS','BW':'AS','BX':'AS',
    'VU':'AS','AT':'AS','AU':'AS','AP':'AS','4S':'AS',
    'S2':'AS','S3':'AS','9N':'AS','A5':'AS',
    'XV':'AS','XU':'AS','XW':'AS','HS':'AS','XZ':'AS',
    '9M2':'AS','9M6':'AS','9W':'AS',
    'YB':'OC','YC':'OC','YD':'OC',
    'DU':'OC','DV':'OC','DW':'OC','DX':'OC',
    '9V':'AS','VR':'AS',
    'VK':'OC','VL':'OC','ZL':'OC','YJ':'OC','FO':'OC','T8':'OC','V6':'OC',
    # Africa
    'ZS':'AF','ZR':'AF','ZT':'AF','ZU':'AF',
    'SU':'AF','CN':'AF','7X':'AF','TS':'AF','5A':'AF',
    'ST':'AF','SS':'AF','5Z':'AF','9L':'AF','9G':'AF','5N':'AF',
    'EL':'AF','TU':'AF','D2':'AF','9J':'AF','Z2':'AF',
    'V5':'AF','A2':'AF','C9':'AF','5R':'AF','VQ9':'AF','ZD8':'AF','ZD7':'AF',
}

def _callsign_continent(call: str) -> str:
    call = call.upper().replace('/', '').strip()
    for l in (4, 3, 2, 1):
        c = _PFX_CONTINENT.get(call[:l])
        if c:
            return c
    # US fallback
    if re.match(r'^[KWNA][A-Z]', call):
        return 'NA'
    return ''


def _cqww_points(worked_call: str, op_call: str) -> int:
    op_cont   = _callsign_continent(op_call)
    wrk_cont  = _callsign_continent(worked_call)
    if not wrk_cont:
        return 3  # unknown → assume DX
    if op_cont == wrk_cont:
        # same continent — 0 if same country prefix, 1 if different
        op_pfx  = op_call[:2]
        wrk_pfx = worked_call[:2]
        return 0 if op_pfx == wrk_pfx else 1
    return 3


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


@app.post("/api/contests/{contest_id}/import_adif", dependencies=[Depends(_require_admin)])
async def import_adif(contest_id: int, file: UploadFile = File(...)):
    conn = get_conn()
    contest = conn.execute("SELECT id, name FROM contests WHERE id=?", (contest_id,)).fetchone()
    if not contest:
        raise HTTPException(status_code=404, detail="Contest not found")
    content = await file.read()
    text = content.decode("utf-8", errors="replace")
    rows = [_adif_record_to_row(r) for r in _parse_adif_records(text)]
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    inserted, updated, skipped = _upsert_rows(conn, contest_id, rows, now)
    conn.commit()
    total = conn.execute(
        "SELECT COUNT(*) FROM contacts WHERE contest_id=? AND deleted=0", (contest_id,)
    ).fetchone()[0]
    await broadcast({"type": "reload_stats", "contest_id": contest_id})
    return {"inserted": inserted, "updated": updated, "skipped": skipped, "total": total}


# ── Cabrillo Import ───────────────────────────────────────────────────────────

def _band_from_khz(khz_str):
    try:
        khz = float(khz_str)
    except (ValueError, TypeError):
        return ""
    mhz = khz / 1000.0
    return _band_from_freq(str(mhz)) or ""


def _parse_cabrillo_records(text: str, fallback_operator: str = ""):
    """Parse Cabrillo QSO lines into dicts compatible with _upsert_row.
    Returns (records, claimed_score) where claimed_score may be None."""
    records = []
    header = {}
    claimed_score = None
    for line in text.splitlines():
        line = line.rstrip()
        if line.upper().startswith("CALLSIGN:"):
            header["callsign"] = line.split(":", 1)[1].strip().upper()
        elif line.upper().startswith("OPERATORS:"):
            header["operators"] = line.split(":", 1)[1].strip().upper()
        elif line.upper().startswith("CLAIMED-SCORE:"):
            try:
                claimed_score = int(line.split(":", 1)[1].strip().replace(",", ""))
            except (ValueError, IndexError):
                pass
        elif line.upper().startswith("QSO:"):
            parts = line[4:].split()
            # Minimum: freq mode date time mycall sent-rst sent-exch hiscall rcvd-rst rcvd-exch
            if len(parts) < 8:
                continue
            freq_khz = parts[0]
            mode_cab = parts[1].upper()
            date_s   = parts[2]   # YYYY-MM-DD
            time_s   = parts[3]   # HHMM
            mycall   = parts[4].upper()
            # sent RST and exchange follow, then hiscall
            # We find hiscall by scanning: after mycall, skip rst+exch fields until next callsign-like token
            # Simpler: CQ WW has exactly: mycall snt-rst snt-zone hiscall rcvd-rst rcvd-zone
            # Other contests may vary; handle both 10-field and 9-field layouts
            # Locate hiscall: after mycall+snt-rst+snt-exchange, find next callsign-like token.
            # Callsign has both letters and digits and length >= 3; RST (599), zone (05),
            # state (FL) and DX are skipped by this test.
            _call_re = re.compile(r'^[A-Z0-9]{3,}$')
            _has_digit = re.compile(r'\d')
            _has_alpha = re.compile(r'[A-Z]')
            hiscall = None
            hiscall_idx = None
            for _i, _p in enumerate(parts[5:], start=5):
                _pu = _p.upper()
                if _call_re.match(_pu) and _has_digit.search(_pu) and _has_alpha.search(_pu):
                    hiscall = _pu
                    hiscall_idx = _i
                    break
            if not hiscall:
                continue

            mode_map = {"RY": "RTTY", "DG": "RTTY", "CW": "CW", "PH": "SSB", "FM": "FM"}
            mode = mode_map.get(mode_cab, mode_cab)

            band = _band_from_khz(freq_khz)

            try:
                qso_utc = datetime.strptime(f"{date_s} {time_s}", "%Y-%m-%d %H%M").replace(
                    tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            except ValueError:
                qso_utc = None

            operator = (header.get("callsign") or fallback_operator or mycall).upper()
            key = f"{hiscall}|{qso_utc}|{band}|{mode}|{operator}"
            n1mm_id = "cab_" + hashlib.md5(key.encode()).hexdigest()

            # CQ WW scoring: derive points from continent comparison
            points = _cqww_points(hiscall, operator)

            # Extract received zone from fields after hiscall (first numeric-only field)
            rcvd_zone = None
            for _rp in parts[hiscall_idx + 1:]:
                if _rp.isdigit():
                    rcvd_zone = _rp
                    break

            # is_mult1 = new CQ zone on this band (we flag it; dashboard just displays)
            is_mult1 = 1 if rcvd_zone else 0

            records.append(dict(
                n1mm_id=n1mm_id, call=hiscall, band=band, mode=mode,
                operator=operator, rx_freq=None,
                tx_freq=str(float(freq_khz) / 1000) if freq_khz else None,
                points=points, station_name=mycall, radio_nr=1, is_original=1,
                qso_utc=qso_utc, is_mult1=is_mult1, is_mult2=0, is_mult3=0, is_run_qso=0,
            ))
    return records, claimed_score, header


def _upsert_rows(conn, contest_id: int, rows: list, now: str):
    inserted = updated = skipped = 0
    for row in rows:
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
    return inserted, updated, skipped


@app.post("/api/contests/{contest_id}/import_cabrillo", dependencies=[Depends(_require_admin)])
async def import_cabrillo(contest_id: int, file: UploadFile = File(...)):
    conn = get_conn()
    contest = conn.execute("SELECT id, name FROM contests WHERE id=?", (contest_id,)).fetchone()
    if not contest:
        raise HTTPException(status_code=404, detail="Contest not found")
    content = await file.read()
    text = content.decode("utf-8", errors="replace")
    rows, claimed_score, header = _parse_cabrillo_records(text)
    operator = (header.get("callsign") or "").upper()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    inserted, updated, skipped = _upsert_rows(conn, contest_id, rows, now)
    if claimed_score is not None and operator:
        conn.execute("""
            INSERT INTO imported_log_scores (contest_id, operator, claimed_score)
            VALUES (?,?,?)
            ON CONFLICT(contest_id, operator) DO UPDATE SET
                claimed_score=excluded.claimed_score,
                imported_at=strftime('%Y-%m-%dT%H:%M:%SZ','now')
        """, (contest_id, operator, claimed_score))
    conn.commit()
    total = conn.execute(
        "SELECT COUNT(*) FROM contacts WHERE contest_id=? AND deleted=0", (contest_id,)
    ).fetchone()[0]
    await broadcast({"type": "reload_stats", "contest_id": contest_id})
    return {"inserted": inserted, "updated": updated, "skipped": skipped, "total": total,
            "claimed_score": claimed_score, "operator": operator}


@app.get("/api/contests/{contest_id}/import_adif", response_class=HTMLResponse)
def import_adif_form(contest_id: int):
    conn = get_conn()
    contest = conn.execute("SELECT id, name FROM contests WHERE id=?", (contest_id,)).fetchone()
    if not contest:
        raise HTTPException(status_code=404, detail="Contest not found")
    name = contest[1]
    return f"""<!doctype html><html><head><meta charset=utf-8>
<title>Import Log – {name}</title>
<style>body{{font-family:sans-serif;max-width:520px;margin:60px auto;padding:0 1rem}}
h2{{margin-bottom:0.3em}}p{{color:#555;font-size:.9em}}
h3{{margin:1.5rem 0 .3rem;font-size:1rem}}
input[type=file]{{display:block;margin:1rem 0}}
button{{padding:.5rem 1.4rem;font-size:1rem;cursor:pointer}}
.result{{margin-top:1rem;padding:.8rem;border-radius:4px;display:none}}
.ok{{background:#d4edda;color:#155724}}.err{{background:#f8d7da;color:#721c24}}
hr{{margin:2rem 0;border:none;border-top:1px solid #ddd}}</style>
</head><body>
<h2>Import Log — {name}</h2>

<h3>ADIF (.adi / .adif)</h3>
<p>Export from N1MM: <em>File → Export → ADIF</em></p>
<form id=fa>
  <input type=file id=fa-file accept=".adi,.adif" required>
  <button type=submit>Upload ADIF</button>
</form>
<div id=ra class=result></div>

<hr>

<h3>Cabrillo (.log / .cbr)</h3>
<p>The Cabrillo file submitted for the contest (or exported from N1MM).</p>
<form id=fc>
  <input type=file id=fc-file accept=".log,.cbr,.txt" required>
  <button type=submit>Upload Cabrillo</button>
</form>
<div id=rc class=result></div>

<script>
async function doUpload(formId, fileId, url, resultId) {{
  const fd = new FormData();
  fd.append('file', document.getElementById(fileId).files[0]);
  const r = document.getElementById(resultId);
  r.style.display = 'block'; r.className = 'result'; r.textContent = 'Importing…';
  try {{
    const res = await fetch(url, {{method:'POST', body:fd}});
    const j = await res.json();
    if (res.ok) {{ r.className='result ok'; r.textContent=`Done! Inserted: ${{j.inserted}}, Updated: ${{j.updated}}, Skipped: ${{j.skipped}}. Total QSOs: ${{j.total}}`; }}
    else {{ r.className='result err'; r.textContent='Error: '+JSON.stringify(j); }}
  }} catch(e) {{ r.className='result err'; r.textContent='Error: '+e; }}
}}
document.getElementById('fa').onsubmit = e => {{ e.preventDefault(); doUpload('fa','fa-file','/api/contests/{contest_id}/import_adif','ra'); }};
document.getElementById('fc').onsubmit = e => {{ e.preventDefault(); doUpload('fc','fc-file','/api/contests/{contest_id}/import_cabrillo','rc'); }};
</script></body></html>"""


# ── Static files (frontend) ────────────────────────────────────────────────
# Mounted last so /api routes take precedence

import pathlib
_frontend = pathlib.Path(__file__).parent.parent / "frontend"
if _frontend.exists():
    app.mount("/", StaticFiles(directory=str(_frontend), html=True), name="frontend")

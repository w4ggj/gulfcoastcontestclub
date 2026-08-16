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

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
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


# ── Static files (frontend) ────────────────────────────────────────────────
# Mounted last so /api routes take precedence

import pathlib
_frontend = pathlib.Path(__file__).parent.parent / "frontend"
if _frontend.exists():
    app.mount("/", StaticFiles(directory=str(_frontend), html=True), name="frontend")

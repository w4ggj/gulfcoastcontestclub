"""
Entrypoint: starts the UDP listener and FastAPI server in one asyncio event loop.

Usage:
    python main.py
    # or via systemd (see deploy/gccc-collector.service)

Environment variables (see config.py for full list):
    DB_PATH              path to SQLite file (recommend on USB stick)
    N1MM_UDP_PORT        default 12060
    API_PORT             default 8080
    SUPABASE_URL         optional
    SUPABASE_SERVICE_KEY optional
"""

import asyncio
import json
import logging
import socket
import sys
from datetime import datetime, timezone, timedelta

import uvicorn

import db
import ingest
import mirror
from api import app, set_conn, broadcast
from config import (
    UDP_PORT, UDP_BIND_HOST, API_HOST, API_PORT, DB_PATH,
    EXPECT_DUPLICATE_BROADCASTS,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("gccc.main")


class UDPListener(asyncio.DatagramProtocol):
    def __init__(self, conn, loop):
        self._conn = conn
        self._loop = loop
        self._seen: set[str] = set()   # rolling dedupe set (n1mm_id)

    def datagram_received(self, data: bytes, addr):
        self._loop.create_task(self._handle(data, addr))

    async def _handle(self, data: bytes, addr):
        result = ingest.parse_packet(data)
        if result is None:
            return

        ptype, payload = result
        conn = self._conn

        # Contest binding (§4): only process if a contest is live
        contest = db.get_live_contest(conn)
        if contest is None:
            log.debug("No live contest — quarantining %s packet", ptype)
            return

        contest_id = contest["id"]

        if ptype in ("contact_info", "contact_replace"):
            n1mm_id = payload.get("n1mm_id", "")

            if EXPECT_DUPLICATE_BROADCASTS and not payload.get("is_original"):
                # Non-original copy from another seat's re-broadcast; skip
                # unless we have no record of this ID yet.
                existing = conn.execute(
                    "SELECT is_original FROM contacts WHERE contest_id=? AND n1mm_id=?",
                    (contest_id, n1mm_id)
                ).fetchone()
                if existing and existing["is_original"]:
                    log.debug("Skipping non-original duplicate: %s", n1mm_id)
                    return

            with db.transaction(conn):
                db.upsert_contact(conn, contest_id, payload)
                _CONTACT_MIRROR_COLS = {
                    "contest_id","n1mm_id","operator","call","band","mode",
                    "rx_freq","tx_freq","points","station_name","radio_nr",
                    "is_original","qso_utc","is_mult1","is_mult2","is_mult3",
                    "is_run_qso","deleted",
                }
                mirror_payload = {k: v for k, v in {"contest_id": contest_id, **payload}.items()
                                  if k in _CONTACT_MIRROR_COLS}
                db.enqueue_mirror(conn, "upsert_contact", mirror_payload)

            stats = db.get_live_stats(conn, contest_id)
            await broadcast({"type": "stats_update", "stats": stats})

        elif ptype == "contact_delete":
            n1mm_id = payload.get("n1mm_id", "")
            with db.transaction(conn):
                db.soft_delete_contact(conn, contest_id, n1mm_id)
                db.enqueue_mirror(conn, "delete_contact",
                                  {"contest_id": contest_id, "n1mm_id": n1mm_id})
            stats = db.get_live_stats(conn, contest_id)
            await broadcast({"type": "stats_update", "stats": stats})

        elif ptype == "score":
            with db.transaction(conn):
                db.upsert_score_snapshot(conn, contest_id, payload)
                db.enqueue_mirror(conn, "upsert_score",
                                  {"contest_id": contest_id, **payload})
            await broadcast({"type": "score_update", "score": payload})


async def run_udp(conn, loop):
    log.info("Binding UDP listener on %s:%d", UDP_BIND_HOST, UDP_PORT)
    transport, _ = await loop.create_datagram_endpoint(
        lambda: UDPListener(conn, loop),
        local_addr=(UDP_BIND_HOST, UDP_PORT),
        family=socket.AF_INET,
        allow_broadcast=True,
    )
    return transport


async def contest_scheduler(conn):
    """Auto-start drafts 2 min before start_utc, auto-complete live contests
    2 min after end_utc. Checks every 30 seconds."""
    log.info("Contest scheduler started")
    while True:
        try:
            now = datetime.now(timezone.utc)

            # Auto-start: draft contests whose start_utc is <= 2 min from now
            drafts = conn.execute(
                "SELECT id, name, start_utc FROM contests "
                "WHERE status='draft' AND start_utc IS NOT NULL AND start_utc != ''"
            ).fetchall()
            for c in drafts:
                try:
                    start = datetime.fromisoformat(c["start_utc"].replace("Z", "+00:00"))
                except (ValueError, AttributeError):
                    continue
                if now >= start - timedelta(minutes=2):
                    # Check no other contest is already live
                    already_live = conn.execute(
                        "SELECT id FROM contests WHERE status='live' LIMIT 1"
                    ).fetchone()
                    if already_live:
                        log.warning("Skipping auto-start of contest %d (%s) — contest %d already live",
                                    c["id"], c["name"], already_live["id"])
                        continue
                    db.set_contest_status(conn, c["id"], "live")
                    log.info("Auto-started contest %d (%s)", c["id"], c["name"])
                    await broadcast({"type": "contest_started", "contest_id": c["id"]})

            # Auto-complete: live contests whose end_utc + 2 min has passed
            lives = conn.execute(
                "SELECT id, name, end_utc FROM contests "
                "WHERE status='live' AND end_utc IS NOT NULL AND end_utc != ''"
            ).fetchall()
            for c in lives:
                try:
                    end = datetime.fromisoformat(c["end_utc"].replace("Z", "+00:00"))
                except (ValueError, AttributeError):
                    continue
                if now >= end + timedelta(minutes=2):
                    db.set_contest_status(conn, c["id"], "complete")
                    log.info("Auto-completed contest %d (%s)", c["id"], c["name"])
                    await broadcast({"type": "contest_completed", "contest_id": c["id"]})

        except Exception:
            log.exception("Contest scheduler error")

        await asyncio.sleep(30)


async def main():
    log.info("GCCC Contest Collector starting (DB: %s)", DB_PATH)
    conn = db.get_connection()
    db.init_db(conn)
    set_conn(conn)

    loop = asyncio.get_event_loop()

    # Start UDP listener
    transport = await run_udp(conn, loop)
    log.info("UDP listener ready on port %d", UDP_PORT)

    # Start Supabase mirror drain loop
    asyncio.create_task(mirror.drain_loop(conn))

    # Start contest auto-start/stop scheduler
    asyncio.create_task(contest_scheduler(conn))

    # Start FastAPI / uvicorn
    config = uvicorn.Config(
        app,
        host=API_HOST,
        port=API_PORT,
        log_level="info",
        ws_ping_interval=20,
        ws_ping_timeout=30,
    )
    server = uvicorn.Server(config)

    try:
        await server.serve()
    finally:
        transport.close()
        conn.close()
        log.info("Collector shut down")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Interrupted — exiting")
        sys.exit(0)

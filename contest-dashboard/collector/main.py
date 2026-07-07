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
                db.enqueue_mirror(conn, "upsert_contact",
                                  {"contest_id": contest_id, **payload})

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

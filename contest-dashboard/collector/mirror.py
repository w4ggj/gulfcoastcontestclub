"""
Async Supabase mirror with local retry queue (SQLite mirror_queue table).

Architecture:
- Every local write also enqueues a mirror_queue row (written in the same
  SQLite transaction — so nothing is lost even if internet is down).
- A background task drains the queue with exponential back-off.
- On contest completion, call drain_and_reconcile() to flush and verify.

Supabase is optional: if SUPABASE_URL is blank the mirror is a no-op.
"""

import asyncio
import json
import logging
from typing import Optional

import sqlite3
import db
from config import SUPABASE_URL, SUPABASE_KEY

log = logging.getLogger(__name__)

_supabase = None   # supabase-py AsyncClient, initialised lazily


async def _get_client():
    global _supabase
    if _supabase is not None:
        return _supabase
    if not SUPABASE_URL or not SUPABASE_KEY:
        return None
    try:
        from supabase import create_async_client
        _supabase = await create_async_client(SUPABASE_URL, SUPABASE_KEY)
        log.info("Supabase mirror connected to %s", SUPABASE_URL)
    except Exception as e:
        log.warning("Supabase client init failed: %s", e)
        _supabase = None
    return _supabase


async def _push_row(client, op: str, payload: dict) -> None:
    """Send one queue item to Supabase."""
    if op == "upsert_contact":
        await client.table("contacts").upsert(payload, on_conflict="contest_id,n1mm_id").execute()
    elif op == "delete_contact":
        await client.table("contacts").update({"deleted": True}).eq(
            "contest_id", payload["contest_id"]
        ).eq("n1mm_id", payload["n1mm_id"]).execute()
    elif op == "upsert_score":
        await client.table("score_snapshots").insert(payload).execute()
    elif op == "upsert_contest":
        await client.table("contests").upsert(payload, on_conflict="id").execute()
    else:
        log.warning("Unknown mirror op: %s", op)


async def drain_queue(conn: sqlite3.Connection, *, limit: int = 100) -> int:
    """
    Drain up to `limit` pending mirror_queue rows.
    Returns number successfully sent.
    """
    client = await _get_client()
    if client is None:
        return 0

    rows = db.get_pending_mirror(conn, limit=limit)
    sent = 0
    for row in rows:
        try:
            payload = json.loads(row["payload"])
            await _push_row(client, row["operation"], payload)
            with db.transaction(conn):
                db.ack_mirror(conn, row["id"])
            sent += 1
        except Exception as e:
            with db.transaction(conn):
                db.fail_mirror(conn, row["id"], str(e))
            log.warning("Mirror push failed for id=%d: %s", row["id"], e)
    return sent


async def drain_loop(conn: sqlite3.Connection) -> None:
    """Background task: drain the queue every 5 seconds."""
    backoff = 5
    while True:
        try:
            sent = await drain_queue(conn)
            if sent:
                log.debug("Mirror: sent %d row(s)", sent)
            backoff = 5
        except Exception as e:
            log.error("Mirror drain error: %s", e)
            backoff = min(backoff * 2, 120)
        await asyncio.sleep(backoff)


async def drain_and_reconcile(conn: sqlite3.Connection) -> dict:
    """
    Called at contest completion. Drain all pending rows, then compare
    local totals to Supabase totals. Returns a reconciliation report.
    """
    # Drain until queue is empty or 10 attempts exhaust
    for attempt in range(10):
        sent = await drain_queue(conn, limit=500)
        pending = len(db.get_pending_mirror(conn, limit=1))
        if pending == 0:
            break
        await asyncio.sleep(2 ** attempt)

    client = await _get_client()
    if client is None:
        return {"status": "no_mirror", "message": "Supabase not configured"}

    # Get local count for live (just-completed) contest
    live = db.get_live_contest(conn)
    if live is None:
        # Already marked complete; grab the most recent complete
        row = conn.execute(
            "SELECT * FROM contests WHERE status='complete' ORDER BY completed_at DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return {"status": "error", "message": "No contest found"}
        contest_id = row["id"]
    else:
        contest_id = live["id"]

    local_count = conn.execute(
        "SELECT COUNT(*) as n FROM contacts WHERE contest_id=? AND deleted=0",
        (contest_id,)
    ).fetchone()["n"]

    try:
        resp = await client.table("contacts").select(
            "id", count="exact"
        ).eq("contest_id", contest_id).eq("deleted", False).execute()
        remote_count = resp.count or 0
    except Exception as e:
        return {"status": "error", "message": f"Supabase count failed: {e}"}

    pending = len(db.get_pending_mirror(conn, limit=1))
    status = "synced" if local_count == remote_count and pending == 0 else "mismatch"
    return {
        "status":        status,
        "local_qsos":    local_count,
        "remote_qsos":   remote_count,
        "pending_queue": pending,
    }

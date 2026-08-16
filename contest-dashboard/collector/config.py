"""
All configurable constants for the collector.

§0 VERIFY-FIRST callout: the N1MM_FIELDS dict maps our internal names to
the XML element names found in actual N1MM packets. Before deploying,
run a live N1MM station and capture a real ContactInfo packet to confirm
these names match the current N1MM version. They are representative, not
gospel — update here without touching any other file.

Similarly, UDP_PORT and BROADCAST_BEHAVIOR are configurable so the ingest
layer can adapt without code changes.
"""

import os

# ── Network ────────────────────────────────────────────────────────────────
UDP_PORT: int = int(os.getenv("N1MM_UDP_PORT", "12060"))
UDP_BIND_HOST: str = os.getenv("N1MM_BIND_HOST", "0.0.0.0")

# ── Local API ──────────────────────────────────────────────────────────────
API_HOST: str = os.getenv("API_HOST", "0.0.0.0")
API_PORT: int = int(os.getenv("API_PORT", "8080"))

# ── Database ───────────────────────────────────────────────────────────────
# Recommend pointing DB_PATH at a USB thumb drive, e.g. /media/usb/gccc.db
DB_PATH: str = os.getenv("DB_PATH", "gccc_contest.db")

# ── Supabase mirror (optional — leave blank to disable) ────────────────────
SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY: str = os.getenv("SUPABASE_SERVICE_KEY", "")

# ── Dashboard rotation ─────────────────────────────────────────────────────
# Default rotation interval in seconds (20–60 per brief); overridable in UI
DEFAULT_ROTATION_SECONDS: int = int(os.getenv("ROTATION_SECONDS", "30"))

# ── §0.2 — networked re-broadcast behavior ─────────────────────────────────
# Set to True if the master N1MM re-broadcasts replicated QSOs, meaning the
# same QSO arrives from multiple seats. When True, dedupe is enforced via
# n1mm_id + is_original. When False (each seat only broadcasts its own),
# dedupe is still safe but less critical.
EXPECT_DUPLICATE_BROADCASTS: bool = os.getenv("EXPECT_DUPES", "true").lower() == "true"

# ── §0.1 — N1MM XML field names (ContactInfo / ContactReplace) ─────────────
# Map our internal names → XML element names in the current N1MM packet.
# Root tag names are also listed so ingest.py has a single source of truth.
N1MM_TAGS = {
    "contact_info":     "contactinfo",
    "contact_replace":  "contactreplace",
    "contact_delete":   "contactdelete",
    "score":            "score",
    "dynamicresults":   "dynamicresults",  # N1MM Score broadcast actual tag
    "radio_info":       "RadioInfo",       # per-radio status (nice-to-have)
}

N1MM_FIELDS = {
    # Identity / dedupe
    "id":              "ID",            # stable unique record ID; confirm present
    "is_original":     "isoriginal",    # "True"/"False" string
    "networked_comp":  "NetBiosName",   # station (PC) that owns the QSO

    # QSO data
    "timestamp":       "timestamp",     # "YYYY-MM-DD HH:MM:SS"
    "operator":        "operator",      # OPON callsign — the human
    "call":            "call",          # worked station
    "band":            "band",          # N1MM sends band in MHz as string (e.g. "14")
    "rx_freq":         "rxfreq",        # in 10 Hz units (e.g. 14225100 = 14.225100 MHz)
    "tx_freq":         "txfreq",
    "mode":            "mode",          # SSB / CW / RTTY / FT8 …
    "points":          "points",
    "station_name":    "StationName",   # same as NetBiosName in most versions
    "radio_nr":        "radionr",       # 1 or 2 (SO2R)
    "is_mult1":        "ismult1",
    "is_mult2":        "ismult2",
    "is_mult3":        "ismult3",
    "is_run_qso":      "IsRunQSO",      # 1=Run, 0=S&P (nice-to-have; may be absent)
    "contest_name":    "contestname",
    "contest_nr":      "contestnr",

    # Score packet fields
    "score_qsos":      "qsos",
    "score_points":    "points",        # reused; root tag distinguishes context
    "score_mults":     "mults",
    "score_score":     "score",
    "score_power":     "power",
}

# Band label mapping: N1MM band values → human label
# N1MM sends the band as a numeric string (MHz centre freq or label — confirm)
BAND_LABELS: dict[str, str] = {
    "1.8":  "160m",  "160": "160m",
    "3.5":  "80m",   "80":  "80m",
    "7":    "40m",   "40":  "40m",
    "14":   "20m",   "20":  "20m",
    "21":   "15m",   "15":  "15m",
    "28":   "10m",   "10":  "10m",
    "50":   "6m",    "6":   "6m",
    "144":  "2m",    "2":   "2m",
    "432":  "70cm",  "70":  "70cm",
}

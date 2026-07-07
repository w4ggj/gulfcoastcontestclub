"""
UDP packet parser and ingest logic.

All XML field names come from config.N1MM_FIELDS / N1MM_TAGS — never
hard-coded here — so the field map can be corrected after §0 verification
without touching this file.
"""

import xml.etree.ElementTree as ET
import logging
from typing import Optional

from config import N1MM_FIELDS as F, N1MM_TAGS as T, BAND_LABELS

log = logging.getLogger(__name__)


def _txt(root: ET.Element, key: str) -> Optional[str]:
    """Get text from element using configured field name. Returns None if absent."""
    el = root.find(key)
    if el is None or el.text is None:
        return None
    return el.text.strip()


def _int(root: ET.Element, key: str) -> Optional[int]:
    val = _txt(root, key)
    if val is None:
        return None
    try:
        return int(val)
    except ValueError:
        return None


def _bool_flag(root: ET.Element, key: str) -> int:
    """Parse N1MM True/False strings or 0/1 integers → 0 or 1."""
    val = _txt(root, key)
    if val is None:
        return 0
    return 1 if val.lower() in ("true", "1", "yes") else 0


def normalize_band(raw: Optional[str]) -> Optional[str]:
    """Map N1MM band value to human label (e.g. '14' → '20m')."""
    if raw is None:
        return None
    return BAND_LABELS.get(raw.strip(), raw.strip())


def parse_packet(raw: bytes) -> Optional[tuple[str, dict]]:
    """
    Parse a raw UDP payload into (packet_type, data_dict).
    Returns None if the packet is unrecognised or malformed.

    Packet types: 'contact_info', 'contact_replace', 'contact_delete', 'score'
    """
    try:
        root = ET.fromstring(raw.decode("utf-8", errors="replace"))
    except ET.ParseError as e:
        log.debug("XML parse error: %s", e)
        return None

    tag = root.tag.lower()

    if tag in (T["contact_info"].lower(), T["contact_replace"].lower()):
        ptype = "contact_replace" if tag == T["contact_replace"].lower() else "contact_info"
        data = _parse_contact(root)
        return (ptype, data) if data else None

    if tag == T["contact_delete"].lower():
        data = _parse_delete(root)
        return ("contact_delete", data) if data else None

    if tag == T["score"].lower():
        data = _parse_score(root)
        return ("score", data) if data else None

    log.debug("Unrecognised packet tag: %s", root.tag)
    return None


def _parse_contact(root: ET.Element) -> Optional[dict]:
    n1mm_id = _txt(root, F["id"])
    if not n1mm_id:
        # Build a fallback composite key from timestamp + call + band + station
        ts = _txt(root, F["timestamp"]) or ""
        call = _txt(root, F["call"]) or ""
        band = _txt(root, F["band"]) or ""
        station = _txt(root, F["station_name"]) or ""
        n1mm_id = f"composite:{ts}:{call}:{band}:{station}"
        if n1mm_id == "composite::::":
            log.warning("Contact packet has no usable ID; dropping")
            return None

    raw_band = _txt(root, F["band"])
    is_run_raw = _txt(root, F["is_run_qso"])

    return {
        "n1mm_id":      n1mm_id,
        "operator":     _txt(root, F["operator"]),
        "call":         _txt(root, F["call"]),
        "band":         normalize_band(raw_band),
        "mode":         _txt(root, F["mode"]),
        "rx_freq":      _txt(root, F["rx_freq"]),
        "tx_freq":      _txt(root, F["tx_freq"]),
        "points":       _int(root, F["points"]) or 0,
        "station_name": _txt(root, F["station_name"]) or _txt(root, F["networked_comp"]),
        "radio_nr":     _int(root, F["radio_nr"]),
        "is_original":  _bool_flag(root, F["is_original"]),
        "qso_utc":      _txt(root, F["timestamp"]),
        "is_mult1":     _bool_flag(root, F["is_mult1"]),
        "is_mult2":     _bool_flag(root, F["is_mult2"]),
        "is_mult3":     _bool_flag(root, F["is_mult3"]),
        "is_run_qso":   (1 if is_run_raw in ("1", "true") else 0) if is_run_raw is not None else None,
        "contest_name": _txt(root, F["contest_name"]),
    }


def _parse_delete(root: ET.Element) -> Optional[dict]:
    n1mm_id = _txt(root, F["id"])
    if not n1mm_id:
        log.warning("Delete packet has no ID; dropping")
        return None
    return {"n1mm_id": n1mm_id}


def _parse_score(root: ET.Element) -> Optional[dict]:
    # Score packet has a nested band breakdown; structure varies by N1MM version.
    # Try to collect <band_breakdown> children or equivalent.
    band_breakdown = {}
    bb_el = root.find("band_breakdown") or root.find("bandbreakdown")
    if bb_el is not None:
        for child in bb_el:
            label = normalize_band(child.tag) or child.tag
            band_breakdown[label] = {
                "qsos": _int(child, "qsos") or 0,
                "points": _int(child, "points") or 0,
                "mults": _int(child, "mults") or 0,
            }

    return {
        "total_qsos":    _int(root, F["score_qsos"]),
        "total_points":  _int(root, F["score_points"]),
        "total_mults":   _int(root, F["score_mults"]),
        "score":         _int(root, F["score_score"]),
        "band_breakdown": band_breakdown,
    }

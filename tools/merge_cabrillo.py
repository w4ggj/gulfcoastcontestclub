#!/usr/bin/env python3
"""
Merge multiple Cabrillo log files into one combined log.

Usage:
    python3 merge_cabrillo.py AA2MF.log N4MMR.log W4GGJ.log -o combined.log \
        --callsign W4GGJ --operators "AA2MF N4MMR W4GGJ"

The combined CLAIMED-SCORE is the sum of all input files' claimed scores.
All QSO records from all files are included, sorted by date/time.
"""

import argparse
import sys
from pathlib import Path


def parse_cabrillo(path: str) -> dict:
    """Parse a Cabrillo file, returning header fields and QSO lines."""
    header = {}
    qsos = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.rstrip()
            upper = line.upper()
            if upper.startswith("QSO:"):
                qsos.append(line)
            elif upper.startswith("END-OF-LOG"):
                pass
            else:
                # Store header lines preserving original case of value
                if ":" in line:
                    key, _, val = line.partition(":")
                    header[key.upper().strip()] = (key.strip(), val.strip())
                else:
                    # Lines without colon (rare) — keep as-is under blank key
                    header.setdefault("_MISC", ("", []))[1].append(line)
    return {"header": header, "qsos": qsos, "path": path}


def merge(logs: list[dict], callsign: str, operators: str) -> str:
    """Build a merged Cabrillo string from parsed logs."""

    # Sum claimed scores
    total_claimed = 0
    for log in logs:
        sc = log["header"].get("CLAIMED-SCORE", (None, "0"))[1]
        try:
            total_claimed += int(sc.replace(",", "").strip())
        except ValueError:
            pass

    # Pull header fields from first log as base, override key fields
    base = logs[0]["header"]

    def hval(key, default=""):
        entry = base.get(key)
        return entry[1] if entry else default

    lines = []
    lines.append("START-OF-LOG: 3.0")
    lines.append(f"CALLSIGN: {callsign}")
    lines.append(f"OPERATORS: {operators}")

    # Preserve contest, category, etc. from base log
    for key in ("CONTEST", "CATEGORY-OPERATOR", "CATEGORY-ASSISTED",
                 "CATEGORY-BAND", "CATEGORY-MODE", "CATEGORY-POWER",
                 "CATEGORY-STATION", "CATEGORY-TRANSMITTER",
                 "CATEGORY-OVERLAY", "CLUB", "LOCATION", "NAME",
                 "ADDRESS", "ADDRESS-CITY", "ADDRESS-STATE-PROVINCE",
                 "ADDRESS-POSTALCODE", "ADDRESS-COUNTRY", "EMAIL"):
        val = hval(key)
        if val:
            lines.append(f"{key}: {val}")

    lines.append(f"CLAIMED-SCORE: {total_claimed}")

    created_by = hval("CREATED-BY", "merge_cabrillo.py")
    lines.append(f"CREATED-BY: {created_by} [merged]")

    # Operator source files in SOAPBOX
    sources = ", ".join(Path(log["path"]).name for log in logs)
    lines.append(f"SOAPBOX: Merged from {sources}")

    lines.append("")  # blank line before QSOs

    # Collect and sort all QSOs by date+time (fields 3+4 in QSO line)
    all_qsos = []
    for log in logs:
        all_qsos.extend(log["qsos"])

    def qso_sort_key(line):
        parts = line.split()
        # QSO: freq mode date time ...
        # parts[0]=QSO:  [1]=freq [2]=mode [3]=date [4]=time
        try:
            return parts[3] + parts[4]
        except IndexError:
            return ""

    all_qsos.sort(key=qso_sort_key)
    lines.extend(all_qsos)

    lines.append("")
    lines.append("END-OF-LOG:")

    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description="Merge Cabrillo log files")
    parser.add_argument("logs", nargs="+", help="Input .log files")
    parser.add_argument("-o", "--output", default="combined.log",
                        help="Output file (default: combined.log)")
    parser.add_argument("--callsign", default="",
                        help="Callsign for combined log (default: from first file)")
    parser.add_argument("--operators", default="",
                        help="Space-separated operator list")
    args = parser.parse_args()

    parsed = []
    for path in args.logs:
        print(f"Reading {path}…")
        p = parse_cabrillo(path)
        qso_count = len(p["qsos"])
        claimed = p["header"].get("CLAIMED-SCORE", (None, "?"))[1]
        print(f"  {qso_count} QSOs, claimed score: {claimed}")
        parsed.append(p)

    # Fill in callsign/operators from first file if not specified
    callsign = args.callsign or parsed[0]["header"].get("CALLSIGN", ("", ""))[1]
    if not callsign:
        print("ERROR: no callsign found in first file, use --callsign", file=sys.stderr)
        sys.exit(1)

    if args.operators:
        operators = args.operators
    else:
        ops = []
        for p in parsed:
            cs = p["header"].get("CALLSIGN", ("", ""))[1]
            if cs and cs not in ops:
                ops.append(cs)
        operators = " ".join(ops)

    result = merge(parsed, callsign.upper(), operators.upper())

    total_qsos = sum(len(p["qsos"]) for p in parsed)
    total_claimed = 0
    for p in parsed:
        try:
            total_claimed += int(p["header"].get("CLAIMED-SCORE", ("", "0"))[1].replace(",", ""))
        except ValueError:
            pass

    with open(args.output, "w", encoding="utf-8") as f:
        f.write(result)

    print(f"\nWrote {args.output}")
    print(f"  Total QSOs:    {total_qsos}")
    print(f"  Total claimed: {total_claimed:,}")
    print(f"  Callsign:      {callsign.upper()}")
    print(f"  Operators:     {operators.upper()}")


if __name__ == "__main__":
    main()

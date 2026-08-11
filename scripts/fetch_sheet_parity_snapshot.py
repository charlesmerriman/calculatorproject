#!/usr/bin/env python3
"""
Snapshot the source spreadsheet's per-banner figures for the parity harness.

WHY A SNAPSHOT AND NOT A LIVE FETCH
-----------------------------------
The sheet's anchors are `NOW()` and `TODAY()`, so every figure it reports moves
daily. A test that fetched it live would be non-deterministic and would fail
offline. We capture a dated snapshot, commit it, and diff against that; when the
sheet or our engine changes, re-run this and review the diff as part of the
change.

WHAT IT CAPTURES
----------------
Both sides of the comparison, for the same instant:

  * the sheet's settings block (ranks, toggles, starting balances) so the test
    can reproduce the same scenario, and
  * its banner table — name, type, planned pulls, resolved dates, and the three
    output cells the site also shows: Carat Est., Paid Carat Est., Max Pulls.

USAGE
-----
    python scripts/fetch_sheet_parity_snapshot.py [--sheet-id ID] [--gid GID]
        [--out PATH]

The default sheet is the PUBLIC TEMPLATE, whose banner table is empty — it has
no plan in it, so it yields no rows to compare and the harness will skip. Point
this at a copy with an actual plan configured to get a meaningful snapshot:

    python scripts/fetch_sheet_parity_snapshot.py --sheet-id <your-copy-id>

The sheet must be readable without auth ("anyone with the link can view").

NOTE: python `requests` is not installed in this project — stdlib urllib only.
"""

import argparse
import csv
import io
import json
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# Henry Handsome Derby's Banner Timeline Carat Calculator — the public template.
DEFAULT_SHEET_ID = "100t3hnYl5Qm2UR8RtPlH-8Xd9KQbBlxEdXUOIR4d394"
DEFAULT_GID = "607505096"  # the "Carat Calculator" tab

DEFAULT_OUT = (
    Path(__file__).resolve().parents[2]
    / "frontend/src/__tests__/fixtures/sheetParitySnapshot.json"
)

# The banner table: one banner per three rows, first block starting at row 42.
# Verified against the sheet's own indexing formula, which walks the table as
# ROW($C$43) + (n * 3).
FIRST_BANNER_ROW = 42
ROWS_PER_BANNER = 3
MAX_BANNERS = 100

# Settings cells, read straight off the Carat Calculator tab.
SETTING_CELLS = {
    "server": "B5",
    "team_trials_rank": "E29",
    "club_rank": "E30",
    "champions_meeting_rank": "E31",
    "league_of_heroes_rank": "E32",
    "daily_carat_pack": "E33",
    "training_pass": "E34",
    "current_carat": "D37",
    "current_paid_carat": "D39",
    "today_utc": "AG3",
    "now_utc": "AG2",
}

# Per-banner cells, as offsets from a block's first row.
# The sheet puts a banner's inputs and outputs on the block's SECOND row.
BANNER_CELLS = {
    "type": ("C", 1),
    "name": ("F", 1),
    "pulls": ("Q", 1),
    "start_date": ("D", 1),
    "end_date": ("L", 1),
    "carat_est": ("M", 1),
    "paid_carat_est": ("N", 1),
    "max_pulls": ("O", 1),
}


def column_index(letters):
    """'AG' -> 32 (zero-based), matching a spreadsheet column reference."""
    n = 0
    for char in letters:
        n = n * 26 + (ord(char) - 64)
    return n - 1


def fetch_tab_csv(sheet_id, gid):
    """The tab as a raw grid.

    Uses `export?format=csv`, NOT the gviz endpoint: gviz applies header
    detection that silently drops leading blank rows and shifts every
    subsequent row reference, which is exactly the kind of off-by-N that would
    make a parity harness lie.
    """
    url = (
        f"https://docs.google.com/spreadsheets/d/{sheet_id}"
        f"/export?format=csv&gid={gid}"
    )
    with urllib.request.urlopen(url, timeout=120) as response:
        body = response.read().decode("utf-8")
    return list(csv.reader(io.StringIO(body)))


def cell(grid, ref, row_override=None):
    """Read an A1-style reference (or a column letter plus an explicit row)."""
    match = re.match(r"([A-Z]+)(\d*)", ref)
    col = column_index(match.group(1))
    row = (row_override if row_override is not None else int(match.group(2))) - 1
    if row < 0 or row >= len(grid) or col >= len(grid[row]):
        return ""
    return grid[row][col].strip()


def to_number(text):
    """Sheet cells arrive as display strings — '1,234' or '' — not numbers."""
    if not text:
        return None
    cleaned = text.replace(",", "").replace("$", "").strip()
    try:
        return float(cleaned) if "." in cleaned else int(cleaned)
    except ValueError:
        return None


def read_banners(grid):
    """Every configured banner block, skipping empty and 'N/A' rows."""
    banners = []
    for index in range(MAX_BANNERS):
        base = FIRST_BANNER_ROW + index * ROWS_PER_BANNER
        if base > len(grid):
            break
        values = {
            key: cell(grid, letter, base + offset)
            for key, (letter, offset) in BANNER_CELLS.items()
        }
        # An unconfigured block has no banner chosen. The sheet also renders
        # "N/A" in the picker for a slot past the end of the plan.
        if not values["name"] or values["name"] == "N/A":
            continue
        banners.append({
            "index": index + 1,
            "type": values["type"],
            "name": values["name"],
            "pulls": to_number(values["pulls"]) or 0,
            "start_date": values["start_date"],
            "end_date": values["end_date"],
            "carat_est": to_number(values["carat_est"]),
            "paid_carat_est": to_number(values["paid_carat_est"]),
            "max_pulls": to_number(values["max_pulls"]),
        })
    return banners


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sheet-id", default=DEFAULT_SHEET_ID)
    parser.add_argument("--gid", default=DEFAULT_GID)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    grid = fetch_tab_csv(args.sheet_id, args.gid)
    settings = {key: cell(grid, ref) for key, ref in SETTING_CELLS.items()}
    banners = read_banners(grid)

    snapshot = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "sheet_id": args.sheet_id,
        "gid": args.gid,
        "settings": settings,
        "banners": banners,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(snapshot, indent=2) + "\n")

    print(f"Wrote {args.out}")
    print(f"  sheet today (UTC): {settings.get('today_utc') or '(blank)'}")
    print(f"  banners captured:  {len(banners)}")
    if not banners:
        print()
        print("  NOTE: no banners are configured in this sheet, so the parity")
        print("  harness has nothing to compare and will skip. Point --sheet-id")
        print("  at a copy with an actual plan in it.")


if __name__ == "__main__":
    main()

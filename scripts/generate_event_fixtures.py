"""
generate_event_fixtures.py

Parses the Uma Musume global timeline CSV and generates one Django fixture file:
  - calculatorapi/fixtures/gameEvents.json

Run from the backend/ directory:
    python scripts/generate_event_fixtures.py [path/to/csv]

If no path is given it defaults to the Windows Downloads path via WSL.

GameEvent no longer stores its own start_date/end_date -- dates are derived
entirely from a linked BannerTimeline (see calculatorapi/predictions.py), so
each emitted event gets a `banner_timeline` id (or null) instead. That link
is resolved via (JP Start Date, name) against the already-generated
bannerTimelines.json -- CM/LoH rows (Banner Type -1) never resolve to one
(Champions Meeting/League of Heroes are a separate system; GameEvent never
derives dates from them), and neither do rows whose name has no single
matching banner (multi-Uma campaign-wide rows, etc.) -- those events are
simply left unlinked, which is expected, not an error.

Reward amounts (carat_amount, carats_throughout, ticket/shard amounts) live
directly on GameEvent -- there's no separate EventReward row/model. carat_amount
is the "Carat First Day" column (earned once the event's own resolved start_date
passes); carats_throughout is the "Carat Throughout" column (prorated across the
event's start_date..end_date by the frontend, see getThroughoutCaratsInWindow).
The CSV has no "Carat Last Day" column anymore -- that category was retired.

Two kinds of rows are skipped entirely (not emitted as GameEvents):
  - Champions Meeting / League of Heroes rows (Banner Type -1, identified by a
    "CM #"/"LoH #" tag rather than a distinct type value) -- those payouts are
    tracked by the separate ChampionsMeeting/LeagueOfHeroes models.
  - Placeholder rows with no Banner Uma AND no Banner Support (a calendar slot
    with nothing announced/decided yet).

The CSV's header row has "Global Start Date" listed twice (the second is
actually the end date) -- csv.DictReader would silently let the second
column overwrite the first, so date columns are read positionally instead.
"""

import csv
import json
import sys
from pathlib import Path

DEFAULT_CSV = Path(
    "/mnt/c/Users/Zac82/Downloads/Timeline Master 5.4+ - CSV Download.csv"
)
OUT_DIR = Path(__file__).parent.parent / "calculatorapi" / "fixtures"


def norm(name):
    return " ".join(name.split()).strip().lower()


def load_banner_timeline_lookup():
    """(jp_start_date as YYYY-MM-DD, normalized name) -> BannerTimeline pk,
    built from the already-generated bannerTimelines.json fixture."""
    with open(OUT_DIR / "bannerTimelines.json", encoding="utf-8") as f:
        banner_timelines = json.load(f)
    lookup = {}
    for b in banner_timelines:
        jp_start = b["fields"]["jp_start_date"]
        if not jp_start:
            continue
        lookup[(jp_start[:10], norm(b["fields"]["name"]))] = b["pk"]
    return lookup


def parse_int(value: str) -> int:
    """Return 0 for blank or non-numeric cells."""
    stripped = value.strip()
    if not stripped:
        return 0
    try:
        return int(stripped)
    except ValueError:
        return 0


def derive_name(row: dict, banner_type: int, start_date: str) -> str:
    """Build a human-readable event name from the CSV row."""
    uma = row.get("Banner Uma", "").strip()
    support = row.get("Banner Support", "").strip()

    if uma:
        return uma

    if support:
        # Type-2 rows sometimes have no Uma ID — use support names, truncated
        names = [s.strip() for s in support.split("+")]
        # Keep it short: first two names + ellipsis if there are more
        label = " + ".join(names[:2])
        if len(names) > 2:
            label += " +"
        return label

    return f"Event {start_date}"


def generate(csv_path: Path):
    banner_timeline_lookup = load_banner_timeline_lookup()

    events = []
    event_pk = 1
    skipped = 0

    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        header = next(reader)
        col_jp_start = header.index("JP Start Date")
        col_start_override = header.index("Start Date Override")
        col_end_override = header.index("End Date Override")
        col_global_start = 4  # first "Global Start Date" column (real start)
        col_global_end = 5  # second "Global Start Date" column (mislabeled end)
        raw_rows = list(reader)

    for r in raw_rows:
        # Dict access is fine for every column except the two ambiguous
        # "Global Start Date" columns, which collide by name -- those are
        # read positionally from the raw row instead.
        row = dict(zip(header, r))
        jp_start = r[col_jp_start].strip()
        # The Global Start/End Date columns are the sheet's own formula
        # estimate and are often not yet confirmed -- prefer the manually
        # entered Override column when present, falling back to the
        # estimate only when no override has been filled in.
        start = r[col_start_override].strip() or r[col_global_start].strip()
        end = r[col_end_override].strip() or r[col_global_end].strip()

        # Skip rows with missing dates
        if not start or not end:
            skipped += 1
            continue

        try:
            banner_type = int(row.get("Banner Type", "0").strip() or 0)
        except ValueError:
            banner_type = 0

        # Champions Meeting / League of Heroes rows are tracked entirely by
        # their own models (ChampionsMeeting/LeagueOfHeroes) -- skip
        # unconditionally. CM and LoH rows share Banner Type -1 and are only
        # distinguished by a "CM #"/"LoH #" tag, but neither ever becomes a
        # GameEvent.
        if banner_type == -1:
            skipped += 1
            continue

        uma_name = row.get("Banner Uma", "").strip()
        support_name = row.get("Banner Support", "").strip()

        # Placeholder rows: no banner has been announced/decided for this
        # calendar slot yet.
        if not uma_name and not support_name:
            skipped += 1
            continue

        carat_first = parse_int(row.get("Carat First Day", ""))
        carat_thru = parse_int(row.get("Carat Throughout", ""))
        uma_tix = parse_int(row.get("Tickets Uma", ""))
        sup_tix = parse_int(row.get("Tickets Support", ""))
        ssr_shard = parse_int(row.get("SSR Shard", ""))
        sr_shard = parse_int(row.get("SR Shard", ""))

        name = derive_name(row, banner_type, start)

        # Resolve banner_timeline via (JP Start Date, name); rows with no
        # single-banner name (multi-Uma campaign-wide rows) simply won't
        # match -- they stay unlinked (null dates), by design.
        banner_timeline_id = banner_timeline_lookup.get(
            (jp_start, norm(uma_name))
        ) or banner_timeline_lookup.get((jp_start, norm(support_name)))

        events.append(
            {
                "model": "calculatorapi.gameevent",
                "pk": event_pk,
                "fields": {
                    "name": name,
                    "image": None,
                    "banner_timeline": banner_timeline_id,
                    "carat_amount": carat_first,
                    "carats_throughout": carat_thru,
                    "support_ticket_amount": sup_tix,
                    "uma_ticket_amount": uma_tix,
                    "sr_shard_amount": sr_shard,
                    "sr_crystal_amount": 0,
                    "ssr_shard_amount": ssr_shard,
                    "ssr_crystal_amount": 0,
                },
            }
        )

        event_pk += 1

    return events, skipped


def main():
    csv_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_CSV

    if not csv_path.exists():
        print(f"Error: CSV not found at {csv_path}")
        sys.exit(1)

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Reading {csv_path} ...")
    events, skipped = generate(csv_path)

    events_path = OUT_DIR / "gameEvents.json"

    with open(events_path, "w", encoding="utf-8") as f:
        json.dump(events, f, indent=2, ensure_ascii=False)

    print("Done.")
    print(f"  GameEvents:   {len(events):>4}  → {events_path}")
    print(f"  Rows skipped: {skipped:>4}  (no dates, CM/LoH, or placeholder)")


if __name__ == "__main__":
    main()

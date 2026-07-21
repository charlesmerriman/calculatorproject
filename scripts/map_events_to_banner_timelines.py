"""
One-off script (not part of the numbered migration chain) that builds the
GameEvent -> BannerTimeline id mapping used to seed migration
0023_backfill_gameevent_banner_timeline.py.

Two-hop join:

  1. GameEvent <-> CSV row, matched by fuzzy name similarity (against both
     Banner Uma and Banner Support columns, ignoring parenthetical suffixes
     like "(Rerun)"/"(Anime)") with date-proximity to GameEvent.start_date as
     the tiebreaker/sanity check -- character names get reused across
     reruns, so name alone is ambiguous and date alone doesn't line up
     exactly (the app's existing dates have some pre-existing drift from
     this CSV).
  2. That CSV row's "JP Start Date" + Banner Uma/Support name <->
     bannerTimelines.json's jp_start_date + name, resolving to a
     BannerTimeline pk.

CSV rows with Banner Type -1 (CM #N / LoH #N) are excluded entirely --
GameEvent never derives dates from ChampionsMeeting/LeagueOfHeroes.

Usage: python scripts/map_events_to_banner_timelines.py <path-to-csv>
Prints the resulting {game_event_pk: banner_timeline_pk} dict plus an
unmatched-events report to stderr for manual review.
"""

import csv
import json
import re
import sys
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent.parent / "calculatorapi" / "fixtures"

# Two rows the CSV's own text encoding corrupts a "♡" character in (renders
# as "â¡"), which breaks the CSV-row -> BannerTimeline name lookup even
# though the underlying banner is an unambiguous match (same JP start date,
# same name once the mojibake is discounted). Confirmed by hand against
# bannerTimelines.json: pk22 "Kawakami Princess♡" (JP 2021-10-11), pk43
# "Ines Fujin ♡" (JP 2022-05-10).
MANUAL_OVERRIDES = {
    23: 22,   # GameEvent "Kawakami Princess♡" -> BannerTimeline "Kawakami Princess♡"
    44: 43,   # GameEvent "Ines Fujin♡" -> BannerTimeline "Ines Fujin ♡"
}


def load_json(name):
    with open(FIXTURES / name, encoding="utf-8") as f:
        return json.load(f)


def parse_dt(value):
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def parse_csv_date(value):
    if not value:
        return None
    return datetime.strptime(value.strip(), "%Y-%m-%d").date()


def norm(name):
    return " ".join(name.split()).strip().lower()


def _strip_parens(name):
    return re.sub(r"\s*\([^)]*\)", "", name).strip()


def name_similarity(a, b):
    """Best-of-two similarity: verbatim, and with parenthetical suffixes like
    "(Rerun)"/"(Anime)" stripped (reruns/variants often drop these when the
    GameEvent was named, even though the banner itself kept the suffix)."""
    return max(
        SequenceMatcher(None, a, b).ratio(),
        SequenceMatcher(None, _strip_parens(a), _strip_parens(b)).ratio(),
    )


def main(csv_path):
    banner_timelines = load_json("bannerTimelines.json")
    game_events = load_json("gameEvents.json")

    # (jp_start_date as date, normalized name) -> banner_timeline pk
    banner_by_jp_and_name = {}
    for b in banner_timelines:
        jp_start = parse_dt(b["fields"]["jp_start_date"])
        if jp_start is None:
            continue
        banner_by_jp_and_name[(jp_start.date(), norm(b["fields"]["name"]))] = b["pk"]

    # The header row has "Global Start Date" TWICE (the second is actually the
    # end date, per column order) -- csv.DictReader would silently let the
    # second overwrite the first, so we read positionally instead.
    with open(csv_path, encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        header = next(reader)
        rows = list(reader)
    COL_JP_START = header.index("JP Start Date")
    COL_GLOBAL_START = 4  # first "Global Start Date" column (real start)
    COL_BANNER_TYPE = header.index("Banner Type")
    COL_BANNER_UMA = header.index("Banner Uma")
    COL_BANNER_SUPPORT = header.index("Banner Support")

    # Build candidate CSV rows (excluding CM/LoH), each pre-resolved to a
    # BannerTimeline pk via hop 2 (JP Start Date + name -> bannerTimelines.json).
    candidates = []
    unresolvable_csv_rows = []
    for row in rows:
        if row[COL_BANNER_TYPE].strip() == "-1":
            continue  # CM/LoH rows are never GameEvent candidates
        jp_start = parse_csv_date(row[COL_JP_START])
        global_start = parse_csv_date(row[COL_GLOBAL_START])
        uma_name = row[COL_BANNER_UMA].strip()
        support_name = row[COL_BANNER_SUPPORT].strip()
        name = uma_name or support_name
        if jp_start is None or global_start is None or not name:
            continue
        banner_pk = banner_by_jp_and_name.get((jp_start, norm(name)))
        if banner_pk is None:
            unresolvable_csv_rows.append((jp_start, global_start, name))
            continue
        candidates.append(
            {
                "global_start": global_start,
                "uma_name": uma_name,
                "support_name": support_name,
                "banner_pk": banner_pk,
            }
        )

    # GameEvent -> CSV candidate row, matched by name similarity (character
    # names get reused across reruns, so name alone is ambiguous) with
    # date-proximity as the tiebreaker among close name scores, and a date
    # bound as a sanity check against matching the wrong-year rerun.
    NAME_SCORE_THRESHOLD = 0.9
    DATE_TOLERANCE_DAYS = 30

    mapping = {}
    unmatched = []
    for event in game_events:
        event_name = norm(event["fields"]["name"])
        start_date = parse_dt(event["fields"]["start_date"])
        best = None
        best_score = 0.0
        best_diff = None
        for candidate in candidates:
            score = max(
                name_similarity(event_name, norm(candidate["uma_name"])) if candidate["uma_name"] else 0.0,
                name_similarity(event_name, norm(candidate["support_name"])) if candidate["support_name"] else 0.0,
            )
            if score < NAME_SCORE_THRESHOLD:
                continue
            diff = abs((start_date.date() - candidate["global_start"]).days) if start_date else None
            if diff is not None and diff > DATE_TOLERANCE_DAYS:
                continue
            if best is None or score > best_score or (score == best_score and diff is not None and diff < best_diff):
                best, best_score, best_diff = candidate, score, diff

        if best is None:
            if event["pk"] in MANUAL_OVERRIDES:
                mapping[event["pk"]] = MANUAL_OVERRIDES[event["pk"]]
                continue
            unmatched.append((event["pk"], event["fields"]["name"], "no CSV/banner match"))
            continue
        mapping[event["pk"]] = best["banner_pk"]

    print(json.dumps(mapping, indent=4))

    print(f"\n--- matched {len(mapping)}/{len(game_events)} events ---", file=sys.stderr)
    print(f"--- {len(unmatched)} unmatched events ---", file=sys.stderr)
    for pk, name, reason in unmatched:
        print(f"  {pk}: {name!r} ({reason})", file=sys.stderr)
    if unresolvable_csv_rows:
        print(f"--- {len(unresolvable_csv_rows)} CSV rows with no BannerTimeline match ---", file=sys.stderr)
        for jp_start, global_start, name in unresolvable_csv_rows:
            print(f"  JP {jp_start} / Global {global_start}: {name!r}", file=sys.stderr)


if __name__ == "__main__":
    main(sys.argv[1])

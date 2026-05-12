"""
generate_event_fixtures.py

Parses the Uma Musume global timeline CSV and generates two Django fixture files:
  - calculatorapi/fixtures/gameEvents.json
  - calculatorapi/fixtures/eventRewards.json

Run from the backend/ directory:
    python scripts/generate_event_fixtures.py [path/to/csv]

If no path is given it defaults to the Windows Downloads path via WSL.
"""

import csv
import json
import sys
from pathlib import Path

DEFAULT_CSV = Path(
    "/mnt/c/Users/Zac82/Downloads/Timeline Master 4.511-5.0 - Filter Sheet (2).csv"
)
OUT_DIR = Path(__file__).parent.parent / "calculatorapi" / "fixtures"


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

    if banner_type == -1:
        return f"Champions Meeting {start_date}"

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


def make_reward(pk, event_pk, name, carat, uma_tix, sup_tix, ssr_shard, sr_shard, date):
    return {
        "model": "calculatorapi.eventreward",
        "pk": pk,
        "fields": {
            "event": event_pk,
            "name": name,
            "carat_amount": carat,
            "support_ticket_amount": sup_tix,
            "uma_ticket_amount": uma_tix,
            "sr_shard_amount": sr_shard,
            "sr_crystal_amount": 0,
            "ssr_shard_amount": ssr_shard,
            "ssr_crystal_amount": 0,
            "date": date,
        },
    }


def generate(csv_path: Path):
    events = []
    rewards = []
    event_pk = 1
    reward_pk = 1
    skipped = 0

    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            start = row.get("Global Start Date", "").strip()
            end = row.get("Global End Date", "").strip()

            # Skip rows with missing dates
            if not start or not end:
                skipped += 1
                continue

            try:
                banner_type = int(row.get("Banner Type", "0").strip() or 0)
            except ValueError:
                banner_type = 0

            carat_first = parse_int(row.get("Carat First Day", ""))
            carat_thru = parse_int(row.get("Carat Throughout", ""))
            carat_last = parse_int(row.get("Carat Last Day", ""))
            uma_tix = parse_int(row.get("Tickets Uma", ""))
            sup_tix = parse_int(row.get("Tickets Support", ""))
            ssr_shard = parse_int(row.get("SSR Shard", ""))
            sr_shard = parse_int(row.get("SR Shard", ""))

            has_rewards = any(
                [carat_first, carat_thru, carat_last, uma_tix, sup_tix, ssr_shard, sr_shard]
            )

            # Champions Meeting rows: only include when there are actual rewards
            # (carat payouts are already tracked via the ChampionsMeeting model)
            if banner_type == -1 and not has_rewards:
                skipped += 1
                continue

            name = derive_name(row, banner_type, start)

            events.append(
                {
                    "model": "calculatorapi.gameevent",
                    "pk": event_pk,
                    "fields": {
                        "name": name,
                        "image": None,
                        "start_date": f"{start}T00:00:00Z",
                        "end_date": f"{end}T00:00:00Z",
                    },
                }
            )

            # First-day EventReward (only when non-zero)
            if carat_first > 0:
                rewards.append(
                    make_reward(
                        reward_pk,
                        event_pk,
                        f"{name} Day 1 Bonus",
                        carat_first,
                        0,
                        0,
                        0,
                        0,
                        f"{start}T00:00:00Z",
                    )
                )
                reward_pk += 1

            # End-of-event EventReward (throughout + last-day carats + tickets + shards)
            end_carat = carat_thru + carat_last
            if any([end_carat, uma_tix, sup_tix, ssr_shard, sr_shard]):
                rewards.append(
                    make_reward(
                        reward_pk,
                        event_pk,
                        f"{name} Campaign Rewards",
                        end_carat,
                        uma_tix,
                        sup_tix,
                        ssr_shard,
                        sr_shard,
                        f"{end}T00:00:00Z",
                    )
                )
                reward_pk += 1

            event_pk += 1

    return events, rewards, skipped


def main():
    csv_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_CSV

    if not csv_path.exists():
        print(f"Error: CSV not found at {csv_path}")
        sys.exit(1)

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Reading {csv_path} ...")
    events, rewards, skipped = generate(csv_path)

    events_path = OUT_DIR / "gameEvents.json"
    rewards_path = OUT_DIR / "eventRewards.json"

    with open(events_path, "w", encoding="utf-8") as f:
        json.dump(events, f, indent=2, ensure_ascii=False)

    with open(rewards_path, "w", encoding="utf-8") as f:
        json.dump(rewards, f, indent=2, ensure_ascii=False)

    print(f"Done.")
    print(f"  GameEvents:   {len(events):>4}  → {events_path}")
    print(f"  EventRewards: {len(rewards):>4}  → {rewards_path}")
    print(f"  Rows skipped: {skipped:>4}  (no dates or CM with no rewards)")


if __name__ == "__main__":
    main()

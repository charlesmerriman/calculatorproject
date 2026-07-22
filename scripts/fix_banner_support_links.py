"""
fix_banner_support_links.py

Re-links calculatorapi.fixtures.supportsOnSupportBanner rows to the correct
SupportCard game_id variant.

Why this is needed: most characters have several SSR support cards released
over time (new game_id each time, same name). supportsOnSupportBanner.json
was originally populated before SupportCard had a game_id anchor, so
ambiguous links were effectively assigned by whichever same-named row the
admin's autocomplete happened to show first - in practice this meant nearly
every banner ended up linked to that character's *oldest* SSR card,
regardless of which one the banner actually featured.

The fix: a featured SSR card almost always debuts on the exact same day as
its banner. For each join row, look at the linked card's name, find every
SSR (game_id >= 30000) variant of that name, and if exactly one of them has
a source-data release_ja date equal to the banner's banner_timeline
jp_start_date, that's the correct card. Only auto-apply exact, unambiguous
date matches - anything else is left untouched and reported for manual
review rather than guessed at.

Special case: banners whose name contains "(Rerun)" intentionally re-feature
an existing card *after* its original release date, so date-matching would
incorrectly "correct" them. Those are left exactly as they already are.

Run from backend/:
    python scripts/fix_banner_support_links.py
"""

import json
from collections import defaultdict
from datetime import date
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent.parent / "calculatorapi" / "fixtures"
SOURCE_PATH = Path(__file__).parent / "data" / "support_cards_source.json"

SUPPORT_CARDS_PATH = FIXTURES_DIR / "supportCards.json"
BANNER_SUPPORTS_PATH = FIXTURES_DIR / "bannerSupports.json"
BANNER_TIMELINES_PATH = FIXTURES_DIR / "bannerTimelines.json"
JOIN_PATH = FIXTURES_DIR / "supportsOnSupportBanner.json"


def load(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    sc = load(SUPPORT_CARDS_PATH)
    bs = load(BANNER_SUPPORTS_PATH)
    bt = load(BANNER_TIMELINES_PATH)
    sob = load(JOIN_PATH)
    source = load(SOURCE_PATH)

    sc_by_pk = {r["pk"]: r["fields"] for r in sc}
    bs_by_pk = {r["pk"]: r["fields"] for r in bs}
    bt_by_pk = {r["pk"]: r["fields"] for r in bt}
    release_ja_by_game_id = {c["id"]: c.get("release_ja") for c in source}

    # name -> [(game_id, pk), ...] for SSR-rarity cards only (banners never
    # feature R/SR cards - confirmed every existing banner link is 30000+)
    ssr_variants_by_name: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for pk, fields in sc_by_pk.items():
        game_id = fields["game_id"]
        if game_id is not None and game_id >= 30000:
            ssr_variants_by_name[fields["name"]].append((game_id, pk))

    changes: list[tuple] = []
    unresolved: list[tuple] = []
    rerun_skipped = 0

    for row in sob:
        fields = row["fields"]
        banner = bs_by_pk[fields["banner_support"]]

        if "(Rerun)" in banner["name"]:
            rerun_skipped += 1
            continue

        current_pk = fields["support_card"]
        current_fields = sc_by_pk[current_pk]
        name = current_fields["name"]

        variants = ssr_variants_by_name.get(name, [])
        if len(variants) <= 1:
            continue  # only one possible card for this name - nothing to check

        jp_start = bt_by_pk[banner["banner_timeline"]]["jp_start_date"][:10]
        exact = [
            (gid, pk) for gid, pk in variants
            if release_ja_by_game_id.get(gid) == jp_start
        ]

        if len(exact) != 1:
            unresolved.append(
                (row["pk"], banner["name"], name, current_fields["game_id"], jp_start)
            )
            continue

        best_gid, best_pk = exact[0]
        if best_pk != current_pk:
            changes.append(
                (row["pk"], banner["name"], name, current_fields["game_id"], best_gid)
            )
            fields["support_card"] = best_pk

    if changes:
        JOIN_PATH.write_text(
            json.dumps(sob, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )

    print(f"{len(sob)} join rows checked, {rerun_skipped} rerun banner(s) skipped by name")
    print(f"\n{len(changes)} corrected (exact release-date match found a different card):")
    for join_pk, banner_name, card_name, old_gid, new_gid in changes:
        print(f"  join pk={join_pk:3d}  '{banner_name}'  {card_name}: {old_gid} -> {new_gid}")

    print(f"\n{len(unresolved)} left unchanged - no single exact date match, needs manual review:")
    for join_pk, banner_name, card_name, current_gid, jp_start in unresolved:
        print(f"  join pk={join_pk:3d}  '{banner_name}'  {card_name}: currently {current_gid}  (banner jp_start={jp_start})")


if __name__ == "__main__":
    main()

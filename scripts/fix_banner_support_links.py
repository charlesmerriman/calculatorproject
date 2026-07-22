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

The fix runs two tiers of date matching against each join row's linked
card name and its banner's banner_timeline jp_start_date, applying the
first one that produces a confident answer:

  Tier 1 (debut match): exactly one same-name SSR variant has a source-data
  release_ja equal to jp_start_date - the card debuted alongside this banner.

  Tier 2 (rerun match): no exact debut match, but among same-name SSR
  variants released on or before jp_start_date (a banner can't feature a
  card that doesn't exist yet), the most recently-released one beats the
  next-most-recent by at least 14 days. A tighter margin means two cards
  launched close together in time and there's no confident way to tell
  which one a later rerun banner is reusing, so it's left alone.

Anything neither tier resolves is left untouched and reported for manual
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


MIN_RERUN_MARGIN_DAYS = 14


def load(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def resolve(
    variants: list[tuple[int, int]],
    release_ja_by_game_id: dict[int, str | None],
    jp_start: str,
) -> tuple[int, int, str] | None:
    """
    Returns (game_id, pk, reason) for the confident match, or None.
    `variants` is [(game_id, pk), ...] for one card name.
    """
    exact = [
        (gid, pk) for gid, pk in variants
        if release_ja_by_game_id.get(gid) == jp_start
    ]
    if len(exact) == 1:
        return (*exact[0], "debut")

    jp_start_date = date.fromisoformat(jp_start)
    preceding = sorted(
        (
            (date.fromisoformat(release_ja_by_game_id[gid]), gid, pk)
            for gid, pk in variants
            if release_ja_by_game_id.get(gid) and date.fromisoformat(release_ja_by_game_id[gid]) <= jp_start_date
        ),
        reverse=True,
    )
    if not preceding:
        return None
    if len(preceding) > 1 and (preceding[0][0] - preceding[1][0]).days < MIN_RERUN_MARGIN_DAYS:
        return None  # two candidates launched too close together to tell apart
    _, best_gid, best_pk = preceding[0]
    return best_gid, best_pk, "rerun"


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
        result = resolve(variants, release_ja_by_game_id, jp_start)

        if result is None:
            unresolved.append(
                (row["pk"], banner["name"], name, current_fields["game_id"], jp_start)
            )
            continue

        best_gid, best_pk, reason = result
        if best_pk != current_pk:
            changes.append(
                (row["pk"], banner["name"], name, current_fields["game_id"], best_gid, reason)
            )
            fields["support_card"] = best_pk

    if changes:
        JOIN_PATH.write_text(
            json.dumps(sob, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )

    print(f"{len(sob)} join rows checked, {rerun_skipped} rerun banner(s) skipped by name")
    print(f"\n{len(changes)} corrected:")
    for join_pk, banner_name, card_name, old_gid, new_gid, reason in changes:
        print(f"  join pk={join_pk:3d}  '{banner_name}'  {card_name}: {old_gid} -> {new_gid}  ({reason})")

    print(f"\n{len(unresolved)} left unchanged - no confident match, needs manual review:")
    for join_pk, banner_name, card_name, current_gid, jp_start in unresolved:
        print(f"  join pk={join_pk:3d}  '{banner_name}'  {card_name}: currently {current_gid}  (banner jp_start={jp_start})")


if __name__ == "__main__":
    main()

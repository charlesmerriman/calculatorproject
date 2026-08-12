"""
Shared pieces for the commands that attach missing support cards to banners.

Two commands need the same three things — read the pipeline's master CSV, turn
a " + "-joined name list into SupportCard rows, and refuse rather than guess
when a name doesn't resolve. They live here so the two cannot drift apart.

MATCHING MIRRORS THE FIXTURE PIPELINE. `scripts/build_missing_banners.py`
already solves this problem when it generates fixtures, and if the two
disagreed the same CSV row would produce different links depending on which
path built it. So `normalize`, `ALIASES` and the collision rule below are
deliberate copies of that script's. **Change them together.** They are copied
rather than imported because `scripts/` is a standalone tool tree, not an
importable package inside the deployed app.

WHY NAMES ALONE ARE AMBIGUOUS: SupportCard.name is not unique, by design — see
the model's own note that "many characters have 2-3 support cards sharing the
exact same name (different rarities/reprints)". Production holds four rows
named exactly "Grass Wonder". `game_id` is the real identity, and the CSV
carries only names, so a collision has to be resolved by rule. The pipeline's
rule is LOWEST game_id, and this follows it.

WHY NOT FUZZY MATCHING: a similarity check offered "Hishi Miracle" as the
second-best match for "K.S. Miracle". Those are different cards. Normalization
plus an explicit alias table is as far as this goes; an unresolved name is
reported, never guessed at.
"""

import csv
import os
import re

from django.conf import settings

from calculatorapi.models import SupportCard

# The pipeline's master timeline, the same file build_missing_banners.py reads.
# Tracked in git and present on the deployed container, so a command may read it
# at runtime in production.
TIMELINE_MASTER = os.path.join(
    settings.BASE_DIR, "scripts", "data", "timeline_master.csv"
)

# The sheet's "Banner Type" code for a race-prep support rerun: one uma (usually)
# alongside ten support cards. See BannerCategory in models/banner_timeline.py.
RACE_PREP_BANNER_TYPE = "2"

# Sheet spellings that differ from the card names, keyed by NORMALIZED name.
# Copied from build_missing_banners.py — keep in step.
#
# "K.S. Miracle" needs no entry: normalize() drops the periods, so it and the
# card's own "K.S.Miracle" both collapse to "k s miracle".
ALIASES = {
    "tamano cross": "tamamo cross",
    "tazuna": "tazuna hayakawa",
}


def split_names(joined):
    """The CSV's " + "-joined lists, as a list of trimmed names."""
    return [part.strip() for part in (joined or "").split(" + ") if part.strip()]


def normalize(value):
    """Copied from build_missing_banners.py's `norm` — keep in step."""
    value = value.lower()
    value = re.sub(r"[.'’♡♥❤♪&]", " ", value)
    value = re.sub(r"[-_]", " ", value)
    value = re.sub(r"\b3\d{4}\b", " ", value)  # drop embedded support game ids
    return re.sub(r"\s+", " ", value).strip()


def strip_rerun(value):
    """Copied from build_missing_banners.py — keep in step."""
    return re.sub(r"\s*\(rerun\)\s*", " ", value, flags=re.I).strip()


def build_support_index():
    """
    Normalized name -> the SupportCard to use for it.

    Built once per run rather than queried per name: 290 links across 85 names
    would otherwise be 290 round trips. Collisions resolve to the LOWEST
    game_id, matching the fixture pipeline; a null game_id sorts as 0, exactly
    as `gid = r["fields"].get("game_id") or 0` does there.
    """
    index = {}
    for card in SupportCard.objects.all().only("id", "name", "game_id"):
        key = normalize(card.name)
        game_id = card.game_id or 0
        if key not in index or game_id < index[key][0]:
            index[key] = (game_id, card)
    return {key: card for key, (_, card) in index.items()}


def resolve_support_cards(names, index=None):
    """
    Map names to SupportCard rows.

    Returns (found, missing), `found` in input order. Tries the name as given
    and then with "(Rerun)" stripped, applying the alias table to each — the
    same two-step the pipeline uses.

    Looks at every SupportCard, not just those already on a banner: production
    holds 315 cards attached to nothing, and they are invisible to the public
    API. Resolving against the API alone would wrongly report them missing.
    """
    if index is None:
        index = build_support_index()

    found, missing = [], []
    for name in names:
        card = None
        for candidate in (name, strip_rerun(name)):
            key = normalize(candidate)
            key = ALIASES.get(key, key)
            card = index.get(key)
            if card:
                break
        if card:
            found.append(card)
        else:
            missing.append(name)
    return found, missing


def read_timeline_master(banner_type=None):
    """
    Rows of the master CSV, optionally filtered to one "Banner Type" code.

    The header repeats "Global Start Date" twice, so csv.DictReader collapses
    the pair and the second wins. Nothing here reads that column — matching is
    on JP start date, which is stable — but don't add a dependency on it
    without fixing the header first.
    """
    with open(TIMELINE_MASTER, newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    if banner_type is not None:
        rows = [row for row in rows if row["Banner Type"] == banner_type]
    return rows

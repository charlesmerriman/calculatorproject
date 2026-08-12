"""
Shared pieces for the commands that attach missing support cards to banners.

Two commands need the same three things — read the pipeline's master CSV, turn
a " + "-joined name list into SupportCard rows, and refuse rather than guess
when a name doesn't resolve. They live here so the two cannot drift apart.

WHY NOT FUZZY MATCHING: an earlier similarity check offered "Hishi Miracle" as
the second-best match for "K.S. Miracle". Those are different cards. Every name
here therefore resolves by exact (case-insensitive) match, with a small explicit
alias table for the handful of known spelling differences between the CSV and
the database. An unresolved name is reported and the row is skipped — nothing is
created, and nothing is linked on a guess.
"""

import csv
import os

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

# Spelling differences between timeline_master.csv and the SupportCard table.
# Deliberately tiny and hand-verified — this is not a place to be clever.
#
#   K.S. Miracle   the CSV spaces the initials, the card does not
#   Tamano Cross   a typo in the CSV; the character is Tamamo Cross
#   Tazuna         the card carries the trainer's full name
SUPPORT_NAME_ALIASES = {
    "k.s. miracle": "K.S.Miracle",
    "tamano cross": "Tamamo Cross",
    "tazuna": "Tazuna Hayakawa",
}


def split_names(joined):
    """The CSV's " + "-joined lists, as a list of trimmed names."""
    return [part.strip() for part in (joined or "").split(" + ") if part.strip()]


def resolve_support_cards(names):
    """
    Map names to SupportCard rows.

    Returns (found, missing) where `found` preserves the input order and
    `missing` holds the names with no row. Queries SupportCard directly rather
    than walking banners, so a card that exists but is not yet featured
    anywhere still resolves — that case is invisible to the public API and is
    exactly the kind of thing worth catching in a dry run.
    """
    found, missing = [], []
    for name in names:
        lookup = SUPPORT_NAME_ALIASES.get(name.lower(), name)
        card = SupportCard.objects.filter(name__iexact=lookup).first()
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

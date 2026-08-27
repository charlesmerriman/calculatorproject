"""
Patreon member-CSV import for the supporters list.

WHY THIS EXISTS AS ITS OWN NARROW PARSER
----------------------------------------
Patreon's member export is a wide, PII-heavy file: email, Discord handle,
Patreon user ID, postal address, phone, charge history and lifetime totals.
None of that belongs in this database, and the safest way to guarantee it never
lands there is to never read those columns at all.

`parse_patreon_csv` therefore names the three columns it wants and discards the
row's every other field before it is returned. There is no "extra data" dict
and no passthrough — if a future field is wanted it has to be added here
deliberately, which is the review point.

CONSENT
-------
An import NEVER sets `is_public`. New rows are created with the model default
(False, i.e. counted anonymously) and existing rows keep whatever the editor
chose. So re-importing the monthly export can add and remove supporters, but it
can never publish a name, and it can never un-publish one either.
"""

import csv
import io

from django import forms
from django.db import transaction

from .models import PatreonSupporter, PatreonTier

# The only three columns this importer will look at. Everything else in the
# Patreon export is billing or contact data — see the module docstring.
NAME_COLUMN = "Name"
TIER_COLUMN = "Tier"
STATUS_COLUMN = "Patron Status"
REQUIRED_COLUMNS = (NAME_COLUMN, TIER_COLUMN, STATUS_COLUMN)

# Patreon writes "Active patron", "Declined patron" or "Former patron".
ACTIVE_STATUS = "active patron"

# Gap left between generated tier orders so an editor can slot a new tier
# between two existing ones without renumbering the others.
TIER_ORDER_STEP = 10


class PatreonCsvImportForm(forms.Form):
    """Upload form for the members CSV."""

    csv_file = forms.FileField(
        label="Patreon members CSV",
        help_text=(
            "The members export from Patreon. Only the Name, Tier and Patron Status "
            "columns are read — email, Discord, address and payment columns are ignored "
            "and never stored."
        ),
    )
    deactivate_missing = forms.BooleanField(
        required=False,
        initial=False,
        label="Deactivate supporters missing from this file",
        help_text=(
            "Only tick this for a COMPLETE export. A partial or filtered file would "
            "otherwise deactivate everyone it happens to omit."
        ),
    )
    dry_run = forms.BooleanField(
        required=False,
        initial=True,
        label="Preview only (don't save)",
        help_text="Shows exactly what would change without writing anything.",
    )


def parse_patreon_csv(uploaded_file):
    """Read the CSV down to `(display_name, tier_name, is_active)` triples.

    Raises ValueError with a human-readable message for anything an editor can
    fix themselves (wrong file, missing column).
    """
    # utf-8-sig strips the BOM Excel adds when a CSV is opened and re-saved,
    # which would otherwise corrupt the first header into "﻿Name".
    raw_bytes = uploaded_file.read()
    try:
        text = raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError(
            "That file isn't UTF-8 text. Re-download the export from Patreon "
            "rather than re-saving it from a spreadsheet app."
        ) from exc

    reader = csv.DictReader(io.StringIO(text))
    fieldnames = reader.fieldnames or []
    missing = [column for column in REQUIRED_COLUMNS if column not in fieldnames]
    if missing:
        raise ValueError(
            "This doesn't look like a Patreon members export — missing column(s): "
            + ", ".join(missing)
        )

    rows = []
    seen = set()
    for record in reader:
        # Only these three keys are ever touched. `record` is dropped here.
        name = (record.get(NAME_COLUMN) or "").strip()
        if not name:
            # A patron with no name can't be thanked and can't be matched to an
            # existing row; counting them would also double-count on re-import.
            continue
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        rows.append({
            # Truncated to the model's max_length rather than raising: a name
            # over 100 characters is a display problem, not an import failure.
            "display_name": name[:100],
            "tier_name": (record.get(TIER_COLUMN) or "").strip(),
            "is_active": (record.get(STATUS_COLUMN) or "").strip().casefold() == ACTIVE_STATUS,
        })
    return rows


def _resolve_tier(tier_name, tiers_by_name, created_tiers):
    """Find or create the tier, caching by casefolded name."""
    if not tier_name:
        return None
    key = tier_name.casefold()
    tier = tiers_by_name.get(key)
    if tier is None:
        # New tiers land at the bottom; the editor reorders them afterwards.
        # Their pledge order isn't inferable from the CSV (see PatreonTier).
        next_order = (
            max((existing.order for existing in tiers_by_name.values()), default=0)
            + TIER_ORDER_STEP
        )
        tier = PatreonTier.objects.create(name=tier_name, order=next_order)
        tiers_by_name[key] = tier
        created_tiers.append(tier.name)
    return tier


@transaction.atomic
def apply_patreon_import(rows, deactivate_missing=False, dry_run=False):
    """Reconcile parsed rows against the table. Returns a summary dict.

    Matching is on casefolded `display_name`, the same key as the model's
    uniqueness constraint, so a re-import updates rather than duplicating.
    """
    summary = {
        "created": [],
        "reactivated": [],
        "tier_changed": [],
        "deactivated": [],
        "unchanged": 0,
        "tiers_created": [],
    }

    tiers_by_name = {tier.name.casefold(): tier for tier in PatreonTier.objects.all()}
    existing = {
        supporter.display_name.casefold(): supporter
        for supporter in PatreonSupporter.objects.select_related("tier")
    }

    seen_keys = set()
    for row in rows:
        key = row["display_name"].casefold()
        seen_keys.add(key)
        tier = _resolve_tier(row["tier_name"], tiers_by_name, summary["tiers_created"])
        supporter = existing.get(key)

        if supporter is None:
            # NOTE: is_public is left at the model default (False). An import
            # must never publish a name — see the module docstring.
            PatreonSupporter.objects.create(
                display_name=row["display_name"],
                tier=tier,
                is_active=row["is_active"],
            )
            summary["created"].append(row["display_name"])
            continue

        changed_fields = []
        if supporter.tier_id != (tier.id if tier else None):
            supporter.tier = tier
            changed_fields.append("tier")
            summary["tier_changed"].append(supporter.display_name)
        if supporter.is_active != row["is_active"]:
            supporter.is_active = row["is_active"]
            changed_fields.append("is_active")
            if row["is_active"]:
                summary["reactivated"].append(supporter.display_name)
            else:
                summary["deactivated"].append(supporter.display_name)
        if changed_fields:
            supporter.save(update_fields=changed_fields)
        else:
            summary["unchanged"] += 1

    if deactivate_missing:
        for key, supporter in existing.items():
            if key in seen_keys or not supporter.is_active:
                continue
            supporter.is_active = False
            supporter.save(update_fields=["is_active"])
            summary["deactivated"].append(supporter.display_name)

    if dry_run:
        # Everything above ran for real inside this atomic block, so the
        # summary reflects exactly what a live run would do — then it is
        # rolled back. Cheaper and more honest than a parallel "what if" path
        # that could drift from the real one.
        transaction.set_rollback(True)

    return summary

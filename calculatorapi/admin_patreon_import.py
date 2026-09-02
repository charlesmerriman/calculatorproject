"""
Patreon member-CSV import for the supporters list, and the reconcile both import
paths share.

TWO PRODUCERS, ONE RECONCILE
----------------------------
`parse_patreon_csv` (here) and `patreon_api.fetch_members` both emit the same row
dicts, and both hand them to `apply_patreon_import`. Keeping the reconcile in one
place is what stops the manual and automatic paths drifting into treating the
same data differently — and means the consent rule below is stated once and holds
for both.

WHY THIS EXISTS AS ITS OWN NARROW PARSER
----------------------------------------
Patreon's member export is a wide, PII-heavy file: email, Discord handle,
Patreon user ID, postal address, phone, charge history and lifetime totals.
Almost none of that belongs in this database, and the safest way to guarantee
it never lands there is to never read those columns at all.

`parse_patreon_csv` therefore names the four columns it wants and discards the
row's every other field before it is returned. There is no "extra data" dict
and no passthrough — if a future field is wanted it has to be added here
deliberately, which is the review point.

Email is the one contact column that IS read, so an editor can tell two
supporters with similar or changed display names apart. It is admin-only and
excluded from the public serializer; see the field comment on PatreonSupporter.
Discord, user id, address, phone and every money column stay unread.

CONSENT
-------
An import NEVER sets `is_public`. New rows are created with the model default
(False, i.e. counted anonymously) and existing rows keep whatever the editor
chose. So re-importing the monthly export can add and remove supporters, but it
can never publish a name, and it can never un-publish one either.

This holds for the API sync too, which runs unattended on a schedule — so it is
the rule that keeps an automated job from publishing a real billing name at 6am
with nobody watching. Patreon has no field recording consent to be named on
someone else's website, so that decision cannot be automated from their data.
"""

import csv
import io

from django import forms
from django.db import transaction

from .models import PatreonSupporter, PatreonTier

# The only four columns this importer will look at. Everything else in the
# Patreon export is billing or contact data — see the module docstring.
NAME_COLUMN = "Name"
EMAIL_COLUMN = "Email"
TIER_COLUMN = "Tier"
STATUS_COLUMN = "Patron Status"
REQUIRED_COLUMNS = (NAME_COLUMN, TIER_COLUMN, STATUS_COLUMN)
# Email is read but NOT required: a file exported before this column existed, or
# one an editor trimmed by hand, must still import. A missing column simply
# leaves every row's email empty, which the reconcile reads as "don't know".
OPTIONAL_COLUMNS = (EMAIL_COLUMN,)

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
            "The members export from Patreon. Only the Name, Email, Tier and Patron "
            "Status columns are read — Discord, address and payment columns are ignored "
            "and never stored. The email is admin-only and never appears on the website."
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


class PatreonSyncForm(forms.Form):
    """Options for the API sync. No file — the server fetches the list itself."""

    # Defaults the OPPOSITE way to the CSV form's equivalent, and the difference
    # is deliberate: an uploaded file might have been filtered, but a paginated
    # API response is the complete member list, so a supporter it omits has
    # genuinely lapsed. See sync_patreon_supporters.py.
    deactivate_missing = forms.BooleanField(
        required=False,
        initial=True,
        label="Deactivate supporters Patreon no longer lists",
        help_text=(
            "Recommended. Patreon returns every member, so anyone missing from the "
            "response has cancelled. Untick only if you keep supporters here that "
            "Patreon doesn't know about."
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
        # Only these four keys are ever touched. `record` is dropped here.
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
            # Absent column or empty cell both give "", which the reconcile
            # treats as "don't know" rather than "clear the stored one".
            "email": (record.get(EMAIL_COLUMN) or "").strip(),
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


def _update_supporter(supporter, row, tier, summary):
    """Bring one existing supporter into line with its row.

    Returns True if anything was written. Note what is NOT here: `is_public` is
    never assigned, on any path. That is the consent rule in the module
    docstring, and it holds for the unattended API sync as much as for a manual
    upload.
    """
    changed_fields = []

    if supporter.tier_id != (tier.id if tier else None):
        supporter.tier = tier
        changed_fields.append("tier")
        summary["tier_changed"].append(supporter.display_name)

    if supporter.is_active != row["is_active"]:
        supporter.is_active = row["is_active"]
        changed_fields.append("is_active")
        bucket = "reactivated" if row["is_active"] else "deactivated"
        summary[bucket].append(supporter.display_name)

    # Unlike `patron_since` below, email IS overwritten: a patron who changes
    # their billing address on Patreon should show the new one here, and there
    # is no editorial judgement to preserve — nobody hand-corrects an email to
    # something Patreon disagrees with. But an EMPTY incoming value never wins:
    # a file with no Email column, or a member Patreon gave us no address for,
    # means "don't know", so the stored value stays.
    incoming_email = (row.get("email") or "").strip()
    if incoming_email and supporter.email != incoming_email:
        supporter.email = incoming_email
        changed_fields.append("email")
        summary["emails_updated"].append(supporter.display_name)

    # Fill only, never overwrite. Patreon is authoritative about when a pledge
    # started, but this field is also editable by hand, and a date an editor
    # corrected (a patron who resubscribed, say) should not be reset to
    # Patreon's version on the next sync. A row with no `patron_since` key at
    # all — every CSV row — means "don't know", never "clear it".
    if row.get("patron_since") and supporter.patron_since is None:
        supporter.patron_since = row["patron_since"]
        changed_fields.append("patron_since")
        summary["dates_filled"].append(supporter.display_name)

    if not changed_fields:
        return False
    supporter.save(update_fields=changed_fields)
    return True


@transaction.atomic
def apply_patreon_import(rows, deactivate_missing=False, dry_run=False):
    """Reconcile parsed rows against the table. Returns a summary dict.

    Matching is on casefolded `display_name`, the same key as the model's
    uniqueness constraint, so a re-import updates rather than duplicating.

    Rows come from either source — `parse_patreon_csv` or `patreon_api.fetch_members`
    — and carry the same keys, with one optional extra: the API knows each
    patron's pledge start date and the CSV does not. A row may therefore include
    `patron_since`; a row without the key leaves the stored value alone.

    `email` behaves the same way when it is empty (an older CSV export has no
    such column, and Patreon does not always have an address for a member), but
    a NON-empty one overwrites — see _update_supporter.
    """
    summary = {
        "created": [],
        "reactivated": [],
        "tier_changed": [],
        "deactivated": [],
        "dates_filled": [],
        "emails_updated": [],
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
                # "" when the source had no email for them — the model's own
                # default, and a legitimate state for a hand-entered supporter.
                email=row.get("email") or "",
                tier=tier,
                is_active=row["is_active"],
                patron_since=row.get("patron_since"),
            )
            summary["created"].append(row["display_name"])
            continue

        if not _update_supporter(supporter, row, tier, summary):
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

"""
Backfills AnniversaryEvent.jp_cutoff_date for the campaigns the source sheet
never gave one for.

0033 added the column, and only the five campaigns with an explicit "Cutoff
Date" row on the sheet (3rd, 3.5th, 4th, 4.5th, 5th anniversaries) were seeded
with a value. Every other campaign was left null -- and null means UNRESTRICTED
to both eligibility checks (calculatorapi.eligibility.is_eligible and the
frontend's isCardEligible), so their selectors offered every card ever released
rather than only those predating the campaign. That is the whole point of a
selector, so a wrong-by-a-few-days cutoff beats no cutoff.

The values match seed_anniversary_campaigns.CAMPAIGNS and are derived there as
Part 1's JP start date minus 14 days; see that module's ASSUMED CUTOFFS note for
the derivation and its corroboration. They are assumptions, not sourced facts.

Deliberately conservative in the same shape as 0032: only rows still sitting at
null are touched, so a rerun -- or a squash replayed after an editor has since
set a real cutoff in the admin -- cannot clobber a hand-corrected value. A
campaign whose name is not in the map is left alone rather than guessed at.
"""

import datetime

from django.db import migrations

# Campaign name -> assumed JP cutoff. Keep in step with CAMPAIGNS in
# calculatorapi/management/commands/seed_anniversary_campaigns.py.
ASSUMED_CUTOFFS = {
    "0.5th Anniversary": datetime.date(2021, 8, 2),
    "1st Anniversary": datetime.date(2022, 1, 31),
    "1.5th Anniversary": datetime.date(2022, 8, 2),
    "2nd Anniversary": datetime.date(2023, 1, 31),
    "2.5th Anniversary": datetime.date(2023, 7, 31),
    "Trainer Support Pack": datetime.date(2023, 9, 21),
    "New Years 2024": datetime.date(2023, 12, 14),
    "New Years 2025": datetime.date(2024, 12, 13),
    "New Years 2026": datetime.date(2025, 12, 12),
}


def backfill_cutoffs(apps, schema_editor):
    AnniversaryEvent = apps.get_model("calculatorapi", "AnniversaryEvent")
    to_update = []
    for event in AnniversaryEvent.objects.filter(jp_cutoff_date__isnull=True):
        cutoff = ASSUMED_CUTOFFS.get(event.name)
        if cutoff is None:
            continue
        event.jp_cutoff_date = cutoff
        to_update.append(event)
    if to_update:
        AnniversaryEvent.objects.bulk_update(to_update, ["jp_cutoff_date"])


def clear_cutoffs(apps, schema_editor):
    """Restore the post-0033 state for exactly the rows this migration set.

    Matched on the assumed value as well as the name, so a cutoff an editor has
    since corrected in the admin survives a reverse instead of being wiped.
    """
    AnniversaryEvent = apps.get_model("calculatorapi", "AnniversaryEvent")
    for name, cutoff in ASSUMED_CUTOFFS.items():
        AnniversaryEvent.objects.filter(
            name=name, jp_cutoff_date=cutoff
        ).update(jp_cutoff_date=None)


class Migration(migrations.Migration):

    dependencies = [
        ("calculatorapi", "0033_anniversaryevent_and_more"),
    ]

    operations = [
        migrations.RunPython(backfill_cutoffs, clear_cutoffs),
    ]

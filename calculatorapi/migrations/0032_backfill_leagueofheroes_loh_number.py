"""
Backfills LeagueOfHeroes.loh_number for rows that predate the column.

0031 added the field with default=0, so every existing row landed on 0 — an
in-game LoH is never "league 0", so 0 reads as "unset". The names are already
canonical ("League of Heroes 12"), so the number is recoverable from the trailing
integer without anyone re-keying 15 rows in the admin.

Deliberately conservative: only rows still sitting at 0 are touched (so a rerun,
or a squash replayed after an editor has since set numbers by hand, can't clobber
real data), and a name with no trailing integer is skipped rather than guessed at
from row order — a wrong number is worse than a blank one an editor can spot.
"""

import re

from django.db import migrations

TRAILING_NUMBER = re.compile(r"(\d+)\s*$")


def backfill_loh_number(apps, schema_editor):
    LeagueOfHeroes = apps.get_model("calculatorapi", "LeagueOfHeroes")
    to_update = []
    for event in LeagueOfHeroes.objects.filter(loh_number=0):
        match = TRAILING_NUMBER.search(event.name or "")
        if match is None:
            continue
        event.loh_number = int(match.group(1))
        to_update.append(event)
    if to_update:
        LeagueOfHeroes.objects.bulk_update(to_update, ["loh_number"])


def unset_loh_number(apps, schema_editor):
    # Reversing restores the post-0031 state (everything unset). Safe because
    # 0031's reverse drops the column outright anyway.
    LeagueOfHeroes = apps.get_model("calculatorapi", "LeagueOfHeroes")
    LeagueOfHeroes.objects.update(loh_number=0)


class Migration(migrations.Migration):

    dependencies = [
        ("calculatorapi", "0031_leagueofheroes_direction_leagueofheroes_distance_and_more"),
    ]

    operations = [
        migrations.RunPython(backfill_loh_number, unset_loh_number),
    ]

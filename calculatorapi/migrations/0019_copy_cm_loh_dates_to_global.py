from django.db import migrations


def _copy_to_global(model):
    # Existing rows hold CONFIRMED global dates, so copy the old start_date/
    # end_date into the new global_* fields. JP dates stay null and are
    # backfilled later in the admin.
    rows = list(model.objects.all())
    for row in rows:
        row.global_start_date = row.start_date
        row.global_end_date = row.end_date
    if rows:
        model.objects.bulk_update(rows, ["global_start_date", "global_end_date"])


def _copy_from_global(model):
    # Reversible: copy the global dates back into the old columns (which still
    # exist at this historical migration state, before 0020 removes them).
    rows = list(model.objects.all())
    for row in rows:
        row.start_date = row.global_start_date
        row.end_date = row.global_end_date
    if rows:
        model.objects.bulk_update(rows, ["start_date", "end_date"])


def forwards(apps, schema_editor):
    _copy_to_global(apps.get_model("calculatorapi", "ChampionsMeeting"))
    _copy_to_global(apps.get_model("calculatorapi", "LeagueOfHeroes"))


def backwards(apps, schema_editor):
    _copy_from_global(apps.get_model("calculatorapi", "ChampionsMeeting"))
    _copy_from_global(apps.get_model("calculatorapi", "LeagueOfHeroes"))


class Migration(migrations.Migration):

    dependencies = [
        ("calculatorapi", "0018_add_cm_loh_jp_global_dates"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]

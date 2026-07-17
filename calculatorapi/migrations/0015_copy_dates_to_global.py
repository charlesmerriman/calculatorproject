from django.db import migrations


def forwards(apps, schema_editor):
    # Existing rows hold CONFIRMED global dates, so copy the old start_date/
    # end_date into the new global_* fields. JP dates stay null and are
    # backfilled later in the admin.
    BannerTimeline = apps.get_model("calculatorapi", "BannerTimeline")
    rows = list(BannerTimeline.objects.all())
    for row in rows:
        row.global_start_date = row.start_date
        row.global_end_date = row.end_date
    if rows:
        BannerTimeline.objects.bulk_update(rows, ["global_start_date", "global_end_date"])


def backwards(apps, schema_editor):
    # Reversible: copy the global dates back into the old columns (which still
    # exist at this historical migration state, before 0016 removes them).
    BannerTimeline = apps.get_model("calculatorapi", "BannerTimeline")
    rows = list(BannerTimeline.objects.all())
    for row in rows:
        row.start_date = row.global_start_date
        row.end_date = row.global_end_date
    if rows:
        BannerTimeline.objects.bulk_update(rows, ["start_date", "end_date"])


class Migration(migrations.Migration):

    dependencies = [
        ("calculatorapi", "0014_add_jp_global_dates"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]

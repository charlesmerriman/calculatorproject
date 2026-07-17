from django.db import migrations, models


class Migration(migrations.Migration):
    """
    Adds the JP and global date fields to BannerTimeline (all nullable).
    The existing start_date/end_date are copied into global_* by 0015 and
    removed by 0016 — split across three migrations so the destructive
    removal only lands after the data copy is proven, and rollback is clean.
    """

    dependencies = [
        ("calculatorapi", "0013_alter_bannersupport_options_alter_banneruma_options_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="bannertimeline",
            name="jp_start_date",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="bannertimeline",
            name="jp_end_date",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="bannertimeline",
            name="global_start_date",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="bannertimeline",
            name="global_end_date",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]

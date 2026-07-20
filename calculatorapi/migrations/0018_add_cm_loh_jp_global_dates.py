from django.db import migrations, models


class Migration(migrations.Migration):
    """
    Adds the JP and global date fields to ChampionsMeeting and LeagueOfHeroes
    (all nullable), mirroring the BannerTimeline change in 0014. The existing
    start_date/end_date are copied into global_* by 0019 and removed by 0020 —
    split across three migrations so the destructive removal only lands after
    the data copy is proven, and rollback is clean.
    """

    dependencies = [
        ("calculatorapi", "0017_changelogentry_changelogchange"),
    ]

    operations = [
        migrations.AddField(
            model_name="championsmeeting",
            name="jp_start_date",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="championsmeeting",
            name="jp_end_date",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="championsmeeting",
            name="global_start_date",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="championsmeeting",
            name="global_end_date",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="leagueofheroes",
            name="jp_start_date",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="leagueofheroes",
            name="jp_end_date",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="leagueofheroes",
            name="global_start_date",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="leagueofheroes",
            name="global_end_date",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]

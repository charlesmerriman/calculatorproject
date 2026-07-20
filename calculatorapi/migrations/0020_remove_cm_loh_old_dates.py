from django.db import migrations


class Migration(migrations.Migration):
    """Removes the old start_date/end_date columns from ChampionsMeeting and
    LeagueOfHeroes now that 0019 copied their values into the global_* fields."""

    dependencies = [
        ("calculatorapi", "0019_copy_cm_loh_dates_to_global"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="championsmeeting",
            name="start_date",
        ),
        migrations.RemoveField(
            model_name="championsmeeting",
            name="end_date",
        ),
        migrations.RemoveField(
            model_name="leagueofheroes",
            name="start_date",
        ),
        migrations.RemoveField(
            model_name="leagueofheroes",
            name="end_date",
        ),
    ]

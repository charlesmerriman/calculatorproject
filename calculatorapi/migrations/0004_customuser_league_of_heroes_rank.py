from django.db import migrations


class Migration(migrations.Migration):
    """
    Production DB had 0001_initial applied before league_of_heroes_rank was
    added to CustomUser, so the column was never created. This migration adds
    it with IF NOT EXISTS so it's a no-op on local DBs where the column
    already exists.
    """

    dependencies = [
        ("calculatorapi", "0003_leagueofheroes"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                ALTER TABLE calculatorapi_customuser
                ADD COLUMN IF NOT EXISTS league_of_heroes_rank_id bigint
                REFERENCES calculatorapi_leagueofheroesrank(id) ON DELETE SET NULL;
            """,
            reverse_sql="""
                ALTER TABLE calculatorapi_customuser
                DROP COLUMN IF EXISTS league_of_heroes_rank_id;
            """,
        ),
    ]

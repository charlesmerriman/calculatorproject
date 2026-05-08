from django.db import migrations


class Migration(migrations.Migration):
    """
    sr_shards, sr_crystals, ssr_shards, and ssr_crystals were backfilled into
    0001_initial after production had already applied it, so those columns do
    not exist in the prod DB. Uses IF NOT EXISTS so this is a no-op locally.
    """

    dependencies = [
        ("calculatorapi", "0004_customuser_league_of_heroes_rank"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                ALTER TABLE calculatorapi_customuser
                ADD COLUMN IF NOT EXISTS sr_shards integer NOT NULL DEFAULT 0;

                ALTER TABLE calculatorapi_customuser
                ADD COLUMN IF NOT EXISTS sr_crystals integer NOT NULL DEFAULT 0;

                ALTER TABLE calculatorapi_customuser
                ADD COLUMN IF NOT EXISTS ssr_shards integer NOT NULL DEFAULT 0;

                ALTER TABLE calculatorapi_customuser
                ADD COLUMN IF NOT EXISTS ssr_crystals integer NOT NULL DEFAULT 0;
            """,
            reverse_sql="""
                ALTER TABLE calculatorapi_customuser
                DROP COLUMN IF EXISTS sr_shards;

                ALTER TABLE calculatorapi_customuser
                DROP COLUMN IF EXISTS sr_crystals;

                ALTER TABLE calculatorapi_customuser
                DROP COLUMN IF EXISTS ssr_shards;

                ALTER TABLE calculatorapi_customuser
                DROP COLUMN IF EXISTS ssr_crystals;
            """,
        ),
    ]

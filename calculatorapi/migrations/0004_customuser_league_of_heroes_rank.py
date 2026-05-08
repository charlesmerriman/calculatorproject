from django.db import migrations


class Migration(migrations.Migration):
    """
    Both LeagueOfHeroesRank and the league_of_heroes_rank FK on CustomUser
    were backfilled into 0001_initial instead of generating new migrations.
    Production had already applied 0001_initial without either, so neither
    the table nor the column exist there.

    This migration creates both with IF NOT EXISTS guards so it is a no-op
    on local DBs that already have them.
    """

    dependencies = [
        ("calculatorapi", "0003_leagueofheroes"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                CREATE TABLE IF NOT EXISTS calculatorapi_leagueofheroesrank (
                    id bigserial PRIMARY KEY,
                    name varchar(255) NOT NULL,
                    income_amount integer NOT NULL
                );

                ALTER TABLE calculatorapi_customuser
                ADD COLUMN IF NOT EXISTS league_of_heroes_rank_id bigint
                REFERENCES calculatorapi_leagueofheroesrank(id) ON DELETE SET NULL;
            """,
            reverse_sql="""
                ALTER TABLE calculatorapi_customuser
                DROP COLUMN IF EXISTS league_of_heroes_rank_id;

                DROP TABLE IF EXISTS calculatorapi_leagueofheroesrank;
            """,
        ),
    ]

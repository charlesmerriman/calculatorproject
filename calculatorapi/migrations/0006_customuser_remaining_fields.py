from django.db import migrations


class Migration(migrations.Migration):
    """
    Several CustomUser fields were backfilled into 0001_initial after
    production had already applied it. This migration adds all remaining
    custom fields with IF NOT EXISTS so it is safe on local DBs that
    already have them.

    Fields already covered by earlier migrations are excluded:
      - training_pass (0002)
      - league_of_heroes_rank_id (0004)
      - sr_shards/sr_crystals/ssr_shards/ssr_crystals (0005)
    """

    dependencies = [
        ("calculatorapi", "0005_customuser_shard_fields"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                ALTER TABLE calculatorapi_customuser
                ADD COLUMN IF NOT EXISTS daily_carat boolean NOT NULL DEFAULT false;

                ALTER TABLE calculatorapi_customuser
                ADD COLUMN IF NOT EXISTS current_carat integer NOT NULL DEFAULT 0;

                ALTER TABLE calculatorapi_customuser
                ADD COLUMN IF NOT EXISTS current_paid_carat integer NOT NULL DEFAULT 0;

                ALTER TABLE calculatorapi_customuser
                ADD COLUMN IF NOT EXISTS uma_ticket integer NOT NULL DEFAULT 0;

                ALTER TABLE calculatorapi_customuser
                ADD COLUMN IF NOT EXISTS support_ticket integer NOT NULL DEFAULT 0;

                ALTER TABLE calculatorapi_customuser
                ADD COLUMN IF NOT EXISTS club_rank_id bigint
                REFERENCES calculatorapi_clubrank(id) ON DELETE SET NULL;

                ALTER TABLE calculatorapi_customuser
                ADD COLUMN IF NOT EXISTS team_trials_rank_id bigint
                REFERENCES calculatorapi_teamtrialsrank(id) ON DELETE SET NULL;

                ALTER TABLE calculatorapi_customuser
                ADD COLUMN IF NOT EXISTS champions_meeting_rank_id bigint
                REFERENCES calculatorapi_championsmeetingrank(id) ON DELETE SET NULL;
            """,
            reverse_sql="""
                ALTER TABLE calculatorapi_customuser DROP COLUMN IF EXISTS daily_carat;
                ALTER TABLE calculatorapi_customuser DROP COLUMN IF EXISTS current_carat;
                ALTER TABLE calculatorapi_customuser DROP COLUMN IF EXISTS current_paid_carat;
                ALTER TABLE calculatorapi_customuser DROP COLUMN IF EXISTS uma_ticket;
                ALTER TABLE calculatorapi_customuser DROP COLUMN IF EXISTS support_ticket;
                ALTER TABLE calculatorapi_customuser DROP COLUMN IF EXISTS club_rank_id;
                ALTER TABLE calculatorapi_customuser DROP COLUMN IF EXISTS team_trials_rank_id;
                ALTER TABLE calculatorapi_customuser DROP COLUMN IF EXISTS champions_meeting_rank_id;
            """,
        ),
    ]

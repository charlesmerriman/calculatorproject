from django.db import migrations


def forwards(apps, schema_editor):
    # SQLite already has these columns from 0001_initial; only prod PostgreSQL
    # needs them patched in because 0007's CREATE TABLE IF NOT EXISTS silently
    # skipped the already-existing table (created before these fields existed).
    if schema_editor.connection.vendor != 'postgresql':
        return
    schema_editor.execute("""
        ALTER TABLE calculatorapi_eventreward
        ADD COLUMN IF NOT EXISTS sr_shard_amount integer NOT NULL DEFAULT 0;

        ALTER TABLE calculatorapi_eventreward
        ADD COLUMN IF NOT EXISTS sr_crystal_amount integer NOT NULL DEFAULT 0;

        ALTER TABLE calculatorapi_eventreward
        ADD COLUMN IF NOT EXISTS ssr_shard_amount integer NOT NULL DEFAULT 0;

        ALTER TABLE calculatorapi_eventreward
        ADD COLUMN IF NOT EXISTS ssr_crystal_amount integer NOT NULL DEFAULT 0;
    """)


def backwards(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    schema_editor.execute("""
        ALTER TABLE calculatorapi_eventreward DROP COLUMN IF EXISTS sr_shard_amount;
        ALTER TABLE calculatorapi_eventreward DROP COLUMN IF EXISTS sr_crystal_amount;
        ALTER TABLE calculatorapi_eventreward DROP COLUMN IF EXISTS ssr_shard_amount;
        ALTER TABLE calculatorapi_eventreward DROP COLUMN IF EXISTS ssr_crystal_amount;
    """)


class Migration(migrations.Migration):
    """
    Production's calculatorapi_eventreward table was created before the shard/
    crystal fields were added to the model, and 0007's CREATE TABLE IF NOT EXISTS
    skipped the already-existing table. This patches the four missing columns in.
    """

    dependencies = [
        ("calculatorapi", "0009_add_event_id_to_eventreward"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]

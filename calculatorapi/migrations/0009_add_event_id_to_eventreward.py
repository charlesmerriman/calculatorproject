from django.db import migrations


def forwards(apps, schema_editor):
    # SQLite already has this column from 0001_initial; only prod PostgreSQL
    # needs it patched in because 0007's CREATE TABLE IF NOT EXISTS silently
    # skipped the already-existing table (created before the event FK existed).
    if schema_editor.connection.vendor != 'postgresql':
        return
    schema_editor.execute("""
        ALTER TABLE calculatorapi_eventreward
        ADD COLUMN IF NOT EXISTS event_id bigint NULL
        REFERENCES calculatorapi_gameevent(id) ON DELETE CASCADE;
    """)


def backwards(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    schema_editor.execute("""
        ALTER TABLE calculatorapi_eventreward DROP COLUMN IF EXISTS event_id;
    """)


class Migration(migrations.Migration):
    """
    Production's calculatorapi_eventreward table was created before the event
    FK was added, and 0007's CREATE TABLE IF NOT EXISTS skipped it, so event_id
    was never added. This migration patches the column onto the existing table.
    """

    dependencies = [
        ("calculatorapi", "0008_championsmeetingrank_sr_shard_amount_and_more"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]

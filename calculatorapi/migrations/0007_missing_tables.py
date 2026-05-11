from django.db import migrations


def forwards(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    schema_editor.execute("""
        CREATE TABLE IF NOT EXISTS calculatorapi_gameevent (
            id bigserial PRIMARY KEY,
            name varchar(255) NOT NULL,
            image varchar(200) NULL,
            start_date timestamp with time zone NOT NULL,
            end_date timestamp with time zone NOT NULL
        );

        CREATE TABLE IF NOT EXISTS calculatorapi_eventreward (
            id bigserial PRIMARY KEY,
            name varchar(255) NOT NULL,
            carat_amount integer NOT NULL DEFAULT 0,
            support_ticket_amount integer NOT NULL DEFAULT 0,
            uma_ticket_amount integer NOT NULL DEFAULT 0,
            sr_shard_amount integer NOT NULL DEFAULT 0,
            sr_crystal_amount integer NOT NULL DEFAULT 0,
            ssr_shard_amount integer NOT NULL DEFAULT 0,
            ssr_crystal_amount integer NOT NULL DEFAULT 0,
            date timestamp with time zone NOT NULL,
            event_id bigint NULL REFERENCES calculatorapi_gameevent(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS calculatorapi_championsmeeting (
            id bigserial PRIMARY KEY,
            name varchar(255) NOT NULL,
            cm_number integer NOT NULL,
            start_date timestamp with time zone NOT NULL,
            end_date timestamp with time zone NOT NULL,
            image varchar(200) NULL,
            track varchar(255) NOT NULL,
            surface_type varchar(255) NOT NULL,
            distance varchar(255) NOT NULL,
            length varchar(255) NOT NULL,
            track_condition varchar(255) NOT NULL,
            season varchar(255) NOT NULL,
            weather varchar(255) NOT NULL,
            direction varchar(255) NOT NULL,
            speed_recommendation integer NOT NULL,
            stamina_recommendation integer NOT NULL,
            power_recommendation integer NOT NULL,
            guts_recommendation integer NOT NULL,
            wit_recommendation integer NOT NULL
        );

        CREATE TABLE IF NOT EXISTS calculatorapi_championsmeetingumarecommendation (
            id bigserial PRIMARY KEY,
            champions_meeting_id bigint NOT NULL REFERENCES calculatorapi_championsmeeting(id) ON DELETE CASCADE,
            uma_id bigint NOT NULL REFERENCES calculatorapi_uma(id) ON DELETE CASCADE
        );
    """)


def backwards(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    schema_editor.execute("""
        DROP TABLE IF EXISTS calculatorapi_championsmeetingumarecommendation;
        DROP TABLE IF EXISTS calculatorapi_eventreward;
        DROP TABLE IF EXISTS calculatorapi_gameevent;
        DROP TABLE IF EXISTS calculatorapi_championsmeeting;
    """)


class Migration(migrations.Migration):
    """
    GameEvent, EventReward, ChampionsMeeting, and
    ChampionsMeetingUmaRecommendation were backfilled into 0001_initial
    after production had already applied it, so those tables do not exist
    in the prod DB. SQLite (test runner) skips entirely since 0001_initial
    already built the schema there.
    """

    dependencies = [
        ("calculatorapi", "0006_customuser_remaining_fields"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]

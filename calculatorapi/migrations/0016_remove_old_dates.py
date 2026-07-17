from django.db import migrations, models


class Migration(migrations.Migration):
    """Removes the old start_date/end_date columns now that 0015 copied their
    values into global_start_date/global_end_date."""

    dependencies = [
        ("calculatorapi", "0015_copy_dates_to_global"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="bannertimeline",
            name="start_date",
        ),
        migrations.RemoveField(
            model_name="bannertimeline",
            name="end_date",
        ),
    ]

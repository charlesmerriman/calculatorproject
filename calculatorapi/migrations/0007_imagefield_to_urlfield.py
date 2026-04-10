from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('calculatorapi', '0006_alter_bannersupport_banner_timeline_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='bannertimeline',
            name='image',
            field=models.URLField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='championsmeeting',
            name='image',
            field=models.URLField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='uma',
            name='image',
            field=models.URLField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='supportcard',
            name='image',
            field=models.URLField(blank=True, null=True),
        ),
    ]
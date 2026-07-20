from django.db import models

class ChampionsMeeting(models.Model):
    name = models.CharField(max_length=255, null=False)
    cm_number = models.IntegerField(verbose_name="meeting number")
    # JP server dates: always known well in advance (JP runs content first).
    # Nullable so historical rows migrated from the old schema (which only had
    # confirmed global dates) can be backfilled gradually in the admin.
    jp_start_date = models.DateTimeField(blank=True, null=True)
    jp_end_date = models.DateTimeField(blank=True, null=True)
    # Global server dates: only filled once the meeting is officially confirmed
    # (~1 month out). When null, the global dates are predicted from the JP
    # dates (see calculatorapi/predictions.py).
    global_start_date = models.DateTimeField(blank=True, null=True)
    global_end_date = models.DateTimeField(blank=True, null=True)
    image = models.ImageField(upload_to="champions_meetings/", blank=True, null=True)
    track = models.CharField(max_length=255)
    surface_type = models.CharField(max_length=255)
    distance = models.CharField(max_length=255)
    length = models.CharField(max_length=255)
    track_condition = models.CharField(max_length=255)
    season = models.CharField(max_length=255)
    weather = models.CharField(max_length=255)
    direction = models.CharField(max_length=255)
    speed_recommendation = models.IntegerField()
    stamina_recommendation = models.IntegerField()
    power_recommendation = models.IntegerField()
    guts_recommendation = models.IntegerField()
    wit_recommendation = models.IntegerField()

    class Meta:
        # Proper-noun casing (default capfirst would render "Champions meetings").
        verbose_name = "Champions Meeting"
        verbose_name_plural = "Champions Meetings"

    def __str__(self):
        return str(self.name)

from django.db import models

class ChampionsMeeting(models.Model):
    name = models.CharField(max_length=255, null=False)
    cm_number = models.IntegerField()
    start_date = models.DateTimeField()
    end_date = models.DateTimeField()
    image = models.URLField(blank=True, null=True)
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

    def __str__(self):
        return str(self.name)
    
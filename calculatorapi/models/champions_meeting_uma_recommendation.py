from django.db import models
from .uma import Uma
from .champions_meeting import ChampionsMeeting


class ChampionsMeetingUmaRecommendation(models.Model):
    uma = models.ForeignKey(Uma, on_delete=models.CASCADE)
    champions_meeting = models.ForeignKey(ChampionsMeeting, on_delete=models.CASCADE)

    class Meta:
        # Default would be "champions meeting uma recommendation object (N)" rows
        # under an unwieldy heading — this reads naturally in the admin.
        verbose_name = "recommended uma"
        verbose_name_plural = "recommended umas"

    def __str__(self):
        return f"{self.uma.name} — {self.champions_meeting.name}"

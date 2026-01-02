from django.db import models
from .uma import Uma
from .champions_meeting import ChampionsMeeting


class ChampionsMeetingUmaRecommendation(models.Model):
    uma = models.ForeignKey(Uma, on_delete=models.CASCADE)
    champions_meeting = models.ForeignKey(ChampionsMeeting, on_delete=models.CASCADE)

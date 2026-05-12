from django.db import models
from .game_event import GameEvent

class EventReward(models.Model):
    event = models.ForeignKey(GameEvent, on_delete=models.CASCADE, related_name='rewards', null=True, blank=True)
    name = models.CharField(max_length=500, null=False)
    carat_amount = models.IntegerField(default=0)
    support_ticket_amount = models.IntegerField(default=0)
    uma_ticket_amount = models.IntegerField(default=0)
    sr_shard_amount = models.IntegerField(default=0)
    sr_crystal_amount = models.IntegerField(default=0)
    ssr_shard_amount = models.IntegerField(default=0)
    ssr_crystal_amount = models.IntegerField(default=0)
    date = models.DateTimeField()

    def __str__(self):
        return str(self.name)

from django.db import models


class ChampionsMeetingRank(models.Model):
    name = models.CharField(max_Length=255)
    income_amount = models.IntegerField()


def __str__(self):
    return self.name

from django.db import models


class TeamTrialsRank(models.Model):
    name = models.CharField(max_length=255)
    income_amount = models.IntegerField()


def __str__(self):
    return self.name

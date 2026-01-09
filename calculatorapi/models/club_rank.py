from django.db import models


class ClubRank(models.Model):
    name = models.CharField(max_length=255, null=False)
    income_amount = models.IntegerField()

    def __str__(self):
        return str(self.name)

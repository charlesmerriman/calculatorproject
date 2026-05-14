from django.db import models


class LeagueOfHeroes(models.Model):
    name = models.CharField(max_length=255)
    start_date = models.DateTimeField()
    end_date = models.DateTimeField()
    image = models.ImageField(upload_to="league_of_heroes/", blank=True, null=True)

    def __str__(self):
        return str(self.name)

from django.db import models


class LeagueOfHeroes(models.Model):
    name = models.CharField(max_length=255)
    start_date = models.DateTimeField()
    end_date = models.DateTimeField()
    image = models.ImageField(upload_to="league_of_heroes/", blank=True, null=True)

    class Meta:
        # Fixes the auto-generated plural "league of heroess".
        verbose_name = "League of Heroes event"
        verbose_name_plural = "League of Heroes events"

    def __str__(self):
        return str(self.name)

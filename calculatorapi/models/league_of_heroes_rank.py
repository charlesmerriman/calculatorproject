from django.db import models


class LeagueOfHeroesRank(models.Model):
    name = models.CharField(max_length=255)
    income_amount = models.IntegerField()
    uma_ticket_amount = models.IntegerField(default=0)
    support_ticket_amount = models.IntegerField(default=0)
    ssr_shard_amount = models.IntegerField(default=0)
    sr_shard_amount = models.IntegerField(default=0)

    class Meta:
        # Proper-noun casing for the admin.
        verbose_name = "League of Heroes rank"
        verbose_name_plural = "League of Heroes ranks"

    def __str__(self):
        return str(self.name) if self.name else "Unnamed Rank"

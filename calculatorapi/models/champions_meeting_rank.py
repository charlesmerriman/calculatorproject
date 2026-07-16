from django.db import models


class ChampionsMeetingRank(models.Model):
    name = models.CharField(max_length=255, null=False)
    income_amount = models.IntegerField()
    uma_ticket_amount = models.IntegerField(default=0)
    support_ticket_amount = models.IntegerField(default=0)
    ssr_shard_amount = models.IntegerField(default=0)
    sr_shard_amount = models.IntegerField(default=0)

    class Meta:
        # Proper-noun casing for the admin.
        verbose_name = "Champions Meeting rank"
        verbose_name_plural = "Champions Meeting ranks"

    def __str__(self):
        return str(self.name)

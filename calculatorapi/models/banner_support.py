from django.db import models
from .banner_timeline import BannerTimeline
from .support_card import SupportCard


class BannerSupport(models.Model):
    banner_timeline = models.ForeignKey(BannerTimeline, on_delete=models.CASCADE)
    name = models.CharField(max_length=255, null=False)
    support_cards = models.ManyToManyField(
        SupportCard, through="SupportsOnSupportBanner", related_name="support_banners"
    )
    admin_comments = models.TextField(blank=True, null=True)
    free_pulls = models.IntegerField(default=0)

    def __str__(self):
        return str(self.name)

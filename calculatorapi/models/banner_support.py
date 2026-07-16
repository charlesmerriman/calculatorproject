from django.db import models
from .banner_timeline import BannerTimeline
from .support_card import SupportCard


class BannerSupport(models.Model):
    banner_timeline = models.ForeignKey(BannerTimeline, on_delete=models.CASCADE, related_name="support_banners")
    name = models.CharField(max_length=255, null=False)
    support_cards = models.ManyToManyField(
        SupportCard, through="SupportsOnSupportBanner"
    )
    admin_comments = models.TextField(blank=True, null=True, help_text="Notes for editors.")
    free_pulls = models.IntegerField(
        default=0,
        help_text="Free pulls players get on this banner — the calculator counts these toward affordability.",
    )

    class Meta:
        # Default would be "banner support / banner supports" — confusing for editors.
        verbose_name = "support card banner"
        verbose_name_plural = "support card banners"

    def __str__(self):
        return str(self.name)

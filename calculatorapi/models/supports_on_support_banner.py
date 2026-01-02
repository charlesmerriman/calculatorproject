from django.db import models
from .banner_support import BannerSupport
from .support_card import SupportCard
from .recommendation_tag import RecommendationTag


class SupportsOnSupportBanner(models.Model):
    banner_support = models.ForeignKey(BannerSupport, on_delete=models.CASCADE)
    support_card = models.ForeignKey(SupportCard, on_delete=models.CASCADE)
    recommendation_tag = models.ForeignKey(
        RecommendationTag, on_delete=models.CASCADE, blank=True, null=True
    )

    def __str__(self):
        return f"{self.support_card.name} on {self.banner_support.name}"

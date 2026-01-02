from django.db import models
from .banner_timeline import BannerTimeline
from .support_card import SupportCard
from .recommendation_tag import RecommendationTag


class BannerSupport(models.Model):
    banner_timeline = models.ForeignKey(BannerTimeline, on_delete=models.CASCADE)
    support_card = models.ForeignKey(SupportCard, on_delete=models.CASCADE)
    recommendation_tag = models.ForeignKey(
        RecommendationTag, on_delete=models.CASCADE, blank=True, null=True
    )
    name = models.CharField(max_length=255)
    admin_comments = models.TextField(blank=True, null=True)

from django.db import models
from .banner_timeline import BannerTimeline
from .uma import Uma
from .recommendation_tag import RecommendationTag


class BannerUma(models.Model):
    banner_timeline = models.ForeignKey(BannerTimeline, on_delete=models.CASCADE)
    uma = models.ForeignKey(Uma, on_delete=models.CASCADE)
    recommendation_tag = models.ForeignKey(
        RecommendationTag, on_delete=models.CASCADE, blank=True, null=True
    )
    name = models.CharField(max_length=255)
    admin_comments = models.TextField(blank=True, null=True)

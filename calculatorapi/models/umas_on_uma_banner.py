from django.db import models
from .banner_uma import BannerUma
from .uma import Uma
from .recommendation_tag import RecommendationTag


class UmasOnUmaBanner(models.Model):
    banner_uma = models.ForeignKey(BannerUma, on_delete=models.CASCADE)
    uma = models.ForeignKey(Uma, on_delete=models.CASCADE)
    recommendation_tag = models.ForeignKey(
        RecommendationTag, on_delete=models.CASCADE, blank=True, null=True
    )

    def __str__(self):
        return f"{self.uma.name} on {self.banner_uma.name}"

from django.db import models
from .banner_timeline import BannerTimeline


class BannerSupport(models.Model):
    banner_timeline = models.ForeignKey(BannerTimeline, on_delete=models.CASCADE)
    name = models.CharField(max_length=255, null=False)
    admin_comments = models.TextField(blank=True, null=True)

    def __str__(self):
        return str(self.name)

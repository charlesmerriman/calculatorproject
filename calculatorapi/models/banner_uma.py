from django.db import models
from .banner_timeline import BannerTimeline
from .uma import Uma


class BannerUma(models.Model):
    banner_timeline = models.ForeignKey(BannerTimeline, on_delete=models.CASCADE)
    name = models.CharField(max_length=255, null=False)
    umas = models.ManyToManyField(
        Uma, through="UmasOnUmaBanner", related_name="uma_banners"
    )
    admin_comments = models.TextField(blank=True, null=True)
    free_pulls = models.IntegerField(default=0)

    def __str__(self):
        return str(self.name)

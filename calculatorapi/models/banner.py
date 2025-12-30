from django.db import models
from .banner_type import BannerType
from .banner_tag import BannerTag


class Banner(models.Model):
    name = models.CharField(max_length=255)
    banner_type = models.ForeignKey(BannerType, on_delete=models.CASCADE)
    banner_tag = models.ForeignKey(
        BannerTag, on_delete=models.CASCADE, blank=True, null=True
    )
    start_date = models.DateTimeField()
    end_date = models.DateTimeField()
    image = models.ImageField(upload_to="banners/", blank=True, null=True)
    admin_comments = models.TextField(blank=True, null=True)


def __str__(self):
    return self.name

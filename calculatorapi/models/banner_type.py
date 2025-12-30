from django.db import models


class BannerType(models.Model):
    name = models.CharField(max_length=100)

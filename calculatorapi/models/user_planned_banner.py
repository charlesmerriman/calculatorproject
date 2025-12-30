from django.db import models
from .banner import Banner
from .custom_user import CustomUser


class UserPlannedBanner(models.Model):
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    banner = models.ForeignKey(Banner, on_delete=models.CASCADE)
    number_of_pulls = models.IntegerField()


def __str__(self):
    return f"{self.user.username} - {self.banner.name} ({self.number_of_pulls} pulls)"

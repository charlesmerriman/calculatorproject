from django.db import models
from .Banner import Banner
from .User import UserProfile


class UserPlannedBanner(models.Model):
    user = models.ForeignKey(UserProfile, on_delete=models.CASCADE)
    banner = models.ForeignKey(Banner, on_delete=models.CASCADE)
    number_of_pulls = models.IntegerField()


def __str__(self):
    return f"{self.user.username} - {self.banner.name} ({self.number_of_pulls} pulls)"

from django.contrib.auth.models import User
from django.db import models
from .ClubRank import ClubRank
from .ChampionsMeetingRank import ChampionsMeetingRank
from .TeamTrialsRank import TeamTrialsRank


class UserProfile(models.Model):
    # Django's built-in User model
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")

    # Additional fields for the user profile
    club_rank = models.ForeignKey(
        ClubRank, on_delete=models.SET_NULL, null=True, blank=True
    )
    champions_meeting_rank = models.ForeignKey(
        ChampionsMeetingRank, on_delete=models.SET_NULL, null=True, blank=True
    )
    team_trials_rank = models.ForeignKey(
        TeamTrialsRank, on_delete=models.SET_NULL, null=True, blank=True
    )
    daily_carat = models.BooleanField(default=False)
    current_carat = models.IntegerField(default=0)
    uma_ticket = models.IntegerField(default=0)
    support_ticket = models.IntegerField(default=0)

    def __str__(self):
        return self.user.username

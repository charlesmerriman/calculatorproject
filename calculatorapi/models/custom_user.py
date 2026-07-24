from django.contrib.auth.models import AbstractUser
from django.db import models
from .club_rank import ClubRank
from .champions_meeting_rank import ChampionsMeetingRank
from .team_trials_rank import TeamTrialsRank
from .league_of_heroes_rank import LeagueOfHeroesRank


class CustomUser(AbstractUser):
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
    league_of_heroes_rank = models.ForeignKey(
        LeagueOfHeroesRank, on_delete=models.SET_NULL, null=True, blank=True
    )
    sr_shards = models.IntegerField(default=0)
    sr_crystals = models.IntegerField(default=0)
    ssr_shards = models.IntegerField(default=0)
    ssr_crystals = models.IntegerField(default=0)
    daily_carat = models.BooleanField(default=False)
    training_pass = models.BooleanField(default=False)
    # Approximates the sheet's "Misc Earnings" (gifts, team trials, careers):
    # a flat monthly carat estimate. On by default to match the source sheet,
    # which is the reference the projection is calibrated against.
    misc_earnings = models.BooleanField(default=True)
    current_carat = models.IntegerField(default=0)
    current_paid_carat = models.IntegerField(default=0)
    uma_ticket = models.IntegerField(default=0)
    support_ticket = models.IntegerField(default=0)

    # No Meta needed: AbstractUser already sets verbose_name "user" / "users".

    def __str__(self):
        return self.username

from django.contrib import admin
from .models import (
    CustomUser, Uma, SupportCard, UserPlannedBanner,
    TeamTrialsRank, ClubRank, ChampionsMeetingRank,
    BannerTimeline, BannerUma, BannerSupport,
    ChampionsMeeting, ChampionsMeetingUmaRecommendation,
    SupportsOnSupportBanner, UmasOnUmaBanner,
    EventReward, LeagueOfHeroes,
)

# Register your models here.
admin.site.register(CustomUser)
admin.site.register(Uma)
admin.site.register(SupportCard)
admin.site.register(UserPlannedBanner)
admin.site.register(TeamTrialsRank)
admin.site.register(ClubRank)
admin.site.register(ChampionsMeetingRank)
admin.site.register(BannerTimeline)
admin.site.register(BannerUma)
admin.site.register(BannerSupport)
admin.site.register(ChampionsMeeting)
admin.site.register(ChampionsMeetingUmaRecommendation)
admin.site.register(SupportsOnSupportBanner)
admin.site.register(UmasOnUmaBanner)
admin.site.register(EventReward)
admin.site.register(LeagueOfHeroes)

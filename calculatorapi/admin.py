from django.contrib import admin
from .models import *

# Register your models here.
admin.site.register(CustomUser)
admin.site.register(Uma)
admin.site.register(SupportCard)
admin.site.register(UserPlannedBanner)
admin.site.register(TeamTrialsRank)
admin.site.register(ClubRank)
admin.site.register(ChampionsMeetingRank)
admin.site.register(RecommendationTag)
admin.site.register(BannerTimeline)
admin.site.register(BannerUma)
admin.site.register(BannerSupport)
admin.site.register(ChampionsMeeting)
admin.site.register(ChampionsMeetingUmaRecommendation)
admin.site.register(SupportsOnSupportBanner)
admin.site.register(UmasOnUmaBanner)

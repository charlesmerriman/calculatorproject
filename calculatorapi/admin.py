from django.contrib import admin
from .models import *

# Register your models here.
admin.site.register(CustomUser)
admin.site.register(Banner)
admin.site.register(UserPlannedBanner)
admin.site.register(TeamTrialsRank)
admin.site.register(ClubRank)
admin.site.register(ChampionsMeetingRank)
admin.site.register(BannerType)
admin.site.register(BannerTag)

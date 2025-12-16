from django.contrib import admin
from django.urls import include, path
from django.conf import settings
from rest_framework import routers
from django.conf.urls.static import static
from calculatorapi.views import (
    BannerViewSet,
    UserViewSet,
    UserPlannedBannerViewSet,
    TeamTrialsRankViewSet,
    ClubRankViewSet,
    ChampionsMeetingRankViewSet,
    BannerTypeView,
    BannerTagView,
)

router = routers.DefaultRouter(trailing_slash=False)
router.register(r"banners", BannerViewSet, basename="banner")
router.register(r"users", UserViewSet, basename="user")
router.register(
    r"userplannedbanners", UserPlannedBannerViewSet, basename="userplannedbanner"
)
router.register(r"teamtrialranks", TeamTrialsRankViewSet, basename="teamtrialrank")
router.register(r"clubranks", ClubRankViewSet, basename="clubrank")
router.register(
    r"championsmeetingranks",
    ChampionsMeetingRankViewSet,
    basename="championsmeetingrank",
)
router.register(r"bannertypes", BannerTypeView, basename="bannertype")
router.register(r"bannertags", BannerTagView, basename="bannertag")

urlpatterns = [
    path("", include(router.urls)),
    path("login", UserViewSet.as_view({"post": "user_login"}), name="login"),
    path(
        "register", UserViewSet.as_view({"post": "register_account"}), name="register"
    ),
    path("logout", UserViewSet.as_view({"post": "user_logout"}), name="logout"),
    path("admin/", admin.site.urls),
    path(
        "update-stats",
        UserViewSet.as_view({"patch": "update_stats"}),
        name="update-stats",
    ),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

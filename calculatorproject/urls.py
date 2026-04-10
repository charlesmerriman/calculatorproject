from django.contrib import admin
from django.urls import include, path
from django.conf import settings
from rest_framework import routers
from django.conf.urls.static import static
from calculatorapi.views import (
    TeamTrialsRankViewSet,
    ClubRankViewSet,
    ChampionsMeetingRankViewSet,
    CalculatorViewSet,
)
from calculatorapi.views.user import register_account, user_login, user_logout

router = routers.DefaultRouter(trailing_slash=False)
router.register(r"teamtrialranks", TeamTrialsRankViewSet, basename="teamtrialrank")
router.register(r"clubranks", ClubRankViewSet, basename="clubrank")
router.register(
    r"championsmeetingranks",
    ChampionsMeetingRankViewSet,
    basename="championsmeetingrank",
)

urlpatterns = [
    path("", include(router.urls)),
    path("login", user_login, name="login"),
    path("register", register_account, name="register"),
    path("logout", user_logout, name="logout"),
    path("admin/", admin.site.urls),
    path(
        "calculator-data",
        CalculatorViewSet.as_view(
            {"get": "get_calculator_data", "patch": "update_calculator_data"}
        ),
        name="calculator-data",
    ),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
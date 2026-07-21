from django.contrib import admin
from django.conf import settings
from django.conf.urls.static import static
from django.urls import include, path
from rest_framework import routers
from calculatorapi.views import (
    TeamTrialsRankViewSet,
    ClubRankViewSet,
    ChampionsMeetingRankViewSet,
    LeagueOfHeroesRankViewSet,
    LeagueOfHeroesViewSet,
    CalculatorViewSet,
    GameEventViewSet,
    ChangelogEntryViewSet,
)
from calculatorapi.views.analytics import analytics_dashboard
from calculatorapi.views.user import register_account, user_login, user_logout

router = routers.SimpleRouter(trailing_slash=False)
router.register(r"teamtrialranks", TeamTrialsRankViewSet, basename="teamtrialrank")
router.register(r"clubranks", ClubRankViewSet, basename="clubrank")
router.register(
    r"championsmeetingranks",
    ChampionsMeetingRankViewSet,
    basename="championsmeetingrank",
)
router.register(
    r"leagueofheroesranks",
    LeagueOfHeroesRankViewSet,
    basename="leagueofheroesrank",
)
router.register(r"leagueofheroes", LeagueOfHeroesViewSet, basename="leagueofheroes")
router.register(r"events", GameEventViewSet, basename="event")
router.register(r"changelog", ChangelogEntryViewSet, basename="changelog")

urlpatterns = [
    path("", include(router.urls)),
    path("login", user_login, name="login"),
    path("register", register_account, name="register"),
    path("logout", user_logout, name="logout"),
    # Must come BEFORE admin.site.urls — the admin URLconf ends in a
    # catch-all that would 404 this path. admin_view() makes the page
    # staff-only (redirects everyone else to the admin login).
    path(
        "admin/analytics/",
        admin.site.admin_view(analytics_dashboard),
        name="admin-analytics",
    ),
    path("admin/", admin.site.urls),
    path(
        "calculator-data",
        CalculatorViewSet.as_view(
            {"get": "get_calculator_data", "patch": "update_calculator_data"}
        ),
        name="calculator-data",
    ),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

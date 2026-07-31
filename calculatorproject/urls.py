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
from calculatorapi.views.admin_images import admin_image_library
from calculatorapi.views.analytics import analytics_dashboard
from calculatorapi.views.user import user_login, user_logout
from calculatorapi.views.social_auth import social_auth_start, social_auth_complete

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
    # Password login is staff-only now; ordinary accounts use /auth/* below.
    # There is intentionally no "register" route — see views/user.py.
    path("login", user_login, name="login"),
    path("logout", user_logout, name="logout"),
    # Social sign-in (Google / Discord). The <provider> segment is validated by
    # the view against oauth.SUPPORTED_PROVIDERS rather than by a URL regex, so
    # an unknown provider gets a JSON 404 instead of Django's HTML one.
    path("auth/<str:provider>/start", social_auth_start, name="social-auth-start"),
    path("auth/social", social_auth_complete, name="social-auth-complete"),
    # Must come BEFORE admin.site.urls — the admin URLconf ends in a
    # catch-all that would 404 this path. admin_view() makes the page
    # staff-only (redirects everyone else to the admin login).
    path(
        "admin/analytics/",
        admin.site.admin_view(analytics_dashboard),
        name="admin-analytics",
    ),
    # Same placement rule as analytics above: before admin.site.urls, and
    # admin_view() makes it staff-only. Feeds the "choose an existing image"
    # picker on the content change forms.
    path(
        "admin/image-library/",
        admin.site.admin_view(admin_image_library),
        name="admin-image-library",
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

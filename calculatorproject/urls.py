from django.contrib import admin
from django.urls import include, path
from django.conf import settings
from rest_framework import permissions, routers
from django.conf.urls.static import static
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularSwaggerView,
    SpectacularRedocView,
)
from calculatorapi.views import (
    UserViewSet,
    TeamTrialsRankViewSet,
    ClubRankViewSet,
    ChampionsMeetingRankViewSet,
    CalculatorViewSet,
)
from django.http import JsonResponse

def test_view(request):
    return JsonResponse({"status": "ok"})


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
    path("login", UserViewSet.as_view({"post": "user_login"}, permission_classes=[permissions.AllowAny]), name="login"),
    path("register", UserViewSet.as_view({"post": "register_account"}, permission_classes=[permissions.AllowAny]), name="register"),
    path("logout", UserViewSet.as_view({"post": "user_logout"}, permission_classes=[permissions.IsAuthenticated]), name="logout"),
    path("admin/", admin.site.urls),
    path(
        "update-stats",
        UserViewSet.as_view({"patch": "update_stats"}),
        name="update-stats",
    ),
    # API Documentation URLs
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path(
        "api/schema/swagger-ui/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger-ui",
    ),
    path(
        "api/schema/redoc/",
        SpectacularRedocView.as_view(url_name="schema"),
        name="redoc",
    ),
    path(
        "calculator-data",
        CalculatorViewSet.as_view(
            {"get": "get_calculator_data", "patch": "update_calculator_data"}
        ),
        name="calculator-data",
    ),
    path("test", test_view, name="test"),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

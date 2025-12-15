from django.contrib import admin
from django.urls import include, path
from django.conf import settings
from rest_framework import routers
from django.conf.urls.static import static
from calculatorapi.views import BannerViewSet, UserViewSet

router = routers.DefaultRouter(trailing_slash=False)
router.register(r"banners", BannerViewSet, basename="banner")
router.register(r"users", UserViewSet, basename="user")

urlpatterns = [
    path("", include(router.urls)),
    path("login", UserViewSet.as_view({"post": "user_login"}), name="login"),
    path(
        "register", UserViewSet.as_view({"post": "register_account"}), name="register"
    ),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

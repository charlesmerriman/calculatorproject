from rest_framework.viewsets import ViewSet
from rest_framework.response import Response
from rest_framework import serializers
from rest_framework import status
from calculatorapi.models import UserPlannedBanner
from .banner import BannerSerializer
from .user import UserSerializer


class UserPlannedBannerSerializer(serializers.ModelSerializer):
    """Serializer for UserPlannedBanner model"""

    user = UserSerializer()
    banner = BannerSerializer()

    class Meta:
        model = UserPlannedBanner
        fields = (
            "id",
            "user",
            "banner",
            "number_of_pulls",
        )


class UserPlannedBannerViewSet(ViewSet):

    def retrieve(self, request, pk=None):
        try:
            user_planned_banners = UserPlannedBanner.objects.filter(
                user_id=pk
            ).order_by("start_date")
            serializer = UserPlannedBannerSerializer(
                user_planned_banners, many=True, context={"request": request}
            )

            return Response(serializer.data)

        except UserPlannedBanner.DoesNotExist:
            return Response(
                {"message": "UserPlannedBanners not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

from rest_framework.viewsets import ViewSet
from rest_framework.response import Response
from rest_framework import serializers
from rest_framework import status
from calculatorapi.models import BannerType


class BannerTypeSerializer(serializers.ModelSerializer):
    """Serializer for BannerType"""

    class Meta:
        model = BannerType
        fields = (
            "id",
            "name",
        )


class BannerTypeView(ViewSet):

    def list(self, request):
        banner_types = BannerType.objects.all()
        serializer = BannerTypeSerializer(banner_types, many=True)
        return Response(serializer.data)

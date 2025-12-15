from rest_framework.viewsets import ViewSet
from rest_framework.response import Response
from rest_framework import serializers
from rest_framework import status
from calculatorapi.models import BannerTag


class BannerTagSerializer(serializers.ModelSerializer):
    """Serializer for BannerType"""

    class Meta:
        model = BannerTag
        fields = (
            "id",
            "name",
        )


class BannerTagView(ViewSet):

    def list(self, request):
        banner_tags = BannerTag.objects.all()
        serializer = BannerTagSerializer(banner_tags, many=True)
        return Response(serializer.data)

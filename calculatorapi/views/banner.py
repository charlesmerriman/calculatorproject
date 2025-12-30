from rest_framework.viewsets import ViewSet
from rest_framework.response import Response
from rest_framework import serializers
from rest_framework import status
from calculatorapi.models import Banner
from .banner_type import BannerTypeSerializer
from .banner_tag import BannerTagSerializer


class BannerSerializer(serializers.ModelSerializer):
    """Serializer for Banner model"""

    banner_type = BannerTypeSerializer()
    banner_tag = BannerTagSerializer()
    image = serializers.SerializerMethodField()

    class Meta:
        model = Banner
        fields = (
            "id",
            "name",
            "banner_type",
            "banner_tag",
            "start_date",
            "end_date",
            "image",
            "admin_comments",
        )

    def get_image(self, obj):
        if obj.image:
            request = self.context.get("request")
            if request is not None:
                return request.build_absolute_uri(obj.image.url)
            return obj.image.url
        return None


class BannerViewSet(ViewSet):
    """Viewset for handling Banner requests"""

    def list(self, request):
        # Retrieve all Banners
        banners = Banner.objects.all().order_by("start_date")

        serializer = BannerSerializer(banners, many=True, context={"request": request})
        return Response(serializer.data)

    def retrieve(self, request, pk=None):
        try:
            banner = Banner.objects.get(pk=pk)
            serializer = BannerSerializer(banner, context={"request": request})
            return Response(serializer.data)
        except Banner.DoesNotExist:
            return Response(
                {"message": "Banner not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

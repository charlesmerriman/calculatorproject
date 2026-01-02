from rest_framework.viewsets import ViewSet
from rest_framework.response import Response
from rest_framework import serializers
from rest_framework import status
from calculatorapi.models import BannerTimeline


class BannerTimelineSerializer(serializers.ModelSerializer):
    """Serializer for Banner model"""

    image = serializers.SerializerMethodField()

    class Meta:
        model = BannerTimeline
        fields = (
            "id",
            "name",
            "start_date",
            "end_date",
            "image",
        )

    def get_image(self, obj):
        if obj.image:
            request = self.context.get("request")
            if request is not None:
                return request.build_absolute_uri(obj.image.url)
            return obj.image.url
        return None


class BannerTimelineViewSet(ViewSet):
    """Viewset for handling Banner requests"""

    def list(self, request):
        banner_timelines = BannerTimeline.objects.all().order_by("start_date")

        serializer = BannerTimelineSerializer(
            banner_timelines, many=True, context={"request": request}
        )
        return Response(serializer.data)

    def retrieve(self, request, pk=None):
        try:
            banner_timeline = BannerTimeline.objects.get(pk=pk)
            serializer = BannerTimelineSerializer(
                banner_timeline, context={"request": request}
            )
            return Response(serializer.data)
        except BannerTimeline.DoesNotExist:
            return Response(
                {"message": "Banner Timeline not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

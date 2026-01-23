from rest_framework.viewsets import ViewSet
from rest_framework.response import Response
from rest_framework import serializers
from rest_framework import status
from calculatorapi.models import BannerTimeline, BannerSupport, BannerUma
from .uma import UmaSerializer
from .support_card import SupportCardSerializer


class BannerTimelineSerializer(serializers.ModelSerializer):
    """Serializer for embedding inside banners"""

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

class BannerSupportNestedSerializer(serializers.ModelSerializer):
    support_cards = serializers.SerializerMethodField()

    class Meta:
        model = BannerSupport
        fields = (
            "id",
            "name",
            "free_pulls",
            "admin_comments",
            "support_cards",
        )

    def get_support_cards(self, obj):
        result = []
        for junction in obj.supportsonsupportbanner_set.select_related('support_card').all():
            card_data = SupportCardSerializer(junction.support_card, context=self.context).data
            card_data['recommendation'] = junction.recommendation
            result.append(card_data)
        return result

class BannerUmaNestedSerializer(serializers.ModelSerializer):
    umas = serializers.SerializerMethodField()

    class Meta:
        model = BannerUma
        fields = (
            "id",
            "name",
            "free_pulls",
            "admin_comments",
            "umas",
        )
    
    def get_umas(self, obj):
        result = []
        for junction in obj.umasonumabanner_set.select_related('uma').all():
            uma_data = UmaSerializer(junction.uma, context=self.context).data
            uma_data['recommendation'] = junction.recommendation
            result.append(uma_data)
        return result

class BannerTimelineForViewingSerializer(serializers.ModelSerializer):
    """Serializer for viewing inside the banner timeline component, embedded with any related fields"""

    image = serializers.SerializerMethodField()
    banner_umas = BannerUmaNestedSerializer(source="uma_banners", many=True, read_only=True)
    banner_supports = BannerSupportNestedSerializer(source="support_banners", many=True, read_only=True)

    class Meta:
        model = BannerTimeline
        fields = (
            "id",
            "name",
            "start_date",
            "end_date",
            "image",
            "banner_umas",
            "banner_supports",
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

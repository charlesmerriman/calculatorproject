from rest_framework.viewsets import ViewSet
from rest_framework.response import Response
from rest_framework import serializers
from rest_framework import status
from calculatorapi.models import BannerTimeline, BannerSupport, BannerUma
from .uma import UmaSerializer
from .support_card import SupportCardSerializer


# One shared DateTimeField instance to reproduce DRF's exact ISO wire format
# (e.g. "2025-06-26T22:00:00Z") when serializing resolved dates below.
_DT = serializers.DateTimeField()


class EffectiveDateMixin(serializers.Serializer):
    """
    Emits the RESOLVED global dates (confirmed-or-predicted) under the existing
    `start_date`/`end_date` field names, plus an `is_predicted` flag, by looking
    up this timeline's id in the `effective_dates` map passed via serializer
    context. Keying by id (not queryset position) is what keeps every
    serialization path — top-level, nested in uma/support banners, and inside
    planned banners — consistent for a given timeline.

    Falls back to the raw global_* fields when no map is in context, so the
    serializer is still safe when used standalone.
    """

    start_date = serializers.SerializerMethodField()
    end_date = serializers.SerializerMethodField()
    is_predicted = serializers.SerializerMethodField()

    def _entry(self, obj):
        emap = self.context.get("effective_dates")
        if emap is not None and obj.id in emap:
            return emap[obj.id]
        return {
            "start_date": obj.global_start_date,
            "end_date": obj.global_end_date,
            "is_predicted": False,
        }

    def get_start_date(self, obj):
        value = self._entry(obj)["start_date"]
        return _DT.to_representation(value) if value is not None else None

    def get_end_date(self, obj):
        value = self._entry(obj)["end_date"]
        return _DT.to_representation(value) if value is not None else None

    def get_is_predicted(self, obj):
        return self._entry(obj)["is_predicted"]


class BannerTimelineSerializer(EffectiveDateMixin, serializers.ModelSerializer):
    class Meta:
        model = BannerTimeline
        fields = (
            "id", "name",
            "start_date", "end_date", "is_predicted",
            "jp_start_date", "jp_end_date", "global_start_date", "global_end_date",
            "image",
        )


class BannerSupportNestedSerializer(serializers.ModelSerializer):
    support_cards = serializers.SerializerMethodField()

    class Meta:
        model = BannerSupport
        fields = ("id", "name", "free_pulls", "admin_comments", "support_cards")

    def get_support_cards(self, obj):
        result = []
        for junction in obj.supportsonsupportbanner_set.select_related('support_card').all():
            card_data = SupportCardSerializer(junction.support_card).data
            card_data['recommendation'] = junction.recommendation
            result.append(card_data)
        return result


class BannerUmaNestedSerializer(serializers.ModelSerializer):
    umas = serializers.SerializerMethodField()

    class Meta:
        model = BannerUma
        fields = ("id", "name", "free_pulls", "admin_comments", "umas")

    def get_umas(self, obj):
        result = []
        for junction in obj.umasonumabanner_set.select_related('uma').all():
            uma_data = UmaSerializer(junction.uma).data
            uma_data['recommendation'] = junction.recommendation
            result.append(uma_data)
        return result


class BannerTimelineForViewingSerializer(EffectiveDateMixin, serializers.ModelSerializer):
    banner_umas = BannerUmaNestedSerializer(source="uma_banners", many=True, read_only=True)
    banner_supports = BannerSupportNestedSerializer(source="support_banners", many=True, read_only=True)

    class Meta:
        model = BannerTimeline
        fields = (
            "id", "name",
            "start_date", "end_date", "is_predicted",
            "jp_start_date", "jp_end_date", "global_start_date", "global_end_date",
            "image", "banner_umas", "banner_supports",
        )


class BannerTimelineViewSet(ViewSet):
    def list(self, request):
        banner_timelines = BannerTimeline.objects.all().order_by("global_start_date")
        serializer = BannerTimelineSerializer(banner_timelines, many=True)
        return Response(serializer.data)

    def retrieve(self, request, pk=None):
        try:
            banner_timeline = BannerTimeline.objects.get(pk=pk)
            serializer = BannerTimelineSerializer(banner_timeline)
            return Response(serializer.data)
        except BannerTimeline.DoesNotExist:
            return Response({"message": "Banner Timeline not found."}, status=status.HTTP_404_NOT_FOUND)

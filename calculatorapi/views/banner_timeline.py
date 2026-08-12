from rest_framework.viewsets import ViewSet
from rest_framework.response import Response
from rest_framework import serializers
from rest_framework import status
from calculatorapi.models import BannerTimeline, BannerSupport, BannerUma
from .uma import UmaSerializer
from .support_card import SupportCardSerializer
from .mixins import EffectiveDateMixin, EventTypeMixin


class BannerTimelineSerializer(EffectiveDateMixin, serializers.ModelSerializer):
    class Meta:
        model = BannerTimeline
        fields = (
            "id", "name", "banner_category",
            "start_date", "end_date", "is_predicted",
            "jp_start_date", "jp_end_date", "global_start_date", "global_end_date",
            "schedule_offset_days", "applied_offset_days",
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
            # Context is forwarded so the nested card can resolve first_jp_date
            # from the request-wide map; a SerializerMethodField doesn't inherit
            # it the way a declared nested field would.
            card_data = SupportCardSerializer(
                junction.support_card, context=self.context
            ).data
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
            # See get_support_cards above on why context is forwarded here.
            uma_data = UmaSerializer(junction.uma, context=self.context).data
            uma_data['recommendation'] = junction.recommendation
            result.append(uma_data)
        return result


class BannerTimelineForViewingSerializer(EventTypeMixin, EffectiveDateMixin,
                                         serializers.ModelSerializer):
    # Only this serializer is tagged, not BannerTimelineSerializer above — the
    # tag exists for the merged timeline array, which is fed exclusively by
    # /calculator-data's banner_timeline_data.
    event_type_value = "banner_timeline"

    banner_umas = BannerUmaNestedSerializer(source="uma_banners", many=True, read_only=True)
    banner_supports = BannerSupportNestedSerializer(source="support_banners", many=True, read_only=True)
    anniversary_event = serializers.SerializerMethodField()

    class Meta:
        model = BannerTimeline
        fields = (
            "id", "name", "event_type", "banner_category",
            "start_date", "end_date", "is_predicted",
            "jp_start_date", "jp_end_date", "global_start_date", "global_end_date",
            "schedule_offset_days", "applied_offset_days",
            "image", "banner_umas", "banner_supports", "anniversary_event",
        )

    def get_anniversary_event(self, obj):
        """The campaign this banner is a part of, if any, plus which part it is.

        Deliberately a flat summary rather than the full AnniversaryEventSerializer:
        the timeline only needs enough to draw the attached strip, and the same
        campaign is already sent in full (with its products) under
        anniversary_event_data. Nesting it here would repeat the whole catalogue
        once per part.

        A banner in more than one campaign is not meaningful, so the first link
        wins rather than the field becoming a list for a case that never occurs.
        """
        link = next(iter(obj.anniversary_links.all()), None)
        if link is None:
            return None
        event = link.anniversary_event
        return {
            "id": event.id,
            "name": event.name,
            "event_type": event.event_type,
            "accent_label": event.accent_label,
            "image": event.image.url if event.image else None,
            "part_number": link.part_number,
        }


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

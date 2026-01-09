from rest_framework import serializers
from calculatorapi.models import BannerSupport
from .banner_timeline import BannerTimelineSerializer
from .support_card import SupportCardSerializer


class BannerSupportSerializer(serializers.ModelSerializer):
    banner_timeline = BannerTimelineSerializer()
    support_cards = SupportCardSerializer(many=True, read_only=True)

    class Meta:
        model = BannerSupport
        fields = (
            "id",
            "banner_timeline",
            "name",
            "free_pulls",
            "admin_comments",
            "support_cards",
        )

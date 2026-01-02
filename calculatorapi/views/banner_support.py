from rest_framework import serializers
from calculatorapi.models import BannerSupport, SupportsOnSupportBanner
from .banner_timeline import BannerTimelineSerializer
from .recommendation_tag import RecommendationTagSerializer
from .support_card import SupportCardSerializer


class SupportsOnSupportBannerSerializer(serializers.ModelSerializer):
    """Serializer for the junction table showing support cards on a banner"""

    support_card = SupportCardSerializer()
    recommendation_tag = RecommendationTagSerializer()

    class Meta:
        model = SupportsOnSupportBanner
        fields = (
            "id",
            "support_card",
            "recommendation_tag",
        )


class BannerSupportSerializer(serializers.ModelSerializer):
    """Serializer for Banner Support with multiple support cards"""

    banner_timeline = BannerTimelineSerializer()
    support_cards = SupportsOnSupportBannerSerializer(
        source="supportsonsupportbanner_set", many=True
    )

    class Meta:
        model = BannerSupport
        fields = (
            "id",
            "banner_timeline",
            "name",
            "admin_comments",
            "support_cards",
        )

from rest_framework import serializers
from calculatorapi.models import BannerSupport
from .banner_timeline import BannerTimelineSerializer
from .recommendation_tag import RecommendationTagSerializer
from .support_card import SupportCardSerializer


class BannerSupportSerializer(serializers.ModelSerializer):
    banner_timeline = BannerTimelineSerializer()
    recommendation_tag = RecommendationTagSerializer()
    support_card = SupportCardSerializer()

    class Meta:
        model = BannerSupport
        fields = (
            "id",
            "banner_timeline",
            "recommendation_tag",
            "support_card",
            "name",
            "admin_comments",
        )

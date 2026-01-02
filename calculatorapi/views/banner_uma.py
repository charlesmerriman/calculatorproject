from rest_framework import serializers
from calculatorapi.models import BannerUma
from .banner_timeline import BannerTimelineSerializer
from .recommendation_tag import RecommendationTagSerializer
from .uma import UmaSerializer


class BannerUmaSerializer(serializers.ModelSerializer):
    banner_timeline = BannerTimelineSerializer()
    recommendation_tag = RecommendationTagSerializer()
    uma = UmaSerializer()

    class Meta:
        model = BannerUma
        fields = (
            "id",
            "banner_timeline",
            "recommendation_tag",
            "uma",
            "name",
            "admin_comments",
        )

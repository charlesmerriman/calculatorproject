from rest_framework import serializers
from calculatorapi.models import BannerUma, UmasOnUmaBanner
from .banner_timeline import BannerTimelineSerializer
from .recommendation_tag import RecommendationTagSerializer
from .uma import UmaSerializer


class UmasOnUmaBannerSerializer(serializers.ModelSerializer):
    """Serializer for the junction table showing umas on a banner"""

    uma = UmaSerializer()
    recommendation_tag = RecommendationTagSerializer()

    class Meta:
        model = UmasOnUmaBanner
        fields = (
            "id",
            "uma",
            "recommendation_tag",
        )


class BannerUmaSerializer(serializers.ModelSerializer):
    """Serializer for Banner Uma with multiple umas"""

    banner_timeline = BannerTimelineSerializer()
    umas = UmasOnUmaBannerSerializer(source="umasontumabanner_set", many=True)

    class Meta:
        model = BannerUma
        fields = (
            "id",
            "banner_timeline",
            "name",
            "admin_comments",
            "umas",
        )

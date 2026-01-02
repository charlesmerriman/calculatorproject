from rest_framework import serializers
from calculatorapi.models import RecommendationTag


class RecommendationTagSerializer(serializers.ModelSerializer):
    """Serializer for BannerType"""

    class Meta:
        model = RecommendationTag
        fields = (
            "id",
            "name",
        )

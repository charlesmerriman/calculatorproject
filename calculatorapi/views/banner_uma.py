from rest_framework import serializers
from calculatorapi.models import BannerUma
from .banner_timeline import BannerTimelineSerializer
from .uma import UmaSerializer


class BannerUmaSerializer(serializers.ModelSerializer):
    banner_timeline = BannerTimelineSerializer()
    umas = UmaSerializer(many=True, read_only=True)

    class Meta:
        model = BannerUma
        fields = (
            "id",
            "banner_timeline",
            "name",
            "admin_comments",
            "umas",
        )

from rest_framework import serializers
from calculatorapi.models import SupportCard
from .mixins import FirstJpDateMixin


class SupportCardSerializer(FirstJpDateMixin, serializers.ModelSerializer):
    context_key = "support_first_jp_dates"

    class Meta:
        model = SupportCard
        fields = (
            "id",
            "name",
            "image",
            "admin_comments",
            "first_jp_date",
        )

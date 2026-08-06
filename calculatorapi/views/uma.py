from rest_framework import serializers
from calculatorapi.models import Uma
from .mixins import FirstJpDateMixin


class UmaSerializer(FirstJpDateMixin, serializers.ModelSerializer):
    context_key = "uma_first_jp_dates"

    class Meta:
        model = Uma
        fields = (
            "id",
            "name",
            "image",
            "admin_comments",
            "first_jp_date",
        )

from rest_framework import serializers
from calculatorapi.models import SupportCard


class SupportCardSerializer(serializers.ModelSerializer):
    class Meta:
        model = SupportCard
        fields = (
            "id",
            "name",
            "image",
            "admin_comments",
        )

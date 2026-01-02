from rest_framework import serializers
from calculatorapi.models import Uma


class UmaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Uma
        fields = (
            "id",
            "name",
            "image",
            "admin_comments",
        )

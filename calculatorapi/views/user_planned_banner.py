from rest_framework import serializers
from calculatorapi.models import UserPlannedBanner, BannerUma, BannerSupport
from .banner_uma import BannerUmaSerializer
from .banner_support import BannerSupportSerializer


class UserPlannedBannerSerializer(serializers.ModelSerializer):
    banner_uma = serializers.PrimaryKeyRelatedField(
        queryset=BannerUma.objects.all(), required=False, allow_null=True
    )
    banner_support = serializers.PrimaryKeyRelatedField(
        queryset=BannerSupport.objects.all(), required=False, allow_null=True
    )

    class Meta:
        model = UserPlannedBanner
        fields = (
            "id",
            "user",
            "number_of_pulls",
            "banner_uma",
            "banner_support",
        )
        read_only_fields = ("user",)

    def to_representation(self, instance):
        # For GET requests, return nested objects
        representation = super().to_representation(instance)
        if instance.banner_uma:
            representation["banner_uma"] = BannerUmaSerializer(
                instance.banner_uma, context=self.context
            ).data
        if instance.banner_support:
            representation["banner_support"] = BannerSupportSerializer(
                instance.banner_support, context=self.context
            ).data
        return representation

    def validate(self, data):
        banner_uma = data.get("banner_uma")
        banner_support = data.get("banner_support")

        if not banner_uma and not banner_support:
            raise serializers.ValidationError(
                "Either banner_uma or banner_support must be provided."
            )
        if banner_uma and banner_support:
            raise serializers.ValidationError(
                "Cannot provide both banner_uma and banner_support."
            )

        return data

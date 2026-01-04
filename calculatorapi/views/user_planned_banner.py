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


# class UserPlannedBannerViewSet(ViewSet):

#     def retrieve(self, request, pk=None):
#         try:
#             user_planned_banners = UserPlannedBanner.objects.filter(
#                 user_id=pk
#             ).order_by("banner_uma__banner_timeline__start_date")
#             serializer = UserPlannedBannerSerializer(
#                 user_planned_banners, many=True, context={"request": request}
#             )

#             return Response(serializer.data)

#         except UserPlannedBanner.DoesNotExist:
#             return Response(
#                 {"message": "UserPlannedBanners not found."},
#                 status=status.HTTP_404_NOT_FOUND,
#             )

#     def create(self, request):
#         banner = request.data.get("banner")
#         number_of_pulls = request.data.get("number_of_pulls")

#         planned_banner = UserPlannedBanner.objects.create(
#             user=request.user,
#             banner_id=banner,
#             number_of_pulls=number_of_pulls,
#         )

#         serializer = UserPlannedBannerSerializer(planned_banner)
#         return Response(serializer.data, status=status.HTTP_201_CREATED)

#     def update(self, request, pk=None):
#         try:
#             planned_banner = UserPlannedBanner.objects.get(pk=pk)

#             self.check_object_permissions(request, planned_banner)

#             serializer = UserPlannedBannerSerializer(data=request.data)

#             if serializer.is_valid():
#                 planned_banner.banner_id = serializer.validated_data.get(
#                     "banner", planned_banner.banner_id
#                 )
#                 planned_banner.number_of_pulls = serializer.validated_data.get(
#                     "number_of_pulls", planned_banner.number_of_pulls
#                 )
#                 planned_banner.save()

#                 return Response(
#                     UserPlannedBannerSerializer(planned_banner).data,
#                     status=status.HTTP_200_OK,
#                 )

#             return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

#         except UserPlannedBanner.DoesNotExist:
#             return Response(
#                 {"message": "UserPlannedBanner not found."},
#                 status=status.HTTP_404_NOT_FOUND,
#             )

#     def destroy(self, request, pk=None):
#         try:
#             planned_banner = UserPlannedBanner.objects.get(pk=pk)

#             self.check_object_permissions(request, planned_banner)

#             planned_banner.delete()
#             return Response(status=status.HTTP_204_NO_CONTENT)

#         except UserPlannedBanner.DoesNotExist:
#             return Response(
#                 {"message": "UserPlannedBanner not found."},
#                 status=status.HTTP_404_NOT_FOUND,
#             )

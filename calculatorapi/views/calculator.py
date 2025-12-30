from rest_framework.viewsets import ViewSet
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework import status
from calculatorapi.models import (
    ClubRank,
    TeamTrialsRank,
    ChampionsMeetingRank,
    Banner,
    UserPlannedBanner,
    CustomUser as User,
    BannerType,
    BannerTag,
)
from calculatorapi.views import (
    ClubRankSerializer,
    TeamTrialsRankSerializer,
    ChampionsMeetingRankSerializer,
    BannerSerializer,
    UserPlannedBannerSerializer,
    BannerTypeSerializer,
    BannerTagSerializer,
    UserStatsSerializer,
)


class CalculatorViewSet(ViewSet):
    @action(detail=False, methods=["get"], url_path="calculator-data")
    def get_calculator_data(self, request):
        club_rank_data = ClubRank.objects.all()
        team_trials_rank_data = TeamTrialsRank.objects.all()
        champions_meeting_rank_data = ChampionsMeetingRank.objects.all()
        banner_data = Banner.objects.all().order_by("start_date")
        user_planned_banner_data = UserPlannedBanner.objects.filter(user=request.user)
        banner_type_data = BannerType.objects.all()
        banner_tag_data = BannerTag.objects.all()
        user_stats_data = request.user

        club_rank_serializer = ClubRankSerializer(club_rank_data, many=True)
        team_trials_rank_serializer = TeamTrialsRankSerializer(
            team_trials_rank_data, many=True
        )
        champions_meeting_rank_serializer = ChampionsMeetingRankSerializer(
            champions_meeting_rank_data, many=True
        )
        banner_serializer = BannerSerializer(
            banner_data, many=True, context={"request": request}
        )
        user_planned_banner_serializer = UserPlannedBannerSerializer(
            user_planned_banner_data, many=True
        )
        banner_type_serializer = BannerTypeSerializer(banner_type_data, many=True)
        banner_tag_serializer = BannerTagSerializer(banner_tag_data, many=True)
        user_stats_data_serializer = UserStatsSerializer(user_stats_data, many=False)

        response = {
            "club_rank_data": club_rank_serializer.data,
            "team_trials_rank_data": team_trials_rank_serializer.data,
            "champions_meeting_rank_data": champions_meeting_rank_serializer.data,
            "banner_data": banner_serializer.data,
            "user_planned_banner_data": user_planned_banner_serializer.data,
            "banner_type_data": banner_type_serializer.data,
            "banner_tag_data": banner_tag_serializer.data,
            "user_stats_data": user_stats_data_serializer.data,
        }

        return Response(response, status=status.HTTP_200_OK)

    @action(detail=False, methods=["patch"], url_path="calculator-data")
    def update_calculator_data(self, request):
        user = request.user

        user_stats_data = request.data.get("user_stats_data")
        if user_stats_data:
            user_stats_serializer = UserStatsSerializer(
                user, data=user_stats_data, partial=True
            )

            if user_stats_serializer.is_valid():
                user_stats_serializer.save()
            else:
                return Response(
                    user_stats_serializer.errors, status=status.HTTP_400_BAD_REQUEST
                )

        user_planned_banner_data = request.data.get("user_planned_banner_data")
        if user_planned_banner_data is not None:

            incoming_banners = [
                banner["id"] for banner in user_planned_banner_data if "id" in banner
            ]

            UserPlannedBanner.objects.filter(user=user).exclude(
                id__in=incoming_banners
            ).delete()

            for banner_data in user_planned_banner_data:
                banner_id = banner_data.get("id")
                if banner_id:

                    try:
                        banner = UserPlannedBanner.objects.get(id=banner_id, user=user)
                        banner_serializer = UserPlannedBannerSerializer(
                            banner, data=banner_data, partial=True
                        )
                        if banner_serializer.is_valid():
                            banner_serializer.save()
                        else:
                            return Response(
                                banner_serializer.errors,
                                status=status.HTTP_400_BAD_REQUEST,
                            )
                    except UserPlannedBanner.DoesNotExist:
                        return Response(
                            {"error": "Banner not found"},
                            status=status.HTTP_404_NOT_FOUND,
                        )
                else:
                    banner_serializer = UserPlannedBannerSerializer(data=banner_data)
                    if banner_serializer.is_valid():
                        banner_serializer.save(user=user)
                    else:
                        return Response(
                            banner_serializer.errors, status=status.HTTP_400_BAD_REQUEST
                        )
            return Response(
                {"message": "Data updated successfully"}, status=status.HTTP_200_OK
            )

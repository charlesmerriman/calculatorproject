from rest_framework.viewsets import ViewSet
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework import permissions, status
from django.db.models.functions import Coalesce
from django.db.models import F
from calculatorapi.models import (
    ClubRank, TeamTrialsRank, ChampionsMeetingRank,
    UserPlannedBanner, BannerUma, BannerSupport,
    ChampionsMeeting, EventReward, BannerTimeline
)
from calculatorapi.views.club_rank import ClubRankSerializer
from calculatorapi.views.team_trials_rank import TeamTrialsRankSerializer
from calculatorapi.views.champions_meeting_rank import ChampionsMeetingRankSerializer
from calculatorapi.views.user_planned_banner import UserPlannedBannerSerializer
from calculatorapi.views.user import UserStatsSerializer
from calculatorapi.views.banner_uma import BannerUmaSerializer
from calculatorapi.views.banner_support import BannerSupportSerializer
from calculatorapi.views.champions_meeting import ChampionsMeetingSerializer
from calculatorapi.views.event_reward import EventRewardsSerializer
from calculatorapi.views.banner_timeline import BannerTimelineForViewingSerializer


class CalculatorViewSet(ViewSet):
    permission_classes = [permissions.IsAuthenticated]

    @action(detail=False, methods=["get"], url_path="calculator-data")
    def get_calculator_data(self, request):
        club_rank_data = ClubRank.objects.all()
        team_trials_rank_data = TeamTrialsRank.objects.all()
        champions_meeting_rank_data = ChampionsMeetingRank.objects.all()
        banner_uma_data = BannerUma.objects.all().order_by("banner_timeline__start_date")
        banner_support_data = BannerSupport.objects.all().order_by("banner_timeline__start_date")
        user_planned_banner_data = UserPlannedBanner.objects.filter(
            user=request.user
        ).annotate(
            timeline_date=Coalesce(
                F('banner_uma__banner_timeline__start_date'),
                F('banner_support__banner_timeline__start_date')
            )
        ).order_by('timeline_date')
        event_rewards_data = EventReward.objects.all()
        champions_meeting_data = ChampionsMeeting.objects.all()
        banner_timeline_data = BannerTimeline.objects.prefetch_related(
            "uma_banners", "support_banners"
        ).order_by("start_date").all()

        response = {
            "club_rank_data": ClubRankSerializer(club_rank_data, many=True).data,
            "team_trials_rank_data": TeamTrialsRankSerializer(team_trials_rank_data, many=True).data,
            "champions_meeting_rank_data": ChampionsMeetingRankSerializer(champions_meeting_rank_data, many=True).data,
            "banner_uma_data": BannerUmaSerializer(banner_uma_data, many=True).data,
            "banner_support_data": BannerSupportSerializer(banner_support_data, many=True).data,
            "user_planned_banner_data": UserPlannedBannerSerializer(user_planned_banner_data, many=True).data,
            "champions_meeting_data": ChampionsMeetingSerializer(champions_meeting_data, many=True).data,
            "event_rewards_data": EventRewardsSerializer(event_rewards_data, many=True).data,
            "user_stats_data": UserStatsSerializer(request.user).data,
            "banner_timeline_data": BannerTimelineForViewingSerializer(banner_timeline_data, many=True).data,
        }

        return Response(response, status=status.HTTP_200_OK)

    @action(detail=False, methods=["patch"], url_path="calculator-data")
    def update_calculator_data(self, request):
        user = request.user

        user_stats_data = request.data.get("user_stats_data")
        if user_stats_data:
            user_stats_serializer = UserStatsSerializer(user, data=user_stats_data, partial=True)
            if user_stats_serializer.is_valid():
                user_stats_serializer.save()
            else:
                return Response(user_stats_serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        user_planned_banner_data = request.data.get("user_planned_banner_data")
        if user_planned_banner_data is not None:
            incoming_ids = [b["id"] for b in user_planned_banner_data if "id" in b]
            UserPlannedBanner.objects.filter(user=user).exclude(id__in=incoming_ids).delete()

            for banner_data in user_planned_banner_data:
                banner_id = banner_data.get("id")
                if banner_id:
                    try:
                        banner = UserPlannedBanner.objects.get(id=banner_id, user=user)
                        serializer = UserPlannedBannerSerializer(banner, data=banner_data, partial=True)
                        if serializer.is_valid():
                            serializer.save()
                        else:
                            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
                    except UserPlannedBanner.DoesNotExist:
                        return Response({"error": "Banner not found"}, status=status.HTTP_404_NOT_FOUND)
                else:
                    serializer = UserPlannedBannerSerializer(data=banner_data)
                    if serializer.is_valid():
                        serializer.save(user=user)
                    else:
                        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        return Response({"message": "Data updated successfully"}, status=status.HTTP_200_OK)

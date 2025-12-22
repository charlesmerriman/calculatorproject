from rest_framework.viewsets import ViewSet
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework import status
from calculatorapi.models import ClubRank, TeamTrialsRank, ChampionsMeetingRank, Banner
from calculatorapi.views import (
    ClubRankSerializer,
    TeamTrialsRankSerializer,
    ChampionsMeetingRankSerializer,
    BannerSerializer,
)


class CalculatorViewSet(ViewSet):
    @action(detail=False, methods=["get"], url_path="calculator-data")
    def get_calculator_data(self, request):
        club_rank_data = ClubRank.objects.all()
        team_trials_rank_data = TeamTrialsRank.objects.all()
        champions_meeting_rank_data = ChampionsMeetingRank.objects.all()
        banner_data = Banner.objects.all()

        club_rank_serializer = ClubRankSerializer(club_rank_data, many=True)
        team_trials_rank_serializer = TeamTrialsRankSerializer(
            team_trials_rank_data, many=True
        )
        champions_meeting_rank_serializer = ChampionsMeetingRankSerializer(
            champions_meeting_rank_data, many=True
        )
        banner_serializer = BannerSerializer(banner_data, many=True)

        response = {
            "club_rank_data": club_rank_serializer.data,
            "team_trials_rank_data": team_trials_rank_serializer.data,
            "champions_meeting_rank_data": champions_meeting_rank_serializer.data,
            "banner_data": banner_serializer.data,
        }

        return Response(response, status=status.HTTP_200_OK)

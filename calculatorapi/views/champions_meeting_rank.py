from rest_framework.viewsets import ViewSet
from rest_framework.response import Response
from rest_framework import serializers
from rest_framework import status
from calculatorapi.models import ChampionsMeetingRank


class ChampionsMeetingRankSerializer(serializers.ModelSerializer):
    """Serializer for ChampionsMeetingRank model"""

    class Meta:
        model = ChampionsMeetingRank
        fields = ("id", "name", "income_amount")


class ChampionsMeetingRankViewSet(ViewSet):
    """Viewset for handling ChampionsMeetingRank requests"""

    def list(self, request):

        ranks = ChampionsMeetingRank.objects.all().order_by("income_amount")
        serializer = ChampionsMeetingRankSerializer(ranks, many=True)
        return Response(serializer.data)

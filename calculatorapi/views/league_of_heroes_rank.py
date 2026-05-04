from rest_framework.viewsets import ViewSet
from rest_framework.response import Response
from rest_framework import serializers
from calculatorapi.models import LeagueOfHeroesRank


class LeagueOfHeroesRankSerializer(serializers.ModelSerializer):
    class Meta:
        model = LeagueOfHeroesRank
        fields = ("id", "name", "income_amount")


class LeagueOfHeroesRankViewSet(ViewSet):
    def list(self, request):
        ranks = LeagueOfHeroesRank.objects.all().order_by("income_amount")
        serializer = LeagueOfHeroesRankSerializer(ranks, many=True)
        return Response(serializer.data)

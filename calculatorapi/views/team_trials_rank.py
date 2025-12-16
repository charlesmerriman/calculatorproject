from rest_framework.viewsets import ViewSet
from rest_framework.response import Response
from rest_framework import serializers
from rest_framework import status
from calculatorapi.models import TeamTrialsRank


class TeamTrialsRankSerializer(serializers.ModelSerializer):
    """Serializer for TeamTrialsRank model"""

    class Meta:
        model = TeamTrialsRank
        fields = ("id", "name", "income_amount")


class TeamTrialsRankViewSet(ViewSet):
    """Viewset for handling TeamTrialsRank requests"""

    def list(self, request):

        ranks = TeamTrialsRank.objects.all().order_by("income_amount")
        serializer = TeamTrialsRankSerializer(ranks, many=True)
        return Response(serializer.data)

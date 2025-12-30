from rest_framework.viewsets import ViewSet
from rest_framework.response import Response
from rest_framework import serializers
from rest_framework import status
from calculatorapi.models import ClubRank


class ClubRankSerializer(serializers.ModelSerializer):
    """Serializer for ClubRank model"""

    class Meta:
        model = ClubRank
        fields = ("id", "name", "income_amount")


class ClubRankViewSet(ViewSet):
    """Viewset for handling ClubRank requests"""

    def list(self, request):

        ranks = ClubRank.objects.all().order_by("income_amount")
        serializer = ClubRankSerializer(ranks, many=True)
        return Response(serializer.data)

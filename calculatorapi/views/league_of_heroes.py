from rest_framework.viewsets import ViewSet
from rest_framework.response import Response
from rest_framework import serializers, permissions
from calculatorapi.models import LeagueOfHeroes


class LeagueOfHeroesSerializer(serializers.ModelSerializer):
    class Meta:
        model = LeagueOfHeroes
        fields = ("id", "name", "start_date", "end_date", "image")


class LeagueOfHeroesViewSet(ViewSet):
    # Pure reference data — readable by guests (was inheriting the global
    # IsAuthenticated default).
    permission_classes = [permissions.AllowAny]

    def list(self, request):
        events = LeagueOfHeroes.objects.all().order_by("start_date")
        serializer = LeagueOfHeroesSerializer(events, many=True)
        return Response(serializer.data)

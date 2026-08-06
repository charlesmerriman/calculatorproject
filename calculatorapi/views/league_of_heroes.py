from rest_framework.viewsets import ViewSet
from rest_framework.response import Response
from rest_framework import serializers, permissions
from calculatorapi.models import LeagueOfHeroes
from .mixins import EffectiveDateMixin, EventTypeMixin


class LeagueOfHeroesSerializer(EventTypeMixin, EffectiveDateMixin, serializers.ModelSerializer):
    event_type_value = "league_of_heroes"

    class Meta:
        model = LeagueOfHeroes
        # Field-for-field identical to ChampionsMeetingSerializer apart from the
        # number's name — the two feed the same timeline card.
        fields = (
            "id", "name", "event_type", "loh_number",
            "start_date", "end_date", "is_predicted",
            "jp_start_date", "jp_end_date", "global_start_date", "global_end_date",
            "schedule_offset_days", "applied_offset_days",
            "image",
            "track", "surface_type", "distance", "length",
            "track_condition", "season", "weather", "direction",
            "speed_recommendation", "stamina_recommendation",
            "power_recommendation", "guts_recommendation", "wit_recommendation",
        )


class LeagueOfHeroesViewSet(ViewSet):
    # Pure reference data — readable by guests (was inheriting the global
    # IsAuthenticated default).
    permission_classes = [permissions.AllowAny]

    def list(self, request):
        # Standalone route serves raw confirmed dates (mixin falls back to the
        # global_* fields with is_predicted=False); only /calculator-data injects
        # the prediction map. Order by global_start_date since the old start_date
        # column is gone.
        events = LeagueOfHeroes.objects.all().order_by("global_start_date")
        serializer = LeagueOfHeroesSerializer(events, many=True)
        return Response(serializer.data)

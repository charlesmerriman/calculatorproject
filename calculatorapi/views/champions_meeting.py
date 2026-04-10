from rest_framework import serializers
from calculatorapi.models import ChampionsMeeting


class ChampionsMeetingSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChampionsMeeting
        fields = (
            "id", "name", "start_date", "end_date", "image",
            "track", "surface_type", "distance", "length",
            "track_condition", "season", "weather", "direction",
            "speed_recommendation", "stamina_recommendation",
            "power_recommendation", "guts_recommendation", "wit_recommendation",
        )

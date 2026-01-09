from rest_framework import serializers
from calculatorapi.models import ChampionsMeeting


class ChampionsMeetingSerializer(serializers.ModelSerializer):
    image = serializers.SerializerMethodField()

    class Meta:
        model = ChampionsMeeting
        fields = (
            "id",
            "name",
            "start_date",
            "end_date",
            "image",
            "track",
            "surface_type",
            "distance",
            "length",
            "track_condition",
            "season",
            "weather",
            "direction",
            "speed_recommendation",
            "stamina_recommendation",
            "power_recommendation",
            "guts_recommendation",
            "wit_recommendation",
        )

    def get_image(self, obj):
        if obj.image:
            request = self.context.get("request")
            if request is not None:
                return request.build_absolute_uri(obj.image.url)
            return obj.image.url
        return None

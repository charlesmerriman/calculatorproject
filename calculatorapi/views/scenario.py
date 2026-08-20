from rest_framework import serializers

from calculatorapi.models import Scenario

from .mixins import StartInstantDateMixin


class ScenarioSerializer(StartInstantDateMixin, serializers.ModelSerializer):
    """A training scenario — a new, optional way to play the game.

    StartInstantDateMixin (not GameEventDateMixin) because a scenario is a
    single instant: it has a start and no end, so `end_date` is absent from the
    payload entirely rather than emitted as a permanent null. Listing it in
    `fields` below would raise — see the mixin.

    `banner_timeline` is emitted as a bare id, not a nested object. The frontend
    already holds every BannerTimeline in banner_timeline_data and needs the id
    to pin the scenario's band directly above its own row in the planner;
    nesting the banner here would duplicate a large payload for no gain, the
    same call AnniversaryEventSerializer.banner_parts makes.
    """

    class Meta:
        model = Scenario
        fields = (
            "id",
            "name",
            "image",
            "banner_timeline",
            "start_date",
            "is_predicted",
            "applied_offset_days",
        )

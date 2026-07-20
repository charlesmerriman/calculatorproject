from rest_framework import serializers


# One shared DateTimeField instance to reproduce DRF's exact ISO wire format
# (e.g. "2025-06-26T22:00:00Z") when serializing resolved (Python-computed) dates.
_DT = serializers.DateTimeField()


class EffectiveDateMixin(serializers.Serializer):
    """
    Emits the RESOLVED global dates (confirmed-or-predicted) under the existing
    `start_date`/`end_date` field names, plus an `is_predicted` flag, by looking
    up this row's id in the `effective_dates` map passed via serializer context.
    Keying by id (not queryset position) is what keeps every serialization path
    consistent for a given row.

    Model-agnostic: reused by BannerTimeline, ChampionsMeeting, and LeagueOfHeroes
    serializers. The fallback reads `obj.global_start_date`/`obj.global_end_date`,
    so any model using those field names is safe when serialized standalone (no map).
    """

    start_date = serializers.SerializerMethodField()
    end_date = serializers.SerializerMethodField()
    is_predicted = serializers.SerializerMethodField()

    def _entry(self, obj):
        emap = self.context.get("effective_dates")
        if emap is not None and obj.id in emap:
            return emap[obj.id]
        return {
            "start_date": obj.global_start_date,
            "end_date": obj.global_end_date,
            "is_predicted": False,
        }

    def get_start_date(self, obj):
        value = self._entry(obj)["start_date"]
        return _DT.to_representation(value) if value is not None else None

    def get_end_date(self, obj):
        value = self._entry(obj)["end_date"]
        return _DT.to_representation(value) if value is not None else None

    def get_is_predicted(self, obj):
        return self._entry(obj)["is_predicted"]

from rest_framework import serializers


# One shared DateTimeField instance to reproduce DRF's exact ISO wire format
# (e.g. "2025-06-26T22:00:00Z") when serializing resolved (Python-computed) dates.
_DT = serializers.DateTimeField()


class _ResolvedDateMixin(serializers.Serializer):
    """
    Emits RESOLVED dates under the existing `start_date`/`end_date` field
    names, plus an `is_predicted` flag, by looking up this row's id in the
    `effective_dates` map passed via serializer context. Keying by id (not
    queryset position) is what keeps every serialization path consistent for
    a given row.

    Subclasses provide `_fallback(obj)` for the no-context-map case — the
    shape differs per model (some models can read their own confirmed date
    fields as a fallback, others can't), so it's not implemented here.
    """

    start_date = serializers.SerializerMethodField()
    end_date = serializers.SerializerMethodField()
    is_predicted = serializers.SerializerMethodField()

    def _entry(self, obj):
        emap = self.context.get("effective_dates")
        if emap is not None and obj.id in emap:
            return emap[obj.id]
        return self._fallback(obj)

    def _fallback(self, obj):
        raise NotImplementedError

    def get_start_date(self, obj):
        value = self._entry(obj)["start_date"]
        return _DT.to_representation(value) if value is not None else None

    def get_end_date(self, obj):
        value = self._entry(obj)["end_date"]
        return _DT.to_representation(value) if value is not None else None

    def get_is_predicted(self, obj):
        return self._entry(obj)["is_predicted"]


class EffectiveDateMixin(_ResolvedDateMixin):
    """
    Model-agnostic: reused by BannerTimeline, ChampionsMeeting, and
    LeagueOfHeroes serializers. The fallback reads `obj.global_start_date`/
    `obj.global_end_date`, so any model using those field names is safe when
    serialized standalone (no map).
    """

    def _fallback(self, obj):
        return {
            "start_date": obj.global_start_date,
            "end_date": obj.global_end_date,
            "is_predicted": False,
        }


class GameEventDateMixin(_ResolvedDateMixin):
    """
    GameEvent has no global_start_date/global_end_date of its own — its dates
    come entirely from its linked BannerTimeline via a context map built by
    build_game_event_date_map/build_game_event_confirmed_date_map. If ever
    serialized without that context, fail safe to unresolved dates rather
    than raising (there's no meaningful per-object fallback to compute here).
    """

    def _fallback(self, obj):
        return {"start_date": None, "end_date": None, "is_predicted": False}

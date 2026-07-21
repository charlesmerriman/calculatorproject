from rest_framework.viewsets import ViewSet
from rest_framework.response import Response
from rest_framework import serializers, status, permissions
from calculatorapi.models import GameEvent
from calculatorapi.predictions import (
    build_game_event_confirmed_date_map,
    effective_sort_key,
)
from calculatorapi.views.mixins import GameEventDateMixin


class GameEventSerializer(GameEventDateMixin, serializers.ModelSerializer):
    class Meta:
        model = GameEvent
        fields = (
            "id", "name", "image", "start_date", "end_date", "is_predicted",
            "banner_timeline",
            "carat_amount", "carats_throughout",
            "support_ticket_amount", "uma_ticket_amount",
            "sr_shard_amount", "sr_crystal_amount",
            "ssr_shard_amount", "ssr_crystal_amount",
        )


class GameEventViewSet(ViewSet):
    def get_permissions(self):
        # create/update/destroy are admin-only; list/retrieve serve reference
        # data and are open to guests
        if self.action in ("create", "update", "destroy"):
            return [permissions.IsAdminUser()]
        return [permissions.AllowAny()]

    def list(self, request):
        game_events = GameEvent.objects.select_related("banner_timeline").all()
        # Standalone route serves confirmed dates only (no prediction), same
        # convention as /leagueofheroes — prediction is reserved for /calculator-data.
        emap = build_game_event_confirmed_date_map(game_events)
        game_events = sorted(game_events, key=lambda ge: effective_sort_key(emap.get(ge.id)))
        serializer = GameEventSerializer(game_events, many=True, context={"effective_dates": emap})
        return Response(serializer.data)

    def retrieve(self, request, pk=None):
        try:
            game_event = GameEvent.objects.select_related("banner_timeline").get(pk=pk)
        except GameEvent.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        emap = build_game_event_confirmed_date_map([game_event])
        serializer = GameEventSerializer(game_event, context={"effective_dates": emap})
        return Response(serializer.data)

    def create(self, request):
        serializer = GameEventSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(self._serialize(serializer.instance), status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def update(self, request, pk=None):
        try:
            game_event = GameEvent.objects.get(pk=pk)
        except GameEvent.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        serializer = GameEventSerializer(game_event, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(self._serialize(serializer.instance))
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def destroy(self, request, pk=None):
        try:
            game_event = GameEvent.objects.get(pk=pk)
        except GameEvent.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        game_event.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @staticmethod
    def _serialize(game_event):
        # A freshly created/updated instance never had effective_dates context
        # during the write, so re-serialize with a one-entry confirmed-date
        # map — otherwise the response would report null dates even when
        # banner_timeline was just set.
        game_event.refresh_from_db()
        emap = build_game_event_confirmed_date_map([game_event])
        return GameEventSerializer(game_event, context={"effective_dates": emap}).data

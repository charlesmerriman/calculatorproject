from rest_framework.viewsets import ViewSet
from rest_framework.response import Response
from rest_framework import serializers, status
from calculatorapi.models import GameEvent, EventReward


class EventRewardNestedSerializer(serializers.ModelSerializer):
    class Meta:
        model = EventReward
        fields = (
            "id",
            "name",
            "carat_amount",
            "support_ticket_amount",
            "uma_ticket_amount",
            "sr_shard_amount",
            "sr_crystal_amount",
            "ssr_shard_amount",
            "ssr_crystal_amount",
            "date",
        )


class GameEventSerializer(serializers.ModelSerializer):
    rewards = EventRewardNestedSerializer(many=True, read_only=True)

    class Meta:
        model = GameEvent
        fields = ("id", "name", "image", "start_date", "end_date", "rewards")


class GameEventViewSet(ViewSet):
    def list(self, request):
        game_events = GameEvent.objects.all().order_by("start_date")
        serializer = GameEventSerializer(game_events, many=True)
        return Response(serializer.data)

    def retrieve(self, request, pk=None):
        try:
            game_event = GameEvent.objects.get(pk=pk)
        except GameEvent.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        serializer = GameEventSerializer(game_event)
        return Response(serializer.data)

    def create(self, request):
        serializer = GameEventSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def update(self, request, pk=None):
        try:
            game_event = GameEvent.objects.get(pk=pk)
        except GameEvent.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        serializer = GameEventSerializer(game_event, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def destroy(self, request, pk=None):
        try:
            game_event = GameEvent.objects.get(pk=pk)
        except GameEvent.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        game_event.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

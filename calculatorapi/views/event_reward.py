from rest_framework.viewsets import ViewSet
from rest_framework.response import Response
from rest_framework import serializers, status, permissions
from calculatorapi.models import EventReward


class EventRewardsSerializer(serializers.ModelSerializer):
    class Meta:
        model = EventReward
        fields = (
            "id",
            "event",
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


class EventRewardViewSet(ViewSet):
    def get_permissions(self):
        # create/update/destroy are admin-only; list/retrieve are open to any authenticated user
        if self.action in ("create", "update", "destroy"):
            return [permissions.IsAdminUser()]
        return [permissions.IsAuthenticated()]

    def list(self, request):
        rewards = EventReward.objects.all()
        event_id = request.query_params.get("event_id")
        if event_id:
            rewards = rewards.filter(event_id=event_id)
        serializer = EventRewardsSerializer(rewards, many=True)
        return Response(serializer.data)

    def retrieve(self, request, pk=None):
        try:
            reward = EventReward.objects.get(pk=pk)
        except EventReward.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        serializer = EventRewardsSerializer(reward)
        return Response(serializer.data)

    def create(self, request):
        serializer = EventRewardsSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def update(self, request, pk=None):
        try:
            reward = EventReward.objects.get(pk=pk)
        except EventReward.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        serializer = EventRewardsSerializer(reward, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def destroy(self, request, pk=None):
        try:
            reward = EventReward.objects.get(pk=pk)
        except EventReward.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        reward.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

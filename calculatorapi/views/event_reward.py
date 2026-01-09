from rest_framework.viewsets import ViewSet
from rest_framework.response import Response
from rest_framework import serializers
from rest_framework import status
from calculatorapi.models import EventReward

class EventRewardsSerializer(serializers.ModelSerializer):
    """Serializer for Event Rewards Model"""

    class Meta:
        model = EventReward
        fields = (
            "id",
            "name",
            "carat_amount",
            "support_ticket_amount",
            "uma_ticket_amount",
            "date",
        )

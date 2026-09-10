from rest_framework import serializers
from calculatorapi.models import Uma
from .mixins import FirstJpDateMixin


class UmaSerializer(FirstJpDateMixin, serializers.ModelSerializer):
    context_key = "uma_first_jp_dates"

    class Meta:
        model = Uma
        fields = (
            "id",
            "name",
            "image",
            "admin_comments",
            # Public and rendered: the Timeline tile's hover overlay.
            "purpose",
            "first_jp_date",
            # The intrinsic selector gates. Sent on every uma because the
            # client filters both pickers and the projection's selector
            # funding by them -- see frontend/src/utils/selectorTickets.ts.
            "is_time_limited",
            "is_three_star",
        )

"""Public read-only endpoint for the Patreon thank-you list.

Deliberately its own route rather than another key on /calculator-data: this
renders on the home page, which never loads calculator data, and that payload
is already the largest response the API serves.

The response is an object, not a bare list, because the anonymous count is not
derivable from the rows that are sent — the whole point of an unticked
`is_public` is that the row never leaves the server.
"""

from rest_framework import permissions, serializers
from rest_framework.response import Response
from rest_framework.viewsets import ViewSet

from calculatorapi.models import PatreonSupporter, PatreonTier


class PatreonTierSerializer(serializers.ModelSerializer):
    class Meta:
        model = PatreonTier
        fields = ("id", "name", "order")


class PatreonSupporterSerializer(serializers.ModelSerializer):
    # Flattened rather than nested: the list renders inline, so every row needs
    # its tier's name and sort key and nothing else about the tier.
    tier_name = serializers.CharField(source="tier.name", default=None, read_only=True)
    tier_order = serializers.IntegerField(source="tier.order", default=None, read_only=True)

    class Meta:
        model = PatreonSupporter
        # `is_public`, `is_active` and `patron_since` are editorial state, not
        # content — they decide what appears here, and none of them belong on
        # the wire. `patron_since` in particular is a fact about a person that
        # the page does not display.
        fields = ("id", "display_name", "tier_name", "tier_order")


class PatreonSupporterViewSet(ViewSet):
    """GET /supporters — public, read-only, no auth header expected.

    There is no create/update/destroy pair here (unlike ChangelogEntryViewSet):
    supporters are authored in the admin only. An API write path would be one
    misconfigured permission away from letting the internet publish a name.
    """

    permission_classes = [permissions.AllowAny]

    def list(self, request):
        supporters = (
            PatreonSupporter.objects.filter(is_active=True, is_public=True)
            .select_related("tier")
        )
        # Counted, never named. This is every active supporter who has not been
        # explicitly cleared for publication.
        anonymous_count = PatreonSupporter.objects.filter(
            is_active=True, is_public=False
        ).count()

        return Response({
            "tiers": PatreonTierSerializer(PatreonTier.objects.all(), many=True).data,
            "supporters": PatreonSupporterSerializer(supporters, many=True).data,
            "anonymous_count": anonymous_count,
        })

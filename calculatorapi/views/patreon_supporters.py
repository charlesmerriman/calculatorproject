"""HTTP surface for the Patreon thank-you list: one public read, one keyed write.

GET /supporters is deliberately its own route rather than another key on
/calculator-data: this renders on the home page, which never loads calculator
data, and that payload is already the largest response the API serves.

The response is an object, not a bare list, because the anonymous count is not
derivable from the rows that are sent — the whole point of an unticked
`is_public` is that the row never leaves the server.

POST /patreon/sync at the bottom is the scheduled job's trigger. It is the one
write here, it is not a REST route on the viewset, and it publishes nothing —
see its docstring.
"""

import hmac

from django.conf import settings
from django.http import Http404
from django.utils import timezone
from rest_framework import permissions, serializers, status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.viewsets import ViewSet

from calculatorapi import patreon_api
from calculatorapi.admin_patreon_import import apply_patreon_import
from calculatorapi.models import PatreonCredentials, PatreonSupporter, PatreonTier


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

    `patreon_sync` below is not an exception to that: it is a separate keyed
    route that takes no caller-supplied content and cannot set `is_public`.
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


# ── Scheduled sync ────────────────────────────────────────────────────────────

SYNC_HEADER = "X-Patreon-Sync-Key"


class PatreonSyncThrottle(AnonRateThrottle):
    """Caps how fast the sync can be triggered from outside.

    Every accepted request spends Patreon API quota and does a full reconcile, so
    this is sized for a daily job plus the occasional manual re-run rather than
    for whatever a leaked key might attempt.
    """

    scope = "patreon_sync"


@api_view(["POST"])
@permission_classes([permissions.AllowAny])
@throttle_classes([PatreonSyncThrottle])
def patreon_sync(request):
    """POST /patreon/sync — run the supporters sync. For the scheduled job only.

    AUTHENTICATION IS A SHARED SECRET, NOT A USER. The caller is a GitHub Action,
    which has no account here and should not have one; issuing it a staff token
    would give a CI secret the run of the admin API. So it presents one key that
    authorises exactly this one action and nothing else.

    Two deliberate choices:

    - While PATREON_SYNC_SECRET is unset the route 404s, so an unconfigured
      deployment does not expose an endpoint at all. There is no state in which
      it exists but accepts anything.
    - `compare_digest` rather than `==`, so a wrong key cannot be found one
      character at a time by timing the response.

    This CANNOT publish a name: it runs the same `apply_patreon_import` as every
    other path, and that never writes `is_public`. The worst a stolen key does is
    refresh the list early and burn Patreon quota.
    """
    expected = getattr(settings, "PATREON_SYNC_SECRET", "")
    if not expected:
        raise Http404

    presented = request.headers.get(SYNC_HEADER, "")
    if not hmac.compare_digest(presented, expected):
        # Deliberately says nothing about whether the header was absent, the
        # wrong length, or simply wrong.
        return Response(
            {"detail": "Not permitted."}, status=status.HTTP_403_FORBIDDEN
        )

    credentials = PatreonCredentials.load()
    try:
        rows = patreon_api.fetch_members(credentials)
    except patreon_api.PatreonApiError as exc:
        credentials.last_sync_error = str(exc)
        credentials.save(update_fields=["last_sync_error"])
        # 502: the failure is upstream, and the scheduled job should go red so a
        # dead token surfaces instead of the list quietly going stale.
        return Response(
            {"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY
        )

    summary = apply_patreon_import(rows, deactivate_missing=True)
    credentials.last_synced_at = timezone.now()
    credentials.last_sync_error = ""
    credentials.save(update_fields=["last_synced_at", "last_sync_error"])

    # Counts only. The job log is a third-party surface, so it gets numbers
    # rather than the names of people who have not been cleared for publication.
    return Response({
        "members_returned": len(rows),
        "created": len(summary["created"]),
        "reactivated": len(summary["reactivated"]),
        "tier_changed": len(summary["tier_changed"]),
        "deactivated": len(summary["deactivated"]),
        "dates_filled": len(summary["dates_filled"]),
        "unchanged": summary["unchanged"],
    })

"""
The site's traffic beacon: a write-only endpoint the SPA pings once per session.

This exists because the frontend is a separate static site on the CDN (see
.do/app.yaml), so Django never sees a page load and cannot count one from its
own request log. The SPA tells us instead.

Counting logic lives in calculatorapi/visits.py; this module is only the HTTP
surface.
"""

from rest_framework import permissions, status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle

from calculatorapi.visits import record_visit


class VisitBeaconThrottle(AnonRateThrottle):
    """Caps how fast one address can register visits.

    The endpoint is public and unauthenticated, so without this a single client
    could inflate the page-view counter indefinitely. The rate is generous
    relative to the SPA's actual behaviour -- it fires once per browser session
    -- so a real visitor will never reach it, including several people behind
    one office or campus NAT.
    """

    scope = "visit_beacon"


@api_view(["POST"])
@permission_classes([permissions.AllowAny])
@throttle_classes([VisitBeaconThrottle])
def site_visit(request):
    """Record one visit. Always 204, never a body.

    Deliberately write-only and contentless: the request body is not read, and
    the response says nothing about whether the visit was counted (a bot filter
    hit and a successful count look identical from outside). Nothing here is
    worth telling a client about, and a beacon that leaks its own logic invites
    someone to work around it.
    """
    record_visit(request)
    return Response(status=status.HTTP_204_NO_CONTENT)

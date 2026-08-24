"""
The public feedback form's HTTP surface: a write-only endpoint anyone can post to.

Modelled closely on views/visits.py, the site's other unauthenticated write
endpoint, and shares its two rules: the request is rate limited because it is
open to the world, and the response tells the caller nothing about how the
submission was handled.
"""

from rest_framework import permissions, serializers, status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle

from calculatorapi.models import Feedback, MESSAGE_MAX_LENGTH


class FeedbackThrottle(AnonRateThrottle):
    """Caps how fast one address can submit feedback.

    The endpoint is public and unauthenticated, so this is what stops someone
    filling the table overnight. The rate is set for a human typing a report,
    not for a script: 10/hour is far more than anyone submits in good faith,
    while still leaving room for a few people behind one NAT.

    Note this reads the client address to build its cache key but never writes
    it anywhere — see the note on Feedback about IP addresses.
    """

    scope = "feedback"


class FeedbackSerializer(serializers.ModelSerializer):
    """Validates an incoming submission.

    `user`, `submitted_at` and `is_resolved` are deliberately absent from
    `fields`: a client must not be able to attribute its message to someone
    else's account, backdate it, or file it pre-resolved. The view sets the
    user itself from the authenticated request.
    """

    # Mirrors the model's cap so an over-long body is a clean 400 with a field
    # error rather than a database-level failure. allow_blank=False is the
    # default but stated explicitly — an empty report is the one thing this
    # endpoint has no use for.
    message = serializers.CharField(
        max_length=MESSAGE_MAX_LENGTH,
        allow_blank=False,
        trim_whitespace=True,
    )

    class Meta:
        model = Feedback
        fields = ("category", "message", "source_path")


@api_view(["POST"])
@permission_classes([permissions.AllowAny])
@throttle_classes([FeedbackThrottle])
def submit_feedback(request):
    """Accept one message. 201 on success, 400 only for a malformed body.

    Guests and signed-in users both post here. A signed-in submission is linked
    to the sender's account so repeat reporters are visible in the admin; a
    guest's is stored with user=None. Nothing about the account beyond that
    reference is recorded, because nothing else is held in the first place.
    """
    # Honeypot. `website` is rendered as a hidden, tab-skipped, autocomplete-off
    # input that a person never sees and therefore never fills; a naive bot
    # fills every field it finds. A filled honeypot returns the SAME 201 as a
    # real submission and stores nothing.
    #
    # Answering "spam detected" would be strictly worse: it tells whoever is
    # probing exactly which field to leave alone next time. This mirrors the
    # reasoning already written into the visit beacon, where a bot filter hit
    # and a successful count are indistinguishable from outside.
    if request.data.get("website"):
        return Response(status=status.HTTP_201_CREATED)

    serializer = FeedbackSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    serializer.save(
        # request.user is AnonymousUser for guests, which is not a saveable FK
        # value — normalize it to None.
        user=request.user if request.user.is_authenticated else None
    )

    return Response(status=status.HTTP_201_CREATED)

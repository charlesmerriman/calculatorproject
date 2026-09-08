"""
GET /account — who the caller is, and what they are entitled to.

WHY THIS IS ITS OWN ROUTE
-------------------------
Until now the SPA decided "is someone signed in?" by asking whether a token
string was sitting in localStorage. That answers a question about the BROWSER,
not about the account: it cannot say who the user is, and it cannot say whether
they are entitled to anything. Every feature that needs a real answer — a
supporter badge in the navbar, suppressing ads for supporters, gating a
supporter-only feature — needs one place to ask, on every route.

It is deliberately NOT a key on /calculator-data, for two reasons:

  * That response is already the largest the API serves, and the answer is
    needed on the home page, the FAQ and the changelog — none of which fetch
    calculator data at all.
  * Everything in it but four user-scoped keys is served out of a shared
    process-wide cache (see public_payload_cache.py). Entitlement must never
    be answerable from a cache keyed on anything but the requesting user.

Same reasoning that gives GET /supporters its own route rather than a corner of
the calculator payload.

WHAT IT DELIBERATELY DOES NOT RETURN
------------------------------------
No `subject_id`, for any provider. That is the opaque per-provider id the whole
sign-in design exists to avoid spreading around (see models/social_account.py),
and being behind IsAuthenticated is not on its own what keeps it off the wire —
the serializer's EXPLICIT FIELD LIST is. That list plays exactly the role
PatreonSupporterSerializer's does for the supporter email: it is the one thing
standing between a private column and a response body. Add a field to it only
with a reason that survives being written down.

SUPPORTER STATUS IS A STUB, ON PURPOSE
--------------------------------------
`supporter` is always {"is_supporter": false} today. Nothing CAN be a supporter
yet: no site account can be matched to a Patreon patron until PatreonSupporter
grows `patreon_user_id` and `linked_user`, which is Phase 2 work.

The block ships now anyway so the client contract does not change when
entitlement becomes real — the frontend reads `supporter.is_supporter` today
and keeps reading the same key afterwards. Retrofitting the shape later would
mean touching every consumer twice.

See patreon-accounts-plan.md, Phase 0.
"""

from django.utils import timezone
from rest_framework import permissions, serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from calculatorapi.models import SocialAccount


class LinkedProviderSerializer(serializers.ModelSerializer):
    """One linked identity, reduced to what a UI needs to draw a row.

    `provider` is the raw stored value ("google", "discord"), not its display
    label: the client keys off it to decide what is already linked, and how to
    spell it for a human is a presentation decision that belongs in the SPA.
    """

    # created_at is a DateTimeField, and DRF's DateField REFUSES to coerce a
    # datetime rather than silently dropping a timezone — so the conversion is
    # explicit here. `localdate` resolves against settings.TIME_ZONE, which is
    # UTC for this project, matching every other date the API emits.
    #
    # A date rather than a timestamp because the exact minute someone linked an
    # account is a detail about a person that no screen needs — the same
    # reasoning that keeps PatreonSupporter.patron_since a DateField.
    linked_at = serializers.SerializerMethodField()

    class Meta:
        model = SocialAccount
        # THE PRIVACY BOUNDARY — read the module docstring before adding to it.
        # `subject_id` and the internal row id are absent deliberately.
        fields = ["provider", "linked_at"]

    def get_linked_at(self, obj):
        return timezone.localdate(obj.created_at)


def _supporter_block(_user):
    """The caller's Patreon entitlement.

    Always "not a supporter" in Phase 0 — see the module docstring. When Phase 2
    lands, this reads the linked PatreonSupporter row and becomes:

        is_supporter = row exists AND row.is_active AND row.tier is not None

    DERIVED, never a cached boolean on CustomUser. A copied flag is a second
    truth that drifts the moment a pledge lapses or resumes, and the drift is
    invisible: someone cancels and keeps their benefits, or renews and silently
    does not get them back. The daily Patreon sync already keeps the supporter
    row honest, so deriving from it costs nothing and cannot go stale.

    When there is no entitlement the block carries `is_supporter` and NOTHING
    ELSE — no null tier fields. A null tier name sitting next to
    `is_supporter: false` is an invitation for a client to render an empty badge
    or read the absence of a tier as a tier.
    """
    return {"is_supporter": False}


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def account_detail(request):
    """The signed-in user's account summary.

    401 for anonymous callers, which is what makes this usable as the client's
    source of truth: a token that has expired or been revoked server-side gets a
    401 here, so the SPA finds out and can drop it, rather than trusting a
    string in localStorage that stopped meaning anything.

    Staff are not a special case. They sign in with a password and so hold no
    SocialAccount rows at all, which simply makes `linked_providers` empty —
    a correct answer, not an error, and worth a test so it stays that way.
    """
    user = request.user

    linked = SocialAccount.objects.filter(user=user).order_by("created_at")

    return Response(
        {
            # The generated handle ("user_a3f9c1"), never a real name — social
            # sign-in deliberately never learns one. Included so the account
            # page has something to show and two accounts can be told apart.
            "username": user.username,
            "linked_providers": LinkedProviderSerializer(linked, many=True).data,
            "supporter": _supporter_block(user),
        }
    )

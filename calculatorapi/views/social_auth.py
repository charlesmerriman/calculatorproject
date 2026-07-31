"""
Sign-in endpoints for Google / Discord.

Two steps, matching the OAuth2 authorization-code flow in calculatorapi/oauth.py:

  GET  /auth/<provider>/start  -> {"authorize_url": ..., "state": ...}
  POST /auth/social            -> {"token": ...}

The SPA sends the browser to `authorize_url`, the provider bounces it back to
the frontend's /auth/callback with a one-time `code`, and the SPA posts that
code here. The response shape {"token": ...} deliberately matches the existing
password login so the frontend stores it identically.
"""

import secrets

from django.conf import settings
from django.core import signing
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.authtoken.models import Token

from calculatorapi import oauth
from calculatorapi.models import CustomUser, SocialAccount

# Namespaces the signature so a state string cannot be repurposed as, or forged
# from, any other value signed with the same SECRET_KEY.
STATE_SALT = "calculatorapi.social-auth-state"

# Generated handles look like "user_a3f9c1". Deliberately NOT derived from the
# provider's username or name -- that is exactly the personal data this whole
# feature exists to avoid holding.
USERNAME_PREFIX = "user_"
USERNAME_RANDOM_BYTES = 3
MAX_USERNAME_ATTEMPTS = 5

# One generic message for every rejection. Distinguishing "bad state" from "bad
# code" would only help someone probing the endpoint.
GENERIC_AUTH_ERROR = {"error": "Could not complete sign in. Please try again."}


def _issue_state(provider):
    """Sign a short-lived state token binding this login attempt to a provider.

    Guards against login CSRF: without it, an attacker could pre-start a login
    with their own account and trick a victim's browser into completing it,
    silently signing the victim into the attacker's account. `signing.dumps`
    uses a TimestampSigner, so `loads(max_age=...)` enforces expiry as well as
    authenticity. The random nonce keeps two states issued in the same second
    from being identical; the frontend also stores a copy in sessionStorage and
    compares it on return, which an attacker cannot write to.
    """
    return signing.dumps(
        {"p": provider, "n": secrets.token_urlsafe(16)},
        salt=STATE_SALT,
    )


def _state_is_valid(state, provider):
    if not state:
        return False
    try:
        payload = signing.loads(
            state,
            salt=STATE_SALT,
            max_age=settings.OAUTH_STATE_MAX_AGE_SECONDS,
        )
    except signing.BadSignature:
        # Covers SignatureExpired too (it subclasses BadSignature).
        return False
    # A state minted for Google must not be replayable against Discord.
    return payload.get("p") == provider


def _create_anonymous_user():
    """Create a CustomUser carrying no personal data at all.

    Blank email/first/last name and an unusable password: there is no password
    to check because sign-in always goes through the provider. The retry loop
    handles the (vanishingly unlikely) case of two random handles colliding --
    the DB's unique constraint on username is what actually decides.
    """
    for _ in range(MAX_USERNAME_ATTEMPTS):
        username = USERNAME_PREFIX + secrets.token_hex(USERNAME_RANDOM_BYTES)
        user = CustomUser(username=username, email="", first_name="", last_name="")
        user.set_unusable_password()
        try:
            with transaction.atomic():
                user.save()
            return user
        except IntegrityError:
            continue
    raise RuntimeError("Could not generate a unique username")


@api_view(["GET"])
@permission_classes([permissions.AllowAny])
def social_auth_start(request, provider):
    """Hand the SPA the provider consent URL to redirect the browser to."""
    if not oauth.is_supported(provider):
        return Response(
            {"error": "Unknown provider"}, status=status.HTTP_404_NOT_FOUND
        )
    state = _issue_state(provider)
    try:
        authorize_url = oauth.build_authorize_url(provider, state)
    except oauth.OAuthError:
        # Only reachable when the client id/secret env vars are missing, which
        # is a deployment fault rather than anything the user did.
        return Response(
            {"error": "Sign in is unavailable right now."},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    return Response({"authorize_url": authorize_url, "state": state})


@api_view(["POST"])
@permission_classes([permissions.AllowAny])
def social_auth_complete(request):
    """Redeem the one-time code and return an API token for the matching user."""
    provider = request.data.get("provider")
    code = request.data.get("code")
    state = request.data.get("state")

    if not oauth.is_supported(provider):
        return Response(
            {"error": "Unknown provider"}, status=status.HTTP_404_NOT_FOUND
        )
    if not code or not _state_is_valid(state, provider):
        return Response(GENERIC_AUTH_ERROR, status=status.HTTP_400_BAD_REQUEST)

    try:
        subject_id = oauth.exchange_code(provider, code)
    except oauth.OAuthError:
        # Expired/replayed code, provider outage, or a redirect_uri mismatch.
        # The underlying detail stays server-side.
        return Response(GENERIC_AUTH_ERROR, status=status.HTTP_400_BAD_REQUEST)

    # get_or_create on (provider, subject_id) is what makes a returning user
    # resolve to their existing account -- and the DB's unique constraint is
    # what guarantees it even if two sign-ins race.
    try:
        with transaction.atomic():
            social, created = SocialAccount.objects.select_related("user").get_or_create(
                provider=provider,
                subject_id=subject_id,
                defaults={"user": _create_anonymous_user},
            )
    except IntegrityError:
        # Lost a race against a concurrent first sign-in; the row now exists.
        social = SocialAccount.objects.select_related("user").get(
            provider=provider, subject_id=subject_id
        )
        created = False

    social.last_login_at = timezone.now()
    social.save(update_fields=["last_login_at"])

    token, _ = Token.objects.get_or_create(user=social.user)
    return Response(
        {"token": token.key},
        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
    )

"""
OAuth2 authorization-code flow for Google and Discord sign-in.

Ordinary users never give us a password. The provider verifies who they are and
hands back one opaque, provider-scoped id (Google's `sub`, Discord's user `id`),
which is the only thing we persist -- see models/social_account.py.

The flow, end to end:

1. `build_authorize_url()` produces the provider's consent-screen URL. The SPA
   sends the browser there.
2. The provider bounces the browser back to OAUTH_REDIRECT_URI with a one-time
   `code`. That code is worthless on its own: it is single-use, expires in
   seconds, and cannot be redeemed without our client secret.
3. `exchange_code()` redeems it server-to-server (no browser involved, secret
   never leaves this process) and returns the subject id.

This module is pure provider logic -- no Django views, no ORM -- mirroring the
split used by predictions.py and analytics.py. Everything that can go wrong
raises OAuthError so the view can collapse the lot into one generic 400 rather
than leaking provider internals to the client.

PRIVACY NOTE: the scopes below are the narrowest each provider allows. Google's
"openid" yields only `sub`; Discord's "identify" yields a small profile object
we read one field from. Neither sends an email address, so none can be stored
here by accident. Do not widen these without a deliberate reason.
"""

import base64
import binascii
import json
import time
from urllib.parse import urlencode

import requests
from django.conf import settings

# Providers can be slow, but a hung request would tie up a gunicorn worker.
HTTP_TIMEOUT_SECONDS = 10

GOOGLE = "google"
DISCORD = "discord"


class OAuthError(Exception):
    """Any failure during the OAuth exchange (network, provider, or malformed
    response). Deliberately carries no provider detail toward the client."""


def _google_config():
    return {
        "authorize_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        # Minimum Google permits. Adding "email"/"profile" would make Google
        # send us PII we have promised not to hold.
        "scope": "openid",
        "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
        "client_secret": settings.GOOGLE_OAUTH_CLIENT_SECRET,
        "extra_authorize_params": {},
    }


def _discord_config():
    return {
        "authorize_url": "https://discord.com/oauth2/authorize",
        "token_url": "https://discord.com/api/oauth2/token",
        # "identify" returns id/username/avatar but NOT email (that would need
        # the separate "email" scope). We read only `id`.
        "scope": "identify",
        "client_id": settings.DISCORD_OAUTH_CLIENT_ID,
        "client_secret": settings.DISCORD_OAUTH_CLIENT_SECRET,
        "extra_authorize_params": {},
    }


# Built per call rather than at import time so @override_settings works in tests.
_PROVIDER_BUILDERS = {
    GOOGLE: _google_config,
    DISCORD: _discord_config,
}

SUPPORTED_PROVIDERS = tuple(_PROVIDER_BUILDERS)


def is_supported(provider):
    """True if `provider` is one we can sign in with. Lets the view 404 an
    unknown provider before any work happens."""
    return provider in _PROVIDER_BUILDERS


def get_config(provider):
    if not is_supported(provider):
        raise OAuthError(f"Unsupported provider: {provider}")
    config = _PROVIDER_BUILDERS[provider]()
    if not config["client_id"] or not config["client_secret"]:
        # Misconfiguration, not user error -- surfaced as a 500 by the view so a
        # missing env var in production is loud rather than looking like a
        # rejected login.
        raise OAuthError(f"{provider} OAuth credentials are not configured")
    return config


def build_authorize_url(provider, state):
    """The provider's consent-screen URL to send the browser to."""
    config = get_config(provider)
    params = {
        "client_id": config["client_id"],
        "redirect_uri": settings.OAUTH_REDIRECT_URI,
        "response_type": "code",
        "scope": config["scope"],
        "state": state,
        **config["extra_authorize_params"],
    }
    return f"{config['authorize_url']}?{urlencode(params)}"


def _post_token_request(config, code):
    """Redeem the one-time code for provider tokens. Server-to-server: this is
    the only place the client secret is used, and it never touches the browser."""
    payload = {
        "client_id": config["client_id"],
        "client_secret": config["client_secret"],
        "code": code,
        "grant_type": "authorization_code",
        # Must match the value sent to the authorize endpoint exactly; providers
        # treat this as part of the code's binding, not as a redirect target.
        "redirect_uri": settings.OAUTH_REDIRECT_URI,
    }
    try:
        response = requests.post(
            config["token_url"],
            data=payload,
            headers={"Accept": "application/json"},
            timeout=HTTP_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise OAuthError("Token request failed") from exc

    if response.status_code != 200:
        # Usually an expired/replayed code or a redirect_uri mismatch. The body
        # can echo request details, so it is not forwarded to the client.
        raise OAuthError(f"Token endpoint returned {response.status_code}")

    try:
        return response.json()
    except ValueError as exc:
        raise OAuthError("Token endpoint returned malformed JSON") from exc


def _decode_jwt_payload(token):
    """Decode a JWT's payload WITHOUT verifying its signature.

    That is normally a serious mistake, but it is the approach Google documents
    for this specific flow: the token did not arrive via the browser, it came
    straight back from Google's token endpoint over TLS in exchange for our
    client secret. There is no untrusted middleman whose tampering a signature
    check would catch -- anyone able to forge this response could already
    intercept TLS. The caller still validates iss/aud/exp below, which is what
    actually catches a misconfigured client id.

    If this ever starts accepting an id_token from any other source (e.g. one
    posted by the frontend), this MUST become a verifying parse instead.
    """
    parts = token.split(".")
    if len(parts) != 3:
        raise OAuthError("Malformed id_token")
    try:
        # JWTs use base64url without padding; b64decode needs it, and an
        # over-long pad is ignored, so always appending "==" is safe.
        decoded = base64.urlsafe_b64decode(parts[1] + "==")
        return json.loads(decoded)
    except (ValueError, binascii.Error) as exc:
        raise OAuthError("Could not decode id_token payload") from exc


def _google_subject_id(config, token_data):
    id_token = token_data.get("id_token")
    if not id_token:
        raise OAuthError("Google response contained no id_token")

    claims = _decode_jwt_payload(id_token)

    # Cheap sanity checks that catch a misconfigured client id or a token minted
    # for a different app entirely.
    if claims.get("iss") not in ("accounts.google.com", "https://accounts.google.com"):
        raise OAuthError("Unexpected id_token issuer")
    if claims.get("aud") != config["client_id"]:
        raise OAuthError("id_token was not issued for this client")
    expires_at = claims.get("exp")
    if not isinstance(expires_at, int) or expires_at <= time.time():
        raise OAuthError("id_token is expired or has no expiry")

    subject_id = claims.get("sub")
    if not subject_id:
        raise OAuthError("id_token contained no subject")
    return str(subject_id)


def _discord_subject_id(_config, token_data):
    access_token = token_data.get("access_token")
    if not access_token:
        raise OAuthError("Discord response contained no access_token")

    try:
        response = requests.get(
            "https://discord.com/api/users/@me",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=HTTP_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise OAuthError("Discord profile request failed") from exc

    if response.status_code != 200:
        raise OAuthError(f"Discord profile endpoint returned {response.status_code}")

    try:
        profile = response.json()
    except ValueError as exc:
        raise OAuthError("Discord profile endpoint returned malformed JSON") from exc

    subject_id = profile.get("id")
    if not subject_id:
        raise OAuthError("Discord profile contained no id")
    # Everything else in `profile` (username, avatar, ...) is intentionally
    # dropped here and never stored or logged.
    return str(subject_id)


_SUBJECT_EXTRACTORS = {
    GOOGLE: _google_subject_id,
    DISCORD: _discord_subject_id,
}


def exchange_code(provider, code):
    """Redeem a one-time authorization code and return the provider's opaque
    subject id. Raises OAuthError on every failure path."""
    config = get_config(provider)
    token_data = _post_token_request(config, code)
    return _SUBJECT_EXTRACTORS[provider](config, token_data)

"""
Patreon API v2 client for the supporters sync.

This module is pure provider logic — no Django views, no serializers — mirroring
the split used by oauth.py, predictions.py and analytics.py. It touches the ORM
for exactly one thing: reading and rotating the token pair on PatreonCredentials.
Everything that can go wrong raises PatreonApiError so callers can report one
readable line instead of leaking Patreon's internals.

WHAT IT ASKS FOR, AND WHY THAT LIST IS THE POINT
------------------------------------------------
Patreon's member resource can carry email, shipping address, phone, charge
history and lifetime totals. None of that belongs in this database.

MEMBER_FIELDS below is the ONLY thing keeping it out. We name the four fields we
want, so the response does not contain the rest in the first place.

Do not expect the OAuth scopes to be a second line of defence here. Email and
address have their own scopes (`campaigns.members[email]`,
`campaigns.members.address`), but a CREATOR access token — the kind issued
straight from the developer portal, which is what this integration uses —
automatically carries every v2 scope. There are no scope checkboxes to leave
unticked. So the token CAN read email and postal addresses, and the only reason
it does not is that this list does not ask for them.

That still leaves this stronger than the CSV path in admin_patreon_import.py,
where the wide export reaches the server and the parser has to discard columns;
here the data never leaves Patreon. But it rests on one thing, not two. Adding a
name to MEMBER_FIELDS is the review point — the same role REQUIRED_COLUMNS plays
over there. Do not add one without a reason that survives being written down.

OUTPUT SHAPE
------------
`fetch_members()` returns the SAME row dicts `parse_patreon_csv` returns —
display_name / tier_name / is_active — plus an optional `patron_since`. Both
feed the one reconcile, `apply_patreon_import`, so the CSV and the API cannot
drift into treating the same data differently.

WHO COUNTS
----------
Only members entitled to a PAID tier. Patreon's members endpoint returns free
followers too, and marks many of them `active_patron` — see _row_from_member.
"""

from datetime import datetime, timedelta, timezone as dt_timezone

import requests
from django.conf import settings
from django.utils import timezone

from calculatorapi.models import PatreonCredentials

API_ROOT = "https://www.patreon.com/api/oauth2/v2"
TOKEN_URL = "https://www.patreon.com/api/oauth2/token"

# Matches oauth.py. Long enough for a slow provider, short enough that a hung
# connection cannot hold a worker (or the admin request behind it) open.
HTTP_TIMEOUT_SECONDS = 10

# Patreon serves up to 1000 members per page. Asking for the maximum keeps a
# few-hundred-patron campaign to a single request.
PAGE_SIZE = 500

# ── The privacy boundary. Read the module docstring before touching. ──────────
MEMBER_FIELDS = ("full_name", "patron_status", "pledge_relationship_start")
# `amount_cents` is the TIER's price, not a person's billing data, and it is read
# transiently to tell a paid tier from a free one — see _row_from_member. It is
# never stored: PatreonTier deliberately carries no money column.
TIER_FIELDS = ("title", "amount_cents")

# Patreon's own vocabulary: "active_patron", "declined_patron", "former_patron".
# A declined patron is a failed payment, not a cancellation — but they are not
# currently paying, so they are treated the same as a former patron here and
# come back automatically when the charge succeeds.
ACTIVE_STATUS = "active_patron"


class PatreonApiError(Exception):
    """Anything that stopped us getting a usable answer out of Patreon."""


def _request(method, url, *, token=None, **kwargs):
    """One HTTP call, with every failure mode collapsed into PatreonApiError."""
    headers = kwargs.pop("headers", {})
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        response = requests.request(
            method, url, headers=headers, timeout=HTTP_TIMEOUT_SECONDS, **kwargs
        )
    except requests.RequestException as exc:
        raise PatreonApiError(f"Could not reach Patreon: {exc}") from exc

    if response.status_code >= 400:
        # Status only. The body can contain member data on some endpoints, and
        # this message ends up in last_sync_error and in job logs.
        raise PatreonApiError(
            f"Patreon returned HTTP {response.status_code} for {url.split('?', maxsplit=1)[0]}"
        )
    try:
        return response.json()
    except ValueError as exc:
        raise PatreonApiError("Patreon returned a response that was not JSON") from exc


def _refresh_access_token(credentials):
    """Spend the refresh token for a new pair and persist BOTH halves.

    Patreon rotates the refresh token on every refresh: the one we sent is dead
    afterwards. If we saved only the access token, the next run would present a
    spent refresh token and the sync would be permanently broken with no obvious
    cause — so the write below must stay atomic in intent, both fields together.
    """
    client_id = getattr(settings, "PATREON_CLIENT_ID", "")
    client_secret = getattr(settings, "PATREON_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        raise PatreonApiError(
            "PATREON_CLIENT_ID / PATREON_CLIENT_SECRET are not set, so the access "
            "token cannot be refreshed."
        )

    payload = _request(
        "POST",
        TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "refresh_token": credentials.refresh_token,
            "client_id": client_id,
            "client_secret": client_secret,
        },
    )

    access_token = payload.get("access_token")
    refresh_token = payload.get("refresh_token")
    if not access_token or not refresh_token:
        raise PatreonApiError(
            "Patreon's token response was missing a token. The refresh token may "
            "have been revoked — re-issue one in the Patreon developer portal."
        )

    credentials.access_token = access_token
    credentials.refresh_token = refresh_token
    expires_in = payload.get("expires_in")
    credentials.expires_at = (
        timezone.now() + timedelta(seconds=int(expires_in))
        if expires_in
        else None
    )
    credentials.save(update_fields=["access_token", "refresh_token", "expires_at"])
    return credentials.access_token


def get_access_token(credentials=None):
    """A token that will still be valid for the duration of this sync."""
    credentials = credentials or PatreonCredentials.load()
    if not credentials.is_configured:
        raise PatreonApiError(
            "No Patreon refresh token is configured. Set PATREON_REFRESH_TOKEN "
            "(and PATREON_ACCESS_TOKEN) from the Patreon developer portal."
        )
    if credentials.token_is_stale():
        return _refresh_access_token(credentials)
    return credentials.access_token


def fetch_campaign_id(token, credentials=None):
    """The creator's own campaign id, resolved once and then cached on the row."""
    credentials = credentials or PatreonCredentials.load()
    if credentials.campaign_id:
        return credentials.campaign_id

    payload = _request("GET", f"{API_ROOT}/campaigns", token=token)
    campaigns = payload.get("data") or []
    if not campaigns:
        raise PatreonApiError(
            "This Patreon account has no campaigns. The token must belong to the "
            "creator account that owns the page."
        )
    # A creator can in principle own several; the token is issued per account and
    # this project has exactly one page, so the first is the only one.
    credentials.campaign_id = str(campaigns[0].get("id", ""))
    credentials.save(update_fields=["campaign_id"])
    return credentials.campaign_id


def _parse_pledge_start(raw):
    """Patreon's ISO-8601 pledge start -> a date, or None.

    Only the date half is kept: `patron_since` is a DateField whose sole job is
    ordering supporters within a tier, and the exact minute someone pledged is a
    detail about a person that the site has no use for.
    """
    if not raw:
        return None
    try:
        # Python 3.11+ parses the trailing "Z" that Patreon sends.
        parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt_timezone.utc)
    return parsed.astimezone(dt_timezone.utc).date()


def _tiers_by_id(included):
    """Index the sideloaded `included` block as {id: (title, amount_cents)}."""
    tiers = {}
    for entry in included or []:
        if entry.get("type") != "tier":
            continue
        attributes = entry.get("attributes") or {}
        tiers[entry.get("id")] = (
            attributes.get("title", ""),
            attributes.get("amount_cents") or 0,
        )
    return tiers


def _row_from_member(member, tiers):
    """One member resource -> the row dict the reconcile expects, or None.

    Returns None for anyone who should not be on a thank-you list at all.

    FREE MEMBERS ARE NOT SUPPORTERS. Patreon's members endpoint returns free
    followers alongside paying patrons, and marks some of them `active_patron`
    — a free membership IS an active membership as far as Patreon is concerned.
    Taking that at face value would thank people who have not pledged and
    inflate the "and N others" count, which is unfair to the people who did.

    The test is the TIER'S PRICE, not its name: "Free" is just what this
    creator called their free tier today, and renaming it must not silently add
    forty followers to the list.

    Former patrons fall out here too, and correctly: once a pledge ends the
    member is entitled to no tier, so they are dropped from the response rows
    and `deactivate_missing` retires the row they already had — keeping their
    consent decision, as the model intends. A DECLINED patron (failed payment)
    usually keeps their entitlement, so they stay, marked inactive.
    """
    attributes = member.get("attributes") or {}
    name = (attributes.get("full_name") or "").strip()
    if not name:
        # Same rule as the CSV parser: someone unnameable cannot be thanked and
        # cannot be matched against an existing row.
        return None

    # A member can hold several entitled tiers; take the first PAID one. The
    # highest-ordered is not knowable from here, and most patrons have exactly
    # one, so the rare multi-tier case is left for an editor to correct.
    tier_ids = [
        item.get("id")
        for item in ((member.get("relationships") or {})
                     .get("currently_entitled_tiers") or {}).get("data") or []
    ]
    tier_name = ""
    for tier_id in tier_ids:
        title, amount_cents = tiers.get(tier_id, ("", 0))
        if amount_cents > 0:
            tier_name = title
            break

    if not tier_name:
        return None

    return {
        # Truncated rather than raising, matching parse_patreon_csv: an
        # over-long name is a display problem, not an import failure.
        "display_name": name[:100],
        "tier_name": tier_name,
        "is_active": attributes.get("patron_status") == ACTIVE_STATUS,
        "patron_since": _parse_pledge_start(attributes.get("pledge_relationship_start")),
    }


def fetch_members(credentials=None):
    """Every member of the campaign, as reconcile-ready rows.

    Paginates by cursor until Patreon stops offering a next one. Duplicate
    display names are collapsed the same way the CSV parser collapses them,
    because the supporters table is unique on a casefolded display name.
    """
    credentials = credentials or PatreonCredentials.load()
    token = get_access_token(credentials)
    campaign_id = fetch_campaign_id(token, credentials)

    rows = []
    seen = set()
    cursor = None
    while True:
        params = {
            "include": "currently_entitled_tiers",
            "fields[member]": ",".join(MEMBER_FIELDS),
            "fields[tier]": ",".join(TIER_FIELDS),
            "page[count]": PAGE_SIZE,
        }
        if cursor:
            params["page[cursor]"] = cursor

        payload = _request(
            "GET", f"{API_ROOT}/campaigns/{campaign_id}/members", token=token, params=params
        )
        tiers = _tiers_by_id(payload.get("included"))
        for member in payload.get("data") or []:
            row = _row_from_member(member, tiers)
            if row is None:
                continue
            key = row["display_name"].casefold()
            if key in seen:
                continue
            seen.add(key)
            rows.append(row)

        cursor = (
            ((payload.get("meta") or {}).get("pagination") or {}).get("cursors") or {}
        ).get("next")
        if not cursor:
            return rows

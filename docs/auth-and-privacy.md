# Authentication & Privacy

Developer notes on how sign-in works and which properties must be preserved.
For endpoint request/response shapes see [api-reference.md](api-reference.md).

---

## The core privacy constraint

Ordinary accounts exist **only** as a Google/Discord identity. The site holds no
email, no name, and no usable password for them.

This is a deliberate design constraint, not an incidental side effect of using
OAuth. Changes in this area should preserve it.

Concretely, a non-staff `CustomUser` row carries:

- blank `email`, `first_name`, `last_name`
- an unusable password
- a generated `user_xxxxxx` username

The linked `SocialAccount` row stores `(provider, subject_id)` — unique together.
That opaque `subject_id` is the only identifying value stored anywhere in the system.

Staff accounts are the exception: they keep password login so `/admin` and the
analytics dashboard remain reachable.

---

## The OAuth2 flow

Implemented in `calculatorapi/oauth.py` (pure logic) and
`calculatorapi/views/social_auth.py` (the views). Standard authorization-code flow:

1. `GET /auth/<provider>/start` returns the provider's consent URL plus a signed `state`.
2. The provider redirects the browser to the **frontend** at `/auth/callback`.
3. The SPA posts `{provider, code, state}` to `POST /auth/social`.
4. Django exchanges the code server-to-server and returns a DRF token.

The client secret never leaves Django. The `code` that transits the browser is safe —
single-use, valid for seconds, and unredeemable without the secret — and is strictly
better than putting a long-lived token in a URL.

`oauth.py` is a pure-logic module (no views, no ORM), mirroring the
`predictions.py` / `analytics.py` split used elsewhere in this app.

---

## Invariants

### Scopes are the narrowest each provider allows — do not widen them

- Google: `openid`
- Discord: `identify`

Neither transmits an email address to us. Widening these would break the privacy
constraint above at the source.

### `state` is signed and provider-bound

Signed with `django.core.signing.dumps`, salt `calculatorapi.social-auth-state`,
`max_age` = `OAUTH_STATE_MAX_AGE_SECONDS`. It carries the provider name, so a Google
state cannot be replayed at Discord.

The frontend keeps a matching copy in `sessionStorage` under `oauthState.v1` — **that
browser binding is what actually defeats login CSRF**, not the signature alone.

sessionStorage rather than a cookie because dev is cross-origin (`:5173` → `:8000`),
and a cookie would need `SameSite=None; Secure`.

### Google's `id_token` is decoded without signature verification

In `_decode_jwt_payload`. This is Google's documented approach for the authorization-code
flow: the token comes straight from their token endpoint over TLS, in exchange for the
client secret. `iss` / `aud` / `exp` are still asserted.

**If an `id_token` ever arrives from any other source, this must become a verifying parse.**

### `get_or_create` is passed the callable, not a call

```python
SocialAccount.objects.get_or_create(
    provider=..., subject_id=...,
    defaults={"user": _create_anonymous_user},   # NOT _create_anonymous_user()
)
```

Django only invokes the callable when it actually creates. Adding `()` would create an
orphan `CustomUser` on **every returning sign-in** — silently, because nothing else
breaks. Covered by `test_returning_user_same_account_no_orphan`.

### `POST /login` is staff-only and non-enumerable

A correct password on a non-staff account returns the same status **and the same body**
as a wrong password, so the endpoint cannot be used to enumerate usernames. Covered by
`test_non_staff_rejection_is_indistinguishable_from_wrong_password`.

### Redirect URI must match byte-for-byte

Derived once as `settings.OAUTH_REDIRECT_URI = f"{FRONTEND_URL}/auth/callback"`. It must
match the provider console entry exactly — a trailing slash breaks it.

Note the frontend owns the `/auth/callback` route: the SPA's `catchall_document:
index.html` serves it, and DigitalOcean ingress does **not** proxy it to Django.

---

## `purge_user_pii`

Retires PII from accounts created before the social-login cutover.

```bash
python manage.py purge_user_pii --dry-run   # report only
python manage.py purge_user_pii             # prompts for confirmation
```

Strips email, name, and password from all non-staff accounts. **Irreversible.** After it
runs, those accounts cannot sign in at all — their plans stay in the database but are
unreachable. Intended to be run once in production.

---

## Related

- Client-side flow, `oauthState.v1` handling, and the StrictMode double-mount guard:
  [../../frontend/docs/state-and-guest-mode.md](../../frontend/docs/state-and-guest-mode.md)
- Endpoint shapes: [api-reference.md](api-reference.md)

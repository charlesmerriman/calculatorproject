# API Reference

All endpoints are relative to the API base URL (e.g. `http://localhost:8000` in development).

Token authentication is required for all protected endpoints. Include the token in every request header:

```
Authorization: Token <token>
```

Read-only reference endpoints (rank tables, events, League of Heroes) and `GET /calculator-data` are public. Note that a request carrying an *invalid* token still returns `401` even on public endpoints — DRF authenticates the token before checking permissions. Clients should drop a rejected token and retry without one.

Not part of the public API: `/admin/analytics/` is a staff-only aggregate analytics page served inside the Django admin (session auth, not token auth) — see [analytics.md](analytics.md). `/admin/image-library/` is likewise staff-only — it lists the media bucket as JSON for the admin's image picker (`?prefix=umas/`, `?refresh=1`), and only accepts folders that back an actual `ImageField`.

---

## Authentication

Ordinary accounts are created and authenticated **only** through Google or Discord (OAuth2 authorization code flow). There is no registration endpoint, and `POST /login` is restricted to staff. A social account stores nothing but the provider's opaque subject id and a generated `user_xxxxxx` handle — no email, name, or password. See `calculatorapi/oauth.py` and `calculatorapi/views/social_auth.py`.

### `GET /auth/<provider>/start`

Public. `<provider>` is `google` or `discord`. Returns the provider consent URL to redirect the browser to, plus the signed `state` the caller must echo back.

**Response `200`**
```json
{ "authorize_url": "https://accounts.google.com/o/oauth2/v2/auth?...", "state": "string" }
```

**Response `404`** — unknown provider.
**Response `503`** — the provider's client id/secret is not configured on the server.

The `state` is signed with `django.core.signing` (salt `calculatorapi.social-auth-state`) and carries the provider name plus a nonce. It expires after `OAUTH_STATE_MAX_AGE_SECONDS` (default 600). The client should also keep its own copy and compare on return — that browser binding is what defeats login CSRF.

---

### `POST /auth/social`

Public. Redeems the one-time authorization code and returns an API token. The code is exchanged server-to-server; the client secret never leaves the backend.

**Request body**
```json
{ "provider": "google", "code": "string", "state": "string" }
```

**Response `201`** — first sign-in for this provider account (a new user was created).
**Response `200`** — returning user.
```json
{ "token": "string" }
```

**Response `400`** — one generic body for every failure (bad/expired/mismatched state, missing code, expired or replayed code, provider error). The specific reason is deliberately not disclosed.
```json
{ "error": "Could not complete sign in. Please try again." }
```

**Response `404`** — unknown provider.

The redirect URI is derived server-side as `<FRONTEND_URL>/auth/callback` and must match the value registered in the provider console exactly.

---

### `POST /login`

Public route, **staff only**. Authenticates a staff user by password and returns their auth token. This exists so admins can reach `/admin` and the analytics dashboard; ordinary accounts have unusable passwords and must use the social endpoints above.

**Request body**
```json
{ "username": "string", "password": "string" }
```

**Response `200`**
```json
{ "token": "string" }
```

**Response `400`** — wrong credentials **or** a correct password on a non-staff account. Both return an identical body, so the endpoint cannot be used to discover which usernames exist.
```json
{ "error": "Invalid Credentials" }
```

---

### `POST /logout`

Protected. Deletes the user's current auth token.

**Response `200`**
```json
{ "message": "Successfully logged out" }
```

---

## Core Calculator

### `GET /calculator-data`

Public. Returns a single aggregated payload containing all reference data and user-specific state. The frontend calls this once on mount.

For anonymous requests, all reference keys are populated as usual but the user-scoped keys are empty: `user_stats_data` is `null`, and `user_planned_banner_data` / `user_planned_purchase_data` are `[]`. The frontend uses the `null` stats to detect guest mode and seed local defaults.

**Response `200`**
```json
{
  "club_rank_data":              [ ClubRank ],
  "team_trials_rank_data":       [ TeamTrialsRank ],
  "champions_meeting_rank_data": [ ChampionsMeetingRank ],
  "league_of_heroes_rank_data":  [ LeagueOfHeroesRank ],
  "banner_uma_data":             [ BannerUma ],
  "banner_support_data":         [ BannerSupport ],
  "user_planned_banner_data":    [ UserPlannedBanner ],
  "champions_meeting_data":      [ ChampionsMeeting ],
  "league_of_heroes_event_data": [ LeagueOfHeroes ],
  "events_data":                 [ GameEvent ],
  "user_stats_data":             UserStats,
  "banner_timeline_data":        [ BannerTimeline ],
  "anniversary_event_data":      [ AnniversaryEvent ],
  "user_planned_purchase_data":  [ UserPlannedPurchase ],
  "income_ledger":               [ IncomeLedgerRow ],
  "calculation_constants":       CalculationConstants
}
```

`user_planned_banner_data`, `banner_uma_data`, `banner_support_data`, `champions_meeting_data`, `league_of_heroes_event_data`, `events_data`, `anniversary_event_data` and `user_planned_purchase_data` are all ordered by each row's **resolved** (confirmed-or-predicted) global start date, sorted server-side in Python since predicted dates aren't a DB column.

---

### `PATCH /calculator-data`

Protected. Upserts the user's planned banners and planned purchases, and updates their stats, in one request.

**Upsert semantics** — identical for `user_planned_banner_data` and `user_planned_purchase_data`:
- Key absent from the body → that collection is left completely alone
- Key present as `[]` → every row in that collection is deleted
- Row with `id` → update that row (`404` if the id isn't this user's)
- Row without `id` → create new row
- Any row in the database not present in the payload → deleted

The whole request is one transaction: if any section fails validation, **nothing** is
written, including sections already applied earlier in the same request. This relies on
`transaction.set_rollback(True)` — returning a `Response` from inside an atomic block
exits it normally, so Django would otherwise commit the accepted half.

**Request body** (all keys are optional)
```json
{
  "user_stats_data": {
    "current_carat":          0,
    "current_paid_carat":     0,
    "uma_ticket":             0,
    "support_ticket":         0,
    "uma_selector_ticket":    0,
    "support_selector_ticket": 0,
    "daily_carat":            false,
    "training_pass":          false,
    "misc_earnings":          true,
    "monthly_shop_tickets":   false,
    "discounted_paid_pulls":  false,
    "full_price_paid_pulls":  true,
    "include_purchases_in_projection": false,
    "webstore_bonus":         false,
    "sr_shards":              0,
    "sr_crystals":            0,
    "ssr_shards":             0,
    "ssr_crystals":           0,
    "club_rank":              1,
    "team_trials_rank":       1,
    "champions_meeting_rank": 1,
    "league_of_heroes_rank":  1
  },
  "user_planned_banner_data": [
    { "id": 5, "number_of_pulls": 20, "reserved_copies": 0, "banner_uma": 3, "banner_support": null },
    { "number_of_pulls": 10, "reserved_copies": 2, "banner_uma": null, "banner_support": 7 }
  ],
  "user_planned_purchase_data": [
    { "id": 2, "product": 14, "quantity": 3, "target_uma": null, "target_support": null },
    { "product": 17, "quantity": 1, "target_uma": 88, "target_support": null }
  ]
}
```

Rank fields accept the integer primary key of the corresponding rank row. Exactly one of `banner_uma` / `banner_support` must be non-null per planned banner row (enforced by both the serializer and a DB check constraint).

`reserved_copies` is how many copies the user plans to take with a selector ticket or an
SSR crystal rather than by pulling. Only the count is stored — which resource pays is
derived client-side per render from the projected balances and JP eligibility.

For a planned purchase, **at most one** of `target_uma` / `target_support` may be set, it
must match the product's type, and a carat pack may have neither. A selector target is
additionally rejected (`400`) when the card was released on JP after the product's
effective cutoff — see `calculatorapi/eligibility.py`.

**Response `200`**
```json
{ "message": "Data updated successfully" }
```

---

## Reference Data (read-only)

These endpoints return static rank tables. All are public and support `list` and `retrieve`.

| Endpoint | Resource |
|---|---|
| `GET /clubranks` | Club rank tiers and monthly income amounts |
| `GET /teamtrialranks` | Team Trials rank tiers and weekly income amounts |
| `GET /championsmeetingranks` | Champions Meeting placement tiers and per-event income amounts |
| `GET /leagueofheroesranks` | League of Heroes rank tiers and income amounts |
| `GET /events` | Game events, including their own reward amounts |
| `GET /changelog` | Patch-note entries (newest first) with nested, ordered change lines |

All list responses return an array of the resource object. Retrieve by appending `/<id>`.

---

## Telemetry

### `POST /visit`

Public. Records one site visit for the admin analytics dashboard. Takes no
request body — anything sent is ignored — and returns `204 No Content` with an
empty body.

The frontend is a separate static site on the CDN, so Django never sees a page
load; this beacon is the only way it learns of one. `frontend/src/services/visitBeacon.ts`
fires it **once per browser session**, not per route change, and suppresses it
entirely when a dev server is pointed at a remote API (`npm run dev:live`).

The response is deliberately uninformative. A request filtered as a bot and a
request that was counted both return `204`, so the filter cannot be probed by
trial and error.

Throttled at 60/hour per address (`visit_beacon` scope) — far above one beacon
per session, with headroom for several people behind one NAT. Over the limit
returns `429`.

No IP address is stored. See `backend/docs/analytics.md` for what is recorded,
and for why the monthly unique-visitor count is deliberately smaller than the
sum of the daily ones.

---

## Shape Reference

### `UserStats`
```json
{
  "current_carat":          0,
  "current_paid_carat":     0,
  "uma_ticket":             0,
  "support_ticket":         0,
  "uma_selector_ticket":    0,
  "support_selector_ticket": 0,
  "daily_carat":            false,
  "training_pass":          false,
  "misc_earnings":          true,
  "monthly_shop_tickets":   false,
  "discounted_paid_pulls":  false,
  "full_price_paid_pulls":  true,
  "include_purchases_in_projection": false,
  "webstore_bonus":         false,
  "sr_shards":              0,
  "sr_crystals":            0,
  "ssr_shards":             0,
  "ssr_crystals":           0,
  "club_rank":              1,
  "team_trials_rank":       1,
  "champions_meeting_rank": 1,
  "league_of_heroes_rank":  1
}
```

Rank fields are returned as integer IDs (primary keys).

`uma_selector_ticket` / `support_selector_ticket` are **not** gacha tickets. A gacha
ticket is worth one pull and is spent by the pull strategy; a selector takes a specific
card outright and never funds a pull. They are the user's current holdings and are
treated as unrestricted (no JP cutoff); tickets projected from campaigns carry their
campaign's cutoff instead.

### `UserPlannedBanner` (response)

On GET, `banner_uma` and `banner_support` are expanded to nested objects (not IDs). On PATCH request bodies they must be integer IDs.

```json
{
  "id": 1,
  "user": 1,
  "number_of_pulls": 20,
  "reserved_copies": 0,
  "banner_uma": { ... BannerUma object ... },
  "banner_support": null
}
```

### `AnniversaryEvent` (from `anniversary_event_data`)

A dated campaign that sells discounted carat packs and grants selector tickets. Public.

It owns **no dates**: `start_date` / `end_date` are resolved by spanning the
`BannerTimeline` "Parts" it links to (earliest start, latest end), so it follows exactly
the same confirmed-or-predicted rules as everything else on the calendar. Both are
`null` when the campaign has no linked parts with resolved dates, and `is_predicted` is
true if **any** contributing part is predicted.

```json
{
  "id": 8,
  "name": "3rd Anniversary",
  "event_type": "anniversary",
  "jp_cutoff_date": "2024-01-31",
  "image": null,
  "accent_label": "",
  "start_date": "2027-07-17T22:00:00Z",
  "end_date": "2027-08-19T21:59:59Z",
  "is_predicted": true,
  "applied_offset_days": 0,
  "products": [ AnniversaryEventProduct ],
  "banner_parts": [ { "banner_timeline": 142, "part_number": 1 } ]
}
```

`event_type` is one of `anniversary` / `new_year` / `campaign` — the source sheet plans
New Years campaigns and one-off promotions alongside anniversaries, and this keeps them
in one table without the name lying about what a row holds.

### `AnniversaryEventProduct`

One purchasable line on a campaign. Packs and selectors share one shape, tagged by
`product_type` (`carat_pack` / `uma_selector` / `support_selector`) — narrow on the tag,
never on which fields happen to be set.

```json
{
  "id": 14,
  "product_type": "carat_pack",
  "name": "7500 Carat Pack",
  "usd_cost": 70.0,
  "paid_carat_amount": 7500,
  "webstore_multiplier": 1.1,
  "max_quantity": 10,
  "jp_cutoff_date": "2024-01-31",
  "jp_cutoff_date_override": null,
  "order": 1
}
```

`usd_cost` and `webstore_multiplier` are JSON **numbers**, not DRF's default
Decimal-as-string, so the client can do arithmetic on them directly.

`jp_cutoff_date` is already resolved against the campaign's — the client never has to
reimplement the fallback. `jp_cutoff_date_override` exposes the product's own value and
is `null` when the cutoff came from the campaign.

### `UserPlannedPurchase` (from `user_planned_purchase_data`)

`product` stays an integer id on both read and write — unlike planned banners, nothing is
nested, because the client already holds the whole campaign catalogue and joins on it.

```json
{
  "id": 2,
  "user": 1,
  "product": 14,
  "quantity": 3,
  "target_uma": null,
  "target_support": null
}
```

### `BannerUma`
```json
{
  "id": 1,
  "name": "string",
  "free_pulls": 0,
  "admin_comments": "string | null",
  "banner_timeline": { "id": 1, "name": "string", "start_date": "ISO8601", "end_date": "ISO8601", "is_predicted": false, "jp_start_date": "ISO8601 | null", "jp_end_date": "ISO8601 | null", "global_start_date": "ISO8601 | null", "global_end_date": "ISO8601 | null", "image": "url | null" },
  "umas": [ { "id": 1, "name": "string", "image": "url | null", "admin_comments": "string | null", "first_jp_date": "ISO8601 | null" } ]
}
```

`first_jp_date` on a nested uma or support card is the earliest JP banner it appeared
on, derived server-side (never stored) and the key **selector eligibility** is judged
on: a selector may only take cards released on JP on or before its cutoff, inclusive.
`null` means the card has never been featured on a banner in our data — treat that as
*unknown*, not *ancient*; eligibility refuses `null` under a real cutoff. See
`calculatorapi/eligibility.py`.

### `BannerSupport`
```json
{
  "id": 1,
  "name": "string",
  "free_pulls": 0,
  "admin_comments": "string | null",
  "banner_timeline": { ... },
  "support_cards": [ { "id": 1, "name": "string", "image": "url | null", "admin_comments": "string | null", "first_jp_date": "ISO8601 | null" } ]
}
```

### `GameEvent`

`start_date`/`end_date`/`is_predicted`/`applied_offset_days` are RESOLVED from the linked `banner_timeline` (a `GameEvent` has no `schedule_offset_days` of its own — it inherits whatever offset its banner ended up with)
(not stored columns) — `end_date` trails the banner's own resolved end date by 4 days.
`banner_timeline` is a nullable id: not every event ties to a single banner (some tie to
Champions Meeting rewards instead, some are multi-banner campaign events), in which case
`start_date`/`end_date` are `null` and `is_predicted` is `false`. The standalone `GET
/events` route only ever resolves **confirmed** dates (no prediction) — the richer,
possibly-predicted dates shown here are exclusive to `/calculator-data`.

Reward amounts are fields on the event itself (no separate reward model/list).
`carat_amount` and the ticket/shard/crystal fields are earned once `start_date` passes;
`carats_throughout` is carats only, prorated client-side by elapsed time across
`start_date`..`end_date` — see `backend/docs/income-calculation.md`.

```json
{
  "id": 1,
  "name": "string",
  "image": "url | null",
  "start_date": "ISO8601 | null",
  "end_date": "ISO8601 | null",
  "is_predicted": false,
  "banner_timeline": 1,
  "carat_amount": 0,
  "carats_throughout": 0,
  "support_ticket_amount": 0,
  "uma_ticket_amount": 0,
  "sr_shard_amount": 0,
  "sr_crystal_amount": 0,
  "ssr_shard_amount": 0,
  "ssr_crystal_amount": 0
}
```

### `IncomeLedgerRow` (from `income_ledger`)

The flat, date-sorted timeline the projection queries for cumulative income totals, instead of accruing income window by window as it walks. Assembled by `calculatorapi/ledger.py` from the `GameEvent`, `ChampionsMeeting` and `LeagueOfHeroes` rows and date maps already built for this request — no extra queries, no prediction of its own.

```json
{
  "date": "ISO8601",
  "kind": "event | champions_meeting | league_of_heroes",
  "source_id": 1,
  "name": "Narita Brian",
  "is_predicted": false,
  "throughout_end": "ISO8601 | null",
  "carats": 80,
  "carats_throughout": 1050,
  "uma_tickets": 0,
  "support_tickets": 0,
  "ssr_shards": 0,
  "ssr_crystals": 0,
  "sr_shards": 0,
  "sr_crystals": 0
}
```

Four things to know:

- **`date` is the instant the reward lands** — an event's resolved start, a race event's resolved **end**.
- **Race rows carry no amounts.** `champions_meeting` / `league_of_heroes` rows are indicators; what a placement pays depends on the user's rank row, which only the client knows. Every amount field is still present (as `0`), so the client never guards on shape.
- **`throughout_end` is the linked banner's end, with `GAME_EVENT_END_DATE_BUFFER` already removed.** The `carats_throughout` pool decays over the banner, not over the event, whose own `end_date` trails it by 4 days. Emitting it pre-stripped is what stops the client keeping its own copy of that constant.
- **No rows are filtered by "today".** The ledger is a set of dated facts, past ones included; the projection applies `today < date <= end` client-side so the whole calculation shares one anchor. Rows with no *resolvable* date are dropped, since a ledger row's only purpose is its position on the calendar.

### `CalculationConstants` (from `calculation_constants`)

Every tunable number the carat projection uses, from a singleton row edited in
Django admin under **Configuration → Calculation constants**. Served on every
request so an edit takes effect on the next page load without a deploy.

Field names and meanings come straight from
`calculatorapi/models/calculation_constants.py`, where each carries a `help_text`
naming the spreadsheet cell it corresponds to. The frontend mirrors the shape in
`src/types/constants.ts` and falls back to `DEFAULT_CONSTANTS` when the key is
absent.

Two things to know:

- **The decimal fields arrive as numbers, not strings.** DRF serialises
  `DecimalField` as a string by default; these are coerced to floats because the
  client feeds them straight into arithmetic, and `"0.664" * 2` is a silent `NaN`
  in JavaScript rather than an error. Affects `prediction_factor`,
  `throughout_decay_k`, `throughout_decay_linear_slope`.
- **`training_pass_start_date` is a plain `YYYY-MM-DD` calendar day**, not a
  datetime.

`id` is deliberately excluded — there is only ever one row.

### `ChangelogEntry` (from `GET /changelog`)

Entries are returned newest-first by `date`. Each entry nests its `changes`,
ordered by their `order` field. `version` is an optional label (empty string when
unset). `category` is one of `"added"`, `"fixed"`, `"changed"`.

```json
{
  "id": 1,
  "title": "string",
  "version": "v1.2",
  "date": "YYYY-MM-DD",
  "changes": [
    {
      "id": 1,
      "category": "added",
      "text": "string",
      "order": 0
    }
  ]
}
```

### `BannerTimeline` (from `banner_timeline_data`)

The `banner_timeline_data` key uses an expanded serializer that nests uma and support banners (including per-card/uma recommendation text from the through table), distinct from the flat `BannerTimelineSerializer` used inside `BannerUma`/`BannerSupport` objects.

**Date fields.** `start_date`/`end_date` are the **resolved** global dates: the confirmed global dates when set, otherwise dates **predicted** from the JP schedule (see `backend/calculatorapi/predictions.py`). `is_predicted` is `true` when they are an estimate. The raw source fields (`jp_start_date`, `jp_end_date`, `global_start_date`, `global_end_date`) are also exposed; `global_*` is null until a banner is officially confirmed. The same resolved values and `is_predicted` appear on every nested `banner_timeline` (inside `banner_uma_data`, `banner_support_data`, and `user_planned_banner_data`), keyed consistently by timeline id.

**Schedule offsets.** `schedule_offset_days` is the row's own manual correction to the prediction (0 for almost every row); `applied_offset_days` is the cumulative total — its own plus every offset earlier in the calendar — **already baked into** `start_date`/`end_date`. Both are 0 on confirmed rows, which offsets never touch. The cascade spans banners, Champions Meetings and League of Heroes together, so a banner's offset can show up as a non-zero `applied_offset_days` on a later Champions Meeting. `applied_offset_days` is diagnostic only — the dates are complete without it. See `backend/docs/data-model.md` for the rule.

**`event_type`.** A constant tag identifying which model a row came from. The frontend merges `banner_timeline_data`, `champions_meeting_data` and `league_of_heroes_event_data` into one sorted timeline array and narrows on this. It exists because the three shapes are **not** reliably distinguishable structurally: `ChampionsMeeting` and `LeagueOfHeroes` are field-identical apart from their number, and a `BannerTimeline` shares every base field with both. Emitted by `EventTypeMixin` (`calculatorapi/views/mixins.py`) on the three serializers that feed those keys — *not* on the flat `BannerTimelineSerializer` used for nested banners and `GET /bannertimelines`.

```json
{
  "id": 1,
  "name": "string",
  "event_type": "banner_timeline",
  "start_date": "ISO8601 (resolved: confirmed or predicted)",
  "end_date": "ISO8601 (resolved: confirmed or predicted)",
  "is_predicted": false,
  "jp_start_date": "ISO8601 | null",
  "jp_end_date": "ISO8601 | null",
  "global_start_date": "ISO8601 | null",
  "global_end_date": "ISO8601 | null",
  "schedule_offset_days": 0,
  "applied_offset_days": 0,
  "image": "url | null",
  "banner_umas": [ { "id": 1, "name": "string", "free_pulls": 0, "admin_comments": "string | null", "umas": [ { ...uma + "recommendation": "string | null" } ] } ],
  "banner_supports": [ { ... } ],
  "anniversary_event": { "id": 8, "name": "3rd Anniversary", "event_type": "anniversary", "accent_label": "", "image": "url | null", "part_number": 2 }
}
```

**`anniversary_event`.** The campaign this banner is a Part of, or `null`. A flat summary
rather than the full `AnniversaryEvent`: the timeline only needs enough to draw the
attached strip, and the same campaign is already sent in full — with its products — under
`anniversary_event_data`. Nesting it here would repeat the whole catalogue once per Part.
Note the link is owned entirely by `AnniversaryEventBanner`; `BannerTimeline` itself has
no campaign column.

### `ChampionsMeeting` (from `champions_meeting_data`)

Same **resolved-date** contract as `BannerTimeline`: `start_date`/`end_date` are the confirmed global dates when set, otherwise dates **predicted** from the JP schedule; `is_predicted` flags an estimate; the raw `jp_*`/`global_*` fields are exposed (`global_*` null until confirmed). Champions Meetings resolve against their own anchor set, independent of banners and League of Heroes. Schedule offsets are the one exception — they cascade across all three content types, so `applied_offset_days` here may originate from a banner.

**Course details.** `track` through `direction` and the five `*_recommendation` values are hand-entered in the admin and unknown until a meeting is announced. The columns are non-null, so "unknown" is a **sentinel, not a null**: `"TBD"` for the text fields and `0` for the recommendations. Clients should treat those two values as "not announced" rather than displaying them raw.

```json
{
  "id": 1,
  "name": "string",
  "event_type": "champions_meeting",
  "cm_number": 1,
  "start_date": "ISO8601 (resolved: confirmed or predicted)",
  "end_date": "ISO8601 (resolved: confirmed or predicted)",
  "is_predicted": false,
  "jp_start_date": "ISO8601 | null",
  "jp_end_date": "ISO8601 | null",
  "global_start_date": "ISO8601 | null",
  "global_end_date": "ISO8601 | null",
  "schedule_offset_days": 0,
  "applied_offset_days": 0,
  "image": "url | null",
  "track": "string", "surface_type": "string", "distance": "string", "length": "string",
  "track_condition": "string", "season": "string", "weather": "string", "direction": "string",
  "speed_recommendation": 0, "stamina_recommendation": 0, "power_recommendation": 0,
  "guts_recommendation": 0, "wit_recommendation": 0
}
```

### `LeagueOfHeroes` (from `league_of_heroes_event_data`, and `GET /leagueofheroes`)

Same resolved-date contract as above, with its own anchor set (schedule offsets excepted — those cascade across all three content types). Note the standalone `GET /leagueofheroes` route serves raw confirmed dates only (`is_predicted` is always `false` and `applied_offset_days` always 0 there); predictions and offsets are emitted only via `GET /calculator-data`.

**Identical to `ChampionsMeeting` apart from `event_type` and `loh_number`** — same course details, same stat recommendations, same `"TBD"`/`0` sentinels — because the two render through one shared timeline card. Treat them as one shape with two tags: a field added to one belongs on the other.

```json
{
  "id": 1,
  "name": "string",
  "event_type": "league_of_heroes",
  "loh_number": 1,
  "start_date": "ISO8601 (resolved: confirmed or predicted)",
  "end_date": "ISO8601 (resolved: confirmed or predicted)",
  "is_predicted": false,
  "jp_start_date": "ISO8601 | null",
  "jp_end_date": "ISO8601 | null",
  "global_start_date": "ISO8601 | null",
  "global_end_date": "ISO8601 | null",
  "schedule_offset_days": 0,
  "applied_offset_days": 0,
  "image": "url | null",
  "track": "string", "surface_type": "string", "distance": "string", "length": "string",
  "track_condition": "string", "season": "string", "weather": "string", "direction": "string",
  "speed_recommendation": 0, "stamina_recommendation": 0, "power_recommendation": 0,
  "guts_recommendation": 0, "wit_recommendation": 0
}
```

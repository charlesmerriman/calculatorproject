# API Reference

All endpoints are relative to the API base URL (e.g. `http://localhost:8000` in development).

Token authentication is required for all protected endpoints. Include the token in every request header:

```
Authorization: Token <token>
```

---

## Authentication

### `POST /register`

Public. Creates a new user account and returns an auth token.

**Request body**
```json
{
  "username": "string",
  "password": "string",
  "first_name": "string",
  "last_name": "string",
  "email": "string"
}
```

**Response `201`**
```json
{ "token": "string" }
```

---

### `POST /login`

Public. Authenticates an existing user and returns their auth token.

**Request body**
```json
{ "username": "string", "password": "string" }
```

**Response `200`**
```json
{ "token": "string" }
```

**Response `400`**
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

Protected. Returns a single aggregated payload containing all reference data and user-specific state. The frontend calls this once on mount.

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
  "events_data":                 [ GameEvent ],
  "user_stats_data":             UserStats,
  "banner_timeline_data":        [ BannerTimeline ]
}
```

`user_planned_banner_data` is ordered by timeline start date. `banner_uma_data` and `banner_support_data` are ordered by timeline start date. `events_data` is ordered by `start_date`.

---

### `PATCH /calculator-data`

Protected. Upserts the user's planned banners and updates their stats in one request.

**Upsert semantics for `user_planned_banner_data`**:
- Row with `id` → update that row
- Row without `id` → create new row
- Any row in the database not present in the payload → deleted

**Request body** (both keys are optional)
```json
{
  "user_stats_data": {
    "current_carat":          0,
    "current_paid_carat":     0,
    "uma_ticket":             0,
    "support_ticket":         0,
    "daily_carat":            false,
    "training_pass":          false,
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
    { "id": 5, "number_of_pulls": 20, "banner_uma": 3, "banner_support": null },
    { "number_of_pulls": 10, "banner_uma": null, "banner_support": 7 }
  ]
}
```

Rank fields accept the integer primary key of the corresponding rank row. Exactly one of `banner_uma` / `banner_support` must be non-null per planned banner row (enforced by both the serializer and a DB check constraint).

**Response `200`**
```json
{ "message": "Data updated successfully" }
```

---

## Reference Data (read-only)

These endpoints return static rank tables. All are protected and support `list` and `retrieve`.

| Endpoint | Resource |
|---|---|
| `GET /clubranks` | Club rank tiers and monthly income amounts |
| `GET /teamtrialranks` | Team Trials rank tiers and weekly income amounts |
| `GET /championsmeetingranks` | Champions Meeting placement tiers and per-event income amounts |
| `GET /leagueofheroesranks` | League of Heroes rank tiers and income amounts |
| `GET /events` | Game events with nested reward entries |
| `GET /eventrewards` | Individual dated reward entries |

All list responses return an array of the resource object. Retrieve by appending `/<id>`.

---

## Shape Reference

### `UserStats`
```json
{
  "current_carat":          0,
  "current_paid_carat":     0,
  "uma_ticket":             0,
  "support_ticket":         0,
  "daily_carat":            false,
  "training_pass":          false,
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

### `UserPlannedBanner` (response)

On GET, `banner_uma` and `banner_support` are expanded to nested objects (not IDs). On PATCH request bodies they must be integer IDs.

```json
{
  "id": 1,
  "user": 1,
  "number_of_pulls": 20,
  "banner_uma": { ... BannerUma object ... },
  "banner_support": null
}
```

### `BannerUma`
```json
{
  "id": 1,
  "name": "string",
  "free_pulls": 0,
  "admin_comments": "string | null",
  "banner_timeline": { "id": 1, "name": "string", "start_date": "ISO8601", "end_date": "ISO8601", "image": "url | null" },
  "umas": [ { "id": 1, "name": "string", "image": "url | null", "admin_comments": "string | null" } ]
}
```

### `BannerSupport`
```json
{
  "id": 1,
  "name": "string",
  "free_pulls": 0,
  "admin_comments": "string | null",
  "banner_timeline": { ... },
  "support_cards": [ { "id": 1, "name": "string", "image": "url | null", "admin_comments": "string | null" } ]
}
```

### `GameEvent`
```json
{
  "id": 1,
  "name": "string",
  "image": "url | null",
  "start_date": "ISO8601",
  "end_date": "ISO8601",
  "rewards": [
    {
      "id": 1,
      "name": "string",
      "carat_amount": 0,
      "support_ticket_amount": 0,
      "uma_ticket_amount": 0,
      "sr_shard_amount": 0,
      "sr_crystal_amount": 0,
      "ssr_shard_amount": 0,
      "ssr_crystal_amount": 0,
      "date": "ISO8601"
    }
  ]
}
```

### `BannerTimeline` (from `banner_timeline_data`)

The `banner_timeline_data` key uses an expanded serializer that nests uma and support banners (including per-card/uma recommendation text from the through table), distinct from the flat `BannerTimelineSerializer` used inside `BannerUma`/`BannerSupport` objects.

```json
{
  "id": 1,
  "name": "string",
  "start_date": "ISO8601",
  "end_date": "ISO8601",
  "image": "url | null",
  "banner_umas": [ { "id": 1, "name": "string", "free_pulls": 0, "admin_comments": "string | null", "umas": [ { ...uma + "recommendation": "string | null" } ] } ],
  "banner_supports": [ { ... } ]
}
```

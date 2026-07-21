# Data Model

Entity-relationship overview for the `calculatorapi` app. All models live in `calculatorapi/models/`, one file per entity.

---

## ERD

```mermaid
erDiagram
    CustomUser {
        int id PK
        string username
        string email
        int current_carat
        int current_paid_carat
        int uma_ticket
        int support_ticket
        bool daily_carat
        bool training_pass
        int sr_shards
        int sr_crystals
        int ssr_shards
        int ssr_crystals
        int club_rank_id FK
        int team_trials_rank_id FK
        int champions_meeting_rank_id FK
        int league_of_heroes_rank_id FK
    }

    ClubRank {
        int id PK
        string name
        int income_amount
    }

    TeamTrialsRank {
        int id PK
        string name
        int income_amount
    }

    ChampionsMeetingRank {
        int id PK
        string name
        int income_amount
    }

    LeagueOfHeroesRank {
        int id PK
        string name
        int income_amount
    }

    BannerTimeline {
        int id PK
        string name
        datetime jp_start_date "nullable"
        datetime jp_end_date "nullable"
        datetime global_start_date "nullable; set when confirmed"
        datetime global_end_date "nullable; set when confirmed"
        string image
    }

    BannerUma {
        int id PK
        int banner_timeline_id FK
        string name
        int free_pulls
        string admin_comments
    }

    BannerSupport {
        int id PK
        int banner_timeline_id FK
        string name
        int free_pulls
        string admin_comments
    }

    Uma {
        int id PK
        string name
        string image
        string admin_comments
    }

    SupportCard {
        int id PK
        string name
        int game_id "unique, nullable; anchors image to the DO Space file for this card"
        string image
        string admin_comments
    }

    UmasOnUmaBanner {
        int id PK
        int banner_uma_id FK
        int uma_id FK
        string recommendation
    }

    SupportsOnSupportBanner {
        int id PK
        int banner_support_id FK
        int support_card_id FK
        string recommendation
    }

    UserPlannedBanner {
        int id PK
        int user_id FK
        int banner_uma_id FK
        int banner_support_id FK
        int number_of_pulls
    }

    GameEvent {
        int id PK
        string name
        string image
        int banner_timeline_id FK "nullable"
    }

    EventReward {
        int id PK
        int event_id FK
        string name
        int carat_amount
        int support_ticket_amount
        int uma_ticket_amount
        int sr_shard_amount
        int sr_crystal_amount
        int ssr_shard_amount
        int ssr_crystal_amount
        datetime date
    }

    ChangelogEntry {
        int id PK
        string title
        string version
        date date
    }

    ChangelogChange {
        int id PK
        int entry_id FK
        string category
        string text
        int order
    }

    ChampionsMeeting {
        int id PK
        string name
        int cm_number
        datetime jp_start_date "nullable"
        datetime jp_end_date "nullable"
        datetime global_start_date "nullable; set when confirmed"
        datetime global_end_date "nullable; set when confirmed"
        string image
        string track
        string surface_type
        string distance
        string length
        string track_condition
        string season
        string weather
        string direction
        int speed_recommendation
        int stamina_recommendation
        int power_recommendation
        int guts_recommendation
        int wit_recommendation
    }

    CustomUser }o--|| ClubRank : "club_rank"
    CustomUser }o--|| TeamTrialsRank : "team_trials_rank"
    CustomUser }o--|| ChampionsMeetingRank : "champions_meeting_rank"
    CustomUser }o--|| LeagueOfHeroesRank : "league_of_heroes_rank"

    BannerUma }o--|| BannerTimeline : "banner_timeline"
    BannerSupport }o--|| BannerTimeline : "banner_timeline"

    UmasOnUmaBanner }o--|| BannerUma : "banner_uma"
    UmasOnUmaBanner }o--|| Uma : "uma"

    SupportsOnSupportBanner }o--|| BannerSupport : "banner_support"
    SupportsOnSupportBanner }o--|| SupportCard : "support_card"

    UserPlannedBanner }o--|| CustomUser : "user"
    UserPlannedBanner }o--o| BannerUma : "banner_uma"
    UserPlannedBanner }o--o| BannerSupport : "banner_support"

    EventReward }o--|| GameEvent : "event"
    GameEvent }o--o| BannerTimeline : "banner_timeline"
    ChangelogChange }o--|| ChangelogEntry : "entry"
```

---

## Key Constraints and Design Notes

### `UserPlannedBanner` — exactly-one check constraint

A DB-level `CheckConstraint` named `only_one_support_or_uma` enforces that every row has exactly one of `banner_uma` or `banner_support` set and the other null. The serializer also validates this at the application layer before the row reaches the database.

This is the discriminated union that the frontend mirrors with the `SavedPlannedBanner` / `LocalPlannedBanner` types.

### Rank tables — static reference data

`ClubRank`, `TeamTrialsRank`, `ChampionsMeetingRank`, and `LeagueOfHeroesRank` are static reference tables seeded from fixtures. They are never written to by user-facing endpoints. `CustomUser` holds a nullable FK to the user's current tier in each.

`LeagueOfHeroesRank` data is returned by the API and used by the resource projection — each `LeagueOfHeroes` event whose `end_date` falls within a banner window contributes the user's rank `income_amount` to the carat total.

### Through tables carry recommendation text

`UmasOnUmaBanner` and `SupportsOnSupportBanner` are explicit through models (not Django's auto-generated M2M table) because they carry a `recommendation` field — freeform admin notes about whether a card/uma on a banner is worth pulling. This text is exposed by the `BannerTimelineForViewingSerializer` used in `banner_timeline_data`.

### `EventReward.event` is nullable

The FK from `EventReward` to `GameEvent` allows null, meaning rewards can exist in the database without being attached to a named event. In practice all rewards are attached to an event, but the schema permits orphaned rewards.

### `BannerTimeline` has two serializers

`BannerTimelineSerializer` — the flat version, embedded inside `BannerUma` and `BannerSupport` objects.

`BannerTimelineForViewingSerializer` — the expanded version returned under `banner_timeline_data`, which nests the full `banner_umas` and `banner_supports` lists including the per-card/uma recommendation text from the through tables.

Both serializers share an `EffectiveDateMixin` that emits **resolved** `start_date`/`end_date` (plus an `is_predicted` flag) under the original field names.

### JP-based dates with predicted global dates

The site targets the **global** server, but global dates are only confirmed ~1 month out. `BannerTimeline`, `ChampionsMeeting`, and `LeagueOfHeroes` all store JP dates (`jp_start_date`/`jp_end_date`, always known) and confirmed global dates (`global_start_date`/`global_end_date`, null until confirmed). For unconfirmed rows the global dates are **predicted** from the JP schedule. The three serializers share `EffectiveDateMixin`, and each content type is resolved into its **own** effective-date map (its own anchor set) — rows are never mixed across models.

Prediction (fixed anchor, in `calculatorapi/predictions.py`):
- **Anchor** = the row with the greatest `jp_start_date` among those having BOTH a confirmed `global_start_date` and a `jp_start_date`.
- `predicted_global_start = anchor.global_start_date + (target.jp_start_date − anchor.jp_start_date) × 0.7`
- `predicted_global_end = predicted_global_start + (target.jp_end_date − target.jp_start_date)`

The calculator view builds one effective-date map per content type (keyed by row id) once per request and injects each via serializer context, so the resolved dates are consistent across every serialization path. **Prediction requires the anchor to have a `jp_start_date`** — historical rows migrate with JP dates null, so the most-recent confirmed rows must have their JP dates backfilled in the admin for prediction to activate.

### `GameEvent` dates are derived from its linked `BannerTimeline`, not owned

Unlike `BannerTimeline`/`ChampionsMeeting`/`LeagueOfHeroes`, `GameEvent` has no `jp_*`/`global_*` columns of its own — it never runs its own anchor/prediction math. Instead it holds a nullable `banner_timeline` FK, and its `start_date`/`end_date`/`is_predicted` are resolved by looking that FK up in the *existing* `BannerTimeline` effective-date map (`game_event_effective_dates()` in `calculatorapi/predictions.py`, mirroring the same cross-model-lookup pattern `planned_effective_start()` uses for `UserPlannedBanner`): `start_date` is the linked banner's own resolved start, `end_date` is the banner's resolved end **plus 4 days**, and `is_predicted` propagates from the banner's entry.

`banner_timeline` is nullable (`on_delete=SET_NULL`) because not every event corresponds to a single banner — some tie to Champions Meeting rewards instead, some are campaign-wide events spanning multiple banners at once, and some are future placeholders — and because an event's own content (image, its `EventReward` payout schedule) stays meaningful even if the banner it was tied to is later deleted. An unlinked (or unresolvable) event simply resolves to `null` dates, same as any other "no anchor" case in this system.

The standalone `/events` route serves **confirmed-only** dates (`game_event_confirmed_dates()`, no prediction), matching the same convention used by `/leagueofheroes` — prediction is reserved for `/calculator-data`, which builds the richer map (`build_game_event_date_map()`) and reuses the request's single `BannerTimeline` emap rather than computing a second one.

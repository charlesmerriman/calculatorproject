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
        datetime start_date
        datetime end_date
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
        datetime start_date
        datetime end_date
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

    ChampionsMeeting {
        int id PK
        string name
        int cm_number
        datetime start_date
        datetime end_date
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

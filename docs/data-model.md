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
        int schedule_offset_days "days to push this and every later date forward"
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
        int game_id "unique, nullable; anchors image to the DO Space file. ALSO ENCODES RARITY: 1xxxx R, 2xxxx SR, 3xxxx SSR — banners may only link 3xxxx"
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
        int banner_step_up_id FK
        int number_of_pulls "steps on a step-up row"
    }

    BannerStepUp {
        int id PK
        int banner_timeline_id FK
        int anniversary_event_id FK
        string name
        string card_type "uma | support"
        int banner_count
        string image
        int order
    }

    GameEvent {
        int id PK
        string name
        string image
        int banner_timeline_id FK "nullable"
        int carat_amount
        int carats_throughout
        int support_ticket_amount
        int uma_ticket_amount
        int sr_shard_amount
        int sr_crystal_amount
        int ssr_shard_amount
        int ssr_crystal_amount
    }

    Scenario {
        int id PK
        string name
        string image "nullable; art often lands after the row"
        int banner_timeline_id FK "nullable; supplies the START only"
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
        int schedule_offset_days "days to push this and every later date forward"
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

    LeagueOfHeroes {
        int id PK
        int loh_number
        string name
        datetime jp_start_date "nullable"
        datetime jp_end_date "nullable"
        datetime global_start_date "nullable; set when confirmed"
        datetime global_end_date "nullable; set when confirmed"
        int schedule_offset_days "days to push this and every later date forward"
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
    UserPlannedBanner }o--o| BannerStepUp : "banner_step_up"
    BannerStepUp }o--|| BannerTimeline : "banner_timeline"
    BannerStepUp }o--|| AnniversaryEvent : "anniversary_event"

    GameEvent }o--o| BannerTimeline : "banner_timeline"
    Scenario }o--o| BannerTimeline : "banner_timeline"
    ChangelogChange }o--|| ChangelogEntry : "entry"

    AnniversaryEventBanner }o--|| AnniversaryEvent : "anniversary_event"
    AnniversaryEventBanner }o--|| BannerTimeline : "banner_timeline"
    AnniversaryEventProduct }o--|| AnniversaryEvent : "anniversary_event"
    UserPlannedPurchase }o--|| CustomUser : "user"
    UserPlannedPurchase }o--|| AnniversaryEventProduct : "product"
    UserPlannedPurchase }o--o| Uma : "target_uma"
    UserPlannedPurchase }o--o| SupportCard : "target_support"
```

---

## Key Constraints and Design Notes

### `CalculationConstants` — the projection's tunables

A singleton (always `pk=1`, `save()` pins it, `delete()` is refused) holding every
flat rate and schedule the carat projection uses. Read it with `.load()`, which
creates it with defaults on first access so a fresh database starts correctly
calibrated. Deliberately **not cached**: production runs several worker
processes, so an edit saved by one would not invalidate a local cache held by the
others and the site would serve two different sets of constants depending on
which worker answered.

It also owns `prediction_factor` and `game_event_end_buffer_days`, which used to
be module constants in `predictions.py` *and* duplicated in the frontend's
`gameConstants.ts` with a comment on each warning they be kept in sync by hand.
`predictions.py` keeps its DB-free purity: the pure functions take both as
parameters defaulting to the module constants, and only the ORM wrappers read the
model.

### The income ledger

`calculatorapi/ledger.py` assembles a flat, date-sorted row per reward instant
from `GameEvent`, `ChampionsMeeting` and `LeagueOfHeroes`, served as
`income_ledger`. It is built from the querysets and effective-date maps
`/calculator-data` already has in hand — no extra queries, no model of its own.

It computes **no income**: it places rows on a calendar and nothing more, which
is the one narrow exception to this project's "backend carries no projection
math" rule. Race rows carry no amounts (the payout depends on the user's rank,
which only the client knows), and no row is gated on "today" — the ledger is a
set of dated facts, past ones included, so that the client's single `today`
anchor governs every income source uniformly.

### `UserPlannedBanner` — exactly-one check constraint

A DB-level `CheckConstraint` named `exactly_one_banner_target` enforces that every row has
exactly one of `banner_uma`, `banner_support` or `banner_step_up` set and the other two
null. The serializer also validates this at the application layer before the row reaches
the database.

It replaced the two-way `only_one_support_or_uma` in migration `0039` when step-ups were
added. A three-way `Q(...) | Q(...) | Q(...)` rather than a count, because the constraint
has to be expressible in SQL and enumerating the legal combinations is what Django's
`CheckConstraint` can compile.

This is the discriminated union that the frontend mirrors — narrowed with
`plannedBannerTarget()`, never by checking which FK happens to be set.

### `BannerStepUp` — a campaign's Select Step-Up ladder

A Select Step-Up is not a banner you pull on; it is a five-step cost ladder bought with
paid carats, where the fifth step of each round hands over a card the player chooses from
the back catalogue. One row per **pool** per campaign, not one per banner: `card_type`
says which pool (`uma` = star-3, `support` = SSR) and `banner_count` says how many such
banners the campaign runs. The 5th Anniversary is therefore two rows, not five.

`max_steps` is a property, `banner_count * 5` — served rather than left to the client so
the count and the rule that turns it into steps stay together.

**Two FKs, and they must agree.** `banner_timeline` says when the ladder is buyable;
`anniversary_event` says which campaign it belongs to (and therefore which
`jp_cutoff_date` bounds its candidates). `clean()` validates that the timeline is one of
the campaign's own Parts, because nothing in the schema prevents wiring a step-up to a
window its campaign never runs in. Both use `related_name="step_up_banners"` — different
models, so no clash, and each side reads naturally.

The cutoff is **folded onto the serialized step-up** as `jp_cutoff_date`, the same way
`AnniversaryEventProductSerializer` folds it onto a selector product. The client reads it
from there rather than joining the campaign: one place resolves the cutoff, and it is the
server.

### `UserStepUpSelection` — the ten cards a user would pick

One row per filled slot, keyed to **`BannerStepUp`** rather than to `UserPlannedBanner`.
"Which ten cards would I pick here" is a fact about the banner, not about a plan row: it
changes no cost, no odds and no eligibility. So it needs no plan to exist, and survives
one being deleted.

That keying is also what keeps it a **flat sibling collection** in the PATCH body.
Hanging it off `UserPlannedBanner` would have forced a writable nested serializer,
because a newly staged planner row has no id until the same request creates it — the
client could not have referenced it.

Three constraints:

| Constraint | What it says |
|---|---|
| `exactly_one_selection_card` | one of `uma` / `support`. **Exactly** one, unlike `UserPlannedPurchase.at_most_one_selector_target` — an empty slot is an absent row, so a row with no card means nothing |
| `unique_step_up_selection_slot` | one card per `(user, banner_step_up, slot)` |
| `one_step_up_target_per_banner` | partial unique index on `is_target=True` — at most one step 5 pick per banner |

The card FKs **CASCADE**, not `SET_NULL`. A nulled FK would leave a row the first
constraint forbids, and nothing is lost: the UI renders slots 1–10 and derives the empty
ones from *missing* rows, so a cascaded delete and a nulled FK look identical on screen.

**Eligibility is validated but grandfathered.** A card released on JP after the
campaign's `jp_cutoff_date` is rejected — *unless* the user already had that
`(step-up, card)` pair stored. Cutoffs are reference data editors keep correcting, and
re-checking untouched picks lets one narrowed cutoff `400` an entire PATCH, taking the
user's stats and banners with it. `UserPlannedPurchaseSerializer` learned this the hard
way and solves it with `_pairing_is_unchanged`; that keys off `self.instance`, which
cannot work here because selections are replaced wholesale with **id-less** rows, so
every row is a create. `_stored_selection_pairs` snapshots the prior set before the
reconcile instead.

Nothing in the projection reads any of this — see
`frontend/docs/resource-projection-logic.md`.

### `AnniversaryEvent` owns the link to `BannerTimeline`, not the other way round

A campaign spans several banner "Parts" (the 3rd Anniversary is four separate
`BannerTimeline` rows), recorded by the `AnniversaryEventBanner` through table with a
`part_number`. The link deliberately lives on the campaign side: `BannerTimeline` is
shared, heavily-used content and gains no campaign column, exactly as `GameEvent`
already owns its own FK to it.

**The campaign owns no dates.** `start_date` / `end_date` are resolved by spanning the
linked parts — earliest resolved start, latest resolved end — via
`predictions.anniversary_event_effective_dates`. That keeps campaigns on the one shared
prediction calendar, inheriting `is_predicted` and the cascading schedule offsets for
free. A standalone set of jp/global date fields would need its own prediction anchor,
and with only ~3 campaigns holding confirmed global dates that anchor would be far
weaker than `BannerTimeline`'s. `is_predicted` is true if **any** contributing part is
predicted: a range is only as certain as its least certain edge.

**`main_start_date` is a third date: when the event itself begins.** An anniversary opens
with a **Part 1 run-up** — "the anniversary is coming, here are some login rewards" — and
the anniversary proper starts at **Part 2**, on JP 02-24 or 08-24, the game's own launch
date. `start_date` answers "when does the campaign open"; `main_start_date` answers "when
is the anniversary", and they sit about ten days apart. `predictions._main_part` picks it:

- **Anniversaries** take the lowest `part_number` **≥ 2**. Selected on part number, never
  on date order — the 5th Anniversary's Part 4 opens *before* its Part 3 (concurrent
  banners, as the sheet records them), so "the second part by date" is not Part 2.
- **Falling back to the opening part** covers two real shapes. The 0.5th Anniversary has
  no Part 2 in the timeline data at all (that banner has no `BannerTimeline` row, so only
  its Part 3 link resolves), and a campaign an editor has linked only a Part 1 to has no
  later part to point at.
- **`new_year` and `campaign` keep the opening part.** Only anniversaries run a run-up. A
  New Year campaign's Part 1 *is* the New Year banner (New Years 2025 = Katsuragi Ace +
  Mr. C.B.), and the `campaign` catch-all is a single-part promotion. For both,
  `main_start_date == start_date`.

It is never null when `start_date` isn't, and always inside `[start_date, end_date]`.
`applied_offset_days` tracks the **main** part, because that is the instant the projection
credits a purchase at. Consumers that *place* a campaign on a calendar (the planner's
section bands, the Timeline's campaign card) or credit a purchase read `main_start_date`;
consumers describing the campaign's window read `start_date` / `end_date`.

### `AnniversaryEventProduct` — one tagged model for packs and selectors

Carat packs and selector tickets are the same shape: a priced item attached to a
campaign, bought in some quantity, crediting paid carats. The only difference is that a
selector additionally grants a ticket, which `product_type` records
(`carat_pack` / `uma_selector` / `support_selector`). Two near-identical tables would
have duplicated every field and forced every reader to union them; this repo already
narrows on tag fields elsewhere (see `event_type` on the timeline union).

Real-money prices live in the database, never in code, so they can be corrected without
a deploy when the store changes.

### Selector eligibility is derived, not stored

A selector may only take cards released on JP on or before its cutoff (inclusive). There
is no stored "JP release date": it is derived as `MIN(BannerTimeline.jp_start_date)` over
the banners a card has appeared on (`calculatorapi/eligibility.py`). Validated against
the source sheet's own cutoffs — `30184 Sakura Bakushin O` derives 2024-01-31, exactly
the 3rd Anniversary cutoff it is listed as selectable under; `30287 Neo Universe` derives
2026-01-30, exactly the 5th's. Deriving keeps this correct for free as banner data grows;
a stored column would drift.

Note the constraint is usually **binding**, and that is correct: a campaign's cutoff
falls before its own banners, so a selector granted at an anniversary essentially never
covers that anniversary's featured unit.

### Rank tables — static reference data

`ClubRank`, `TeamTrialsRank`, `ChampionsMeetingRank`, and `LeagueOfHeroesRank` are static reference tables seeded from fixtures. They are never written to by user-facing endpoints. `CustomUser` holds a nullable FK to the user's current tier in each.

`LeagueOfHeroesRank` data is returned by the API and used by the resource projection — each `LeagueOfHeroes` event whose `end_date` falls within a banner window contributes the user's rank `income_amount` to the carat total.

### `ChampionsMeeting` and `LeagueOfHeroes` are the same shape

The two hold identical data — course details (`track` … `direction`) and five stat
recommendations — differing only in their number field (`cm_number` / `loh_number`) and in
`ChampionsMeeting` owning the `ChampionsMeetingUmaRecommendation` join table. They render
through one shared frontend card (`components/timeline/RaceEventCard.tsx`), so a field
added to one almost always belongs on the other; the same goes for their serializers and
`ModelAdmin` fieldsets.

They are deliberately **two concrete models, not one table with a type column**: they
predict their global dates against *separate* anchor sets (see below), and merging them
would mix those anchors. The fields are duplicated rather than pulled into an abstract base
— a conscious trade of a little repetition for keeping each model readable on its own.

The course/stat columns are non-null, so "not announced yet" is encoded as a **sentinel**:
`"TBD"` for text and `0` for the recommendations. Both models default to those, and the
frontend translates them into a pending state rather than rendering them raw.

### Through tables carry recommendation text

`UmasOnUmaBanner` and `SupportsOnSupportBanner` are explicit through models (not Django's auto-generated M2M table) because they carry a `recommendation` field — freeform admin notes about whether a card/uma on a banner is worth pulling. This text is exposed by the `BannerTimelineForViewingSerializer` used in `banner_timeline_data`.

### `GameEvent` reward amounts are fields, not a separate model

Reward amounts used to live on a separate `EventReward` model, one-to-many with `GameEvent`. In practice every event had at most one immediate reward and one throughout-the-event reward, so the two were folded directly onto `GameEvent` as fields instead: `carat_amount` (+ the ticket/shard/crystal fields) is earned once the event's own resolved `start_date` passes, and `carats_throughout` is prorated by elapsed time across `start_date`..`end_date` (computed client-side — see `remainingThroughoutForRow` in `frontend/src/utils/incomeLedger.ts`), independent of `start_date`. Only carats are ever distributed this way; tickets/shards/crystals are always a lump on `start_date`.

### `BannerTimeline.banner_category` — presentation only, and it mirrors the sheet

A `TextChoices` field recording what *kind* of banner window a row is. Nothing in the projection math reads it; it exists to drive the timeline card's layout and the category filter, and to give sheet-parity audits a diffable key.

It maps 1:1 onto the "Banner Type" column (`BC`) of the source sheet's Timeline tab:

| Sheet code | `banner_category` | Rows in sheet | Shape |
|---|---|---|---|
| `1` | `standard` | 105 | 1–2 umas + 1–2 supports |
| `2` | `race_prep_support` | 29 | 1 uma + **10** supports |
| `-2` | `golden_week_revival` | 4 | 3–11 umas, **zero** supports |
| `0` | `rerun` | 2 | 1 uma |
| `-1` | *(no member)* | 46 | Champions Meeting / League of Heroes |

**Sheet code `-1` deliberately has no member.** Those rows are `ChampionsMeeting` and `LeagueOfHeroes`, which are their own models and never become `BannerTimeline` rows. A parity harness that doesn't know this will report 46 phantom missing banners.

Two rules that keep the field from rotting:

- **Category drives the chrome; count drives the grid.** Accent, label and column arrangement key off `banner_category`, but how many tiles fit per row stays derived from the actual `umas` / `support_cards` length. A miscategorised row then still renders every card it has instead of clipping them.
- **It is `banner_category`, not `banner_type`.** "Banner type" already means Uma-vs-Support across the frontend (`initialBannerType`, `bannerKey(bannerType, id)`, the `banner-type-tab--uma` class). These are different axes and must not share a name.

`golden_week_revival` is the only category derivable from the data — more than 2 umas *and* zero supports. That emptiness is structural: the sheet's `-2` block overwrites its support columns with umas, and the supports for that window live on a separate, concurrently-running standard banner. `manage.py classify_banner_categories --dry-run` applies exactly that rule, and `rerun` is reported for confirmation rather than auto-applied.

`race_prep_support` is **not** derived at all. Those 29 rows shipped with their uma side only and no support cards, which makes them indistinguishable from an ordinary one-uma banner, so `manage.py backfill_race_prep_supports` reads the category straight from the master CSV's `Banner Type` column and writes it in the same transaction as the 290 support-card links. Note that backfill moves ~24 support cards' derived `first_jp_date` earlier, which widens selector eligibility — see the command's docstring.

### `BannerTimeline` has two serializers

`BannerTimelineSerializer` — the flat version, embedded inside `BannerUma` and `BannerSupport` objects.

`BannerTimelineForViewingSerializer` — the expanded version returned under `banner_timeline_data`, which nests the full `banner_umas` and `banner_supports` lists including the per-card/uma recommendation text from the through tables.

Both serializers share an `EffectiveDateMixin` that emits **resolved** `start_date`/`end_date` (plus an `is_predicted` flag) under the original field names.

### JP-based dates with predicted global dates

The site targets the **global** server, but global dates are only confirmed ~1 month out. `BannerTimeline`, `ChampionsMeeting`, and `LeagueOfHeroes` all store JP dates (`jp_start_date`/`jp_end_date`, always known) and confirmed global dates (`global_start_date`/`global_end_date`, null until confirmed). For unconfirmed rows the global dates are **predicted** from the JP schedule. The three serializers share `EffectiveDateMixin`, and each content type is resolved into its **own** effective-date map (its own anchor set) — rows are never mixed across models.

Prediction (fixed anchor, in `calculatorapi/predictions.py`):
- **Anchor** = the row with the greatest `jp_start_date` among those having BOTH a confirmed `global_start_date` and a `jp_start_date`.
- `predicted_global_start = anchor.global_start_date + (target.jp_start_date − anchor.jp_start_date) × 0.664`
- `predicted_global_end = predicted_global_start + (target.jp_end_date − target.jp_start_date)`

The calculator view builds one effective-date map per content type (keyed by row id) once per request and injects each via serializer context, so the resolved dates are consistent across every serialization path. **Prediction requires the anchor to have a `jp_start_date`** — historical rows migrate with JP dates null, so the most-recent confirmed rows must have their JP dates backfilled in the admin for prediction to activate.

### Schedule offsets: correcting a prediction that has drifted

The 0.664 factor assumes global keeps a steady pace. When it doesn't — a delayed banner, an inserted break week — *every* prediction after the slip is wrong by the same number of days. `schedule_offset_days` (an `IntegerField(default=0)` on all three models) is the manual correction, applied by `apply_schedule_offsets()` as a **second layer on top of** the anchor math, which it leaves untouched.

- The offset pushes **its own row and every dated row after it** forward by that many days. Both ends move, so the run length is preserved.
- Offsets **stack**: a row's applied offset is the sum of `schedule_offset_days` from every offset-carrying row whose base start date is at or before its own.
- The cascade **spans all three content types at once** — one shared calendar. This is the one place rows *are* mixed across models; anchors remain strictly per-model. `build_effective_date_maps()` is the composed entry point (per-model base maps, then one shared offset pass) and is what `/calculator-data` calls; don't call `build_effective_date_map()` per model there or offsets will be resolved against an incomplete calendar.
- **Only predicted rows take part, as source or target.** A confirmed date is a fact and is never shifted — and because a confirmed row stops *contributing* too, an offset goes inert by itself once its row is confirmed. That second half matters: the newly confirmed row becomes the anchor, so its real date already carries the slip, and a still-live offset would count the same delay twice. Nothing has to be cleaned up by hand.
- **An offset at or before the target's own anchor is skipped.** Same reasoning, one step further out. A prediction is measured forward from its model's anchor, whose global date already embodies every slip up to itself; re-applying those slips double-counts them. `compute_effective_dates()` stamps `anchor_start` on every entry so the (model-blind) offset pass can tell where each row was measured from. The rule above can't cover this on its own — it only sees a slip and the row that absorbed it being *the same row*, never a different model's anchor sitting after the offset.
- Negative values are allowed (pulling the schedule earlier). Unlike positive offsets, a negative one can reorder rows relative to each other.

> **Why the anchor rule exists — the League of Heroes case (fixed 2026-08-13).** Global has never run a League of Heroes event, so `LeagueOfHeroes` has no genuinely confirmed row; the one global date it carries was entered by hand, copied off the already-slip-corrected calendar. That row became the anchor. Every other LoH row inherited the accumulated offset *through* the anchor and then had it applied a second time, putting all 14 predicted events **6–7 days late** against the source spreadsheet while banners and Champions Meetings tracked it to within a day. The trap is generic: it fires whenever a model's anchor is a hand-filled far-future date rather than a near-term confirmation, which is unavoidable for content global hasn't reached yet.

Worked example — a confirmed banner on Aug 10, then predicted rows on Aug 24 (offset **+7**), Sep 2 (a Champions Meeting), Sep 7, Sep 12 (a League of Heroes event, offset **+3**) and Sep 21:

| Row | Offsets at or before it | Applied | Final start |
|---|---|---|---|
| Banner, Aug 10 (confirmed) | — (skipped) | 0 | Aug 10 |
| Banner, Aug 24 | its own +7 | +7 | Aug 31 |
| Champions Meeting, Sep 2 | the banner's +7 | +7 | Sep 9 |
| Banner, Sep 7 | the banner's +7 | +7 | Sep 14 |
| League of Heroes, Sep 12 | +7, plus its own +3 | +10 | Sep 22 |
| Banner, Sep 21 | +7 and +3 | +10 | Oct 1 |

Serializers expose both `schedule_offset_days` (the row's own value) and `applied_offset_days` (the cumulative total already baked into `start_date`/`end_date`). The latter is diagnostic only — the dates are complete without it — but a cascading rule is hard to debug from outside without it.

**Known limitation:** the self-healing is per-model. When a banner confirms, its offset also stops reaching later Champions Meeting / League of Heroes rows, whose own anchors have not moved, so those can snap back. Set an offset on the CM/LoH row itself if that matters in practice.

### `GameEvent` dates are derived from its linked `BannerTimeline`, not owned

Unlike `BannerTimeline`/`ChampionsMeeting`/`LeagueOfHeroes`, `GameEvent` has no `jp_*`/`global_*` columns of its own — it never runs its own anchor/prediction math. Instead it holds a nullable `banner_timeline` FK, and its `start_date`/`end_date`/`is_predicted` are resolved by looking that FK up in the *existing* `BannerTimeline` effective-date map (`game_event_effective_dates()` in `calculatorapi/predictions.py`, mirroring the same cross-model-lookup pattern `planned_effective_start()` uses for `UserPlannedBanner`): `start_date` is the linked banner's own resolved start, `end_date` is the banner's resolved end **plus 4 days**, and `is_predicted` propagates from the banner's entry.

Because those dates are read *after* the offset pass has run, a `GameEvent` inherits its banner's schedule offset for free — it has no `schedule_offset_days` of its own, only the resulting `applied_offset_days`.

`banner_timeline` is nullable (`on_delete=SET_NULL`) because not every event corresponds to a single banner — some tie to Champions Meeting rewards instead, some are campaign-wide events spanning multiple banners at once, and some are future placeholders — and because an event's own content (image, reward amounts) stays meaningful even if the banner it was tied to is later deleted. An unlinked (or unresolvable) event simply resolves to `null` dates, same as any other "no anchor" case in this system.

The standalone `/events` route serves **confirmed-only** dates (`game_event_confirmed_dates()`, no prediction), matching the same convention used by `/leagueofheroes` — prediction is reserved for `/calculator-data`, which builds the richer map (`build_game_event_date_map()`) and reuses the request's single `BannerTimeline` emap rather than computing a second one.

### `Scenario` borrows a start and never has an end — the fourth date shape

A **training scenario** is a new, optional way to play the game (URA Finals, Aoharu, Grand Live, Hashire! Mecha Umamusume). It grants nothing: it exists to mark *when the game changed* on the timeline and in the calculator's section bands.

There are now four ways a model gets dates from `BannerTimeline`, and it is worth reading them together:

| # | Shape | Who | Dates |
|---|---|---|---|
| 1 | Content on a banner | `BannerUma`, `BannerSupport`, `BannerStepUp` | none of its own |
| 2 | Borrow the banner's window | `GameEvent` | start = banner start; end = banner end **+ 4 days** |
| 3 | Span several "Parts" | `AnniversaryEvent` | earliest part start → latest part end |
| 4 | **Borrow the banner's START only** | **`Scenario`** | **start = banner start; no end, ever** |

**Shape 4 is the only one with no end at all, and that is a fact about scenarios rather than a gap in the data.** A scenario is released and then stays available permanently — a newer scenario does *not* retire an older one, it just tends to get played more because it is more rewarding. There is therefore nothing for an end date to mean, and deriving one from the launch banner would invent an expiry the scenario has never had. `scenario_effective_dates()` returns `end_date: None` unconditionally, and `StartInstantDateMixin` drops the field from the wire entirely rather than emitting a permanent `null`.

Otherwise it follows `GameEvent`'s precedent exactly: a nullable `banner_timeline` FK (`on_delete=SET_NULL`, because a scenario's name and image stay real content if its launch banner is later deleted), resolved against the *existing* `BannerTimeline` effective-date map, with `is_predicted` and `applied_offset_days` propagating from the banner — so a scenario inherits its banner's schedule offset for free.

`scenario_effective_dates()` is deliberately its **own** function rather than a generalisation shared with `anniversary_event_effective_dates()`. `predictions.py`'s convention is one function per derivation shape: the mechanisms are shared (`_ResolvedDateMixin`, `effective_sort_key`), the policies are not. An anniversary's range is a *sales window* whose start is the instant purchases are credited; a scenario's start is just when a new way to play appeared. Merging them would put a scenario-only concern inside anniversary date maths the first time the two diverge.

`image` is nullable by workflow, not by accident: scenarios get entered while a feature is being built and the art arrives later. Every consumer must render without it.

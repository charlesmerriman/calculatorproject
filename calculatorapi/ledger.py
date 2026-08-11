"""
The income ledger: one flat, date-sorted list of every reward instant on the
calendar.

WHY THIS EXISTS
---------------
The projection used to be an incremental walk — a cursor stepping banner to
banner, accruing income into half-open `(prevEnd, thisEnd]` windows. Every
income source needed its own occurrence counter, and every counter had to *tile*
perfectly or totals drifted with the number of banners planned. A long run of
bugs came out of that requirement.

The source spreadsheet does it the other way round: it builds a flat dated
timeline first, then each banner asks that timeline for an absolute cumulative
total from today to its own end date. Nothing accumulates across banners, so no
counter has to tile. This module is the backend half of that model — the
analogue of the sheet's `Timeline` tab (columns AS-BD), which it imports wholesale
from a master workbook.

WHAT THIS MODULE DOES *NOT* DO
------------------------------
It computes no income. It assembles and *dates* rows; the frontend multiplies,
decays and totals them. That keeps rank selection, user toggles and the decay
curve on the client where they already live.

It also applies no "as of today" filter. Rows are plain dated facts, past ones
included. The sheet bakes a today-gate into its `CM Check`/`LoH Check` columns
(verified: of 2,142 rows, zero flagged rows predate today), but we deliberately
do not — our "today" is resolved client-side, and a server-side gate would put a
second, slightly different anchor into the calculation. The client applies
`today < date <= end` to every source uniformly instead.

Pure and DB-free, mirroring the split in `predictions.py`: this function takes
already-resolved rows and date maps, so it unit-tests directly without fixtures.
`views/ledger.py` holds the thin serializer that puts it on the wire.
"""

from .predictions import GAME_EVENT_END_DATE_BUFFER

# Row kinds. `event` rows carry amounts; the two race kinds are indicator rows
# that the client scales by the user's rank (the sheet's BL/BM columns), because
# the payout depends on which rank the user picked, not on the event.
KIND_EVENT = "event"
KIND_CHAMPIONS_MEETING = "champions_meeting"
KIND_LEAGUE_OF_HEROES = "league_of_heroes"

# Every amount field a ledger row can carry, so callers (and the serializer) have
# one list to iterate rather than a hand-maintained copy each.
AMOUNT_FIELDS = (
    "carats",
    "carats_throughout",
    "uma_tickets",
    "support_tickets",
    "ssr_shards",
    "ssr_crystals",
    "sr_shards",
    "sr_crystals",
)


def _row(*, date, kind, source_id, name, is_predicted, **amounts):
    """Build one ledger row with every amount field present.

    Filling the zeros here rather than at each call site means a consumer can
    read `row["sr_crystals"]` unconditionally — no `.get(..., 0)` scattered
    through the client, and no row shape that varies by kind.
    """
    row = {
        "date": date,
        "kind": kind,
        "source_id": source_id,
        "name": name,
        "is_predicted": is_predicted,
        "throughout_end": None,
    }
    for field in AMOUNT_FIELDS:
        row[field] = 0
    row.update(amounts)
    return row


def _game_event_rows(game_events, game_event_emap):
    """One row per GameEvent, dated at its resolved start.

    `carats` (and the ticket/shard/crystal amounts) land as a lump on that date.
    `carats_throughout` is a *pool* spread across the event's life by a decay
    curve the client owns — it is carried here undecayed, with the end the curve
    runs to in `throughout_end`.

    That end is the linked BANNER's end, not the event's: the event's resolved
    end trails its banner by GAME_EVENT_END_DATE_BUFFER, and the curve runs over
    the banner. Removing the buffer here means the client uses the value
    directly. Previously it re-derived this by subtracting its own copy of the
    buffer constant, which had to be kept in sync across two repos by hand.
    """
    rows = []
    for event in game_events:
        entry = game_event_emap.get(event.id)
        if entry is None or entry["start_date"] is None:
            # No linked banner, or a banner whose own dates are unresolved.
            # There is no honest instant to place this on.
            continue

        # An all-zero event can never change a total; keeping it would only pad
        # the payload (~200 events ship on every page load).
        amounts = {
            "carats": event.carat_amount,
            "carats_throughout": event.carats_throughout,
            "uma_tickets": event.uma_ticket_amount,
            "support_tickets": event.support_ticket_amount,
            "ssr_shards": event.ssr_shard_amount,
            "ssr_crystals": event.ssr_crystal_amount,
            "sr_shards": event.sr_shard_amount,
            "sr_crystals": event.sr_crystal_amount,
        }
        if not any(amounts.values()):
            continue

        end_date = entry["end_date"]
        throughout_end = (
            end_date - GAME_EVENT_END_DATE_BUFFER if end_date is not None else None
        )

        row = _row(
            date=entry["start_date"],
            kind=KIND_EVENT,
            source_id=event.id,
            name=event.name,
            is_predicted=entry["is_predicted"],
            **amounts,
        )
        row["throughout_end"] = throughout_end
        rows.append(row)
    return rows


def _race_rows(events, emap, kind):
    """One indicator row per Champions Meeting / League of Heroes event.

    Dated at the event's resolved END date — the payout lands when the event
    finishes, which is also the date the sheet keys these off. Amounts stay zero:
    what a placement is worth depends on the user's rank row, which only the
    client knows.
    """
    rows = []
    for event in events:
        entry = emap.get(event.id)
        if entry is None or entry["end_date"] is None:
            continue
        rows.append(
            _row(
                date=entry["end_date"],
                kind=kind,
                source_id=event.id,
                name=event.name,
                is_predicted=entry["is_predicted"],
            )
        )
    return rows


def build_income_ledger(*, game_events, game_event_emap, race_sources):
    """
    Assemble the full ledger, sorted by date.

    Every argument is an already-resolved input — the querysets the view has in
    hand plus the effective-date maps from `build_effective_date_maps()`. Nothing
    here queries, predicts, or re-anchors; the dates arrive resolved (and
    schedule-offset-shifted) and are used as given.

    `race_sources` is an iterable of `(kind, rows, emap)`. Champions Meetings and
    League of Heroes events are one argument rather than two pairs because they
    are field-identical and handled identically — the same reason they share one
    timeline card on the frontend. A third race type would be one more tuple at
    the call site and no change here.

    Rows with no resolvable date are dropped rather than emitted with a null: a
    ledger row's whole purpose is its position on the calendar, and a client
    filtering `today < date <= end` would have to special-case the nulls at every
    call site.

    The sort key breaks ties on (kind, source_id) so the order is total and
    stable — two events sharing an instant must not reorder between requests, or
    a cached response and a fresh one disagree for no reason.
    """
    rows = _game_event_rows(game_events, game_event_emap)
    for kind, events, emap in race_sources:
        rows += _race_rows(events, emap, kind)
    rows.sort(key=lambda row: (row["date"], row["kind"], row["source_id"]))
    return rows

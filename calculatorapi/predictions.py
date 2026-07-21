"""
Global-server date prediction for JP-first content (banner timelines,
Champions Meetings, League of Heroes events).

The site plans pulls on the GLOBAL server, but global dates are only confirmed
~1 month out. Beyond that horizon we predict global dates from the
(always-known) JP schedule.

This module is pure query logic — the math lives in `compute_effective_dates`
(DB-free, unit-tested directly), with a thin ORM wrapper `build_effective_date_map`
that feeds it — mirroring the split in `analytics.py`. `compute_effective_dates`
is model-agnostic (duck-typed, id-keyed), so any content type with the same
jp_*/global_* date fields can reuse it; each model is resolved into its OWN map
(its own anchor set) — rows are never mixed across models.

Prediction model (fixed anchor):
- The "anchor" is the row with the greatest jp_start_date among rows that have
  BOTH a confirmed global_start_date AND a jp_start_date.
- For a row awaiting confirmation (global_start_date is null) with a jp_start_date:
      predicted_global_start = anchor.global_start_date
                               + (target.jp_start_date - anchor.jp_start_date) * FACTOR
      predicted_global_end   = predicted_global_start
                               + (target.jp_end_date - target.jp_start_date)
  The 0.7 factor reflects global historically running content faster than JP.
- Confirmed rows pass through unchanged with is_predicted=False.
- Rows with no usable dates (or when no anchor exists) resolve to
  (None, None, False).
"""

from datetime import datetime, timedelta

from .models import BannerTimeline

# GameEvent's end date always trails its linked banner's end date by this much.
GAME_EVENT_END_DATE_BUFFER = timedelta(days=4)

# Sentinel used only to order rows that have no resolved start date; it never
# gets compared against a real datetime (the leading bool flag separates the
# two groups), so a naive value is safe here.
_NO_DATE_SENTINEL = datetime.max

# Global covers JP's back-catalogue faster than real time; each day of JP gap
# maps to ~0.7 days of global gap. Tune here if the observed cadence shifts.
PREDICTION_FACTOR = 0.7


def _get(row, key):
    """Read `key` from either a .values() dict or a model instance (duck-typed
    so the pure function works in DB-free unit tests)."""
    if isinstance(row, dict):
        return row.get(key)
    return getattr(row, key)


def compute_effective_dates(rows):
    """
    Resolve each timeline's effective global dates.

    rows: iterable of dicts or objects exposing `id`, `jp_start_date`,
          `jp_end_date`, `global_start_date`, `global_end_date`.

    Returns: { id: {"start_date": dt|None, "end_date": dt|None, "is_predicted": bool} }
    """
    rows = list(rows)

    # Anchor = latest-JP banner that is BOTH confirmed on global AND has a JP date.
    anchor = None
    for row in rows:
        jp_start = _get(row, "jp_start_date")
        global_start = _get(row, "global_start_date")
        if jp_start is None or global_start is None:
            continue
        if anchor is None or jp_start > _get(anchor, "jp_start_date"):
            anchor = row

    result = {}
    for row in rows:
        row_id = _get(row, "id")
        global_start = _get(row, "global_start_date")
        jp_start = _get(row, "jp_start_date")

        if global_start is not None:
            # Confirmed: use the real global dates as-is.
            result[row_id] = {
                "start_date": global_start,
                "end_date": _get(row, "global_end_date"),
                "is_predicted": False,
            }
        elif jp_start is not None and anchor is not None:
            # Predicted from the JP schedule, anchored to the last confirmed banner.
            jp_gap = jp_start - _get(anchor, "jp_start_date")
            pred_start = _get(anchor, "global_start_date") + jp_gap * PREDICTION_FACTOR
            jp_end = _get(row, "jp_end_date")
            pred_end = pred_start + (jp_end - jp_start) if jp_end is not None else None
            result[row_id] = {
                "start_date": pred_start,
                "end_date": pred_end,
                "is_predicted": True,
            }
        else:
            # No confirmed dates and no way to predict (no JP date or no anchor).
            result[row_id] = {
                "start_date": None,
                "end_date": None,
                "is_predicted": False,
            }

    return result


def build_effective_date_map(model=BannerTimeline):
    """Fetch every row's raw dates for `model` in one query and resolve them.
    Covers all ids so any serialization path can look up any row. `model` must
    expose the jp_*/global_* date fields; each model gets its own anchor set, so
    pass one model at a time (never merge rows across content types)."""
    rows = model.objects.values(
        "id",
        "jp_start_date",
        "jp_end_date",
        "global_start_date",
        "global_end_date",
    )
    return compute_effective_dates(rows)


def effective_sort_key(entry):
    """Sort key for an effective-date map entry (or None). Timelines with no
    resolved start date sort last (via the leading flag), then by start date
    ascending. The sentinel keeps null entries comparable to each other without
    ever being compared against a real datetime."""
    start = entry["start_date"] if entry else None
    return (start is None, start if start is not None else _NO_DATE_SENTINEL)


def planned_effective_start(planned_banner, emap):
    """Resolve the effective-date entry for a UserPlannedBanner via whichever of
    banner_uma / banner_support it points at."""
    timeline_id = None
    if planned_banner.banner_uma_id is not None:
        timeline_id = planned_banner.banner_uma.banner_timeline_id
    elif planned_banner.banner_support_id is not None:
        timeline_id = planned_banner.banner_support.banner_timeline_id
    return emap.get(timeline_id)


def game_event_effective_dates(game_event, banner_timeline_emap):
    """
    Resolve a GameEvent's dates by following its banner_timeline FK into an
    already-built BannerTimeline effective-date map (from
    build_effective_date_map(BannerTimeline)) — no new anchor/prediction math
    of GameEvent's own, mirroring planned_effective_start's cross-model lookup.

    end_date trails the banner's resolved end_date by GAME_EVENT_END_DATE_BUFFER;
    is_predicted propagates from the banner's own entry. Unlinked events (or a
    linked banner with no resolved start_date) resolve to (None, None, False) —
    some events (Champions Meeting tie-ins, campaign-wide events spanning
    multiple banners) never have a banner to derive from, by design.
    """
    entry = banner_timeline_emap.get(game_event.banner_timeline_id)
    if entry is None or entry["start_date"] is None:
        return {"start_date": None, "end_date": None, "is_predicted": False}
    end_date = entry["end_date"] + GAME_EVENT_END_DATE_BUFFER if entry["end_date"] is not None else None
    return {
        "start_date": entry["start_date"],
        "end_date": end_date,
        "is_predicted": entry["is_predicted"],
    }


def build_game_event_date_map(game_events, banner_timeline_emap):
    """Wraps game_event_effective_dates over a queryset/iterable of GameEvent
    rows, resolving each via the shared BannerTimeline map. Used by
    /calculator-data, which needs prediction for unconfirmed banners."""
    return {
        game_event.id: game_event_effective_dates(game_event, banner_timeline_emap)
        for game_event in game_events
    }


def game_event_confirmed_dates(game_event):
    """
    Non-predicting variant: reads the linked banner's raw (confirmed-only)
    global_start_date/global_end_date directly — never predicts, always
    is_predicted=False. Mirrors the convention that standalone reference
    routes (e.g. /leagueofheroes) serve confirmed dates only, with prediction
    reserved for /calculator-data. Caller must select_related("banner_timeline").
    """
    banner_timeline = game_event.banner_timeline
    if banner_timeline is None or banner_timeline.global_start_date is None:
        return {"start_date": None, "end_date": None, "is_predicted": False}
    global_end = banner_timeline.global_end_date
    end_date = global_end + GAME_EVENT_END_DATE_BUFFER if global_end is not None else None
    return {
        "start_date": banner_timeline.global_start_date,
        "end_date": end_date,
        "is_predicted": False,
    }


def build_game_event_confirmed_date_map(game_events):
    """Wraps game_event_confirmed_dates over a queryset/iterable of GameEvent
    rows. Used by the standalone /events route."""
    return {
        game_event.id: game_event_confirmed_dates(game_event)
        for game_event in game_events
    }

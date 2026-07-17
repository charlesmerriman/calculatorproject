"""
Global-server date prediction for banner timelines.

The site plans pulls on the GLOBAL server, but global banner dates are only
confirmed ~1 month out. Beyond that horizon we predict global dates from the
(always-known) JP schedule.

This module is pure query logic — the math lives in `compute_effective_dates`
(DB-free, unit-tested directly), with a thin ORM wrapper `build_effective_date_map`
that feeds it — mirroring the split in `analytics.py`.

Prediction model (fixed anchor):
- The "anchor" is the banner with the greatest jp_start_date among banners that
  have BOTH a confirmed global_start_date AND a jp_start_date.
- For a banner awaiting confirmation (global_start_date is null) with a jp_start_date:
      predicted_global_start = anchor.global_start_date
                               + (target.jp_start_date - anchor.jp_start_date) * FACTOR
      predicted_global_end   = predicted_global_start
                               + (target.jp_end_date - target.jp_start_date)
  The 0.7 factor reflects global historically running banners faster than JP.
- Confirmed banners pass through unchanged with is_predicted=False.
- Banners with no usable dates (or when no anchor exists) resolve to
  (None, None, False).
"""

from datetime import datetime

from .models import BannerTimeline

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


def build_effective_date_map():
    """Fetch every timeline's raw dates in one query and resolve them. Covers
    all ids so any serialization path can look up any timeline."""
    rows = BannerTimeline.objects.values(
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

"""
Aggregate, anonymized usage statistics for the admin analytics dashboard.

This module is pure query logic — no HTTP concerns — so the math can be
unit-tested directly and reused by both the HTML dashboard and the CSV
export (see views/analytics.py).

Privacy note: everything returned here is an aggregate (counts, percentages,
averages). No function in this module may ever return per-user rows or any
identifying field (username, email, etc.).
"""

from django.db.models import Avg, Count, Q, Sum
from django.utils import timezone

from .models import CustomUser, UserPlannedBanner

# Resource fields averaged for the "Current Resources" section.
# (model field name, human label) — order controls display order.
RESOURCE_FIELDS = [
    ("current_carat", "Carats"),
    ("current_paid_carat", "Paid Carats"),
    ("uma_ticket", "Uma Tickets"),
    ("support_ticket", "Support Tickets"),
    ("ssr_crystals", "SSR Crystals"),
    ("sr_crystals", "SR Crystals"),
    ("ssr_shards", "SSR Shards"),
    ("sr_shards", "SR Shards"),
]

# The four income-rank FKs on CustomUser: (field name, human label).
RANK_FIELDS = [
    ("team_trials_rank", "Team Trials"),
    ("club_rank", "Club Rank"),
    ("champions_meeting_rank", "Champion's Meeting"),
    ("league_of_heroes_rank", "League of Heroes"),
]

# The two paid products the client cares most about.
PAID_PRODUCT_FIELDS = [
    ("daily_carat", "Daily Carat Pack"),
    ("training_pass", "Training Pass"),
]


def _pct(part, whole):
    """Percentage rounded to one decimal; 0.0 when the denominator is empty."""
    return round(part / whole * 100, 1) if whole else 0.0


def _engaged_q():
    """
    Q filter matching "engaged" users: anyone who has changed at least one
    calculator setting away from its default, or planned at least one banner.

    Every CustomUser stat defaults to False/0/null, so accounts that
    registered but never touched the calculator would otherwise drag every
    percentage down. Reports show both denominators (total vs engaged).
    """
    q = Q(userplannedbanner__isnull=False)
    for field, _ in PAID_PRODUCT_FIELDS:
        q |= Q(**{field: True})
    for field, _ in RANK_FIELDS:
        q |= Q(**{f"{field}__isnull": False})
    for field, _ in RESOURCE_FIELDS:
        # "changed from default" = any non-zero value (defaults are all 0)
        q |= ~Q(**{field: 0})
    return q


def _banner_popularity(fk_name):
    """
    Popularity rows for one banner type. fk_name is the FK field on
    UserPlannedBanner: "banner_uma" or "banner_support".

    Grouped by banner id (name/timeline included for display), ranked by
    distinct planners, then total pulls.
    """
    rows = (
        UserPlannedBanner.objects
        # Only this banner type, and never count staff/admin test accounts.
        .filter(**{f"{fk_name}__isnull": False}, user__is_staff=False)
        # values() before annotate() = GROUP BY these fields. Including the
        # FK id guarantees two banners that share a name never merge.
        .values(
            fk_name,
            f"{fk_name}__name",
            f"{fk_name}__banner_timeline__name",
            f"{fk_name}__banner_timeline__global_start_date",
            f"{fk_name}__banner_timeline__global_end_date",
        )
        .annotate(
            planners=Count("user", distinct=True),
            total_pulls=Sum("number_of_pulls"),
            avg_pulls=Avg("number_of_pulls"),
        )
        .order_by("-planners", "-total_pulls")
    )
    return [
        {
            "name": row[f"{fk_name}__name"],
            "timeline": row[f"{fk_name}__banner_timeline__name"],
            # Confirmed global dates; predicted banners report null here (fine
            # for an aggregate popularity report). Output keys stay the same so
            # the dashboard/CSV need no change.
            "start_date": row[f"{fk_name}__banner_timeline__global_start_date"],
            "end_date": row[f"{fk_name}__banner_timeline__global_end_date"],
            "planners": row["planners"],
            "total_pulls": row["total_pulls"],
            "avg_pulls": round(row["avg_pulls"], 1),
        }
        for row in rows
    ]


def build_analytics_report():
    """
    Build the full analytics snapshot as a plain dict.

    Sections:
      - overview: total vs engaged user counts
      - paid_products: daily carat pack / training pass adoption
      - rank_distributions: users per rank, per rank type
      - resource_averages: average current resources among engaged users
      - popular_uma_banners / popular_support_banners: ranked pull plans
    """
    # Staff accounts (the site owner, devs) are excluded from every metric so
    # admin test data never skews the numbers.
    users = CustomUser.objects.filter(is_staff=False)
    total_users = users.count()

    # The engaged filter joins through UserPlannedBanner, which can duplicate
    # user rows; re-filtering by pk keeps `engaged` a clean single-table
    # queryset that is safe to count and aggregate over.
    engaged = users.filter(pk__in=users.filter(_engaged_q()).values("pk"))
    engaged_users = engaged.count()

    # ── Paid products ────────────────────────────────────────────────────
    paid_products = []
    for field, label in PAID_PRODUCT_FIELDS:
        count = users.filter(**{field: True}).count()
        paid_products.append({
            "label": label,
            "count": count,
            "pct_of_total": _pct(count, total_users),
            "pct_of_engaged": _pct(count, engaged_users),
        })

    # ── Rank distributions ───────────────────────────────────────────────
    rank_distributions = []
    for field, label in RANK_FIELDS:
        # Non-null ranks, grouped per rank, in game order (by income).
        # Grouping includes income_amount so equal names in different tiers
        # stay distinct; ordering is deterministic across SQLite/Postgres.
        grouped = (
            users.filter(**{f"{field}__isnull": False})
            .values(f"{field}__name", f"{field}__income_amount")
            .annotate(count=Count("id"))
            .order_by(f"{field}__income_amount", f"{field}__name")
        )
        entries = [
            {
                "name": row[f"{field}__name"],
                "count": row["count"],
                "pct_of_total": _pct(row["count"], total_users),
            }
            for row in grouped
        ]
        # Users who never picked this rank — reported explicitly rather than
        # relying on DB-specific NULL ordering.
        not_set = users.filter(**{f"{field}__isnull": True}).count()
        entries.append({
            "name": "Not set",
            "count": not_set,
            "pct_of_total": _pct(not_set, total_users),
        })
        rank_distributions.append({"label": label, "rows": entries})

    # ── Resource averages (engaged users only) ───────────────────────────
    # Averaging over never-configured accounts full of zeroes would be
    # meaningless, so this section uses the engaged denominator.
    averages = engaged.aggregate(
        **{field: Avg(field) for field, _ in RESOURCE_FIELDS}
    )
    resource_averages = [
        {"label": label, "avg": round(averages[field] or 0, 1)}
        for field, label in RESOURCE_FIELDS
    ]

    return {
        "generated_at": timezone.now(),
        "total_users": total_users,
        "engaged_users": engaged_users,
        "engaged_pct": _pct(engaged_users, total_users),
        "paid_products": paid_products,
        "rank_distributions": rank_distributions,
        "resource_averages": resource_averages,
        "popular_uma_banners": _banner_popularity("banner_uma"),
        "popular_support_banners": _banner_popularity("banner_support"),
    }

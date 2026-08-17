"""
Site traffic counting: how many page views and distinct visitors per day.

Same split as calculatorapi/analytics.py -- this module is pure logic with no
HTTP concerns beyond reading headers off a request object, so the hashing and
the rollup can be unit-tested directly. views/visits.py owns the endpoint and
analytics.py folds build_visit_report() into the dashboard.

PRIVACY CONTRACT. No function here may persist an IP address, a user agent, or
anything else that identifies a request. The only per-visitor artifact written
is a digest salted with the calendar date, which makes it useless tomorrow --
see _visitor_hash below for why that matters and what it costs us.
"""

import hashlib
import logging
import re
from datetime import timedelta

from django.conf import settings
from django.db import DatabaseError, models
from django.db.models.functions import TruncMonth
from django.utils import timezone

from .models import DailyVisit, DailyVisitorHash

logger = logging.getLogger(__name__)

# Crawlers announce themselves in the user agent. This is a blunt filter and it
# will never catch a crawler that lies, but it removes the bulk of the noise --
# without it the counts are dominated by whatever is indexing the site rather
# than by people. Also catches our own tooling (curl, urllib) so a health check
# or a manual poke doesn't register as traffic.
_BOT_UA = re.compile(
    r"bot|crawler|spider|slurp|headless|curl|wget|python-|scrapy|monitor|preview",
    re.IGNORECASE,
)

# How many days of hashes to keep before they are prunable. Only affects the
# scratch table -- DailyVisit rows are never pruned.
VISITOR_HASH_RETENTION_DAYS = 90


def _client_ip(request):
    """The visitor's IP, honouring the proxy in front of us.

    REMOTE_ADDR alone is wrong in production: App Platform terminates TLS at a
    load balancer, so every request arrives from the same handful of internal
    addresses and every visitor would hash identically -- unique_visitors would
    read 1 forever. X-Forwarded-For carries "client, proxy1, proxy2", so the
    FIRST entry is the original client.

    That first entry is client-settable and therefore not trustworthy. It is
    fine here because the only thing a forged value can do is inflate a unique
    count on a staff-only dashboard. Do not reuse this for anything that gates
    access.
    """
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")


def _visitor_hash(ip, user_agent, day):
    """A per-day, non-reversible bucket for one visitor.

    The date is part of the salt, which is the whole privacy property: the same
    person hashes to an unrelated value tomorrow, so these rows cannot be joined
    across days to rebuild anyone's visit history. Nothing is stored that could
    be matched back to an IP either -- reversing it would mean brute-forcing the
    address space against an unknown SECRET_KEY.

    The cost of that rotation is real and deliberate: true monthly unique
    visitors become impossible to compute, so build_visit_report() reports
    visit-days for a month instead of pretending to a MAU. Getting a real MAU
    would mean holding a stable per-person identifier for a month, which is
    exactly what this avoids.
    """
    raw = f"{settings.SECRET_KEY}:{day.isoformat()}:{ip}:{user_agent}"
    # Half a SHA-256. Collision odds are negligible at any traffic level this
    # site will see, and a narrower unique index is cheaper.
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def record_visit(request):
    """Count one visit. Returns True if it was counted, False if skipped.

    Never raises. A traffic counter must not be able to fail a visitor's
    request, so database trouble is logged and swallowed -- losing a data point
    is strictly better than serving them an error.
    """
    user_agent = request.META.get("HTTP_USER_AGENT", "")
    if _BOT_UA.search(user_agent):
        return False

    today = timezone.localdate()
    try:
        visit, _ = DailyVisit.objects.get_or_create(date=today)

        # F() rather than read-modify-write: two simultaneous beacons would
        # otherwise read the same value and one increment would vanish. This
        # pushes the arithmetic into the database, so no transaction or lock is
        # needed for the count to stay correct.
        DailyVisit.objects.filter(pk=visit.pk).update(
            page_views=models.F("page_views") + 1
        )

        # The unique constraint on (date, visitor_hash) does the deduplication;
        # created=False means we have already counted this visitor today.
        _, created = DailyVisitorHash.objects.get_or_create(
            date=today,
            visitor_hash=_visitor_hash(_client_ip(request), user_agent, today),
        )
        if created:
            DailyVisit.objects.filter(pk=visit.pk).update(
                unique_visitors=models.F("unique_visitors") + 1
            )
        return True
    except DatabaseError:
        logger.warning("Failed to record site visit", exc_info=True)
        return False


def build_visit_report(days=30, months=12):
    """Daily rows for the last `days`, plus a monthly rollup of `months`.

    Both windows are trailing and inclusive of today. Days with no traffic have
    no row at all rather than a zero -- the tables read as "days we saw
    anything", which is the honest rendering of what was recorded.
    """
    today = timezone.localdate()

    daily = list(
        DailyVisit.objects.filter(
            date__gte=today - timedelta(days=days - 1)
        ).values("date", "page_views", "unique_visitors")
    )

    # Monthly totals come from the daily rows, so no second write path exists
    # to drift out of step with the first.
    monthly_start = (today - timedelta(days=months * 31)).replace(day=1)
    monthly = list(
        DailyVisit.objects.filter(date__gte=monthly_start)
        .annotate(month=TruncMonth("date"))
        .values("month")
        .annotate(
            page_views=models.Sum("page_views"),
            # NOT monthly unique visitors -- summing daily uniques counts a
            # person once per day they appeared. See _visitor_hash for why a
            # real MAU is off the table. Labelled "visit-days" everywhere it
            # surfaces so the number is never read as something it isn't.
            visit_days=models.Sum("unique_visitors"),
        )
        .order_by("-month")[:months]
    )

    return {
        "daily": daily,
        "monthly": monthly,
        "daily_window_days": days,
    }

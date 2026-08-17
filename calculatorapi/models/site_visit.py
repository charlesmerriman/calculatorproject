from django.db import models


class DailyVisit(models.Model):
    """One row per calendar day: how much traffic the site saw.

    This is the permanent record and the only thing the analytics dashboard
    reads. It holds nothing but counters -- there is no per-visitor row here
    and no way to work backwards from it to a person.

    Written by calculatorapi/visits.py in response to the SPA's beacon (see
    views/visits.py). Deliberately NOT registered in the Django admin: the
    numbers are reporting output, and a hand-edited counter is worse than no
    counter.
    """

    # UTC calendar day, matching timezone.localdate() at the moment of the hit.
    # Unique because the whole design is "find today's row and increment it";
    # a duplicate would silently split a day's traffic across two rows.
    date = models.DateField(unique=True)
    # Total beacons received. One per browser session, not per route change --
    # the SPA fires once and remembers (see frontend visitBeacon.ts), so this
    # counts sessions rather than client-side navigations.
    page_views = models.PositiveIntegerField(default=0)
    # Distinct visitors seen on this date, counted via DailyVisitorHash below.
    # Rolled up here so the figure survives the pruning of the hashes it came
    # from -- the hashes are scratch, this number is history.
    unique_visitors = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "Daily Visit"
        verbose_name_plural = "Daily Visits"
        # Newest first: every consumer wants the recent window.
        ordering = ["-date"]

    def __str__(self):
        return f"{self.date}: {self.page_views} views, {self.unique_visitors} visitors"


class DailyVisitorHash(models.Model):
    """Deduplication scratch space -- "have we already counted this visitor today?"

    Holds a salted digest, never an IP address or any raw request field. The
    salt includes the date (see visits._visitor_hash), so the same person
    produces a completely different value tomorrow: these rows cannot be joined
    across days to reconstruct anyone's visit history, which is precisely why
    "unique visitors" is a per-day number and monthly figures report visit-days
    instead.

    Disposable. Once a day's uniques are rolled up into DailyVisit above, these
    rows carry no further information -- `manage.py prune_visitor_hashes` drops
    the old ones.
    """

    date = models.DateField(db_index=True)
    # 32 hex chars: half a SHA-256, which is far more collision headroom than a
    # daily visitor count needs, and keeps the unique index narrow.
    visitor_hash = models.CharField(max_length=32)

    class Meta:
        verbose_name = "Daily Visitor Hash"
        verbose_name_plural = "Daily Visitor Hashes"
        constraints = [
            # This constraint IS the deduplication: record_visit() relies on
            # get_or_create raising/returning created=False here rather than
            # doing its own "have I seen this?" query, so concurrent requests
            # from the same visitor can never both count as new.
            models.UniqueConstraint(
                fields=["date", "visitor_hash"],
                name="unique_visitor_hash_per_day",
            )
        ]

    def __str__(self):
        # Truncated: the full digest is not a secret, but there is no reason to
        # print it into admin logs or error output either.
        return f"{self.date}: {self.visitor_hash[:8]}..."

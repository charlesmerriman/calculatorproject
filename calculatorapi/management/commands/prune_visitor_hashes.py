"""
Drops old per-visitor deduplication hashes.

DailyVisitorHash rows exist for one reason: to answer "have we already counted
this visitor today?" while a day is still being counted (see
calculatorapi/visits.py). Once that day's uniques have been rolled up into the
DailyVisit counter, the hashes carry no information anyone can use — they are
salted per-day, so they cannot be joined across days or matched back to an IP.

Pruning them is therefore pure housekeeping, not data loss: DailyVisit rows are
the permanent record and this command never touches them. It exists so the
scratch table does not grow without bound.

Usage:
    python manage.py prune_visitor_hashes --dry-run   # report only
    python manage.py prune_visitor_hashes             # keeps the last 90 days
    python manage.py prune_visitor_hashes --days 30

Safe to run on any schedule, including as a POST_DEPLOY job: it is idempotent
and exits 0 when there is nothing to delete.
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from calculatorapi.models import DailyVisitorHash
from calculatorapi.visits import VISITOR_HASH_RETENTION_DAYS


class Command(BaseCommand):
    help = "Delete visitor deduplication hashes older than the retention window."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=VISITOR_HASH_RETENTION_DAYS,
            help=(
                "Keep hashes from the last N days "
                f"(default {VISITOR_HASH_RETENTION_DAYS})."
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be deleted without writing anything.",
        )

    def handle(self, *args, **options):
        days = options["days"]
        dry_run = options["dry_run"]

        cutoff = timezone.localdate() - timedelta(days=days)
        stale = DailyVisitorHash.objects.filter(date__lt=cutoff)
        count = stale.count()

        if not count:
            self.stdout.write(f"Nothing to prune (no hashes older than {cutoff}).")
            return

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f"DRY RUN: would delete {count} hash(es) dated before {cutoff}."
                )
            )
            return

        stale.delete()
        self.stdout.write(
            self.style.SUCCESS(
                f"Deleted {count} hash(es) dated before {cutoff}. "
                "Daily visit counts are unaffected."
            )
        )

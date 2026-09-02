"""
Pulls the supporters list from the Patreon API and reconciles it.

This is the core of the sync. The admin's "Sync from Patreon" button and the
scheduled POST /patreon/sync endpoint both do the same two things this does —
fetch rows, hand them to `apply_patreon_import` — so a change to the reconcile
rules belongs there, not in any of the three callers.

Usage:
    python manage.py sync_patreon_supporters --dry-run
    python manage.py sync_patreon_supporters
    python manage.py sync_patreon_supporters --no-deactivate-missing

WHY DEACTIVATION DEFAULTS ON HERE
---------------------------------
The CSV form defaults it OFF and warns you to only tick it for a complete
export, because an uploaded file might have been filtered and would then retire
everyone it happened to omit. That risk does not exist here: a fully-paginated
API response IS the complete member list by construction. So the default flips,
and `--no-deactivate-missing` is there for the one case that still wants it —
running the sync while knowingly holding rows the API will not return.

IT EXITS 0 EVEN WHEN IT FAILS. Like set_patreon_tier_order, this is built to be
runnable from a POST_DEPLOY job, where a non-zero exit fails the whole
deployment — an expired Patreon token must not be able to take the site down.
Problems are reported on stdout and recorded on the credentials row; read the
log rather than trusting the exit status.

IT NEVER PUBLISHES A NAME. See admin_patreon_import.py — new supporters are
counted anonymously until someone ticks "Show name publicly" by hand.
"""

from django.core.management.base import BaseCommand
from django.utils import timezone

from calculatorapi import patreon_api
from calculatorapi.admin_patreon_import import apply_patreon_import
from calculatorapi.models import PatreonCredentials


class Command(BaseCommand):
    help = "Sync Patreon supporters from the Patreon API."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would change without writing anything.",
        )
        parser.add_argument(
            "--no-deactivate-missing",
            action="store_true",
            help=(
                "Keep supporters the API did not return active. Off by default: an "
                "API response is the complete member list, so a missing supporter "
                "has genuinely lapsed."
            ),
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        credentials = PatreonCredentials.load()

        try:
            rows = patreon_api.fetch_members(credentials)
        except patreon_api.PatreonApiError as exc:
            # Recorded so the admin page and a later run can explain themselves,
            # rather than the failure living only in a job log nobody reads.
            if not dry_run:
                credentials.last_sync_error = str(exc)
                credentials.save(update_fields=["last_sync_error"])
            self.stdout.write(self.style.ERROR(f"Patreon sync failed: {exc}"))
            self.stdout.write("Nothing was written. The existing supporters list is unchanged.")
            return

        summary = apply_patreon_import(
            rows,
            deactivate_missing=not options["no_deactivate_missing"],
            dry_run=dry_run,
        )

        if not dry_run:
            credentials.last_synced_at = timezone.now()
            credentials.last_sync_error = ""
            credentials.save(update_fields=["last_synced_at", "last_sync_error"])

        self._report(rows, summary, dry_run)

    def _report(self, rows, summary, dry_run):
        heading = "Preview — nothing was saved" if dry_run else "Sync complete"
        self.stdout.write(self.style.SUCCESS(heading))
        self.stdout.write(f"  {len(rows)} member(s) returned by Patreon")
        for label, key in (
            ("added", "created"),
            ("reactivated", "reactivated"),
            ("moved tier", "tier_changed"),
            ("deactivated", "deactivated"),
            ("pledge date filled", "dates_filled"),
            ("email updated", "emails_updated"),
        ):
            names = summary[key]
            if names:
                self.stdout.write(f"  {len(names)} {label}: {', '.join(names)}")
        self.stdout.write(f"  {summary['unchanged']} unchanged")
        if summary["tiers_created"]:
            self.stdout.write(
                f"  {len(summary['tiers_created'])} new tier(s): "
                f"{', '.join(summary['tiers_created'])}. "
                "Set their display order with set_patreon_tier_order."
            )
        if summary["created"] and not dry_run:
            self.stdout.write(
                "No names were published — tick 'Show name publicly' in the admin to do that."
            )

"""
Attaches the missing featured umas to the JP launch banner (2021-02-24).

The launch banner exists in production as a bare BannerTimeline row: it has a
name listing nine units, but no BannerUma, no BannerSupport and no image. Since
the featured-card links are what put a unit into the selector pool, the nine
BASE launch units are currently unreachable there — only their costume variants
(Special Week (Summer), Tokai Teio (Anime), ...) can be picked. An uma selector
ticket cannot select base Special Week, Tokai Teio, Oguri Cap and so on at all.

This is a LINKING job, not a creation job. All nine Uma records already exist;
they are simply not attached to any banner. The command creates one BannerUma
against the launch timeline and links the nine through UmasOnUmaBanner.

Two deliberate choices:

  - The timeline is found by its JP start date, not by primary key. The row is
    present in production and absent from local databases, so its id is not
    portable.

  - The unit list is parsed from the timeline's own `name`, which is the sheet's
    " + "-joined concatenation. Hardcoding nine names here would let this drift
    from the row it repairs.

Support cards are left alone: the source sheet's Timeline tab does not reach
back to 2021-02-24, so whether the launch banner carried any is unknown, and
inventing them would be worse than omitting them.

Idempotent: if the timeline already has a uma banner, the command reports and
exits without writing.

Usage:
    python manage.py repair_launch_banner --dry-run   # report only
    python manage.py repair_launch_banner             # prompts
    python manage.py repair_launch_banner --no-input  # scripted

Run against PRODUCTION from the DigitalOcean API component's Console tab, and
--dry-run there first — local databases do not contain this row.
"""

from datetime import date

from django.core.management.base import BaseCommand
from django.db import transaction

from calculatorapi.models import BannerTimeline, BannerUma, Uma, UmasOnUmaBanner

CONFIRM_PHRASE = "repair"

LAUNCH_JP_DATE = date(2021, 2, 24)


class Command(BaseCommand):
    help = "Link the nine featured umas to the JP launch banner (2021-02-24)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would change without writing anything.",
        )
        parser.add_argument(
            "--no-input",
            action="store_true",
            help="Skip the confirmation prompt (for scripted runs).",
        )

    def handle(self, *args, **options):
        timeline = BannerTimeline.objects.filter(
            jp_start_date__date=LAUNCH_JP_DATE
        ).first()

        if timeline is None:
            self.stdout.write(
                self.style.ERROR(
                    f"No banner timeline starts {LAUNCH_JP_DATE}. Nothing to repair. "
                    "(Expected on a local database — this row exists in production only.)"
                )
            )
            return

        self.stdout.write(f"Found timeline id={timeline.pk}: {timeline.name}\n")

        if timeline.uma_banners.exists():
            self.stdout.write(
                self.style.SUCCESS(
                    "It already has a uma banner attached — nothing to do."
                )
            )
            return

        # The name is the sheet's " + "-joined list of featured units.
        wanted = [part.strip() for part in timeline.name.split(" + ") if part.strip()]
        self.stdout.write(f"Parsed {len(wanted)} unit name(s) from the row name.")

        found, missing = [], []
        for name in wanted:
            uma = Uma.objects.filter(name__iexact=name).first()
            (found if uma else missing).append(uma or name)

        self.stdout.write(f"\nMatched {len(found)} Uma record(s):")
        for uma in found:
            self.stdout.write(f"    id={uma.pk:<5} {uma.name}")

        if missing:
            # Reported rather than created: an unmatched name usually means a
            # spelling drift between the row name and the Uma record, and
            # creating a duplicate would make that worse.
            self.stdout.write(
                self.style.WARNING(f"\nNo Uma record for {len(missing)} name(s):")
            )
            for name in missing:
                self.stdout.write(f"    {name}")
            self.stdout.write(
                "Fix these in admin first — the command will not create Uma rows."
            )

        if not found:
            self.stdout.write(self.style.ERROR("\nNothing to link."))
            return

        self.stdout.write(
            f"\nWould create 1 uma banner on timeline {timeline.pk} "
            f"and link {len(found)} uma(s)."
        )

        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("\nDry run — nothing written."))
            return

        if not options["no_input"]:
            typed = input(f'\nType "{CONFIRM_PHRASE}" to apply: ')
            if typed.strip() != CONFIRM_PHRASE:
                self.stdout.write(self.style.ERROR("Aborted."))
                return

        with transaction.atomic():
            banner = BannerUma.objects.create(
                banner_timeline=timeline,
                name=timeline.name,
                free_pulls=0,
            )
            UmasOnUmaBanner.objects.bulk_create(
                [UmasOnUmaBanner(banner_uma=banner, uma=uma) for uma in found]
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"\nCreated uma banner id={banner.pk} with {len(found)} uma(s)."
            )
        )

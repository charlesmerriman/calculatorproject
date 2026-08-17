"""
Attaches the ten support cards to each race-prep support rerun.

Roughly once a month the game reruns a batch of ten support cards alongside a
single uma, to let players prepare for an upcoming race. The source sheet codes
these as "Banner Type" 2. Our database has the uma side of all of them and the
support side of none: 29 timelines, 290 missing links, which is why the
calculator offers fewer pullable support banners than the sheet.

This is a LINKING job, not a creation job. Every one of the 85 distinct support
cards involved already exists — verified against production — so the command
creates no SupportCard rows and fetches no images. It creates one BannerSupport
per timeline and links the ten cards through SupportsOnSupportBanner.

Three deliberate choices:

  - Timelines are matched by JP start date, not primary key. Production ids are
    not portable, and JP dates are the stable identifier the CSV shares with us.

  - Card names resolve by exact match with a tiny alias table, never fuzzily.
    See the note in support_backfill.py — a similarity check happily offered
    "Hishi Miracle" for "K.S. Miracle".

  - It also sets banner_category to race_prep_support, because the CSV's Banner
    Type column is the authority for that and classify_banner_categories cannot
    derive it. Doing it here keeps the category and the cards in one
    transaction, so the two can never disagree.

BEHAVIOUR CHANGE, and it is the reason for --dry-run: selector eligibility is
derived from MIN(BannerTimeline.jp_start_date) per card, so linking a card to an
older banner moves its first_jp_date EARLIER. Around two dozen support cards
become eligible for support-selector tickets that currently refuse them. That is
a fix — the sheet says those cards were featured then, so today's dates are too
late — but it changes user-visible numbers. Run a sheet-parity pass afterwards.

Idempotent: a timeline that already has a support banner is left alone and
reported as skipped, so re-running is a no-op.

Usage:
    python manage.py backfill_race_prep_supports --dry-run   # report only
    python manage.py backfill_race_prep_supports             # prompts
    python manage.py backfill_race_prep_supports --no-input  # scripted

Run against PRODUCTION from the DigitalOcean API component's Console tab, and
--dry-run there first — local databases hold a different set of timelines.
"""

from datetime import date

from django.core.management.base import BaseCommand
from django.db import transaction

from calculatorapi.models import (
    BannerCategory,
    BannerSupport,
    BannerTimeline,
    SupportsOnSupportBanner,
)
from calculatorapi.support_backfill import (
    RACE_PREP_BANNER_TYPE,
    read_timeline_master,
    resolve_support_cards,
    split_names,
)

CONFIRM_PHRASE = "backfill"

# What the BannerSupport rows are called. The convention elsewhere is the
# " + "-joined card names, which for ten cards is an unreadable 150-character
# string in the planner's banner dropdown. These batches are interchangeable by
# nature — the point is the ten cards, not a headline unit — so they take the
# category's own name instead.
BANNER_SUPPORT_NAME = "Race Prep Support"


def parse_jp_date(value):
    """The CSV's "YYYY-MM-DD" as a date, or None when the cell is malformed."""
    try:
        year, month, day = (int(part) for part in value.split("-"))
        return date(year, month, day)
    except ValueError:
        return None


class Command(BaseCommand):
    help = "Link the ten support cards to each race-prep support rerun."

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
        rows = read_timeline_master(banner_type=RACE_PREP_BANNER_TYPE)
        self.stdout.write(f"{len(rows)} race-prep row(s) in the master CSV.\n")

        planned, skipped, problems = self._plan(rows)
        self._report(planned, skipped, problems, options["dry_run"])

        if not planned:
            self.stdout.write(self.style.SUCCESS("\nNothing to change."))
            return

        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("\nDry run — nothing written."))
            return

        if not options["no_input"]:
            typed = input(f'\nType "{CONFIRM_PHRASE}" to apply: ')
            if typed.strip() != CONFIRM_PHRASE:
                self.stdout.write(self.style.ERROR("Aborted."))
                return

        links = self._write(planned)
        self.stdout.write(
            self.style.SUCCESS(
                f"\nCreated {len(planned)} support banner(s) and {links} link(s)."
            )
        )

    def _plan(self, rows):
        """
        Work out what to attach, resolving every name before anything is written.

        A row whose card list does not fully resolve is skipped ENTIRELY rather
        than partially linked: half a batch looks complete in the UI while
        quietly under-representing the banner, which is worse than an obvious gap.
        """
        planned, skipped, problems = [], [], []

        for row in rows:
            jp_start = row["JP Start Date"]
            timeline = self._find_timeline(jp_start)

            if timeline is None:
                problems.append(f"{jp_start}: no banner timeline with this JP start date")
                continue

            if timeline.support_banners.exists():
                skipped.append(timeline)
                continue

            # Pass the CSV's date, not the timeline's: it is the authority the
            # resolver's date tiers are written against, and a race-prep batch
            # re-features older cards whose same-named SSR reprints can only be
            # told apart by it.
            names = split_names(row["Banner Support"])
            found, missing = resolve_support_cards(names, parse_jp_date(jp_start))

            if missing:
                problems.append(
                    f"{jp_start} (id={timeline.pk}): no SupportCard for "
                    f"{', '.join(missing)} — skipped, {len(found)} of "
                    f"{len(names)} resolved"
                )
                continue

            planned.append((timeline, found))

        return planned, skipped, problems

    def _write(self, planned):
        """One transaction for the lot, so the category can't outlive a failure."""
        links = 0
        with transaction.atomic():
            for timeline, cards in planned:
                banner = BannerSupport.objects.create(
                    banner_timeline=timeline,
                    name=BANNER_SUPPORT_NAME,
                    free_pulls=0,
                )
                SupportsOnSupportBanner.objects.bulk_create(
                    [
                        SupportsOnSupportBanner(banner_support=banner, support_card=card)
                        for card in cards
                    ]
                )
                links += len(cards)

                # The CSV's Banner Type is the authority here; the shape only
                # becomes derivable once these cards exist, and even then the
                # category should not be re-guessed from data we just wrote.
                if timeline.banner_category != BannerCategory.RACE_PREP_SUPPORT:
                    timeline.banner_category = BannerCategory.RACE_PREP_SUPPORT
                    timeline.save(update_fields=["banner_category"])
        return links

    def _find_timeline(self, jp_start):
        """Match on the JP start DATE, ignoring the stored time of day."""
        parsed = parse_jp_date(jp_start)
        if parsed is None:
            return None
        return BannerTimeline.objects.filter(jp_start_date__date=parsed).first()

    def _report(self, planned, skipped, problems, dry_run):
        verb = "Would attach" if dry_run else "Attaching"
        if planned:
            self.stdout.write(f"\n{verb} support cards to {len(planned)} timeline(s):")
            for timeline, cards in planned:
                jp = timeline.jp_start_date.date() if timeline.jp_start_date else "?"
                self.stdout.write(
                    f"    id={timeline.pk:<5} {jp}  {len(cards):>2} card(s)  "
                    f"{timeline.name[:40]}"
                )

        if skipped:
            self.stdout.write(
                self.style.SUCCESS(
                    f"\nAlready have a support banner: {len(skipped)} row(s) — left alone."
                )
            )

        if problems:
            self.stdout.write(self.style.WARNING(f"\nUnresolved: {len(problems)}"))
            for problem in problems:
                self.stdout.write(f"    {problem}")
            self.stdout.write(
                "Fix these in admin first — the command will not create SupportCard rows."
            )

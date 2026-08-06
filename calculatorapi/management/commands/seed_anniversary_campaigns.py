"""Seed the anniversary campaigns, their banner parts and their products.

Transcribed from the source sheet's "Selector Planner" tab. A management command
rather than a JSON fixture because campaigns attach to BannerTimeline rows, and
a fixture would have to hardcode those primary keys -- this resolves them by JP
start date instead, which is the sheet's own join key and is stable across
reseeds.

Idempotent: re-running updates existing campaigns in place (matched on name) and
replaces their parts and products, so correcting a price here and re-running is
safe.

KNOWN GAP -- per-campaign purchase limits. Prices, carat amounts, webstore
multipliers, cutoffs and which products each campaign offers are all transcribed
from the sheet and verified. The sheet's per-pack purchase LIMITS live in
unlabelled helper columns whose meaning could not be pinned down, so packs are
seeded with a permissive placeholder (PACK_QUANTITY_LIMIT) and should be
corrected in the admin once the real limits are known. Selectors are 1 by
definition.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from calculatorapi.models import (
    AnniversaryEvent,
    AnniversaryEventBanner,
    AnniversaryEventProduct,
    BannerTimeline,
)

#: Placeholder — see the KNOWN GAP note above.
PACK_QUANTITY_LIMIT = 10

# Product templates. usd / carats / webstore multiplier, all from the sheet's
# header catalogue block.
PACKS = {
    "11000": ("11000 Carat Pack", 140, 11000, "1.20"),
    "7500": ("7500 Carat Pack", 70, 7500, "1.10"),
    "1500": ("1500 Carat Pack", 14, 1500, "1.10"),
    "spark": ("Spark Enhancement", 21, 1500, "1.10"),
}

# Selector tiers. A $21 selector bundles 1,500 paid carats and a $70 one 7,500 —
# confirmed against the sheet's own totals (the 1st Anniversary's two $21
# selectors sum to "3,000 Carats / $42").
SELECTOR_TIERS = {
    "free": ("Free", 0, 0),
    "21": ("$21", 21, 1500),
    "70": ("$70", 70, 7500),
}

# name, event_type, cutoff, part JP start dates, packs, uma tiers, ssr tiers
CAMPAIGNS = [
    ("0.5th Anniversary", "anniversary", None,
     ["2021-08-16", "2021-08-24", "2021-08-30"],
     ["7500", "1500"], ["21", "70"], ["free", "21", "70"]),
    ("1st Anniversary", "anniversary", None,
     ["2022-02-14", "2022-02-24", "2022-03-07", "2022-03-18"],
     ["7500", "1500"], ["21"], ["free", "21"]),
    ("1.5th Anniversary", "anniversary", None,
     ["2022-08-16", "2022-08-24", "2022-09-02"],
     ["7500", "1500"], [], ["free"]),
    ("2nd Anniversary", "anniversary", None,
     ["2023-02-14", "2023-02-24", "2023-03-10", "2023-03-20"],
     ["7500", "1500"], ["21", "70"], ["free", "21", "70"]),
    ("2.5th Anniversary", "anniversary", None,
     ["2023-08-14", "2023-08-24", "2023-09-04"],
     ["7500", "1500"], ["21", "70"], ["free", "21", "70"]),
    ("Trainer Support Pack", "campaign", None,
     ["2023-10-05"],
     [], ["21"], ["21"]),
    ("New Years 2024", "new_year", None,
     ["2023-12-28", "2024-01-09"],
     ["7500", "1500"], ["21"], []),
    ("3rd Anniversary", "anniversary", "2024-01-31",
     ["2024-02-14", "2024-02-24", "2024-03-12", "2024-03-21"],
     ["7500", "1500"], ["21", "70"], ["free", "21", "70"]),
    ("3.5th Anniversary", "anniversary", "2024-07-31",
     ["2024-08-14", "2024-08-24", "2024-09-10"],
     ["7500", "1500"], ["21", "70"], ["free", "21", "70"]),
    ("New Years 2025", "new_year", None,
     ["2024-12-27", "2025-01-10"],
     ["7500", "1500"], [], []),
    ("4th Anniversary", "anniversary", "2025-01-31",
     ["2025-02-14", "2025-02-24", "2025-03-11", "2025-03-21"],
     ["7500", "1500", "spark"], ["21", "70"], ["free", "21", "70"]),
    ("4.5th Anniversary", "anniversary", "2025-07-31",
     ["2025-08-14", "2025-08-24", "2025-09-09"],
     ["7500", "1500", "spark"], ["21", "70"], ["free", "21", "70"]),
    ("New Years 2026", "new_year", None,
     ["2025-12-26", "2026-01-08"],
     ["7500", "1500", "spark"], [], []),
    # Part 4's JP date precedes Part 3's and the two share global dates — that is
    # how the sheet records it (concurrent banners), not a transcription slip.
    ("5th Anniversary", "anniversary", "2026-01-30",
     ["2026-02-14", "2026-02-24", "2026-03-11", "2026-03-01"],
     ["7500", "1500", "11000", "spark"], ["21", "70"], ["free", "21", "70"]),
]


class Command(BaseCommand):
    help = "Create or refresh the anniversary campaigns from the source sheet."

    def handle(self, *args, **options):
        created, updated, missing_parts = 0, 0, []

        with transaction.atomic():
            for row in CAMPAIGNS:
                name, event_type, cutoff, part_dates, packs, uma_tiers, ssr_tiers = row
                event, was_created = AnniversaryEvent.objects.update_or_create(
                    name=name,
                    defaults={"event_type": event_type, "jp_cutoff_date": cutoff},
                )
                created += was_created
                updated += not was_created

                missing_parts += self._link_parts(event, part_dates)
                self._build_products(event, packs, uma_tiers, ssr_tiers)

        self.stdout.write(self.style.SUCCESS(
            f"Campaigns: {created} created, {updated} updated."
        ))
        if missing_parts:
            # Not an error: the earliest campaigns predate the banner data, and
            # a campaign with some parts missing still resolves dates from the
            # ones it found. Surfaced so a real gap in banner data is visible.
            self.stdout.write(self.style.WARNING(
                f"{len(missing_parts)} banner part(s) had no matching timeline "
                f"and were skipped: {', '.join(missing_parts)}"
            ))

    def _link_parts(self, event, part_dates):
        """Attach the campaign to its banner parts, matched on JP start date."""
        missing = []
        event.banner_links.all().delete()
        for part_number, jp_date in enumerate(part_dates, start=1):
            timeline = BannerTimeline.objects.filter(
                jp_start_date__date=jp_date
            ).first()
            if timeline is None:
                missing.append(f"{event.name} Part {part_number} ({jp_date})")
                continue
            AnniversaryEventBanner.objects.create(
                anniversary_event=event,
                banner_timeline=timeline,
                part_number=part_number,
            )
        return missing

    @staticmethod
    def _build_products(event, packs, uma_tiers, ssr_tiers):
        """Replace the campaign's products with the sheet's current offering.

        Rebuilt rather than reconciled: products carry no user-owned state (a
        UserPlannedPurchase pointing at one is CASCADE-deleted with it), and
        matching them on name would silently orphan a renamed row.
        """
        event.products.all().delete()
        order = 0

        for key in packs:
            name, usd, carats, multiplier = PACKS[key]
            order += 1
            AnniversaryEventProduct.objects.create(
                anniversary_event=event,
                product_type="carat_pack",
                name=name,
                usd_cost=usd,
                paid_carat_amount=carats,
                webstore_multiplier=multiplier,
                max_quantity=PACK_QUANTITY_LIMIT,
                order=order,
            )

        for product_type, tiers, label in (
            ("uma_selector", uma_tiers, "Uma Selector"),
            ("support_selector", ssr_tiers, "SSR Selector"),
        ):
            for key in tiers:
                tier_label, usd, carats = SELECTOR_TIERS[key]
                order += 1
                AnniversaryEventProduct.objects.create(
                    anniversary_event=event,
                    product_type=product_type,
                    name=f"{tier_label} {label}",
                    usd_cost=usd,
                    paid_carat_amount=carats,
                    max_quantity=1,
                    order=order,
                )

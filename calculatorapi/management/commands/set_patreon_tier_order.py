"""
Sets the display order of Patreon tiers from NAME=ORDER pairs.

`PatreonTier.order` decides two things about the thank-you block on the home
page: which tier's supporters come first, and which tier gets the strongest chip
styling. The frontend keys emphasis off a tier's POSITION in this order rather
than its name or id — deliberately, so the client can rename tiers without a
deploy — which means a ladder numbered the wrong way round puts the ENTRY tier
at the top of the page in brand colour and the top tier at the bottom in grey.

Normally this is a few numbers on the Patreon Tiers list screen in the admin.
This command exists for when the admin is not the tool to hand — above all a
production run through a POST_DEPLOY job, which is the only route to the
production database from outside it (see the recipe in backend/.do/app.yaml).

Usage:
    python manage.py set_patreon_tier_order \
        "Senior Class=10" "Classic Class=20" "Junior Class=30" --dry-run
    python manage.py set_patreon_tier_order "Senior Class=10" ... --no-input

Tiers are matched by name, case-insensitively. Tiers you do not name keep the
order they already have.

IT EXITS 0 EVEN WHEN IT REFUSES TO WRITE. A POST_DEPLOY job that exits non-zero
fails the entire deployment, so a typo in an argument must not be able to take
the site down with it. Every problem is reported on stdout and nothing is
written; read the job log rather than trusting the exit status.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from calculatorapi.models import PatreonTier

CONFIRM_PHRASE = "reorder"

# PositiveSmallIntegerField's range. Checked here so a bad argument is reported
# as a plain message rather than surfacing as a database error mid-transaction.
MAX_ORDER = 32767


class Command(BaseCommand):
    help = 'Set PatreonTier.order from NAME=ORDER pairs (e.g. "Senior Class=10").'

    def add_arguments(self, parser):
        parser.add_argument(
            "assignments",
            nargs="+",
            metavar="NAME=ORDER",
            help='A tier name and its new order, e.g. "Senior Class=10".',
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would change without writing anything.",
        )
        parser.add_argument(
            "--no-input",
            action="store_true",
            help="Skip the confirmation prompt (for scripted and job runs).",
        )

    def handle(self, *args, **options):
        plan = self._build_plan(options["assignments"])
        if plan is None:
            return

        tiers, final = plan
        changing = [tier for tier in tiers if final[tier.pk] != tier.order]

        # Report the whole ladder, not just the rows that move. In a job log this
        # is the only view of what production actually holds.
        self.stdout.write("Tier ladder (top of the page first):")
        for tier in sorted(tiers, key=lambda t: (final[t.pk], t.name)):
            self._report_row(tier, final[tier.pk])

        if not changing:
            self.stdout.write(self.style.SUCCESS("\nAlready in this order; nothing to do."))
            return

        if options["dry_run"]:
            self.stdout.write(self.style.SUCCESS(
                f"\nDry run — {len(changing)} tier(s) would change, nothing written."
            ))
            return

        if not options["no_input"] and not self._confirmed():
            return

        # One transaction: a half-applied ladder is exactly the duplicate-order
        # state the check in _build_plan exists to prevent.
        with transaction.atomic():
            for tier in changing:
                tier.order = final[tier.pk]
            PatreonTier.objects.bulk_update(changing, ["order"])

        self.stdout.write(self.style.SUCCESS(f"\nUpdated {len(changing)} tier(s)."))

    def _build_plan(self, assignments):
        """Validate everything up front; return (tiers, {pk: order}) or None.

        None means a problem has already been reported and nothing should be
        written. Resolving the whole ladder before touching anything is what
        makes a run all-or-nothing: a partially applied reorder is the one
        outcome worse than the wrong order, because it can leave two tiers
        sharing a number.
        """
        requested, errors = self._parse(assignments)
        if errors:
            self._refuse(errors)
            return None

        tiers = list(PatreonTier.objects.all())
        if not tiers:
            self.stdout.write(self.style.SUCCESS("No Patreon tiers exist; nothing to do."))
            return None

        by_name = {tier.name.casefold(): tier for tier in tiers}
        resolved = {}
        misses = []
        for name, order in requested.items():
            tier = by_name.get(name.casefold())
            if tier is None:
                misses.append(name)
            else:
                resolved[tier.pk] = order

        if misses:
            known = ", ".join(sorted(tier.name for tier in tiers))
            self._refuse(
                [f"No tier named {name!r}." for name in misses] + [f"Tiers that exist: {known}"]
            )
            return None

        # The order each tier ends up with: the requested one where given, the
        # current one otherwise.
        final = {tier.pk: resolved.get(tier.pk, tier.order) for tier in tiers}

        # Two tiers sharing an order is not a database error — `order` has no
        # unique constraint, and Meta.ordering just falls back to name — but the
        # frontend GROUPS supporters by their tier's order, so a collision
        # silently merges two tiers into one block under one of their names.
        # Cheaper to refuse here than to debug it on the live home page.
        clashes = self._clashes(tiers, final)
        if clashes:
            self._refuse(
                ["Two or more tiers would share an order number:"]
                + [f"  order {order}: {names}" for order, names in clashes]
                + ["Name every tier you are renumbering, or pick distinct numbers."]
            )
            return None

        return tiers, final

    def _report_row(self, tier, new):
        """One line of the ladder, flagged when the tier is moving."""
        if new == tier.order:
            self.stdout.write(f"  {new:>5}  {tier.name}  (unchanged)")
        else:
            self.stdout.write(self.style.WARNING(f"  {new:>5}  {tier.name}  (was {tier.order})"))

    def _confirmed(self):
        """Interactive guard. Job and scripted runs pass --no-input instead."""
        if input(f'Type "{CONFIRM_PHRASE}" to write these orders: ').strip() == CONFIRM_PHRASE:
            return True
        self.stdout.write(self.style.WARNING("Aborted; nothing was changed."))
        return False

    def _parse(self, assignments):
        """Turn ["Name=10", ...] into {"Name": 10}, collecting every complaint."""
        requested = {}
        errors = []
        for raw in assignments:
            name, sep, value = raw.partition("=")
            name = name.strip()
            if not sep or not name:
                errors.append(f"{raw!r} is not NAME=ORDER.")
                continue
            try:
                order = int(value.strip())
            except ValueError:
                errors.append(f"{raw!r}: {value.strip()!r} is not a whole number.")
                continue
            if not 0 <= order <= MAX_ORDER:
                errors.append(f"{raw!r}: order must be between 0 and {MAX_ORDER}.")
                continue
            # Case-insensitive, because the lookup above is too — otherwise
            # "Senior Class=10" "senior class=20" would look like two tiers.
            duplicate = next((n for n in requested if n.casefold() == name.casefold()), None)
            if duplicate is not None:
                errors.append(f"{name!r} given twice.")
                continue
            requested[name] = order
        return requested, errors

    def _clashes(self, tiers, final):
        """[(order, "A, B"), ...] for each order number more than one tier takes."""
        grouped = {}
        for tier in tiers:
            grouped.setdefault(final[tier.pk], []).append(tier.name)
        return [
            (order, ", ".join(sorted(names)))
            for order, names in sorted(grouped.items())
            if len(names) > 1
        ]

    def _refuse(self, lines):
        """Report a problem and write nothing — deliberately still exiting 0."""
        for line in lines:
            self.stdout.write(self.style.ERROR(line))
        self.stdout.write(self.style.WARNING("Nothing was changed."))

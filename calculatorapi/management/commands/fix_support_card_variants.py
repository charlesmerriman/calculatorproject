"""
Re-points banner support links that landed on an R card to the right SSR.

WHAT WENT WRONG: game_id encodes rarity — 1xxxx is R, 2xxxx SR, 3xxxx SSR — and
support_backfill's old collision rule picked the LOWEST game_id when several
cards shared a name. For any character with both an R and an SSR card that rule
chose the R, every time. Gacha banners feature SSRs; an R card cannot be pulled
from a banner at all, so every one of these links is wrong.

Production, as measured 2026-08-13 against /calculator-data, holds 31 such links
across 8 banners:

  - 20 on the JP launch banner (2021-02-24), all of them, written by
    `repair_launch_banner` through the old rule.
  - 11 across seven 2026 banners, which predate that command — most likely the
    admin's autocomplete offering same-named rows in id order.

WHY IT MATTERS BEYOND THE ART: `first_jp_date` is MIN(banner jp_start_date) per
card, and selector eligibility is judged on it. With the launch links pointing
at R cards, the real launch SSRs look 71 to 565 days newer than they are, and
seven of them sit on no banner at all — so a selector ticket whose cutoff should
reach base Special Week refuses it. Fixing the links moves those dates back to
2021-02-24, which changes user-visible eligibility. That is the point, but it
means a sheet-parity pass afterwards is worth the time.

This is a RE-LINKING job. It creates no SupportCard rows and fetches no images:
if the correct SSR does not exist in the database it says so and moves on, and
the row is left exactly as it was for an editor to fix in admin.

Resolution is `support_backfill.resolve_variant` — the same rule the backfill
commands now use, so a repaired link and a freshly backfilled one cannot
disagree. Anything it will not resolve confidently is reported, never guessed.

Idempotent: a second run finds no non-SSR links and does nothing, which is what
makes it safe as a POST_DEPLOY job. It also never exits non-zero for unresolved
rows — a deploy should not fail over a data gap it cannot fix.

Usage:
    python manage.py fix_support_card_variants --dry-run   # report only
    python manage.py fix_support_card_variants             # prompts
    python manage.py fix_support_card_variants --no-input  # scripted

Run against PRODUCTION with --dry-run first — local databases hold a different
set of banners, so the local report says nothing about what prod will do.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from calculatorapi.models import SupportsOnSupportBanner
from calculatorapi.support_backfill import (
    SSR_MIN_GAME_ID,
    build_support_index,
    missing_debut_game_ids,
    normalize,
    resolve_variant,
)

CONFIRM_PHRASE = "fix"


class Command(BaseCommand):
    help = "Re-point banner support links from R cards to the correct SSR."

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
        planned, problems = self._plan()
        self._report(planned, problems, options["dry_run"])

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

        repointed, removed = self._write(planned)
        self.stdout.write(
            self.style.SUCCESS(
                f"\nRe-pointed {repointed} link(s), removed {removed} duplicate(s)."
            )
        )

    def _plan(self):
        """
        Work out every re-point before writing any of them.

        select_related because this walks every join row and touches the card,
        the banner and its timeline for each — 300-odd rows would otherwise be
        900-odd queries.
        """
        index = build_support_index()
        planned, problems = [], []

        links = SupportsOnSupportBanner.objects.select_related(
            "support_card", "banner_support__banner_timeline"
        ).order_by("pk")

        for link in links:
            card = link.support_card

            # A null game_id is unclassifiable, not innocent — but it is also
            # not evidence of this bug, so it is reported rather than touched.
            if card.game_id is None:
                problems.append(
                    f"link pk={link.pk}: '{card.name}' has no game_id — cannot tell "
                    "its rarity, left alone"
                )
                continue

            if card.game_id >= SSR_MIN_GAME_ID:
                continue

            banner = link.banner_support
            timeline = banner.banner_timeline
            jp_start = timeline.jp_start_date.date() if timeline.jp_start_date else None

            if jp_start is None:
                problems.append(
                    f"link pk={link.pk}: '{card.name}' ({card.game_id}) on "
                    f"'{banner.name}', whose timeline has no JP start date — "
                    "nothing to date-match against"
                )
                continue

            variants = index.get(normalize(card.name), [])
            target = resolve_variant(variants, jp_start)

            if target is None or target.pk == card.pk:
                # target is card when the R row is the only one of its name —
                # i.e. the SSR was never created. Same outcome either way: an
                # editor has to add it. Separate the two reasons, because a
                # missing debut card names its own fix and mere ambiguity does
                # not.
                absent = missing_debut_game_ids(variants, jp_start)
                if absent:
                    reason = (
                        "the card that debuted here is not in the database — add "
                        f"game_id {', '.join(str(game_id) for game_id in absent)}"
                    )
                else:
                    candidates = sum(
                        1
                        for variant in variants
                        if (variant.game_id or 0) >= SSR_MIN_GAME_ID
                    )
                    reason = f"no confident SSR ({candidates} same-named SSR row(s))"
                problems.append(
                    f"link pk={link.pk}: '{card.name}' ({card.game_id}) on "
                    f"'{banner.name}' [{jp_start}] — {reason}"
                )
                continue

            planned.append((link, card, target, banner, jp_start))

        return planned, problems

    def _write(self, planned):
        """
        All of it in one transaction — a half-repaired banner is worse than an
        unrepaired one, because it looks correct.
        """
        repointed = removed = 0
        with transaction.atomic():
            for link, _card, target, banner, _jp_start in planned:
                # The banner may already carry the correct SSR alongside the
                # wrong R — re-pointing would then duplicate it on the tile.
                # There is no unique constraint on the join to catch this.
                duplicate = (
                    SupportsOnSupportBanner.objects.filter(
                        banner_support=banner, support_card=target
                    )
                    .exclude(pk=link.pk)
                    .exists()
                )
                if duplicate:
                    link.delete()
                    removed += 1
                    continue

                link.support_card = target
                link.save(update_fields=["support_card"])
                repointed += 1
        return repointed, removed

    def _report(self, planned, problems, dry_run):
        verb = "Would re-point" if dry_run else "Re-pointing"
        if planned:
            self.stdout.write(f"\n{verb} {len(planned)} link(s):")
            for link, card, target, banner, jp_start in planned:
                self.stdout.write(
                    f"    pk={link.pk:<5} {jp_start}  {banner.name[:34]:<34} "
                    f"{card.name[:20]:<20} {card.game_id} -> {target.game_id}"
                )

        if problems:
            self.stdout.write(
                self.style.WARNING(f"\nLeft alone: {len(problems)} link(s)")
            )
            for problem in problems:
                self.stdout.write(f"    {problem}")
            self.stdout.write(
                "Add the missing SSR rows in admin and re-run — this command "
                "creates no cards."
            )

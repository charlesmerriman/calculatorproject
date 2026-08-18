from django.db import models
from django.core.exceptions import ValidationError
from .custom_user import CustomUser
from .banner_uma import BannerUma
from .banner_support import BannerSupport
from .banner_step_up import BannerStepUp


class UserPlannedBanner(models.Model):
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    banner_uma = models.ForeignKey(
        BannerUma,
        on_delete=models.CASCADE,
        blank=True,
        null=True,
    )
    banner_support = models.ForeignKey(
        BannerSupport,
        on_delete=models.CASCADE,
        blank=True,
        null=True,
    )
    banner_step_up = models.ForeignKey(
        BannerStepUp,
        on_delete=models.CASCADE,
        blank=True,
        null=True,
    )
    # Deliberately overloaded: on a step-up row this counts STEPS, not pulls,
    # mirroring the source sheet's own overload of the same column. One column
    # beats a second sitting null on almost every row, and a row's kind is fixed
    # at creation so the meaning can never change under it. The client reads it
    # through plannedSteps() / plannedPulls() so nothing assumes pulls.
    number_of_pulls = models.IntegerField()
    # Copies the user intends to obtain WITHOUT pulling, using a selector ticket
    # or an SSR crystal. Only the count is stored — which resource pays for each
    # copy is derived on every render from the projected balances and the
    # banner's JP eligibility, so it can never go stale against them.
    reserved_copies = models.IntegerField(default=0)

    class Meta:
        constraints = [
            # Exactly one target, now across three columns. Widened from the
            # two-way only_one_support_or_uma; every pre-existing row already
            # satisfies this (each carries one of uma/support, with a null
            # step-up), so the migration needs no data pass.
            models.CheckConstraint(
                condition=(
                    models.Q(banner_uma__isnull=False,
                             banner_support__isnull=True,
                             banner_step_up__isnull=True)
                    | models.Q(banner_uma__isnull=True,
                               banner_support__isnull=False,
                               banner_step_up__isnull=True)
                    | models.Q(banner_uma__isnull=True,
                               banner_support__isnull=True,
                               banner_step_up__isnull=False)
                ),
                name="exactly_one_banner_target",
            )
        ]

    @property
    def banner_target(self):
        """Whichever banner this row points at, or None.

        The one place the three FKs are inspected server-side, mirroring
        plannedBannerTarget() on the client. Callers wanting "the banner"
        should not re-derive the precedence each time.
        """
        return self.banner_uma or self.banner_support or self.banner_step_up

    def clean(self):
        targets = [self.banner_uma, self.banner_support, self.banner_step_up]
        chosen = [target for target in targets if target]
        if not chosen:
            raise ValidationError(
                "One of banner_uma, banner_support or banner_step_up must be set."
            )
        if len(chosen) > 1:
            raise ValidationError(
                "Only one of banner_uma, banner_support or banner_step_up may be set."
            )

    def __str__(self):
        banner = self.banner_target
        banner_name = banner.name if banner else "(no banner)"
        # "pulls" is the wrong noun on a step-up row, where the same column
        # counts steps.
        unit = "steps" if self.banner_step_up_id else "pulls"
        return f"{self.user.username} - {banner_name} ({self.number_of_pulls} {unit})"

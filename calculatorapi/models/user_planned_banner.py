from django.db import models
from django.core.exceptions import ValidationError
from .custom_user import CustomUser
from .banner_uma import BannerUma
from .banner_support import BannerSupport


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
    number_of_pulls = models.IntegerField()
    # Copies the user intends to obtain WITHOUT pulling, using a selector ticket
    # or an SSR crystal. Only the count is stored — which resource pays for each
    # copy is derived on every render from the projected balances and the
    # banner's JP eligibility, so it can never go stale against them.
    reserved_copies = models.IntegerField(default=0)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(banner_support__isnull=False, banner_uma__isnull=True)
                    | models.Q(banner_support__isnull=True, banner_uma__isnull=False)
                ),
                name="only_one_support_or_uma",
            )
        ]

    def clean(self):
        if not self.banner_support and not self.banner_uma:
            raise ValidationError("Either support_card or uma must be set.")
        if self.banner_support and self.banner_uma:
            raise ValidationError("Cannot set both support_card and uma.")

    def __str__(self):
        banner_name = (
            self.banner_uma.name if self.banner_uma else self.banner_support.name
        )
        return f"{self.user.username} - {banner_name} ({self.number_of_pulls} pulls)"

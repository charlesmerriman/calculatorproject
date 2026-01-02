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

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(support_card__isnull=False, uma__isnull=True)
                    | models.Q(support_card__isnull=True, uma__isnull=False)
                ),
                name="only_one_support_or_uma",
            )
        ]

    def clean(self):
        if not self.support_card and not self.uma:
            raise ValidationError("Either support_card or uma must be set.")
        if self.support_card and self.uma:
            raise ValidationError("Cannot set both support_card and uma.")


def __str__(self):
    return f"{self.user.username} - {self.banner.name} ({self.number_of_pulls} pulls)"

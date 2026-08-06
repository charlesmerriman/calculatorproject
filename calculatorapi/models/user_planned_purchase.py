from django.core.exceptions import ValidationError
from django.db import models

from .anniversary_event_product import AnniversaryEventProduct
from .custom_user import CustomUser
from .support_card import SupportCard
from .uma import Uma


class UserPlannedPurchase(models.Model):
    """A purchase the user intends to make at a campaign.

    Mirrors UserPlannedBanner: user-owned, replaced wholesale by the
    /calculator-data PATCH upsert, and using the same "at most one of two
    nullable FKs" check-constraint idiom for its target.

    `target_uma` / `target_support` record which card a selector will be spent
    on. Both stay null for carat packs, and for a selector the user has not
    decided on yet — so unlike UserPlannedBanner's constraint this one permits
    neither being set.
    """

    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    product = models.ForeignKey(AnniversaryEventProduct, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=1)
    target_uma = models.ForeignKey(
        Uma,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
    )
    target_support = models.ForeignKey(
        SupportCard,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(target_uma__isnull=True)
                    | models.Q(target_support__isnull=True)
                ),
                name="at_most_one_selector_target",
            )
        ]
        verbose_name = "planned purchase"
        verbose_name_plural = "planned purchases"

    def clean(self):
        if self.target_uma and self.target_support:
            raise ValidationError("Cannot set both target_uma and target_support.")

    def __str__(self):
        return f"{self.user.username} - {self.product.name} x{self.quantity}"

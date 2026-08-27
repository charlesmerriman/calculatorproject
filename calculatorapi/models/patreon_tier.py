from django.db import models


class PatreonTier(models.Model):
    """One Patreon pledge tier ("Junior Class", "Classic Class", …).

    A separate model rather than TextChoices so the client can add or rename a
    tier from the admin — Patreon tiers are theirs to change, and a migration
    per rename would put every change through a deploy.

    Carries no money. The pledge amount is Patreon's business and would only go
    stale here; `order` is the display axis, and that is all the site needs.
    """

    name = models.CharField(max_length=50, unique=True)
    # Display rank, low = shown first and emphasised. Deliberately NOT derived
    # from a price: Patreon's own tier list is ordered by the creator, and the
    # CSV's "Lifetime Amount" is a running total that would reorder the list
    # every month as long-standing patrons overtake newer higher-tier ones.
    order = models.PositiveSmallIntegerField(
        default=0,
        help_text="Lower numbers appear first on the site. Ties fall back to name.",
    )

    class Meta:
        verbose_name = "Patreon Tier"
        verbose_name_plural = "Patreon Tiers"
        ordering = ("order", "name")

    def __str__(self):
        return str(self.name)

from django.db import models
from django.db.models.functions import Lower


class PatreonSupporter(models.Model):
    """One Patreon supporter, for the public thank-you list on the home page.

    PRIVACY — read before adding a field.

    This is the only model holding data about people who never signed up to
    this site, so it deliberately holds the bare minimum needed to say thank
    you: a display name and a tier. Do NOT add email, Discord handle, Patreon
    user ID, pledge amount, or anything else from the Patreon CSV export. Those
    columns are billing data belonging to a third party; the site has no use
    for them and no consent to publish them, and `purge_user_pii` does not
    know about this table.

    `display_name` is the name the patron chose to be thanked by. The CSV's
    "Name" column is frequently a real billing name, so it is not automatically
    publishable — hence `is_public` below.
    """

    display_name = models.CharField(
        max_length=100,
        help_text="The name to thank them by. Use their Patreon handle, never a billing name.",
    )
    tier = models.ForeignKey(
        "calculatorapi.PatreonTier",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="supporters",
    )
    # Consent gate, defaulting to OFF. An unticked supporter still counts
    # towards the "…and N others" line, so the acknowledgement is complete
    # without publishing a name nobody agreed to publish. Turning this on is a
    # deliberate editorial act, which is the point.
    is_public = models.BooleanField(
        default=False,
        verbose_name="Show name publicly",
        help_text=(
            "Off by default. While off they are counted anonymously instead. "
            "Only tick this for a name they chose to be shown by."
        ),
    )
    # Lapsed patrons are deactivated rather than deleted, so a returning
    # supporter keeps their `patron_since` date and their consent decision
    # instead of being re-entered from scratch each time.
    is_active = models.BooleanField(
        default=True,
        help_text="Untick when a pledge lapses. Keeps the row instead of deleting it.",
    )
    patron_since = models.DateField(
        null=True,
        blank=True,
        help_text="Optional. Used only to order supporters within a tier, longest-standing first.",
    )

    class Meta:
        verbose_name = "Patreon Supporter"
        verbose_name_plural = "Patreon Supporters"
        # Tier order first, then longest-standing. `patron_since` nulls last so
        # a row with no date doesn't jump to the top of its tier.
        ordering = ("tier__order", models.F("patron_since").asc(nulls_last=True), "display_name")
        constraints = [
            # Patreon display names are unique in practice, and a duplicate here
            # is nearly always a re-import of someone already listed.
            models.UniqueConstraint(
                Lower("display_name"),
                name="unique_patreon_supporter_display_name",
            ),
        ]

    def __str__(self):
        return str(self.display_name)

from django.db import models
from django.db.models.functions import Lower


class PatreonSupporter(models.Model):
    """One Patreon supporter, for the public thank-you list on the home page.

    PRIVACY — read before adding a field.

    This is the only model holding data about people who never signed up to
    this site, so it holds the minimum needed to say thank you and to tell two
    supporters apart in the admin: a display name, a tier, and an email.

    `email` is the ONE piece of contact data here, added deliberately (see its
    own comment below). Nothing else from the Patreon export belongs in this
    database — no Discord handle, no Patreon user id, no postal address, no
    phone, no pledge amount, no charge history. Those are billing data
    belonging to a third party, the site has no use for them, and the two
    import paths are written to never read them at all.

    `display_name` is the name the patron chose to be thanked by. The CSV's
    "Name" column is frequently a real billing name, so it is not automatically
    publishable — hence `is_public` below.
    """

    display_name = models.CharField(
        max_length=100,
        help_text="The name to thank them by. Use their Patreon handle, never a billing name.",
    )
    # ADMIN-ONLY. Patreon display names collide and change — a patron who
    # renames themselves imports as a second row, and two people can pick names
    # that differ only in punctuation. The email is the one value in the export
    # that is stable and unique per person, so it is what lets an editor tell
    # those rows apart.
    #
    # It is NOT published: `PatreonSupporterSerializer` lists its fields
    # explicitly and this is not among them, so it cannot reach GET /supporters
    # by being added here. Keep it that way.
    #
    # Optional because it is not load-bearing: a hand-entered supporter has no
    # email, and an older CSV export without the column must still import.
    email = models.EmailField(
        blank=True,
        default="",
        help_text=(
            "Admin only — never shown on the website. Used to tell supporters "
            "with similar or changed display names apart."
        ),
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

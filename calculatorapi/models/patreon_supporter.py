from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower

from .custom_user import CustomUser


class PatreonSupporter(models.Model):
    """One Patreon supporter, for the public thank-you list on the home page.

    PRIVACY — read before adding a field.

    This is the only model holding data about people who never signed up to
    this site, so it holds the minimum needed to say thank you and to tell two
    supporters apart in the admin: a display name, a tier, and an email.

    `email` is the ONE piece of contact data here, added deliberately (see its
    own comment below). Nothing else from the Patreon export belongs in this
    database — no Discord handle, no postal address, no phone, no pledge
    amount, no charge history. Those are billing data belonging to a third
    party, the site has no use for them, and the two import paths are written
    to never read them at all.

    `patreon_user_id` is a deliberate amendment to that list (this docstring
    used to name it among the things kept out). It is what lets a patron be
    matched to a site account, which is what entitlement hangs off; the
    reasoning is on the field itself.

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

    # Patreon's opaque, permanent id for the PERSON behind this membership —
    # the same value SocialAccount.subject_id stores when they sign in with
    # Patreon. Holding it in both places is what closes the gap between "who is
    # pledging" (this table, filled by the daily sync) and "who is signed in"
    # (that table), which have entirely independent lifecycles: most patrons
    # have no account here, and most accounts have no pledge.
    #
    # WHY THIS IS ACCEPTABLE TO STORE, when nothing else from the export is:
    #   * It is opaque. It identifies nobody without Patreon's own database,
    #     exactly like the subject ids we already hold for every account.
    #   * It is read as a RELATIONSHIP (`include=user` -> relationships.user.
    #     data.id), never as an attribute, so MEMBER_FIELDS — the privacy
    #     boundary in patreon_api.py — does not change to get it.
    #   * The alternative was matching patrons to accounts BY EMAIL, which
    #     would mean collecting an email from every site user. This id exists
    #     specifically so we never have to.
    #   * It is NEVER serialized. Same treatment as `email`: admin-side only.
    #
    # Empty for CSV-imported and hand-entered rows, which therefore can never
    # be linked to an account. That is a real limitation and a good reason to
    # prefer the API sync — see backend/docs/admin.md.
    patreon_user_id = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text=(
            "Admin only — never shown on the website. Patreon's own id for this "
            "person; filled by the API sync and used to match them to a site account."
        ),
    )
    # The site account this patron signed in with, once both halves are known.
    # Set from EITHER direction: the sync attaches it when it meets a patron
    # whose id already has a SocialAccount, and the link/sign-in flows attach it
    # when a new Patreon identity matches a row the sync already created.
    #
    # SET_NULL, never CASCADE: deleting a site account must not delete the
    # supporter row. They are still a patron — they just have no account here
    # any more, and their consent decision and `patron_since` outlive the
    # account. Unlinking clears this field and drops entitlement, and keeps
    # everything else, exactly like a lapse.
    #
    # OneToOne because entitlement is per person: two supporter rows pointing at
    # one account would make "which tier is this user on?" ambiguous.
    linked_user = models.OneToOneField(
        CustomUser,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="patreon_supporter",
        help_text="The site account this patron signed in with, if they have linked one.",
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
            # THE IDENTITY KEY for anything the API produced. Unique only over
            # rows that HAVE an id, so the CSV and hand-entered rows (which
            # never get one) are not all in violation of a single "" value.
            models.UniqueConstraint(
                fields=["patreon_user_id"],
                condition=~Q(patreon_user_id=""),
                name="unique_patreon_supporter_patreon_user_id",
            ),
            # Display names are the FALLBACK key, and only for rows with no
            # Patreon id. This constraint used to cover every row, which was
            # harmless while this table only fed a thank-you list — but two
            # patrons are free to choose the same display name, and once
            # entitlement hangs off the row, collapsing them costs one of them
            # the thing they paid for. Nothing would report it either: a
            # dropped row looks exactly like a lapsed one.
            #
            # So API rows are keyed on the id and are not name-constrained at
            # all, while CSV and hand-entered rows keep the collision
            # protection they still need (a re-import of someone already listed
            # is otherwise a duplicate).
            models.UniqueConstraint(
                Lower("display_name"),
                condition=Q(patreon_user_id=""),
                name="unique_patreon_supporter_display_name",
            ),
        ]

    def __str__(self):
        return str(self.display_name)

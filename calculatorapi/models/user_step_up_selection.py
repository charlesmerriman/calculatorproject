from django.core.exceptions import ValidationError
from django.db import models

from .banner_step_up import BannerStepUp
from .custom_user import CustomUser
from .support_card import SupportCard
from .uma import Uma


# The game fixes the selection at ten. Not a tunable: the 0.3% target rate the
# projection uses IS 3% / 10, so a different slot count would silently make that
# rate wrong. See frontend/src/utils/stepUpLadder.ts.
SELECTION_SLOTS = 10


class UserStepUpSelection(models.Model):
    """One of the ten cards a user intends to select at a Select Step-Up banner.

    WHAT IT RECORDS
    ---------------
    A Select Step-Up lets the player pick 10 cards from the back catalogue
    (everything released on JP on or before the campaign's `jp_cutoff_date`)
    before climbing the ladder. Steps 3 and 4 guarantee a RANDOM one of those
    ten; step 5 guarantees the one they choose, which is the row flagged
    `is_target`.

    WHY IT KEYS OFF BannerStepUp AND NOT UserPlannedBanner
    ------------------------------------------------------
    "Which ten cards would I pick here" is a fact about the BANNER, not about a
    particular plan row: it changes no cost, no odds and no eligibility. Keying
    it to the banner mirrors UserPlannedPurchase (keyed to a product, not to a
    planned banner) and buys three things:

      * The ids are real server ids that always exist, so this is a flat
        sibling collection in the PATCH body. Keying off UserPlannedBanner
        would have forced a writable nested serializer, because a newly staged
        planner row has no id until the same PATCH creates it.
      * A user can record a selection for a step-up they have not planned yet.
      * Guest migration carries a flat list, exactly like planned purchases.

    The trade: a selection outlives deleting its planner row. That is correct
    for the same reason -- it was never about the planner row.

    WHAT IT DOES NOT DO
    -------------------
    NOTHING in the projection reads this. The step-up target rate is 3% / 10 and
    is true whichever ten are picked, so a partial or empty selection changes no
    number. It is a planning record, exactly as it is on the source sheet, whose
    Selection 1..10 columns feed no formula either. A selection is also NOT a
    reserved copy: a reserved copy is one taken INSTEAD of pulling, funded by a
    ticket or crystal, while these are candidates for pulls already paid for.
    """

    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    banner_step_up = models.ForeignKey(
        BannerStepUp,
        on_delete=models.CASCADE,
        related_name="user_selections",
    )
    # CASCADE, unlike UserPlannedPurchase's SET_NULL target FKs, because the
    # two models mean different things by a null card. A purchase without a
    # target is still a purchase; a SELECTION without a card is nothing at all,
    # which is what exactly_one_selection_card below says. SET_NULL here would
    # produce rows that constraint forbids.
    #
    # Nothing is lost by it: the UI renders slots 1..SELECTION_SLOTS and derives
    # the empty ones from MISSING rows, so a cascaded delete and a nulled FK
    # look identical on screen -- an empty slot the user can re-fill.
    uma = models.ForeignKey(
        Uma,
        on_delete=models.CASCADE,
        blank=True,
        null=True,
    )
    support = models.ForeignKey(
        SupportCard,
        on_delete=models.CASCADE,
        blank=True,
        null=True,
    )
    slot = models.PositiveIntegerField(
        help_text=f"Which of the {SELECTION_SLOTS} selection slots, 1-based.",
    )
    is_target = models.BooleanField(
        default=False,
        help_text="The step 5 pick -- the copy the player chooses outright.",
    )

    class Meta:
        ordering = ["banner_step_up", "slot"]
        constraints = [
            # EXACTLY one, unlike UserPlannedPurchase.at_most_one_selector_target
            # which permits neither. An empty slot is represented by the row not
            # existing, so a row with no card set means nothing at all.
            models.CheckConstraint(
                condition=(
                    models.Q(uma__isnull=False, support__isnull=True)
                    | models.Q(uma__isnull=True, support__isnull=False)
                ),
                name="exactly_one_selection_card",
            ),
            models.UniqueConstraint(
                fields=["user", "banner_step_up", "slot"],
                name="unique_step_up_selection_slot",
            ),
            # At most one step 5 pick per banner. A partial index, so rows with
            # is_target=False are unconstrained.
            models.UniqueConstraint(
                fields=["user", "banner_step_up"],
                condition=models.Q(is_target=True),
                name="one_step_up_target_per_banner",
            ),
        ]
        verbose_name = "step-up selection"
        verbose_name_plural = "step-up selections"

    @property
    def card(self):
        """Whichever card this slot holds.

        The one place the two FKs are inspected server-side. Callers wanting
        "the card" should not re-derive the precedence each time.
        """
        return self.uma or self.support

    def clean(self):
        """Readable errors for what the constraints enforce, plus the two
        cross-table rules a CheckConstraint cannot reach.

        Both layers exist on purpose: the constraints are the guarantee, this is
        what the admin form shows instead of an IntegrityError page.
        """
        chosen = [card for card in (self.uma, self.support) if card]
        if not chosen:
            raise ValidationError("One of uma or support must be set.")
        if len(chosen) > 1:
            raise ValidationError("Only one of uma or support may be set.")

        if not 1 <= self.slot <= SELECTION_SLOTS:
            raise ValidationError(
                {"slot": f"Slot must be between 1 and {SELECTION_SLOTS}."}
            )

        if self.banner_step_up_id is None:
            return
        # The pool a step-up draws from is fixed by its card_type, so a support
        # card on an uma step-up is not a card the game would ever offer.
        expected_uma = self.banner_step_up.card_type == "uma"
        if expected_uma and self.support_id is not None:
            raise ValidationError(
                {"support": "A ★3 uma step-up cannot select a support card."}
            )
        if not expected_uma and self.uma_id is not None:
            raise ValidationError(
                {"uma": "An SSR support step-up cannot select an uma."}
            )

    def __str__(self):
        card = self.card
        name = card.name if card else "(card removed)"
        marker = " ★step 5" if self.is_target else ""
        return f"{self.user.username} - {self.banner_step_up.name} #{self.slot}: {name}{marker}"

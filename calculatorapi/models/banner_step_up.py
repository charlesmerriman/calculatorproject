from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models

from .anniversary_event import AnniversaryEvent
from .banner_timeline import BannerTimeline


CARD_TYPE_CHOICES = [
    ("uma", "★3 Uma"),
    ("support", "SSR Support"),
]


class BannerStepUp(models.Model):
    """A paid-carats-only Select Step-Up banner sold during a campaign.

    WHAT IT IS
    ----------
    The player picks 10 cards from the back catalogue (everything released on JP
    on or before the campaign's `jp_cutoff_date`), then climbs a five-step
    ladder of 10-pulls at 500/700/1000/1300/1500 paid carats. Steps 3 and 4
    guarantee a random one of their 10; step 5 guarantees the one they choose.
    5,000 paid carats buys 50 pulls, against 7,500 at the normal rate.

    WHY IT IS A PEER OF BannerUma / BannerSupport
    ---------------------------------------------
    It carries the same `banner_timeline` FK as they do, which is the whole
    reason this feature is tractable: income in the projection is a pure
    function of a banner's end date, so every date, ordering and income path
    resolves a step-up through exactly the same code as its siblings. Only the
    SPEND half of the engine branches. Do NOT give this model a different date
    source.

    WHY banner_timeline IS EXPLICIT AND NOT DERIVED FROM THE CAMPAIGN
    ----------------------------------------------------------------
    A campaign's resolved range spans ALL its parts, while the source sheet runs
    the step-up over Part 2 only. For the 5th anniversary that is 2029-01-10 vs
    2029-01-18 — eight days of income the projection would otherwise credit.
    The two FKs are therefore both load-bearing: the timeline dates it, the
    campaign supplies the cutoff. `clean()` keeps them consistent.

    WHY ONE ROW PER CARD TYPE
    -------------------------
    The sheet keeps a single pooled row per campaign and contradicts itself
    doing it: its Max Steps sums the ★3 and SSR counts while its odds cells read
    the SSR count alone, so a ★3 step-up at an SSR-only campaign computes its
    odds off zero. Splitting also lets a row label its own odds column, which a
    pooled row cannot — ★3 copies read 1x..5x and SSR copies read 0LB..MLB.
    """

    banner_timeline = models.ForeignKey(
        BannerTimeline,
        on_delete=models.CASCADE,
        related_name="step_up_banners",
        help_text=(
            "The campaign part this step-up runs alongside — normally Part 2. "
            "Supplies the dates the projection uses."
        ),
    )
    anniversary_event = models.ForeignKey(
        AnniversaryEvent,
        on_delete=models.CASCADE,
        related_name="step_up_banners",
        help_text="The campaign selling it. Supplies the JP cutoff for candidates.",
    )
    name = models.CharField(
        max_length=255,
        help_text="As shown on the planner, e.g. '5th Anniversary SSR Select Step-Up'.",
    )
    card_type = models.CharField(
        max_length=10,
        choices=CARD_TYPE_CHOICES,
        default="support",
        help_text="Which pool this step-up draws from. Drives the odds labels.",
    )
    banner_count = models.PositiveIntegerField(
        default=1,
        validators=[MinValueValidator(1)],
        help_text=(
            "How many banners of this card type the campaign sells. This is the "
            "hard ceiling on steps: banner_count x 5."
        ),
    )
    # A step-up has no featured cards to borrow art from — the player picks their
    # own 10 — so this is the row's only thumbnail source. Campaigns carry no
    # image in practice, which is why it lives here rather than being inherited.
    image = models.ImageField(upload_to="step_up_banners/", null=True, blank=True)
    admin_comments = models.TextField(blank=True, null=True, help_text="Notes for editors.")
    order = models.PositiveIntegerField(
        default=0,
        help_text="Sort order within a campaign, e.g. to put ★3 before SSR.",
    )

    class Meta:
        ordering = ["order", "id"]
        # Default would be "banner step up / banner step ups" — confusing for editors.
        verbose_name = "step-up banner"
        verbose_name_plural = "step-up banners"

    def clean(self):
        """The two FKs must agree: the timeline has to be one of the campaign's
        own parts.

        Not a database constraint because it is a cross-table condition —
        CheckConstraint cannot reach through AnniversaryEventBanner. Enforced
        here (so the admin form catches it) rather than left to editor
        discipline, because a step-up pointed at an unrelated banner would date
        itself off an unrelated window and silently project the wrong income.
        """
        if self.anniversary_event_id is None or self.banner_timeline_id is None:
            return
        is_part = self.anniversary_event.banner_links.filter(
            banner_timeline_id=self.banner_timeline_id
        ).exists()
        if not is_part:
            raise ValidationError({
                "banner_timeline": (
                    "Must be one of the selected campaign's banner parts. Add it "
                    "to the campaign first if it belongs there."
                )
            })

    @property
    def max_steps(self):
        """Steps that physically exist: five per banner sold.

        The source sheet caps at 35, but that is the extent of its lookup table
        rather than a game rule — with at most 3 banners the real ceiling is
        always lower. Exposed here so the count and the rule live together.
        """
        return self.banner_count * 5

    def __str__(self):
        return str(self.name)

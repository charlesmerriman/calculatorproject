from django.db import models


EVENT_TYPE_CHOICES = [
    ("anniversary", "Anniversary"),
    ("new_year", "New Year"),
    ("campaign", "Campaign"),
]


class AnniversaryEvent(models.Model):
    """A dated campaign that sells carat packs and/or grants selector tickets.

    Named for the dominant case, but the source sheet also plans "New Years"
    campaigns and one-off promotions like the Trainer Support Pack — hence
    `event_type`, which keeps them in one table (and one code path) without the
    model name lying about what a row contains.

    This model owns NO dates. It borrows them from the BannerTimeline rows it is
    attached to via AnniversaryEventBanner: start = the earliest linked part's
    resolved start, end = the latest part's resolved end. That keeps campaigns on
    the single shared prediction calendar in predictions.py, inheriting
    is_predicted and the cascading schedule offsets for free. A standalone set of
    jp/global date fields would need its own prediction anchor, and with only a
    handful of campaigns having confirmed global dates that anchor would be far
    weaker than BannerTimeline's.

    Expansion point: per-event rewards (welfare/guaranteed SSRs and similar)
    belong here as flat fields, following GameEvent's precedent — see
    docs/data-model.md on why a rewards sub-model was collapsed into columns.
    """

    name = models.CharField(max_length=255)
    event_type = models.CharField(
        max_length=20,
        choices=EVENT_TYPE_CHOICES,
        default="anniversary",
        help_text="Drives the timeline strip's label and styling.",
    )
    # A selector can only pick cards released on JP on or BEFORE this date
    # (inclusive). Null means the campaign's selectors are unrestricted, which is
    # how the sheet records the pre-3rd-anniversary campaigns. Individual
    # products may override it — see AnniversaryEventProduct.jp_cutoff_date.
    jp_cutoff_date = models.DateField(
        null=True,
        blank=True,
        verbose_name="JP cutoff date",
        help_text=(
            "Selectors from this campaign can only pick cards released on JP on "
            "or before this date. Leave blank for no restriction."
        ),
    )
    image = models.ImageField(upload_to="anniversary_events/", null=True, blank=True)
    accent_label = models.CharField(
        max_length=60,
        blank=True,
        help_text="Optional short badge text for the timeline strip, e.g. 'Guaranteed SSR'.",
    )
    banner_timelines = models.ManyToManyField(
        "calculatorapi.BannerTimeline",
        through="calculatorapi.AnniversaryEventBanner",
        related_name="anniversary_events",
        blank=True,
    )

    class Meta:
        verbose_name = "anniversary event"
        verbose_name_plural = "anniversary events"

    def __str__(self):
        return str(self.name)

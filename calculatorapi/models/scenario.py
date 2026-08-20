from django.db import models

from .banner_timeline import BannerTimeline


class Scenario(models.Model):
    """A training scenario — a new, optional way to play the game (URA Finals,
    Aoharu, Grand Live, Hashire! Mecha Umamusume, ...).

    A SINGLE dated instant, not a range. A scenario is released and then stays
    available permanently: a newer scenario does NOT retire an older one, it
    just tends to get played more because it is more rewarding. There is
    therefore no end date to record, and this model must never borrow one from
    its launch banner — that would invent an expiry the scenario does not have.

    This is the fourth way a model attaches to BannerTimeline, and the only one
    with no end at all:

      1. content on a banner   BannerUma / BannerSupport / BannerStepUp
      2. borrow its window     GameEvent (start, and end + a 4-day buffer)
      3. span several Parts    AnniversaryEvent (earliest start, latest end)
      4. borrow its START only Scenario  <- this model

    Dates resolve in predictions.scenario_effective_dates against the shared
    BannerTimeline effective-date map, which is what keeps scenarios on the one
    prediction calendar and gives them schedule offsets for free.

    banner_timeline is nullable + SET_NULL for the same reason GameEvent's is:
    a scenario's name and image stay real content even if the banner it launched
    alongside is later deleted. An unlinked scenario is undated and simply
    doesn't render.
    """

    name = models.CharField(max_length=255)
    # Nullable by workflow, not by accident: scenarios get entered while the
    # feature is being built and the art arrives later. Every consumer must
    # render without it — see the frontend's EventMarkerCard placeholder.
    image = models.ImageField(upload_to="scenarios/", null=True, blank=True)
    banner_timeline = models.ForeignKey(
        BannerTimeline,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="scenarios",
        help_text=(
            "The banner this scenario launches alongside — supplies its start "
            "date. A scenario has no end date."
        ),
    )

    class Meta:
        verbose_name = "scenario"
        verbose_name_plural = "scenarios"

    def __str__(self):
        return str(self.name)

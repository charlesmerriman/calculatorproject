from django.db import models

from .anniversary_event import AnniversaryEvent
from .banner_timeline import BannerTimeline


class AnniversaryEventBanner(models.Model):
    """Links one campaign to one of its banner "Parts".

    The source sheet splits each anniversary into Part 1..N, and each Part is a
    separate BannerTimeline row (3rd Anniversary Part 2 = JP 2024-02-24 =
    "Duramente + Ikuno Dictus"). Recording every part is what lets the campaign
    resolve its full date range and what lets the timeline draw its strip above
    each part's card.

    The link lives here rather than as a column on BannerTimeline deliberately:
    BannerTimeline is shared, heavily-used content and stays untouched, exactly
    as GameEvent already owns its own FK to it.
    """

    anniversary_event = models.ForeignKey(
        AnniversaryEvent,
        on_delete=models.CASCADE,
        related_name="banner_links",
    )
    banner_timeline = models.ForeignKey(
        BannerTimeline,
        on_delete=models.CASCADE,
        related_name="anniversary_links",
    )
    part_number = models.PositiveIntegerField(
        default=1,
        help_text="The sheet's Part number within this campaign (1, 2, 3, ...).",
    )

    class Meta:
        ordering = ["part_number", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["anniversary_event", "banner_timeline"],
                name="unique_anniversary_event_banner",
            )
        ]
        verbose_name = "campaign banner part"
        verbose_name_plural = "campaign banner parts"

    def __str__(self):
        return f"{self.anniversary_event.name} - Part {self.part_number}"

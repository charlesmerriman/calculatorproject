from django.db import models

from .banner_timeline import BannerTimeline

class GameEvent(models.Model):
    name = models.CharField(max_length=255, null=False)
    image = models.ImageField(upload_to="game_events/", null=True, blank=True)
    # Nullable: dates are derived entirely from the linked BannerTimeline (see
    # calculatorapi/predictions.py), but not every event has one — some tie to
    # Champions Meeting/League of Heroes instead, or are campaign-wide events
    # spanning multiple banners. SET_NULL (not CASCADE) because a GameEvent's
    # rewards remain real content even if its banner is later deleted.
    banner_timeline = models.ForeignKey(
        BannerTimeline,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="game_events",
    )

    def __str__(self):
        return str(self.name)

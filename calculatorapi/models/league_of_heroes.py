from django.db import models


class LeagueOfHeroes(models.Model):
    name = models.CharField(max_length=255)
    # JP server dates: always known well in advance (JP runs content first).
    # Nullable so historical rows migrated from the old schema (which only had
    # confirmed global dates) can be backfilled gradually in the admin.
    jp_start_date = models.DateTimeField(blank=True, null=True)
    jp_end_date = models.DateTimeField(blank=True, null=True)
    # Global server dates: only filled once the event is officially confirmed
    # (~1 month out). When null, the global dates are predicted from the JP
    # dates (see calculatorapi/predictions.py).
    global_start_date = models.DateTimeField(blank=True, null=True)
    global_end_date = models.DateTimeField(blank=True, null=True)
    # Manual correction to the JP-based prediction, for when global slips its
    # schedule. Pushes this row AND every dated row after it (banners, Champions
    # Meetings and League of Heroes alike) forward by this many days; offsets
    # stack. Ignored entirely once this row's global dates are confirmed — see
    # calculatorapi/predictions.py.
    schedule_offset_days = models.IntegerField(
        default=0,
        blank=True,
        verbose_name="schedule offset (days)",
        help_text="Days to push this and every later date forward. Leave at 0 unless "
                  "global has slipped its schedule. Ignored once global dates are confirmed.",
    )
    image = models.ImageField(upload_to="league_of_heroes/", blank=True, null=True)

    class Meta:
        # Fixes the auto-generated plural "league of heroess".
        verbose_name = "League of Heroes event"
        verbose_name_plural = "League of Heroes events"

    def __str__(self):
        return str(self.name)

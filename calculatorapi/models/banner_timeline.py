from django.db import models


class BannerCategory(models.TextChoices):
    """What kind of banner window this is.

    Mirrors the "Banner Type" column (BC) of the source Google Sheet's Timeline
    tab, so the two can be diffed when auditing parity. The sheet's codes map:

        1  -> STANDARD              105 rows
        2  -> RACE_PREP_SUPPORT      32 rows
       -2  -> GOLDEN_WEEK_REVIVAL     4 rows
        0  -> RERUN                   2 rows
       -1  -> (no member)            46 rows

    Sheet code -1 deliberately has no member here: those rows are Champions
    Meetings and Leagues of Heroes, which are their own models on our side and
    never become BannerTimeline rows. A parity harness has to know that or it
    will report 46 phantom missing banners.

    NOTE the name. Elsewhere in the codebase "banner type" already means
    Uma-vs-Support (`initialBannerType`, `bannerKey(bannerType, id)`, the
    `banner-type-tab--uma` CSS class). This is a different axis entirely, so it
    is "category" to keep the two from colliding in the same component.
    """

    STANDARD = "standard", "Standard"
    RACE_PREP_SUPPORT = "race_prep_support", "Race prep support rerun"
    GOLDEN_WEEK_REVIVAL = "golden_week_revival", "Golden Week revival"
    RERUN = "rerun", "Rerun"


class BannerTimeline(models.Model):
    name = models.CharField(max_length=255)
    # Presentation and filtering only — nothing in the projection math reads
    # this. The timeline card keys its chrome (accent, label, column layout) off
    # the category, but how many tiles fit per row stays derived from the actual
    # card count, so a miscategorised row still renders every card it has.
    banner_category = models.CharField(
        max_length=32,
        choices=BannerCategory.choices,
        default=BannerCategory.STANDARD,
        help_text="What kind of banner window this is. Drives the timeline "
                  "card's layout and the category filter. Leave as Standard "
                  "unless this is a revival, a rerun, or a race-prep support batch.",
    )
    # JP server dates: always known well in advance (JP runs banners first).
    # Nullable so historical rows migrated from the old schema (which only had
    # confirmed global dates) can be backfilled gradually in the admin.
    jp_start_date = models.DateTimeField(blank=True, null=True)
    jp_end_date = models.DateTimeField(blank=True, null=True)
    # Global server dates: only filled once the banner is officially confirmed
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
    image = models.ImageField(upload_to="banner_timelines/", blank=True, null=True)

    def __str__(self):
        return str(self.name) if self.name else "Unnamed Timeline"

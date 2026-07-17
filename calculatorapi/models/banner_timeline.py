from django.db import models

class BannerTimeline(models.Model):
    name = models.CharField(max_length=255)
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
    image = models.ImageField(upload_to="banner_timelines/", blank=True, null=True)

    def __str__(self):
        return str(self.name) if self.name else "Unnamed Timeline"

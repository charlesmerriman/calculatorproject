from django.db import models
from .banner_timeline import BannerTimeline
from .uma import Uma


class BannerUma(models.Model):
    banner_timeline = models.ForeignKey(BannerTimeline, on_delete=models.CASCADE, related_name="uma_banners")
    name = models.CharField(max_length=255, null=False)
    umas = models.ManyToManyField(
        Uma, through="UmasOnUmaBanner"
    )
    admin_comments = models.TextField(blank=True, null=True, help_text="Notes for editors.")
    free_pulls = models.IntegerField(
        default=0,
        help_text="Free pulls players get on this banner — the calculator counts these toward affordability.",
    )

    class Meta:
        # Default would be "banner uma / banner umas" — confusing for editors.
        verbose_name = "uma banner"
        verbose_name_plural = "uma banners"

    def __str__(self):
        return str(self.name)

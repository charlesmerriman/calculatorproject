from django.db import models
from .banner_uma import BannerUma
from .uma import Uma


class UmasOnUmaBanner(models.Model):
    banner_uma = models.ForeignKey(BannerUma, on_delete=models.CASCADE)
    uma = models.ForeignKey(Uma, on_delete=models.CASCADE)
    recommendation = models.TextField(
        blank=True,
        null=True,
        help_text="Optional recommendation text for this uma on this banner.",
    )

    class Meta:
        # Shown as the inline section title on the uma banner edit page.
        verbose_name = "uma on banner"
        verbose_name_plural = "umas on banner"

    def __str__(self):
        return f"{self.uma.name} on {self.banner_uma.name}"

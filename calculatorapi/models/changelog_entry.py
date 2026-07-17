from django.db import models

class ChangelogEntry(models.Model):
    title = models.CharField(max_length=255, null=False)
    # Optional short version label (e.g. "v1.2"); shown as a badge when filled.
    version = models.CharField(max_length=50, blank=True)
    # A patch note is a whole-day event, so a plain date is enough.
    date = models.DateField()

    class Meta:
        # Proper-noun casing (default capfirst would render "Changelog entrys").
        verbose_name = "Changelog Entry"
        verbose_name_plural = "Changelog Entries"

    def __str__(self):
        return str(self.title)

from django.db import models

class ChangelogEntry(models.Model):
    title = models.CharField(max_length=255, null=False)
    # Optional short version label (e.g. "v1.2"); shown as a badge when filled.
    version = models.CharField(max_length=50, blank=True)
    # A patch note is a whole-day event, so a plain date is enough.
    date = models.DateField()
    # Stable identifier for entries authored in calculatorapi/data/changelog.yaml
    # and written by `manage.py sync_changelog`. Entries created by hand in the
    # admin leave it empty and are never touched by that command.
    #
    # NULL rather than "" for those: `unique` permits any number of NULLs but
    # only one empty string, so a blank default would turn the SECOND
    # hand-written entry into an IntegrityError. See save() below.
    key = models.SlugField(
        max_length=100, unique=True, null=True, blank=True,
        help_text=(
            "Leave blank. A key means this entry is written in the repository "
            "(calculatorapi/data/changelog.yaml) and edits made here are replaced "
            "on the next deploy — edit the file instead."
        ),
    )

    class Meta:
        # Proper-noun casing (default capfirst would render "Changelog entrys").
        verbose_name = "Changelog Entry"
        verbose_name_plural = "Changelog Entries"

    def save(self, *args, **kwargs):
        # A blank admin field submits "", which the unique constraint allows
        # exactly once. Normalise it to NULL here rather than on the form, so
        # every write path — admin, shell, tests, sync_changelog — agrees.
        if not self.key:
            self.key = None
        return super().save(*args, **kwargs)

    def __str__(self):
        return str(self.title)

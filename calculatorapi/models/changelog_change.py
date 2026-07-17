from django.db import models
from .changelog_entry import ChangelogEntry

class ChangelogChange(models.Model):
    # The three kinds of change a patch note line can describe.
    ADDED = "added"
    FIXED = "fixed"
    CHANGED = "changed"
    CATEGORY_CHOICES = [
        (ADDED, "Added"),
        (FIXED, "Fixed"),
        (CHANGED, "Changed"),
    ]

    entry = models.ForeignKey(
        ChangelogEntry, on_delete=models.CASCADE, related_name="changes"
    )
    category = models.CharField(
        max_length=10, choices=CATEGORY_CHOICES, default=CHANGED
    )
    text = models.CharField(max_length=500, null=False)
    # Manual display order within an entry (lower shows first).
    order = models.PositiveIntegerField(default=0)

    class Meta:
        # Children have no view of their own, so ordering lives here — this is
        # what makes the nested serializer emit changes in author-set order.
        ordering = ("order", "id")

    def __str__(self):
        return f"{self.get_category_display()}: {self.text}"

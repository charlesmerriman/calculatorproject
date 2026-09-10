from django.db import models

class Uma(models.Model):
    name = models.CharField(max_length=255)
    image = models.ImageField(upload_to="umas/", blank=True, null=True)
    admin_comments = models.TextField(blank=True, null=True, help_text="Notes for editors.")

    # PUBLIC, and rendered -- unlike admin_comments above, which nothing on the
    # site displays. Shown as an overlay when a player hovers or focuses the uma's
    # art on the Timeline. It describes the uma itself ("Great pace parent"), so it
    # reads the same on every banner; advice about one particular banner belongs
    # on the UmasOnUmaBanner.recommendation junction instead.
    #
    # Capped at 100 because the overlay has to fit the narrowest tile the Timeline
    # draws. CharField rather than TextField so the admin form and the column both
    # enforce the cap; default "" rather than null so "no purpose" has exactly one
    # representation.
    purpose = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text=(
            "Shown publicly when a player hovers this uma's art on the Timeline, "
            "e.g. \"Great pace parent.\" Leave blank to show nothing. Notes for "
            "other editors go in Admin comments instead."
        ),
    )

    # Two INTRINSIC selector gates, stored because neither is derivable from
    # banner data: a time-limited unit and a non-★3 unit both appear on ordinary
    # banners and look exactly like a selectable unit from here. They are
    # independent of the JP cutoff and bite even under an unrestricted (null)
    # one -- see calculatorapi/eligibility.py.
    is_time_limited = models.BooleanField(
        default=False,
        help_text=(
            "Only obtainable during a limited window, so selector tickets and "
            "step-ups can never take them. Hides this uma from every selector "
            "picker and stops a selector funding a banner it is featured on."
        ),
    )
    is_three_star = models.BooleanField(
        default=True,
        verbose_name="Is ★3",
        help_text=(
            "Uncheck for ★1/★2 units. Selectors and step-ups only grant ★3 "
            "umas, so anything unchecked here is hidden from the pickers."
        ),
    )

    def __str__(self):
        return f"{self.name}"

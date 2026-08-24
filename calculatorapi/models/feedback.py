from django.db import models


class FeedbackCategory(models.TextChoices):
    """What kind of report this is.

    Stored as a short slug so the frontend's <select> and the admin filter can
    share one vocabulary. DATA exists separately from BUG because a wrong banner
    date is fixed in the admin panel, not in code — different queue, different
    person, and worth being able to filter for.
    """

    BUG = "bug", "Bug"
    FEATURE = "feature", "Feature idea"
    DATA = "data", "Data correction"
    OTHER = "other", "Other"


# Generous enough for a detailed bug report, bounded so a single POST cannot
# push an unbounded blob into the database. Enforced on the serializer too, so
# an over-long body is a clean 400 rather than a database error.
MESSAGE_MAX_LENGTH = 4000


class Feedback(models.Model):
    """One message submitted through the public /feedback form.

    Deliberately holds NO IP address. The privacy policy states that a visitor's
    IP is never stored, and that promise is site-wide, not scoped to the traffic
    beacon. Abuse is handled by rate limiting instead (views/feedback.py), which
    reads the address without persisting it.

    Also holds no contact details: the form has no email field, so a submission
    is one-way by design. If a message body happens to contain an address the
    sender typed themselves, it lives in `message` like any other text — see the
    "Feedback you send us" section of the privacy policy.
    """

    category = models.CharField(
        max_length=20,
        choices=FeedbackCategory.choices,
        default=FeedbackCategory.OTHER,
    )
    message = models.TextField(max_length=MESSAGE_MAX_LENGTH)

    # Null for guests, who are the majority — the whole site works signed out,
    # and someone reporting a bug is not going to make an account first.
    #
    # SET_NULL rather than CASCADE is load-bearing: purge_user_pii is
    # IRREVERSIBLE and is meant to be run against production. Under CASCADE,
    # stripping PII from accounts would also delete every report those accounts
    # ever filed — silent data loss, months after the code was written. This
    # keeps the report and drops only the linkage.
    user = models.ForeignKey(
        "calculatorapi.CustomUser",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="feedback",
    )

    # Which page the sender was on. Free text rather than a choices field: the
    # route set changes without a migration, and this is a debugging hint, not
    # data anything branches on.
    source_path = models.CharField(max_length=200, blank=True)

    submitted_at = models.DateTimeField(auto_now_add=True)

    # Triage flag — the only field the admin lets you edit. See FeedbackAdmin.
    is_resolved = models.BooleanField(default=False)

    class Meta:
        verbose_name = "Feedback"
        # Default capfirst would render "Feedbacks".
        verbose_name_plural = "Feedback"
        ordering = ("-submitted_at",)

    def __str__(self):
        # Enough to identify a row in the admin's change list and history
        # entries without dumping the whole message.
        preview = self.message[:60]
        suffix = "…" if len(self.message) > 60 else ""
        return f"{self.get_category_display()}: {preview}{suffix}"

from django.db import models
from .custom_user import CustomUser


class SocialAccount(models.Model):
    """Links a CustomUser to an identity held at Google or Discord.

    This is the whole personal footprint of a non-staff account. Sign-in goes
    through the provider (see calculatorapi/oauth.py), which verifies the
    password on their side and hands us back one opaque number. We deliberately
    request the narrowest scope each provider allows -- "openid" for Google,
    "identify" for Discord -- so no email address or display name is ever sent
    to us, and therefore none can be stored here by accident.
    """

    PROVIDER_GOOGLE = "google"
    PROVIDER_DISCORD = "discord"
    PROVIDER_CHOICES = [
        (PROVIDER_GOOGLE, "Google"),
        (PROVIDER_DISCORD, "Discord"),
    ]

    user = models.ForeignKey(
        CustomUser,
        on_delete=models.CASCADE,
        # A FK (rather than columns on CustomUser) costs nothing now and leaves
        # room to let one user link both Google and Discord later without a
        # migration. Today the sign-in view only ever creates one row per user.
        related_name="social_accounts",
    )
    provider = models.CharField(max_length=20, choices=PROVIDER_CHOICES)
    # The provider's permanent, opaque id for this person: Google's `sub` claim
    # or Discord's user `id`. Stable across sign-ins (that is what makes a
    # returning user resolve to the same account) and scoped to our app, so it
    # cannot be cross-referenced against any other service. Stored raw rather
    # than hashed: it identifies nobody without the provider's own database,
    # and hashing would strand every account if DJANGO_SECRET_KEY ever rotated.
    # 255 chars because OpenID Connect permits a `sub` up to that length, though
    # Google's are ~21 digits and Discord's snowflakes ~19.
    subject_id = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    last_login_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Social Account"
        verbose_name_plural = "Social Accounts"
        constraints = [
            # Enforces "same provider account -> same user" in the database
            # rather than trusting the view's get_or_create to race correctly.
            # Scoped to (provider, subject_id) because ids are only unique
            # within a provider -- Google and Discord could collide otherwise.
            models.UniqueConstraint(
                fields=["provider", "subject_id"],
                name="unique_provider_subject",
            )
        ]

    def __str__(self):
        # Deliberately renders the generated handle and provider only -- never
        # subject_id, so it cannot leak into admin logs or error messages.
        return f"{self.user.username} - {self.get_provider_display()}"

"""OAuth credentials for the Patreon API sync, in one row.

WHY THESE LIVE IN THE DATABASE AND NOT IN THE ENVIRONMENT
---------------------------------------------------------
Patreon's creator access tokens expire (roughly monthly), and refreshing one
returns a NEW refresh token as well as a new access token — the old refresh
token is spent. So the credential pair is mutable state, not configuration, and
it has to be written somewhere the running process can write to. App Platform
env vars are set at deploy time and are read-only at runtime, which rules them
out as the store.

The client id and secret DO stay in the environment: those are configuration,
they never rotate on their own, and they are the half that must not be readable
from the database if the database is ever dumped.

BOOTSTRAP
---------
`load()` falls back to PATREON_ACCESS_TOKEN / PATREON_REFRESH_TOKEN when the row
is empty, then persists them. That is what lets production seed itself on its
first sync: the production database has no external endpoint, so the only other
way to get an initial token into it is the POST_DEPLOY job recipe in
backend/.do/app.yaml. After the first refresh the environment values are stale
and ignored — the row is authoritative from then on.

NOT REGISTERED IN THE ADMIN, DELIBERATELY
-----------------------------------------
A live API token has no business being rendered into a web page, and there is
nothing here an editor would ever need to change by hand. Leaving the model
unregistered also means there is no sidebar entry to add and no content-editor
permission to reason about — see backend/docs/admin.md.

PRIVACY
-------
Holds no member data. `last_sync_error` stores our own diagnostic message, never
a response body, so a Patreon error can't smuggle member details into this row.
"""

import os
from datetime import timedelta

from django.db import models
from django.utils import timezone


class PatreonCredentials(models.Model):
    """The one row (always pk=1) holding the current Patreon token pair."""

    access_token = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Current Patreon access token. Rotated automatically; do not edit.",
    )
    refresh_token = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Used to mint the next access token. Single-use — rotated on every refresh.",
    )
    expires_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the current access token stops working.",
    )
    # Looked up once from GET /campaigns and then kept, because it never changes
    # for a given creator and there is no reason to spend a request on it daily.
    campaign_id = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="Resolved from the API on first use and cached here.",
    )
    last_synced_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Last time a sync completed and wrote changes.",
    )
    # Cleared on every success, so a non-empty value always describes the most
    # recent run rather than something that was fixed three weeks ago.
    last_sync_error = models.TextField(
        blank=True,
        default="",
        help_text="Message from the last failed sync. Cleared when one succeeds.",
    )

    class Meta:
        verbose_name = "Patreon credentials"
        verbose_name_plural = "Patreon credentials"

    def __str__(self):
        return "Patreon credentials"

    def save(self, *args, **kwargs):
        # Pin the pk so a second row can never exist, even from the shell.
        self.pk = 1
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        """Refused. Deleting the row would have `load()` recreate it from the
        environment, silently reverting to a refresh token that was already
        spent — which fails in a way that looks like Patreon's fault."""

    @classmethod
    def load(cls):
        """The one row, seeded from the environment on first access.

        The environment is read ONLY to fill an empty row. Once a token pair is
        stored, later env values are ignored: after the first refresh they are
        stale by definition, and honouring them would resurrect a spent token.
        """
        instance, _ = cls.objects.get_or_create(pk=1)
        if not instance.refresh_token:
            env_access = os.getenv("PATREON_ACCESS_TOKEN", "").strip()
            env_refresh = os.getenv("PATREON_REFRESH_TOKEN", "").strip()
            if env_refresh:
                instance.access_token = env_access
                instance.refresh_token = env_refresh
                # No expiry known for a token pasted in from the portal. Left
                # null, which `token_is_stale` treats as "refresh before use" —
                # the safe reading, since a token of unknown age may be spent.
                instance.expires_at = None
                instance.save(update_fields=["access_token", "refresh_token", "expires_at"])
        return instance

    @property
    def is_configured(self):
        """True when there is something to refresh from."""
        return bool(self.refresh_token)

    def token_is_stale(self, leeway_seconds=86400):
        """Whether the access token should be refreshed before it is used.

        Defaults to a day of leeway. The sync runs daily, so anything expiring
        within that window would expire before the next run anyway, and
        refreshing early costs one request against a limit we are nowhere near.
        An unknown expiry counts as stale.
        """
        if not self.access_token or self.expires_at is None:
            return True
        return self.expires_at <= timezone.now() + timedelta(seconds=leeway_seconds)

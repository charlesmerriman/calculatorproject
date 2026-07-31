"""
Strips personal data from non-staff accounts.

Ordinary accounts now sign in through Google/Discord and store nothing but an
opaque provider id (see models/social_account.py). This command retires the
personal data collected by the old password-based sign-up, so the promise holds
for rows that already exist rather than only for new ones.

For every user with is_staff=False it:
  - blanks email / first_name / last_name
  - replaces the password hash with Django's unusable-password marker
  - deletes their API token, so any key still sitting in a browser's
    localStorage stops working immediately

Staff accounts are untouched — they still sign in with a password to reach
/admin and the analytics dashboard.

IRREVERSIBLE. There is no backup of the blanked values, and afterwards those
accounts cannot be logged into at all (their plans stay in the database but
become unreachable). This is the accepted consequence of the migration; see
the project plan.

Usage:
    python manage.py purge_user_pii --dry-run   # report only, changes nothing
    python manage.py purge_user_pii             # prompts for confirmation
    python manage.py purge_user_pii --no-input  # for scripted/CI runs

Run it ONCE in production (DigitalOcean API component's Console tab) after the
social-login deploy has gone out and been verified.
"""

from django.core.management.base import BaseCommand
from django.db import transaction
from rest_framework.authtoken.models import Token

from calculatorapi.models import CustomUser

CONFIRM_PHRASE = "purge"

# Blanked rather than nulled: AbstractUser declares these as non-null CharFields
# with blank=True, so "" is the correct empty value.
PII_FIELDS = ["email", "first_name", "last_name"]


class Command(BaseCommand):
    help = "Blank email/name/password on all non-staff accounts (irreversible)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would change without writing anything.",
        )
        parser.add_argument(
            "--no-input",
            action="store_true",
            help="Skip the confirmation prompt (for scripted runs).",
        )

    def handle(self, *args, **options):
        targets = CustomUser.objects.filter(is_staff=False)
        total = targets.count()

        if not total:
            self.stdout.write(self.style.SUCCESS("No non-staff accounts found; nothing to do."))
            return

        # Counted before the write so the summary can show what was actually
        # holding data, not just how many rows were touched.
        with_pii = targets.exclude(email="", first_name="", last_name="").count()
        with_password = sum(1 for user in targets.only("password") if user.has_usable_password())
        token_count = Token.objects.filter(user__in=targets).count()

        self.stdout.write(f"Non-staff accounts:        {total}")
        self.stdout.write(f"  holding email/name:      {with_pii}")
        self.stdout.write(f"  holding a usable password: {with_password}")
        self.stdout.write(f"  API tokens to delete:    {token_count}")
        self.stdout.write(
            self.style.WARNING(
                f"Staff accounts left untouched: {CustomUser.objects.filter(is_staff=True).count()}"
            )
        )

        if options["dry_run"]:
            self.stdout.write(self.style.SUCCESS("\nDry run — no changes written."))
            return

        if not options["no_input"]:
            self.stdout.write(self.style.ERROR(
                "\nThis cannot be undone. Affected accounts will no longer be able to sign in."
            ))
            answer = input(f'Type "{CONFIRM_PHRASE}" to continue: ')
            if answer.strip() != CONFIRM_PHRASE:
                self.stdout.write(self.style.WARNING("Aborted; nothing was changed."))
                return

        # One transaction so a failure part-way through cannot leave some rows
        # scrubbed and others still holding data.
        with transaction.atomic():
            # Tokens go first: if the run fails after this point the worst case
            # is that people are signed out, not that stale keys survive a
            # partial scrub.
            Token.objects.filter(user__in=targets).delete()

            users = list(targets)
            for user in users:
                user.email = ""
                user.first_name = ""
                user.last_name = ""
                # Writes the "!" marker; check_password() then rejects every
                # input, including "!" itself.
                user.set_unusable_password()

            CustomUser.objects.bulk_update(users, PII_FIELDS + ["password"])

        self.stdout.write(self.style.SUCCESS(
            f"\nPurged {len(users)} account(s) and deleted {token_count} token(s)."
        ))

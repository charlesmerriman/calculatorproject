"""The Patreon supporter roster: CSV import, row matching, tier order, and the public list."""

import datetime
from io import StringIO

from django.db import IntegrityError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from calculatorapi.admin_patreon_import import apply_patreon_import, parse_patreon_csv
from calculatorapi.models import PatreonTier, PatreonSupporter
from calculatorapi.tests.base import CalculatorTestCase, PLAIN_TEST_STORAGES
from calculatorapi.tests.factories import make_ranks, make_user


# A cut-down copy of a real Patreon members export: the same header row, and
# rows carrying the PII columns the importer must ignore. Kept verbatim rather
# than trimmed so a future header change in Patreon's export breaks a test here
# rather than silently importing nothing.
PATREON_CSV_HEADER = (
    "Name,Email,Discord,Patron Status,Follows You,Free Member,Free Trial,"
    "Lifetime Amount,Pledge Amount,Charge Frequency,Tier,Addressee,Street,City,"
    "State,Zip,Country,Phone,Patronage Since Date,Last Charge Date,"
    "Last Charge Status,Additional Details,User ID,Last Updated,Currency,"
    "Max Posts,Access Expiration,Next Charge Date,Full country name,"
    "Subscription Source"
)


def patreon_csv(*rows):
    """Build an uploadable members CSV from (name, email, discord, status, tier) tuples."""
    lines = [PATREON_CSV_HEADER]
    for name, email, discord, status, tier in rows:
        lines.append(
            f"{name},{email},{discord},{status},No,No,No,2.99,2.99,monthly,{tier},"
            ",,,,,,,2026-08-10 13:37:12,2026-08-10 13:37:14,Paid,,12345678,"
            "2026-08-10 15:52:24,USD,,,2026-09-11 00:00:00,,Patreon"
        )
    return SimpleUploadedFile(
        "members.csv", ("\n".join(lines) + "\n").encode("utf-8"), content_type="text/csv"
    )


class PatreonSupporterEndpointTests(CalculatorTestCase):
    """GET /supporters — what the public thank-you list is allowed to expose."""

    def setUp(self):
        self.client = APIClient()
        self.junior = PatreonTier.objects.create(name="Junior Class", order=10)
        self.classic = PatreonTier.objects.create(name="Classic Class", order=20)

    def test_lists_only_public_active_supporters(self):
        PatreonSupporter.objects.create(
            display_name="Rhondal", tier=self.junior, is_public=True, is_active=True)
        PatreonSupporter.objects.create(
            display_name="Consented but lapsed", tier=self.junior,
            is_public=True, is_active=False)
        PatreonSupporter.objects.create(
            display_name="Jonathan Reyes", tier=self.classic,
            is_public=False, is_active=True)

        response = self.client.get("/supporters")
        self.assertEqual(response.status_code, 200)
        names = [row["display_name"] for row in response.data["supporters"]]
        self.assertEqual(names, ["Rhondal"])

    def test_anonymous_count_covers_active_unpublished_only(self):
        PatreonSupporter.objects.create(
            display_name="Shown", tier=self.junior, is_public=True, is_active=True)
        PatreonSupporter.objects.create(
            display_name="Hidden A", tier=self.junior, is_public=False, is_active=True)
        PatreonSupporter.objects.create(
            display_name="Hidden B", tier=self.classic, is_public=False, is_active=True)
        # Lapsed and unpublished: gone entirely, not counted.
        PatreonSupporter.objects.create(
            display_name="Hidden lapsed", is_public=False, is_active=False)

        response = self.client.get("/supporters")
        self.assertEqual(response.data["anonymous_count"], 2)

    def test_response_never_carries_editorial_or_private_fields(self):
        PatreonSupporter.objects.create(
            display_name="Rhondal", tier=self.junior, is_public=True,
            is_active=True, patron_since=datetime.date(2025, 1, 1))

        response = self.client.get("/supporters")
        row = response.data["supporters"][0]
        self.assertEqual(set(row), {"id", "display_name", "tier_name", "tier_order"})

    def test_email_never_reaches_the_public_endpoint(self):
        """The one that matters: this route is public and unauthenticated.

        The email is stored so the ADMIN can tell supporters apart. Serializing
        it here would publish the address of every consenting supporter to
        anyone who loads the home page, so it is asserted on its own rather than
        left to the field-set check above.
        """
        PatreonSupporter.objects.create(
            display_name="Rhondal", tier=self.junior, is_public=True,
            is_active=True, email="rtibplays@gmail.com")

        response = self.client.get("/supporters")
        self.assertNotIn("email", response.data["supporters"][0])
        self.assertNotIn(b"rtibplays", response.content)

    def test_public_endpoint_needs_no_auth_and_has_no_write_actions(self):
        response = self.client.get("/supporters")
        self.assertEqual(response.status_code, 200)
        # SimpleRouter only routes actions the viewset defines; with no create()
        # the list URL must reject POST at the router level.
        self.assertEqual(self.client.post("/supporters", {}, format="json").status_code, 405)

    def test_supporter_with_no_tier_serializes_null_tier_fields(self):
        PatreonSupporter.objects.create(display_name="Untiered", is_public=True, is_active=True)
        response = self.client.get("/supporters")
        row = response.data["supporters"][0]
        self.assertIsNone(row["tier_name"])
        self.assertIsNone(row["tier_order"])

    def test_duplicate_display_names_are_rejected_case_insensitively(self):
        PatreonSupporter.objects.create(display_name="Rhondal")
        with self.assertRaises(IntegrityError):
            PatreonSupporter.objects.create(display_name="rhondal")


class PatreonCsvImportTests(CalculatorTestCase):
    """The importer's two jobs: reconcile the roster, and touch nothing else."""

    def test_parse_reads_only_name_email_tier_and_status(self):
        upload = patreon_csv(
            ("Rhondal", "rtibplays@gmail.com", "rhondal", "Active patron", "Junior Class"),
        )
        rows = parse_patreon_csv(upload)
        self.assertEqual(rows, [{
            "display_name": "Rhondal",
            # Always "" from a CSV, even when the export carries a User ID
            # column — see test_the_csv_parser_never_produces_an_id.
            "patreon_user_id": "",
            "email": "rtibplays@gmail.com",
            "tier_name": "Junior Class",
            "is_active": True,
        }])

    def test_import_stores_the_email_and_nothing_else_from_the_csv(self):
        """Email in, everything else out — the boundary, in one test.

        Email is deliberately kept (it is what tells two supporters apart in the
        admin). The Discord handle beside it in the export, and every billing
        column after it, must still never land — including via a stray field
        added later, hence checking every value rather than a named list.
        """
        email = "rtibplays@gmail.com"
        # A Discord handle that is not a substring of the name or the email, so
        # "it wasn't stored" is actually provable.
        upload = patreon_csv(
            ("Rhondal", email, "dsc_handle_7", "Active patron", "Junior Class"))
        apply_patreon_import(parse_patreon_csv(upload))

        supporter = PatreonSupporter.objects.get(display_name="Rhondal")
        self.assertEqual(supporter.email, email)

        # Every OTHER value on the row, so a stray field added later fails here.
        stored = " ".join(
            str(value)
            for key, value in supporter.__dict__.items()
            if key != "email"
        )
        self.assertNotIn(email, stored)
        self.assertNotIn("dsc_handle_7", stored)
        for billing_value in ("2.99", "12345678", "monthly", "USD"):
            self.assertNotIn(billing_value, stored)

    def test_import_without_an_email_column_still_works(self):
        """An export predating the column, or one trimmed by hand, must import."""
        # Dropping a column shifts every value after it, so the row is built
        # against the trimmed header by name rather than reusing patreon_csv().
        columns = [c for c in PATREON_CSV_HEADER.split(",") if c != "Email"]
        record = dict.fromkeys(columns, "")
        record["Name"] = "Rhondal"
        record["Patron Status"] = "Active patron"
        record["Tier"] = "Junior Class"
        upload = SimpleUploadedFile(
            "members.csv",
            (",".join(columns) + "\n"
             + ",".join(record[column] for column in columns) + "\n").encode("utf-8"),
            content_type="text/csv",
        )

        apply_patreon_import(parse_patreon_csv(upload))
        self.assertEqual(PatreonSupporter.objects.get(display_name="Rhondal").email, "")

    def test_reimport_updates_a_changed_email(self):
        apply_patreon_import(parse_patreon_csv(patreon_csv(
            ("Rhondal", "old@example.com", "", "Active patron", "Junior Class"))))
        apply_patreon_import(parse_patreon_csv(patreon_csv(
            ("Rhondal", "new@example.com", "", "Active patron", "Junior Class"))))

        supporter = PatreonSupporter.objects.get(display_name="Rhondal")
        self.assertEqual(supporter.email, "new@example.com")

    def test_reimport_without_an_email_keeps_the_stored_one(self):
        """An empty incoming value means "don't know", never "clear it"."""
        apply_patreon_import(parse_patreon_csv(patreon_csv(
            ("Rhondal", "keep@example.com", "", "Active patron", "Junior Class"))))
        apply_patreon_import(parse_patreon_csv(patreon_csv(
            ("Rhondal", "", "", "Active patron", "Junior Class"))))

        supporter = PatreonSupporter.objects.get(display_name="Rhondal")
        self.assertEqual(supporter.email, "keep@example.com")

    def test_import_never_publishes_a_name(self):
        upload = patreon_csv(
            ("Jonathan Reyes", "j@example.com", "", "Active patron", "Junior Class"))
        apply_patreon_import(parse_patreon_csv(upload))
        self.assertFalse(PatreonSupporter.objects.get(display_name="Jonathan Reyes").is_public)

    def test_reimport_preserves_an_editors_publish_decision(self):
        tier = PatreonTier.objects.create(name="Junior Class", order=10)
        PatreonSupporter.objects.create(
            display_name="Rhondal", tier=tier, is_public=True, is_active=True)

        upload = patreon_csv(("Rhondal", "r@example.com", "", "Active patron", "Junior Class"))
        apply_patreon_import(parse_patreon_csv(upload))

        self.assertTrue(PatreonSupporter.objects.get(display_name="Rhondal").is_public)
        self.assertEqual(PatreonSupporter.objects.count(), 1)

    def test_matching_is_case_insensitive_so_reimport_does_not_duplicate(self):
        PatreonSupporter.objects.create(display_name="rhondal")
        upload = patreon_csv(("Rhondal", "r@example.com", "", "Active patron", "Junior Class"))
        apply_patreon_import(parse_patreon_csv(upload))
        self.assertEqual(PatreonSupporter.objects.count(), 1)

    def test_former_patron_row_lands_inactive(self):
        upload = patreon_csv(("Gone", "g@example.com", "", "Former patron", "Junior Class"))
        apply_patreon_import(parse_patreon_csv(upload))
        self.assertFalse(PatreonSupporter.objects.get(display_name="Gone").is_active)

    def test_a_csv_import_leaves_patron_since_alone(self):
        """The CSV has no pledge-start column, so its rows omit the key entirely.

        The reconcile is shared with the API sync, which does supply one — a row
        without it must mean "don't know", never "clear it".
        """
        tier = PatreonTier.objects.create(name="Junior Class", order=10)
        PatreonSupporter.objects.create(
            display_name="Rhondal", tier=tier, patron_since=datetime.date(2024, 1, 1))

        upload = patreon_csv(("Rhondal", "r@example.com", "", "Active patron", "Junior Class"))
        apply_patreon_import(parse_patreon_csv(upload))

        self.assertEqual(
            PatreonSupporter.objects.get(display_name="Rhondal").patron_since,
            datetime.date(2024, 1, 1),
        )

    def test_missing_supporters_survive_unless_deactivate_is_requested(self):
        PatreonSupporter.objects.create(display_name="Absent", is_active=True)
        upload = patreon_csv(("Present", "p@example.com", "", "Active patron", "Junior Class"))

        apply_patreon_import(parse_patreon_csv(upload))
        self.assertTrue(PatreonSupporter.objects.get(display_name="Absent").is_active)

        upload = patreon_csv(("Present", "p@example.com", "", "Active patron", "Junior Class"))
        summary = apply_patreon_import(parse_patreon_csv(upload), deactivate_missing=True)
        self.assertFalse(PatreonSupporter.objects.get(display_name="Absent").is_active)
        self.assertIn("Absent", summary["deactivated"])

    def test_dry_run_reports_changes_without_writing_any(self):
        upload = patreon_csv(("Rhondal", "r@example.com", "", "Active patron", "Junior Class"))
        summary = apply_patreon_import(parse_patreon_csv(upload), dry_run=True)

        self.assertEqual(summary["created"], ["Rhondal"])
        self.assertEqual(summary["tiers_created"], ["Junior Class"])
        self.assertEqual(PatreonSupporter.objects.count(), 0)
        self.assertEqual(PatreonTier.objects.count(), 0)

    def test_new_tiers_are_created_and_ordered_after_existing_ones(self):
        PatreonTier.objects.create(name="Junior Class", order=10)
        upload = patreon_csv(("Egg", "e@example.com", "", "Active patron", "Senior Class"))
        apply_patreon_import(parse_patreon_csv(upload))

        senior = PatreonTier.objects.get(name="Senior Class")
        self.assertGreater(senior.order, 10)

    def test_a_wrong_file_is_rejected_with_a_readable_message(self):
        upload = SimpleUploadedFile(
            "wrong.csv", b"Foo,Bar\n1,2\n", content_type="text/csv")
        with self.assertRaises(ValueError) as caught:
            parse_patreon_csv(upload)
        self.assertIn("Patron Status", str(caught.exception))

    def test_nameless_rows_are_skipped(self):
        upload = patreon_csv(
            ("", "anon@example.com", "", "Active patron", "Junior Class"),
            ("Named", "n@example.com", "", "Active patron", "Junior Class"),
        )
        rows = parse_patreon_csv(upload)
        self.assertEqual([row["display_name"] for row in rows], ["Named"])


# Renders real admin templates, so it needs the plain static storage — the
# manifest one has no entry for unfold's fonts without a collectstatic.
@override_settings(STORAGES=PLAIN_TEST_STORAGES)
class PatreonImportAdminViewTests(CalculatorTestCase):
    """The admin upload page — permissions and the round trip through the form."""

    def setUp(self):
        make_ranks()
        self.admin = make_user(username="patreonadmin", is_staff=True)
        self.admin.is_superuser = True
        self.admin.save()
        self.url = reverse("admin:calculatorapi_patreonsupporter_import_csv")

    def test_non_staff_cannot_reach_the_import_page(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login", response["Location"])

    def test_upload_creates_supporters_unpublished(self):
        self.client.force_login(self.admin)
        upload = patreon_csv(
            ("Rhondal", "r@example.com", "rhondal", "Active patron", "Junior Class"))
        response = self.client.post(
            self.url, {"csv_file": upload, "dry_run": ""}, follow=True)

        self.assertEqual(response.status_code, 200)
        supporter = PatreonSupporter.objects.get(display_name="Rhondal")
        self.assertFalse(supporter.is_public)
        self.assertEqual(supporter.tier.name, "Junior Class")

    def test_preview_checkbox_writes_nothing(self):
        self.client.force_login(self.admin)
        upload = patreon_csv(("Rhondal", "r@example.com", "", "Active patron", "Junior Class"))
        self.client.post(self.url, {"csv_file": upload, "dry_run": "on"})
        self.assertEqual(PatreonSupporter.objects.count(), 0)


class SetPatreonTierOrderCommandTests(CalculatorTestCase):
    """`set_patreon_tier_order` — the admin-free route to renumbering the ladder.

    It is built to be run as a POST_DEPLOY job against production, where a
    non-zero exit fails the whole deployment, so most of these cases are about
    it REFUSING cleanly rather than raising.
    """

    def setUp(self):
        # The order production actually shipped with: entry tier first, so the
        # home page gave 21 entry-tier supporters the top emphasis and the sole
        # Senior supporter the grey fallback.
        self.junior = PatreonTier.objects.create(name="Junior Class", order=10)
        self.classic = PatreonTier.objects.create(name="Classic Class", order=20)
        self.senior = PatreonTier.objects.create(name="Senior Class", order=30)

    def run_command(self, *args, **kwargs):
        out = StringIO()
        call_command('set_patreon_tier_order', *args, stdout=out, **kwargs)
        return out.getvalue()

    def refresh(self):
        for tier in (self.junior, self.classic, self.senior):
            tier.refresh_from_db()

    def test_reverses_the_ladder(self):
        self.run_command(
            'Senior Class=10', 'Classic Class=20', 'Junior Class=30', no_input=True
        )
        self.refresh()
        self.assertEqual(self.senior.order, 10)
        self.assertEqual(self.classic.order, 20)
        self.assertEqual(self.junior.order, 30)

    def test_matches_tier_names_case_insensitively(self):
        self.run_command('senior class=10', 'JUNIOR CLASS=30', no_input=True)
        self.refresh()
        self.assertEqual(self.senior.order, 10)
        self.assertEqual(self.junior.order, 30)

    def test_dry_run_writes_nothing(self):
        output = self.run_command(
            'Senior Class=10', 'Junior Class=30', '--dry-run'
        )
        self.refresh()
        self.assertEqual(self.senior.order, 30)
        self.assertEqual(self.junior.order, 10)
        self.assertIn('Dry run', output)

    def test_second_run_is_a_no_op(self):
        args = ('Senior Class=10', 'Classic Class=20', 'Junior Class=30')
        self.run_command(*args, no_input=True)
        output = self.run_command(*args, no_input=True)
        self.assertIn('Already in this order', output)

    def test_unnamed_tiers_keep_their_order(self):
        self.run_command('Senior Class=5', no_input=True)
        self.refresh()
        self.assertEqual(self.senior.order, 5)
        self.assertEqual(self.junior.order, 10)
        self.assertEqual(self.classic.order, 20)

    def test_unknown_tier_name_changes_nothing_and_does_not_raise(self):
        # A CommandError here would fail the deployment the job runs in.
        output = self.run_command(
            'Senior Clas=10', 'Junior Class=30', no_input=True
        )
        self.refresh()
        self.assertEqual(self.senior.order, 30)
        self.assertEqual(self.junior.order, 10)
        self.assertIn('No tier named', output)
        self.assertIn('Nothing was changed', output)

    def test_refuses_to_leave_two_tiers_sharing_an_order(self):
        # The frontend groups supporters by tier ORDER, so a collision merges
        # two tiers into one block on the page.
        output = self.run_command('Senior Class=10', no_input=True)
        self.refresh()
        self.assertEqual(self.senior.order, 30)
        self.assertEqual(self.junior.order, 10)
        self.assertIn('share an order number', output)

    def test_rejects_a_malformed_pair(self):
        output = self.run_command('Senior Class', no_input=True)
        self.refresh()
        self.assertEqual(self.senior.order, 30)
        self.assertIn('is not NAME=ORDER', output)

    def test_rejects_a_non_numeric_order(self):
        output = self.run_command('Senior Class=first', no_input=True)
        self.refresh()
        self.assertEqual(self.senior.order, 30)
        self.assertIn('not a whole number', output)

    def test_rejects_an_out_of_range_order(self):
        output = self.run_command('Senior Class=-1', no_input=True)
        self.refresh()
        self.assertEqual(self.senior.order, 30)
        self.assertIn('between 0 and', output)

    def test_reports_nothing_to_do_with_no_tiers_at_all(self):
        PatreonTier.objects.all().delete()
        output = self.run_command('Senior Class=10', no_input=True)
        self.assertIn('No Patreon tiers exist', output)


class PatreonImportMatchingTests(CalculatorTestCase):
    """Which stored row an incoming row is decided to BE."""

    def setUp(self):
        self.tier = PatreonTier.objects.create(name="Junior Class", order=10)

    def _row(self, name, user_id="", tier="Junior Class", active=True):
        return {
            "display_name": name,
            "patreon_user_id": user_id,
            "email": "",
            "tier_name": tier,
            "is_active": active,
        }

    def test_a_rename_updates_the_row_instead_of_adding_one(self):
        """The everyday case the id exists for. Under name matching this made a
        second row and left the first to be deactivated as though they had
        cancelled."""
        PatreonSupporter.objects.create(
            display_name="Old Name", patreon_user_id="7", tier=self.tier)

        apply_patreon_import([self._row("New Name", user_id="7")])

        supporters = PatreonSupporter.objects.all()
        self.assertEqual(supporters.count(), 1)
        # The row is theirs; the NAME is not updated by the reconcile, which
        # only ever touches tier, status, email, date and id.
        self.assertEqual(supporters.first().patreon_user_id, "7")

    def test_two_patrons_sharing_a_name_get_two_rows(self):
        apply_patreon_import([
            self._row("Trainer", user_id="1"),
            self._row("Trainer", user_id="2"),
        ])

        self.assertEqual(PatreonSupporter.objects.filter(display_name="Trainer").count(), 2)

    def test_an_existing_row_adopts_the_id_on_the_first_sync(self):
        """The backfill. No data migration — the first API sync after deploy
        fills the id for everyone Patreon returns, by name, once."""
        PatreonSupporter.objects.create(display_name="Rhondal", tier=self.tier)

        summary = apply_patreon_import([self._row("Rhondal", user_id="7")])

        self.assertEqual(PatreonSupporter.objects.count(), 1)
        self.assertEqual(PatreonSupporter.objects.first().patreon_user_id, "7")
        self.assertEqual(summary["ids_filled"], ["Rhondal"])

    def test_an_id_is_never_overwritten(self):
        """Fill-only, like `patron_since` — but load-bearing rather than
        courteous. Overwriting would let a name collision move one patron's
        entitlement onto another patron's row."""
        PatreonSupporter.objects.create(
            display_name="Rhondal", patreon_user_id="7", tier=self.tier)

        apply_patreon_import([self._row("Rhondal", user_id="8")])

        stored = {s.patreon_user_id for s in PatreonSupporter.objects.all()}
        # "8" is a different person who shares the name, so they get their own
        # row; "7" keeps the id they had.
        self.assertEqual(stored, {"7", "8"})

    def test_a_csv_row_updates_the_row_the_api_created(self):
        """A CSV re-import of someone the API already knows must not duplicate
        them just because the file carries no id."""
        PatreonSupporter.objects.create(
            display_name="Rhondal", patreon_user_id="7", tier=self.tier, is_active=False)

        apply_patreon_import([self._row("Rhondal", active=True)])

        self.assertEqual(PatreonSupporter.objects.count(), 1)
        self.assertTrue(PatreonSupporter.objects.first().is_active)

    def test_an_idless_row_matching_two_names_is_refused_not_guessed(self):
        """The one case where acting could move a pledge onto the wrong person.

        Nothing is written and the summary says so, rather than the import
        picking whichever row it happened to read last.
        """
        PatreonSupporter.objects.create(
            display_name="Trainer", patreon_user_id="1", tier=self.tier, is_active=True)
        PatreonSupporter.objects.create(
            display_name="Trainer", patreon_user_id="2", tier=self.tier, is_active=True)

        summary = apply_patreon_import([self._row("Trainer", active=False)])

        self.assertEqual(summary["ambiguous"], ["Trainer"])
        self.assertEqual(PatreonSupporter.objects.filter(is_active=True).count(), 2)

    def test_deactivate_missing_retires_by_row_not_by_name(self):
        PatreonSupporter.objects.create(
            display_name="Trainer", patreon_user_id="1", tier=self.tier)
        PatreonSupporter.objects.create(
            display_name="Trainer", patreon_user_id="2", tier=self.tier)

        apply_patreon_import([self._row("Trainer", user_id="1")], deactivate_missing=True)

        by_id = {s.patreon_user_id: s.is_active for s in PatreonSupporter.objects.all()}
        self.assertEqual(by_id, {"1": True, "2": False})

    def test_the_csv_parser_never_produces_an_id(self):
        """The export HAS a User ID column. Reading it would make the wide,
        PII-heavy file the source of a field entitlement depends on."""
        csv_text = (
            "Name,Email,Tier,Patron Status,User ID\n"
            "Rhondal,r@example.com,Junior Class,Active patron,999\n"
        )
        rows = parse_patreon_csv(
            SimpleUploadedFile("members.csv", csv_text.encode("utf-8")))

        self.assertEqual(rows[0]["patreon_user_id"], "")

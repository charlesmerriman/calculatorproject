"""The Patreon API client, and the sync it drives from the command, the endpoint and the admin."""

# Builders and request helpers take one parameter per field a test can vary.
# One method per case, so a thorough test class outgrows the public-method cap.
# pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-public-methods

import datetime
import json
import os
from io import StringIO
from unittest.mock import patch

from django.core.cache import cache
from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from calculatorapi import patreon_api
from calculatorapi.models import PatreonTier, PatreonSupporter, PatreonCredentials
from calculatorapi.tests.base import CalculatorTestCase, PLAIN_TEST_STORAGES
from calculatorapi.tests.factories import make_ranks, make_user, FakeResponse


def patreon_member(name, tier_id=None, status="active_patron", pledge_start=None,
                   email=None, user_id=None):
    """One member resource, shaped like Patreon's JSON:API response.

    `user_id` defaults to one derived from the name; pass "" for a response with
    no user relationship at all, which is what the fallback-to-name path needs.
    """
    if user_id is None:
        user_id = f"u-{name}"
    return {
        "id": f"member-{name}",
        "type": "member",
        "attributes": {
            "full_name": name,
            # Patreon omits the key entirely for a member it has no address for,
            # which is why the client reads it with a default rather than [].
            **({"email": email} if email is not None else {}),
            "patron_status": status,
            "pledge_relationship_start": pledge_start,
        },
        "relationships": {
            "currently_entitled_tiers": {
                "data": [{"id": tier_id, "type": "tier"}] if tier_id else []
            },
            # The linkage object, and nothing else. `fields[user]` is sent empty
            # so the sideloaded resource carries no attributes — the id here is
            # all the client ever reads.
            **({"user": {"data": {"id": user_id, "type": "user"}}} if user_id else {}),
        },
    }


def patreon_page(members, tiers=None, next_cursor=None):
    """One page of /members, with the sideloaded tier block and its cursor.

    `tiers` maps id -> title (a paid tier, priced arbitrarily) or
    id -> (title, amount_cents), which is how a free tier is expressed.
    """
    included = []
    for tier_id, spec in (tiers or {}).items():
        title, amount_cents = spec if isinstance(spec, tuple) else (spec, 500)
        included.append({
            "id": tier_id,
            "type": "tier",
            "attributes": {"title": title, "amount_cents": amount_cents},
        })
    return {
        "data": members,
        "included": included,
        "meta": {"pagination": {"cursors": {"next": next_cursor}}},
    }


@override_settings(PATREON_CLIENT_ID="cid", PATREON_CLIENT_SECRET="csecret")
class PatreonApiClientTests(CalculatorTestCase):
    """The API client: what it asks for, what it refuses to ask for, and tokens."""

    def setUp(self):
        self.credentials = PatreonCredentials.load()
        self.credentials.access_token = "access-1"
        self.credentials.refresh_token = "refresh-1"
        self.credentials.expires_at = timezone.now() + datetime.timedelta(days=30)
        self.credentials.campaign_id = "camp-1"
        self.credentials.save()

    def test_request_asks_for_email_but_never_address_or_phone(self):
        """The whole privacy argument for the API route rests on this.

        Scopes are the other half and are set outside the code — a creator token
        carries every v2 scope automatically — so this is the half a test can
        hold: the request names the fields it wants, and that list is exactly
        what we decided to store. Email is on it deliberately; address, phone
        and the money fields are the ones this asserts we never even ask for.
        """
        captured = {}

        def fake_request(_method, _url, **kwargs):
            captured.update(kwargs.get("params") or {})
            return FakeResponse(patreon_page([]))

        with patch("calculatorapi.patreon_api.requests.request", side_effect=fake_request):
            patreon_api.fetch_members(self.credentials)

        requested = captured["fields[member]"]
        self.assertNotIn("address", requested)
        self.assertNotIn("phone", requested)
        self.assertNotIn("lifetime_support_cents", requested)
        self.assertEqual(
            set(requested.split(",")),
            {"full_name", "email", "patron_status", "pledge_relationship_start"},
        )

    def test_member_email_reaches_the_row(self):
        page = patreon_page(
            [patreon_member("Rhondal", "t1", email="rtibplays@gmail.com")],
            {"t1": "Junior Class"},
        )
        with patch("calculatorapi.patreon_api.requests.request",
                   side_effect=[FakeResponse(page)]):
            rows = patreon_api.fetch_members(self.credentials)

        self.assertEqual(rows[0]["email"], "rtibplays@gmail.com")

    def test_member_with_no_email_gives_an_empty_string(self):
        """Patreon can omit the attribute; that must not become the string "None"."""
        page = patreon_page([patreon_member("Rhondal", "t1")], {"t1": "Junior Class"})
        with patch("calculatorapi.patreon_api.requests.request",
                   side_effect=[FakeResponse(page)]):
            rows = patreon_api.fetch_members(self.credentials)

        self.assertEqual(rows[0]["email"], "")

    def test_pagination_is_followed_to_the_end(self):
        pages = [
            FakeResponse(patreon_page(
                [patreon_member("First", "t1")], {"t1": "Junior Class"}, next_cursor="c2")),
            FakeResponse(patreon_page(
                [patreon_member("Second", "t1")], {"t1": "Junior Class"})),
        ]
        with patch("calculatorapi.patreon_api.requests.request", side_effect=pages) as mocked:
            rows = patreon_api.fetch_members(self.credentials)

        self.assertEqual([row["display_name"] for row in rows], ["First", "Second"])
        self.assertEqual(mocked.call_count, 2)
        # The second call must carry the cursor the first one handed back, or
        # the loop would re-read page one forever.
        self.assertEqual(mocked.call_args_list[1].kwargs["params"]["page[cursor]"], "c2")

    def test_rows_match_the_shape_the_csv_parser_produces(self):
        page = patreon_page(
            [patreon_member("Rhondal", "t1", pledge_start="2025-03-04T12:00:00.000+00:00")],
            {"t1": "Junior Class"},
        )
        with patch("calculatorapi.patreon_api.requests.request", return_value=FakeResponse(page)):
            rows = patreon_api.fetch_members(self.credentials)

        self.assertEqual(rows, [{
            "display_name": "Rhondal",
            "patreon_user_id": "u-Rhondal",
            "email": "",
            "tier_name": "Junior Class",
            "is_active": True,
            "patron_since": datetime.date(2025, 3, 4),
        }])

    def test_declined_and_former_patrons_land_inactive(self):
        page = patreon_page([
            patreon_member("Declined", "t1", status="declined_patron"),
            patreon_member("Former", "t1", status="former_patron"),
        ], {"t1": "Junior Class"})
        with patch("calculatorapi.patreon_api.requests.request", return_value=FakeResponse(page)):
            rows = patreon_api.fetch_members(self.credentials)

        self.assertEqual([row["is_active"] for row in rows], [False, False])

    def test_free_members_are_not_supporters(self):
        """Patreon marks free members `active_patron`; they have not pledged.

        Taking that at face value would thank people who pay nothing and inflate
        the "and N others" count for the people who do.
        """
        page = patreon_page(
            [patreon_member("Follower", "free"), patreon_member("Patron", "paid")],
            {"free": ("Free", 0), "paid": ("Junior Class", 500)},
        )
        with patch("calculatorapi.patreon_api.requests.request", return_value=FakeResponse(page)):
            rows = patreon_api.fetch_members(self.credentials)

        self.assertEqual([row["display_name"] for row in rows], ["Patron"])

    def test_a_free_tier_is_detected_by_price_not_by_name(self):
        """"Free" is just what this creator called it today."""
        page = patreon_page(
            [patreon_member("Follower", "free")],
            {"free": ("Supporter (no charge)", 0)},
        )
        with patch("calculatorapi.patreon_api.requests.request", return_value=FakeResponse(page)):
            rows = patreon_api.fetch_members(self.credentials)

        self.assertEqual(rows, [])

    def test_a_member_entitled_to_nothing_is_dropped(self):
        """A former patron holds no entitlement. Dropping them from the rows is
        what lets `deactivate_missing` retire their row and keep its consent."""
        page = patreon_page([patreon_member("Lapsed", None, status="former_patron")])
        with patch("calculatorapi.patreon_api.requests.request", return_value=FakeResponse(page)):
            rows = patreon_api.fetch_members(self.credentials)

        self.assertEqual(rows, [])

    def test_a_paid_tier_wins_over_a_free_one_held_at_the_same_time(self):
        member = patreon_member("Both", "free")
        member["relationships"]["currently_entitled_tiers"]["data"].append(
            {"id": "paid", "type": "tier"})
        page = patreon_page([member], {"free": ("Free", 0), "paid": ("Junior Class", 500)})

        with patch("calculatorapi.patreon_api.requests.request", return_value=FakeResponse(page)):
            rows = patreon_api.fetch_members(self.credentials)

        self.assertEqual(rows[0]["tier_name"], "Junior Class")

    def test_the_tier_price_is_requested_but_never_stored(self):
        captured = {}

        def fake_request(_method, _url, **kwargs):
            captured.update(kwargs.get("params") or {})
            return FakeResponse(patreon_page(
                [patreon_member("Patron", "paid")], {"paid": ("Junior Class", 500)}))

        with patch("calculatorapi.patreon_api.requests.request", side_effect=fake_request):
            rows = patreon_api.fetch_members(self.credentials)

        self.assertIn("amount_cents", captured["fields[tier]"])
        # It decides who counts and is then discarded — PatreonTier carries no
        # money column, and neither does the row handed to the reconcile.
        self.assertNotIn("amount_cents", rows[0])

    def test_nameless_members_are_skipped(self):
        page = patreon_page([patreon_member("", "t1"), patreon_member("Named", "t1")],
                            {"t1": ("Junior Class", 500)})
        with patch("calculatorapi.patreon_api.requests.request", return_value=FakeResponse(page)):
            rows = patreon_api.fetch_members(self.credentials)

        self.assertEqual([row["display_name"] for row in rows], ["Named"])

    def test_a_stale_token_is_refreshed_before_use(self):
        self.credentials.expires_at = timezone.now() + datetime.timedelta(hours=1)
        self.credentials.save()

        responses = [
            FakeResponse({"access_token": "access-2", "refresh_token": "refresh-2",
                          "expires_in": 2678400}),
            FakeResponse(patreon_page([])),
        ]
        with patch("calculatorapi.patreon_api.requests.request", side_effect=responses) as mocked:
            patreon_api.fetch_members(self.credentials)

        self.assertEqual(mocked.call_args_list[0].args[1], patreon_api.TOKEN_URL)
        # The members call must present the NEW token, not the expiring one.
        self.assertEqual(
            mocked.call_args_list[1].kwargs["headers"]["Authorization"], "Bearer access-2")

    def test_the_rotated_refresh_token_is_persisted(self):
        """Patreon spends the refresh token on every refresh.

        Storing only the access token leaves the next run presenting a dead
        refresh token — a failure that looks like Patreon's fault and never
        recovers on its own.
        """
        self.credentials.expires_at = None
        self.credentials.save()

        responses = [
            FakeResponse({"access_token": "access-2", "refresh_token": "refresh-2",
                          "expires_in": 2678400}),
            FakeResponse(patreon_page([])),
        ]
        with patch("calculatorapi.patreon_api.requests.request", side_effect=responses):
            patreon_api.fetch_members(self.credentials)

        stored = PatreonCredentials.load()
        self.assertEqual(stored.refresh_token, "refresh-2")
        self.assertEqual(stored.access_token, "access-2")
        self.assertIsNotNone(stored.expires_at)

    def test_an_http_error_raises_rather_than_returning_nothing(self):
        """A silent empty list here would deactivate every supporter."""
        with patch("calculatorapi.patreon_api.requests.request",
                   return_value=FakeResponse(None, status_code=401)):
            with self.assertRaises(patreon_api.PatreonApiError):
                patreon_api.fetch_members(self.credentials)

    def test_an_unreachable_patreon_raises(self):
        with patch("calculatorapi.patreon_api.requests.request",
                   side_effect=patreon_api.requests.ConnectionError("no route")):
            with self.assertRaises(patreon_api.PatreonApiError) as caught:
                patreon_api.fetch_members(self.credentials)
        self.assertIn("Could not reach Patreon", str(caught.exception))

    def test_an_error_body_is_not_echoed_into_the_message(self):
        """last_sync_error is stored and shown; it must not become a channel for
        member data that arrived in an error body."""
        payload = {"errors": [{"detail": "patron jane@example.com is invalid"}]}
        with patch("calculatorapi.patreon_api.requests.request",
                   return_value=FakeResponse(payload, status_code=400)):
            with self.assertRaises(patreon_api.PatreonApiError) as caught:
                patreon_api.fetch_members(self.credentials)
        self.assertNotIn("jane@example.com", str(caught.exception))

    def test_missing_credentials_raise_a_readable_error(self):
        self.credentials.refresh_token = ""
        self.credentials.save()
        with self.assertRaises(patreon_api.PatreonApiError) as caught:
            patreon_api.fetch_members(self.credentials)
        self.assertIn("PATREON_REFRESH_TOKEN", str(caught.exception))

    def test_campaign_id_is_resolved_once_and_cached(self):
        self.credentials.campaign_id = ""
        self.credentials.save()

        responses = [
            FakeResponse({"data": [{"id": "camp-9", "type": "campaign"}]}),
            FakeResponse(patreon_page([])),
        ]
        with patch("calculatorapi.patreon_api.requests.request", side_effect=responses):
            patreon_api.fetch_members(self.credentials)

        self.assertEqual(PatreonCredentials.load().campaign_id, "camp-9")

    def test_credentials_seed_from_the_environment_once(self):
        PatreonCredentials.objects.all().delete()
        with patch.dict(os.environ, {"PATREON_ACCESS_TOKEN": "env-access",
                                     "PATREON_REFRESH_TOKEN": "env-refresh"}):
            seeded = PatreonCredentials.load()
        self.assertEqual(seeded.refresh_token, "env-refresh")

        # Once a pair is stored the environment is ignored: after the first
        # refresh those values are stale, and honouring them would resurrect a
        # spent token.
        seeded.refresh_token = "rotated"
        seeded.save()
        with patch.dict(os.environ, {"PATREON_REFRESH_TOKEN": "env-refresh"}):
            self.assertEqual(PatreonCredentials.load().refresh_token, "rotated")


@override_settings(PATREON_CLIENT_ID="cid", PATREON_CLIENT_SECRET="csecret")
class PatreonSyncCommandTests(CalculatorTestCase):
    """`sync_patreon_supporters` — the shared core behind all three triggers.

    Mocked at `fetch_members`, the seam between provider logic and reconcile, so
    these cases are about what a sync DOES rather than about HTTP.
    """

    def setUp(self):
        credentials = PatreonCredentials.load()
        credentials.access_token = "access-1"
        credentials.refresh_token = "refresh-1"
        credentials.expires_at = timezone.now() + datetime.timedelta(days=30)
        credentials.campaign_id = "camp-1"
        credentials.save()

    def run_command(self, rows, **kwargs):
        out = StringIO()
        with patch("calculatorapi.patreon_api.fetch_members", return_value=rows):
            call_command('sync_patreon_supporters', stdout=out, **kwargs)
        return out.getvalue()

    @staticmethod
    def row(name, tier="Junior Class", is_active=True, patron_since=None):
        return {
            "display_name": name,
            "tier_name": tier,
            "is_active": is_active,
            "patron_since": patron_since,
        }

    def test_sync_creates_supporters_unpublished(self):
        """The rule the whole feature depends on. This job runs unattended."""
        self.run_command([self.row("Rhondal")])
        supporter = PatreonSupporter.objects.get(display_name="Rhondal")
        self.assertFalse(supporter.is_public)
        self.assertEqual(supporter.tier.name, "Junior Class")

    def test_sync_preserves_an_editors_publish_decision(self):
        tier = PatreonTier.objects.create(name="Junior Class", order=10)
        PatreonSupporter.objects.create(
            display_name="Rhondal", tier=tier, is_public=True, is_active=True)

        self.run_command([self.row("Rhondal")])
        self.assertTrue(PatreonSupporter.objects.get(display_name="Rhondal").is_public)

    def test_missing_supporters_are_deactivated_by_default(self):
        """Opposite default to the CSV form, because an API response is complete."""
        PatreonSupporter.objects.create(display_name="Absent", is_active=True)
        self.run_command([self.row("Present")])
        self.assertFalse(PatreonSupporter.objects.get(display_name="Absent").is_active)

    def test_no_deactivate_missing_keeps_them(self):
        PatreonSupporter.objects.create(display_name="Absent", is_active=True)
        self.run_command([self.row("Present")], no_deactivate_missing=True)
        self.assertTrue(PatreonSupporter.objects.get(display_name="Absent").is_active)

    def test_dry_run_writes_nothing(self):
        output = self.run_command([self.row("Rhondal")], dry_run=True)
        self.assertEqual(PatreonSupporter.objects.count(), 0)
        self.assertIn("nothing was saved", output)

    def test_patron_since_is_filled_from_the_api(self):
        self.run_command([self.row("Rhondal", patron_since=datetime.date(2025, 3, 4))])
        self.assertEqual(
            PatreonSupporter.objects.get(display_name="Rhondal").patron_since,
            datetime.date(2025, 3, 4),
        )

    def test_a_hand_corrected_patron_since_is_never_overwritten(self):
        tier = PatreonTier.objects.create(name="Junior Class", order=10)
        PatreonSupporter.objects.create(
            display_name="Rhondal", tier=tier, patron_since=datetime.date(2024, 1, 1))

        self.run_command([self.row("Rhondal", patron_since=datetime.date(2025, 3, 4))])
        self.assertEqual(
            PatreonSupporter.objects.get(display_name="Rhondal").patron_since,
            datetime.date(2024, 1, 1),
        )

    def test_a_successful_sync_stamps_the_credentials_row(self):
        self.run_command([self.row("Rhondal")])
        credentials = PatreonCredentials.load()
        self.assertIsNotNone(credentials.last_synced_at)
        self.assertEqual(credentials.last_sync_error, "")

    def test_a_failure_exits_zero_and_records_the_error(self):
        """A POST_DEPLOY job that exits non-zero fails the whole deployment.

        An expired Patreon token must not be able to take the site down, so the
        command reports and returns rather than raising.
        """
        out = StringIO()
        with patch("calculatorapi.patreon_api.fetch_members",
                   side_effect=patreon_api.PatreonApiError("token expired")):
            call_command('sync_patreon_supporters', stdout=out)

        self.assertIn("Patreon sync failed", out.getvalue())
        self.assertIn("token expired", PatreonCredentials.load().last_sync_error)

    def test_a_failure_leaves_the_existing_list_alone(self):
        PatreonSupporter.objects.create(display_name="Existing", is_active=True)
        out = StringIO()
        with patch("calculatorapi.patreon_api.fetch_members",
                   side_effect=patreon_api.PatreonApiError("boom")):
            call_command('sync_patreon_supporters', stdout=out)

        # Nothing reached the reconcile, so deactivate_missing never ran.
        self.assertTrue(PatreonSupporter.objects.get(display_name="Existing").is_active)


class PatreonSyncEndpointTests(CalculatorTestCase):
    """POST /patreon/sync — the scheduled job's trigger and its shared secret."""

    def setUp(self):
        self.url = reverse("patreon-sync")
        # DRF throttles through the shared cache; without this a neighbouring
        # test's hits could throttle ours. Same reason as the feedback endpoint.
        cache.clear()
        credentials = PatreonCredentials.load()
        credentials.access_token = "access-1"
        credentials.refresh_token = "refresh-1"
        credentials.expires_at = timezone.now() + datetime.timedelta(days=30)
        credentials.campaign_id = "camp-1"
        credentials.save()
        self.rows = [{
            "display_name": "Rhondal",
            "tier_name": "Junior Class",
            "is_active": True,
            "patron_since": None,
        }]

    def post(self, key=None):
        headers = {"HTTP_X_PATREON_SYNC_KEY": key} if key is not None else {}
        with patch("calculatorapi.patreon_api.fetch_members", return_value=self.rows):
            return self.client.post(self.url, **headers)

    @override_settings(PATREON_SYNC_SECRET="")
    def test_the_route_does_not_exist_while_unconfigured(self):
        """No half-configured state: without a secret there is no endpoint."""
        self.assertEqual(self.post("anything").status_code, 404)

    @override_settings(PATREON_SYNC_SECRET="s3cret")
    def test_a_missing_key_is_refused(self):
        self.assertEqual(self.post().status_code, 403)

    @override_settings(PATREON_SYNC_SECRET="s3cret")
    def test_a_wrong_key_is_refused(self):
        self.assertEqual(self.post("wrong").status_code, 403)
        self.assertEqual(PatreonSupporter.objects.count(), 0)

    @override_settings(PATREON_SYNC_SECRET="s3cret")
    def test_the_right_key_runs_the_sync(self):
        response = self.post("s3cret")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["created"], 1)
        self.assertTrue(PatreonSupporter.objects.filter(display_name="Rhondal").exists())

    @override_settings(PATREON_SYNC_SECRET="s3cret")
    def test_the_endpoint_cannot_publish_a_name(self):
        self.post("s3cret")
        self.assertFalse(PatreonSupporter.objects.get(display_name="Rhondal").is_public)

    @override_settings(PATREON_SYNC_SECRET="s3cret")
    def test_the_response_carries_counts_and_no_names(self):
        """The job log is a third-party surface — GitHub, in this case."""
        body = self.post("s3cret").json()
        self.assertNotIn("Rhondal", json.dumps(body))
        self.assertEqual(body["members_returned"], 1)

    @override_settings(PATREON_SYNC_SECRET="s3cret")
    def test_an_upstream_failure_returns_502_so_the_job_goes_red(self):
        with patch("calculatorapi.patreon_api.fetch_members",
                   side_effect=patreon_api.PatreonApiError("token expired")):
            response = self.client.post(self.url, HTTP_X_PATREON_SYNC_KEY="s3cret")

        self.assertEqual(response.status_code, 502)
        self.assertIn("token expired", PatreonCredentials.load().last_sync_error)

    @override_settings(PATREON_SYNC_SECRET="s3cret")
    def test_get_is_not_allowed(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)


# Renders real admin templates, so it needs the plain static storage — the
# manifest one has no entry for unfold's fonts without a collectstatic.
@override_settings(STORAGES=PLAIN_TEST_STORAGES,
                   PATREON_CLIENT_ID="cid", PATREON_CLIENT_SECRET="csecret")
class PatreonSyncAdminViewTests(CalculatorTestCase):
    """The admin "Sync from Patreon" page — permissions and the round trip."""

    def setUp(self):
        make_ranks()
        self.admin = make_user(username="patreonsyncadmin", is_staff=True)
        self.admin.is_superuser = True
        self.admin.save()
        self.url = reverse("admin:calculatorapi_patreonsupporter_sync_patreon")

        credentials = PatreonCredentials.load()
        credentials.access_token = "access-1"
        credentials.refresh_token = "refresh-1"
        credentials.expires_at = timezone.now() + datetime.timedelta(days=30)
        credentials.campaign_id = "camp-1"
        credentials.save()

        self.rows = [{
            "display_name": "Rhondal",
            "tier_name": "Junior Class",
            "is_active": True,
            "patron_since": datetime.date(2025, 3, 4),
        }]

    def test_non_staff_cannot_reach_the_sync_page(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login", response["Location"])

    def test_the_page_renders_for_staff(self):
        self.client.force_login(self.admin)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Sync from Patreon")

    def test_sync_creates_supporters_unpublished(self):
        self.client.force_login(self.admin)
        with patch("calculatorapi.patreon_api.fetch_members", return_value=self.rows):
            response = self.client.post(
                self.url, {"deactivate_missing": "on", "dry_run": ""}, follow=True)

        self.assertEqual(response.status_code, 200)
        supporter = PatreonSupporter.objects.get(display_name="Rhondal")
        self.assertFalse(supporter.is_public)
        self.assertEqual(supporter.tier.name, "Junior Class")
        self.assertEqual(supporter.patron_since, datetime.date(2025, 3, 4))

    def test_preview_checkbox_writes_nothing(self):
        self.client.force_login(self.admin)
        with patch("calculatorapi.patreon_api.fetch_members", return_value=self.rows):
            self.client.post(self.url, {"deactivate_missing": "on", "dry_run": "on"})
        self.assertEqual(PatreonSupporter.objects.count(), 0)

    def test_a_failure_is_reported_on_the_page_not_raised(self):
        self.client.force_login(self.admin)
        with patch("calculatorapi.patreon_api.fetch_members",
                   side_effect=patreon_api.PatreonApiError("token expired")):
            response = self.client.post(self.url, {"deactivate_missing": "on", "dry_run": ""})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "token expired")
        self.assertEqual(PatreonSupporter.objects.count(), 0)

    def test_the_page_says_so_when_patreon_is_not_connected(self):
        PatreonCredentials.objects.all().delete()
        with patch.dict(os.environ, {"PATREON_ACCESS_TOKEN": "", "PATREON_REFRESH_TOKEN": ""}):
            self.client.force_login(self.admin)
            response = self.client.get(self.url)
        self.assertContains(response, "isn&rsquo;t connected yet")

    def test_the_changelist_offers_both_import_routes(self):
        self.client.force_login(self.admin)
        response = self.client.get(
            reverse("admin:calculatorapi_patreonsupporter_changelist"))
        self.assertContains(response, "Sync from Patreon")
        self.assertContains(response, "Import Patreon CSV")


class PatreonUserIdFetchTests(CalculatorTestCase):
    """The client reads the Patreon user id WITHOUT widening what it asks for."""

    def setUp(self):
        self.credentials = PatreonCredentials.load()
        self.credentials.access_token = "access-1"
        self.credentials.refresh_token = "refresh-1"
        self.credentials.expires_at = timezone.now() + datetime.timedelta(days=30)
        self.credentials.campaign_id = "camp-1"
        self.credentials.save()

    def _fetch(self, page):
        with patch("calculatorapi.patreon_api.requests.request",
                   return_value=FakeResponse(page)):
            return patreon_api.fetch_members(self.credentials)

    def test_member_fields_is_unchanged_by_the_linking_work(self):
        """The privacy boundary, asserted as a literal.

        The user id arrives as a RELATIONSHIP, so getting it must not have
        added anything to the list of member ATTRIBUTES we ask Patreon for.
        This is the same role REQUIRED_COLUMNS plays for the CSV path: if a
        future change needs a new field here, it should have to change this
        line and explain itself.
        """
        self.assertEqual(
            patreon_api.MEMBER_FIELDS,
            ("full_name", "email", "patron_status", "pledge_relationship_start"),
        )

    def test_the_user_resource_is_requested_with_one_useless_attribute(self):
        """`fields[user]` is what stops Patreon sending the default set.

        Drop the parameter and the sideloaded user arrives complete with full
        name, vanity URL, avatar and social handles — none of which we want,
        and all of which we would then be storing in a response we parse. Send
        it EMPTY and Patreon rejects the whole request with HTTP 400, which is
        how this sync spent 2026-09-09 returning nothing at all.

        So it must name something, and what it names must stay worthless:
        `hide_pledges` is a boolean about a display preference, needs no scope,
        and is never read. Anything on this list that describes the PERSON
        belongs in MEMBER_FIELDS' review conversation instead.
        """
        captured = {}

        def fake_request(_method, _url, **kwargs):
            captured.update(kwargs.get("params") or {})
            return FakeResponse(patreon_page([]))

        with patch("calculatorapi.patreon_api.requests.request", side_effect=fake_request):
            patreon_api.fetch_members(self.credentials)

        self.assertEqual(patreon_api.USER_FIELDS, ("hide_pledges",))
        self.assertEqual(captured["fields[user]"], "hide_pledges")
        self.assertIn("user", captured["include"].split(","))

    def test_the_id_comes_from_the_relationship(self):
        page = patreon_page(
            [patreon_member("Rhondal", "t1", user_id="9911")], {"t1": "Junior Class"})
        self.assertEqual(self._fetch(page)[0]["patreon_user_id"], "9911")

    def test_a_member_with_no_user_relationship_still_imports(self):
        """Falls back to the display name, exactly as every CSV row does."""
        page = patreon_page(
            [patreon_member("Rhondal", "t1", user_id="")], {"t1": "Junior Class"})
        rows = self._fetch(page)
        self.assertEqual(rows[0]["patreon_user_id"], "")
        self.assertEqual(rows[0]["display_name"], "Rhondal")

    def test_two_patrons_sharing_a_display_name_both_survive_the_fetch(self):
        """THE BUG THIS PHASE EXISTS TO PREVENT.

        Deduping on the display name silently dropped the second of two patrons
        who happened to choose the same name. Harmless while this only fed a
        thank-you list; once entitlement hangs off the row it costs one of them
        the thing they paid for — and nothing reports it, because a dropped row
        looks exactly like a lapsed one, after which `deactivate_missing`
        retires whichever row already existed.
        """
        page = patreon_page([
            patreon_member("Trainer", "t1", user_id="1"),
            patreon_member("Trainer", "t1", user_id="2"),
        ], {"t1": "Junior Class"})

        rows = self._fetch(page)

        self.assertEqual(len(rows), 2)
        self.assertEqual({row["patreon_user_id"] for row in rows}, {"1", "2"})

    def test_the_same_patron_twice_is_still_collapsed(self):
        """Deduping did not simply go away — it moved onto the reliable key."""
        page = patreon_page([
            patreon_member("Trainer", "t1", user_id="1"),
            patreon_member("Trainer", "t1", user_id="1"),
        ], {"t1": "Junior Class"})

        self.assertEqual(len(self._fetch(page)), 1)

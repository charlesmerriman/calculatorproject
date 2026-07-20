import datetime
from io import StringIO

from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import NoReverseMatch, reverse
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from calculatorapi.analytics import build_analytics_report
from calculatorapi.predictions import PREDICTION_FACTOR, compute_effective_dates
from calculatorapi.models import (
    CustomUser,
    ClubRank, TeamTrialsRank, ChampionsMeetingRank, LeagueOfHeroesRank,
    BannerTimeline, BannerUma, BannerSupport, UserPlannedBanner,
    ChampionsMeeting, LeagueOfHeroes,
    ChangelogEntry, ChangelogChange,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_ranks():
    """Create one of each rank type with zero income — minimal valid FKs for CustomUser."""
    club = ClubRank.objects.create(name='None', income_amount=0)
    tt = TeamTrialsRank.objects.create(name='None', income_amount=0)
    cm = ChampionsMeetingRank.objects.create(name='None', income_amount=0)
    loh = LeagueOfHeroesRank.objects.create(name='None', income_amount=0)
    return club, tt, cm, loh


def make_user(username='testuser', password='testpass123'):
    """Create a CustomUser with all required FK ranks set."""
    club, tt, cm, loh = make_ranks()
    return CustomUser.objects.create_user(
        username=username,
        password=password,
        email=f'{username}@test.com',
        first_name='Test',
        last_name='User',
        club_rank=club,
        team_trials_rank=tt,
        champions_meeting_rank=cm,
        league_of_heroes_rank=loh,
    )


def make_timeline(name='Test Timeline', jp_start_date=None, jp_end_date=None,
                  global_start_date=None, global_end_date=None):
    """Create a BannerTimeline. By default it's a CONFIRMED global banner
    (now → now+30d) so existing tests keep resolving real dates; pass jp_*/
    global_* explicitly to build predicted (global-null) timelines."""
    now = timezone.now()
    if global_start_date is None and global_end_date is None and \
            jp_start_date is None and jp_end_date is None:
        global_start_date = now
        global_end_date = now + datetime.timedelta(days=30)
    return BannerTimeline.objects.create(
        name=name,
        jp_start_date=jp_start_date,
        jp_end_date=jp_end_date,
        global_start_date=global_start_date,
        global_end_date=global_end_date,
    )


def make_uma_banner(timeline=None, name='Test Uma Banner'):
    return BannerUma.objects.create(
        banner_timeline=timeline or make_timeline(),
        name=name,
    )


def make_support_banner(timeline=None, name='Test Support Banner'):
    return BannerSupport.objects.create(
        banner_timeline=timeline or make_timeline(),
        name=name,
    )


def make_champions_meeting(name='Test CM', cm_number=1, jp_start_date=None,
                           jp_end_date=None, global_start_date=None,
                           global_end_date=None):
    """Create a ChampionsMeeting. Defaults to a CONFIRMED global meeting
    (now → now+7d); pass jp_*/global_* explicitly for predicted rows. Track and
    stat fields are filler — they don't affect date resolution."""
    now = timezone.now()
    if global_start_date is None and global_end_date is None and \
            jp_start_date is None and jp_end_date is None:
        global_start_date = now
        global_end_date = now + datetime.timedelta(days=7)
    return ChampionsMeeting.objects.create(
        name=name, cm_number=cm_number,
        jp_start_date=jp_start_date, jp_end_date=jp_end_date,
        global_start_date=global_start_date, global_end_date=global_end_date,
        track='Tokyo', surface_type='Turf', distance='Long', length='2400m',
        track_condition='Good', season='Spring', weather='Sunny', direction='Right',
        speed_recommendation=0, stamina_recommendation=0, power_recommendation=0,
        guts_recommendation=0, wit_recommendation=0,
    )


def make_league_of_heroes(name='Test LoH', jp_start_date=None, jp_end_date=None,
                          global_start_date=None, global_end_date=None):
    """Create a LeagueOfHeroes event. Defaults to a CONFIRMED global event
    (now → now+7d); pass jp_*/global_* explicitly for predicted rows."""
    now = timezone.now()
    if global_start_date is None and global_end_date is None and \
            jp_start_date is None and jp_end_date is None:
        global_start_date = now
        global_end_date = now + datetime.timedelta(days=7)
    return LeagueOfHeroes.objects.create(
        name=name,
        jp_start_date=jp_start_date, jp_end_date=jp_end_date,
        global_start_date=global_start_date, global_end_date=global_end_date,
    )


def auth_client(user):
    """Return an APIClient already authenticated as `user`."""
    token, _ = Token.objects.get_or_create(user=user)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f'Token {token.key}')
    return client, token


# ── Auth Tests ────────────────────────────────────────────────────────────────

class AuthTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def _register_payload(self, username='newuser'):
        return {
            'username': username,
            'password': 'StrongPass123!',
            'email': f'{username}@test.com',
            'first_name': 'New',
            'last_name': 'User',
        }

    # register ─────────────────────────────────────────────────────────────────

    def test_register_returns_201_and_token(self):
        res = self.client.post('/register', self._register_payload(), format='json')
        self.assertEqual(res.status_code, 201)
        self.assertIn('token', res.data)

    def test_register_creates_user_in_db(self):
        self.client.post('/register', self._register_payload(), format='json')
        self.assertTrue(CustomUser.objects.filter(username='newuser').exists())

    def test_register_duplicate_username_returns_400(self):
        make_user('existing')
        res = self.client.post('/register', self._register_payload('existing'), format='json')
        self.assertEqual(res.status_code, 400)

    def test_register_missing_password_returns_400(self):
        payload = self._register_payload()
        del payload['password']
        res = self.client.post('/register', payload, format='json')
        self.assertEqual(res.status_code, 400)

    def test_register_missing_username_returns_400(self):
        payload = self._register_payload()
        del payload['username']
        res = self.client.post('/register', payload, format='json')
        self.assertEqual(res.status_code, 400)

    # login ────────────────────────────────────────────────────────────────────

    def test_login_returns_200_and_token(self):
        make_user('loginuser', 'correctpass')
        res = self.client.post('/login', {'username': 'loginuser', 'password': 'correctpass'}, format='json')
        self.assertEqual(res.status_code, 200)
        self.assertIn('token', res.data)

    def test_login_wrong_password_returns_400(self):
        make_user('loginuser', 'correctpass')
        res = self.client.post('/login', {'username': 'loginuser', 'password': 'wrongpass'}, format='json')
        self.assertEqual(res.status_code, 400)

    def test_login_nonexistent_user_returns_400(self):
        res = self.client.post('/login', {'username': 'nobody', 'password': 'whatever'}, format='json')
        self.assertEqual(res.status_code, 400)

    # logout ───────────────────────────────────────────────────────────────────

    def test_logout_returns_200_and_deletes_token(self):
        user = make_user()
        client, _token = auth_client(user)
        res = client.post('/logout')
        self.assertEqual(res.status_code, 200)
        self.assertFalse(Token.objects.filter(user=user).exists())

    def test_logout_unauthenticated_returns_401(self):
        res = self.client.post('/logout')
        self.assertEqual(res.status_code, 401)


# ── Calculator GET Tests ──────────────────────────────────────────────────────

# ── Prediction logic (pure, DB-free) ──────────────────────────────────────────

_UTC = datetime.timezone.utc


def _dt(y, m, d):
    return datetime.datetime(y, m, d, tzinfo=_UTC)


class PredictionUnitTests(TestCase):
    """Directly exercises compute_effective_dates on plain dicts (no DB)."""

    def test_confirmed_banner_passes_through(self):
        rows = [{
            "id": 1, "jp_start_date": _dt(2025, 1, 1), "jp_end_date": _dt(2025, 1, 8),
            "global_start_date": _dt(2025, 6, 1), "global_end_date": _dt(2025, 6, 8),
        }]
        out = compute_effective_dates(rows)[1]
        self.assertEqual(out["start_date"], _dt(2025, 6, 1))
        self.assertEqual(out["end_date"], _dt(2025, 6, 8))
        self.assertFalse(out["is_predicted"])

    def test_anchor_is_latest_jp_among_confirmed_with_jp(self):
        rows = [
            # confirmed + jp, earlier jp
            {"id": 1, "jp_start_date": _dt(2024, 6, 1), "jp_end_date": _dt(2024, 6, 8),
             "global_start_date": _dt(2025, 5, 1), "global_end_date": _dt(2025, 5, 8)},
            # confirmed + jp, latest jp -> should be the anchor
            {"id": 2, "jp_start_date": _dt(2025, 1, 1), "jp_end_date": _dt(2025, 1, 8),
             "global_start_date": _dt(2025, 6, 1), "global_end_date": _dt(2025, 6, 8)},
            # confirmed but NO jp -> ineligible as anchor
            {"id": 3, "jp_start_date": None, "jp_end_date": None,
             "global_start_date": _dt(2025, 7, 1), "global_end_date": _dt(2025, 7, 8)},
            # target awaiting confirmation
            {"id": 4, "jp_start_date": _dt(2025, 1, 31), "jp_end_date": _dt(2025, 2, 7),
             "global_start_date": None, "global_end_date": None},
        ]
        target = compute_effective_dates(rows)[4]
        # Anchored to id=2 (jp 2025-01-01 / global 2025-06-01). Δjp = 30 days.
        self.assertTrue(target["is_predicted"])
        self.assertEqual(target["start_date"], _dt(2025, 6, 1) + datetime.timedelta(days=30) * PREDICTION_FACTOR)

    def test_fixed_anchor_worked_example(self):
        rows = [
            {"id": 1, "jp_start_date": _dt(2025, 1, 1), "jp_end_date": _dt(2025, 1, 8),
             "global_start_date": _dt(2025, 6, 1), "global_end_date": _dt(2025, 6, 8)},
            {"id": 2, "jp_start_date": _dt(2025, 1, 31), "jp_end_date": _dt(2025, 2, 7),
             "global_start_date": None, "global_end_date": None},
        ]
        out = compute_effective_dates(rows)[2]
        # Δjp = 30d × 0.7 = 21d -> 2025-06-22; banner runs 7d -> 2025-06-29.
        self.assertEqual(out["start_date"], _dt(2025, 6, 22))
        self.assertEqual(out["end_date"], _dt(2025, 6, 29))
        self.assertTrue(out["is_predicted"])

    def test_no_anchor_leaves_jp_only_rows_unresolved(self):
        rows = [{
            "id": 1, "jp_start_date": _dt(2025, 1, 1), "jp_end_date": _dt(2025, 1, 8),
            "global_start_date": None, "global_end_date": None,
        }]
        out = compute_effective_dates(rows)[1]
        self.assertIsNone(out["start_date"])
        self.assertIsNone(out["end_date"])
        self.assertFalse(out["is_predicted"])

    def test_target_with_no_jp_and_no_global_is_unresolved(self):
        rows = [
            {"id": 1, "jp_start_date": _dt(2025, 1, 1), "jp_end_date": _dt(2025, 1, 8),
             "global_start_date": _dt(2025, 6, 1), "global_end_date": _dt(2025, 6, 8)},
            {"id": 2, "jp_start_date": None, "jp_end_date": None,
             "global_start_date": None, "global_end_date": None},
        ]
        out = compute_effective_dates(rows)[2]
        self.assertIsNone(out["start_date"])
        self.assertFalse(out["is_predicted"])

    def test_negative_delta_predicts_before_anchor(self):
        rows = [
            {"id": 1, "jp_start_date": _dt(2025, 3, 1), "jp_end_date": _dt(2025, 3, 8),
             "global_start_date": _dt(2025, 8, 1), "global_end_date": _dt(2025, 8, 8)},
            # target's jp is BEFORE the anchor's jp -> predicted start before anchor global
            {"id": 2, "jp_start_date": _dt(2025, 1, 30), "jp_end_date": _dt(2025, 2, 6),
             "global_start_date": None, "global_end_date": None},
        ]
        out = compute_effective_dates(rows)[2]
        # Δjp = -30d × 0.7 = -21d -> 2025-07-11.
        self.assertEqual(out["start_date"], _dt(2025, 8, 1) - datetime.timedelta(days=30) * PREDICTION_FACTOR)
        self.assertTrue(out["is_predicted"])

    def test_predicted_start_but_null_jp_end_gives_null_end(self):
        rows = [
            {"id": 1, "jp_start_date": _dt(2025, 1, 1), "jp_end_date": _dt(2025, 1, 8),
             "global_start_date": _dt(2025, 6, 1), "global_end_date": _dt(2025, 6, 8)},
            {"id": 2, "jp_start_date": _dt(2025, 1, 31), "jp_end_date": None,
             "global_start_date": None, "global_end_date": None},
        ]
        out = compute_effective_dates(rows)[2]
        self.assertEqual(out["start_date"], _dt(2025, 6, 22))
        self.assertIsNone(out["end_date"])
        self.assertTrue(out["is_predicted"])


_EXPECTED_GET_KEYS = {
    'club_rank_data', 'team_trials_rank_data', 'champions_meeting_rank_data',
    'league_of_heroes_rank_data', 'banner_uma_data', 'banner_support_data',
    'user_planned_banner_data', 'champions_meeting_data', 'league_of_heroes_event_data',
    'events_data', 'user_stats_data', 'banner_timeline_data',
}


class CalculatorGetTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client, self.token = auth_client(self.user)

    def test_unauthenticated_returns_200_with_empty_user_data(self):
        # Guests get the full reference payload; user-scoped keys are empty/null.
        res = APIClient().get('/calculator-data')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(set(res.data.keys()), _EXPECTED_GET_KEYS)
        self.assertIsNone(res.data['user_stats_data'])
        self.assertEqual(res.data['user_planned_banner_data'], [])

    def test_get_with_invalid_token_returns_401(self):
        # TokenAuthentication rejects a present-but-invalid token before
        # permissions run, even under AllowAny. The frontend relies on this
        # to detect a stale token and retry the fetch as a guest.
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION='Token deadbeef')
        res = client.get('/calculator-data')
        self.assertEqual(res.status_code, 401)

    def test_authenticated_returns_200(self):
        res = self.client.get('/calculator-data')
        self.assertEqual(res.status_code, 200)

    def test_response_contains_all_expected_keys(self):
        res = self.client.get('/calculator-data')
        self.assertEqual(set(res.data.keys()), _EXPECTED_GET_KEYS)

    def test_planned_banners_scoped_to_requesting_user(self):
        # This user's banner should appear; the other user's should not.
        uma_banner = make_uma_banner()
        UserPlannedBanner.objects.create(user=self.user, banner_uma=uma_banner, number_of_pulls=5)
        other_user = make_user('otheruser')
        UserPlannedBanner.objects.create(user=other_user, banner_uma=uma_banner, number_of_pulls=10)

        res = self.client.get('/calculator-data')
        self.assertEqual(len(res.data['user_planned_banner_data']), 1)
        self.assertEqual(res.data['user_planned_banner_data'][0]['number_of_pulls'], 5)

    def test_timeline_data_exposes_resolved_and_predicted_fields(self):
        make_timeline(name='Confirmed')  # default: confirmed global banner
        res = self.client.get('/calculator-data')
        entry = res.data['banner_timeline_data'][0]
        for key in ('start_date', 'end_date', 'is_predicted',
                    'jp_start_date', 'global_start_date'):
            self.assertIn(key, entry)
        self.assertFalse(entry['is_predicted'])
        self.assertTrue(entry['start_date'].endswith('Z'))

    def test_predicted_dates_are_consistent_across_all_paths(self):
        # Anchor: confirmed banner with a JP date. Target: JP-only, so predicted.
        make_timeline(
            name='Anchor',
            jp_start_date=_dt(2025, 1, 1), jp_end_date=_dt(2025, 1, 8),
            global_start_date=_dt(2025, 6, 1), global_end_date=_dt(2025, 6, 8),
        )
        predicted_tl = make_timeline(
            name='Predicted',
            jp_start_date=_dt(2025, 1, 31), jp_end_date=_dt(2025, 2, 7),
        )
        uma_banner = make_uma_banner(timeline=predicted_tl)
        UserPlannedBanner.objects.create(
            user=self.user, banner_uma=uma_banner, number_of_pulls=3
        )

        res = self.client.get('/calculator-data')

        # Δjp = 30d × 0.7 = 21d -> 2025-06-22.
        expected_start = '2025-06-22T00:00:00Z'

        top = next(t for t in res.data['banner_timeline_data'] if t['id'] == predicted_tl.id)
        self.assertTrue(top['is_predicted'])
        self.assertEqual(top['start_date'], expected_start)

        nested_uma = next(
            b for b in res.data['banner_uma_data']
            if b['banner_timeline']['id'] == predicted_tl.id
        )
        self.assertTrue(nested_uma['banner_timeline']['is_predicted'])
        self.assertEqual(nested_uma['banner_timeline']['start_date'], expected_start)

        planned_tl = res.data['user_planned_banner_data'][0]['banner_uma']['banner_timeline']
        self.assertEqual(planned_tl['start_date'], expected_start)
        self.assertTrue(planned_tl['is_predicted'])

    def test_champions_meeting_exposes_resolved_and_predicted_fields(self):
        make_champions_meeting(name='Confirmed CM')  # default: confirmed global
        res = self.client.get('/calculator-data')
        entry = res.data['champions_meeting_data'][0]
        for key in ('start_date', 'end_date', 'is_predicted',
                    'jp_start_date', 'global_start_date'):
            self.assertIn(key, entry)
        self.assertFalse(entry['is_predicted'])
        self.assertTrue(entry['start_date'].endswith('Z'))

    def test_league_of_heroes_exposes_resolved_and_predicted_fields(self):
        make_league_of_heroes(name='Confirmed LoH')  # default: confirmed global
        res = self.client.get('/calculator-data')
        entry = res.data['league_of_heroes_event_data'][0]
        for key in ('start_date', 'end_date', 'is_predicted',
                    'jp_start_date', 'global_start_date'):
            self.assertIn(key, entry)
        self.assertFalse(entry['is_predicted'])
        self.assertTrue(entry['start_date'].endswith('Z'))

    def test_champions_meeting_predicts_from_jp_when_global_unconfirmed(self):
        # Anchor: confirmed CM with a JP date. Target: JP-only, so predicted.
        # Δjp = 30d × 0.7 = 21d -> 2025-06-22.
        make_champions_meeting(
            name='Anchor CM', cm_number=1,
            jp_start_date=_dt(2025, 1, 1), jp_end_date=_dt(2025, 1, 8),
            global_start_date=_dt(2025, 6, 1), global_end_date=_dt(2025, 6, 8),
        )
        predicted = make_champions_meeting(
            name='Predicted CM', cm_number=2,
            jp_start_date=_dt(2025, 1, 31), jp_end_date=_dt(2025, 2, 7),
        )
        res = self.client.get('/calculator-data')
        entry = next(c for c in res.data['champions_meeting_data'] if c['id'] == predicted.id)
        self.assertTrue(entry['is_predicted'])
        self.assertEqual(entry['start_date'], '2025-06-22T00:00:00Z')

    def test_league_of_heroes_predicts_from_jp_when_global_unconfirmed(self):
        make_league_of_heroes(
            name='Anchor LoH',
            jp_start_date=_dt(2025, 1, 1), jp_end_date=_dt(2025, 1, 8),
            global_start_date=_dt(2025, 6, 1), global_end_date=_dt(2025, 6, 8),
        )
        predicted = make_league_of_heroes(
            name='Predicted LoH',
            jp_start_date=_dt(2025, 1, 31), jp_end_date=_dt(2025, 2, 7),
        )
        res = self.client.get('/calculator-data')
        entry = next(l for l in res.data['league_of_heroes_event_data'] if l['id'] == predicted.id)
        self.assertTrue(entry['is_predicted'])
        self.assertEqual(entry['start_date'], '2025-06-22T00:00:00Z')

    def test_cm_and_loh_predictions_use_separate_anchors(self):
        # A confirmed CM must NOT act as an anchor for LoH prediction (and vice
        # versa) — each content type resolves against its own map.
        make_champions_meeting(
            name='CM Anchor', cm_number=1,
            jp_start_date=_dt(2025, 1, 1), jp_end_date=_dt(2025, 1, 8),
            global_start_date=_dt(2025, 6, 1), global_end_date=_dt(2025, 6, 8),
        )
        # LoH with only a JP date and NO confirmed LoH anchor -> unresolved,
        # not predicted off the CM anchor.
        loh = make_league_of_heroes(
            name='LoH JP only',
            jp_start_date=_dt(2025, 1, 31), jp_end_date=_dt(2025, 2, 7),
        )
        res = self.client.get('/calculator-data')
        entry = next(l for l in res.data['league_of_heroes_event_data'] if l['id'] == loh.id)
        self.assertFalse(entry['is_predicted'])
        self.assertIsNone(entry['start_date'])


# ── Reference Endpoint Tests ──────────────────────────────────────────────────

class ReferenceEndpointGuestAccessTests(TestCase):
    """Read-only reference endpoints are open to guests."""

    def test_reference_reads_return_200_for_guests(self):
        client = APIClient()
        for url in (
            '/clubranks', '/teamtrialranks', '/championsmeetingranks',
            '/leagueofheroesranks', '/leagueofheroes', '/events', '/eventrewards',
        ):
            with self.subTest(url=url):
                self.assertEqual(client.get(url).status_code, 200)

    def test_event_writes_still_require_admin(self):
        # Guests (and non-admin users) must not be able to write reference data.
        res = APIClient().post('/events', {'name': 'x'})
        self.assertIn(res.status_code, (401, 403))


# ── Calculator PATCH Tests ────────────────────────────────────────────────────

class CalculatorPatchTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client, _ = auth_client(self.user)

    # stats ────────────────────────────────────────────────────────────────────

    def test_patch_stats_updates_user(self):
        res = self.client.patch(
            '/calculator-data',
            {'user_stats_data': {'current_carat': 9999}},
            format='json',
        )
        self.assertEqual(res.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.current_carat, 9999)

    def test_patch_invalid_stats_returns_400(self):
        res = self.client.patch(
            '/calculator-data',
            {'user_stats_data': {'current_carat': 'not-a-number'}},
            format='json',
        )
        self.assertEqual(res.status_code, 400)

    # banner create ────────────────────────────────────────────────────────────

    def test_patch_creates_new_banner(self):
        uma_banner = make_uma_banner()
        res = self.client.patch(
            '/calculator-data',
            {'user_planned_banner_data': [
                {'banner_uma': uma_banner.id, 'banner_support': None, 'number_of_pulls': 5}
            ]},
            format='json',
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(UserPlannedBanner.objects.filter(user=self.user).count(), 1)
        self.assertEqual(UserPlannedBanner.objects.get(user=self.user).number_of_pulls, 5)

    # banner update ────────────────────────────────────────────────────────────

    def test_patch_updates_existing_banner(self):
        uma_banner = make_uma_banner()
        planned = UserPlannedBanner.objects.create(
            user=self.user, banner_uma=uma_banner, number_of_pulls=5
        )
        res = self.client.patch(
            '/calculator-data',
            {'user_planned_banner_data': [
                {'id': planned.id, 'banner_uma': uma_banner.id, 'banner_support': None, 'number_of_pulls': 10}
            ]},
            format='json',
        )
        self.assertEqual(res.status_code, 200)
        planned.refresh_from_db()
        self.assertEqual(planned.number_of_pulls, 10)

    # banner delete ────────────────────────────────────────────────────────────

    def test_patch_deletes_banners_absent_from_request(self):
        uma_banner = make_uma_banner()
        keep = UserPlannedBanner.objects.create(user=self.user, banner_uma=uma_banner, number_of_pulls=5)
        drop = UserPlannedBanner.objects.create(user=self.user, banner_uma=uma_banner, number_of_pulls=3)

        res = self.client.patch(
            '/calculator-data',
            {'user_planned_banner_data': [
                {'id': keep.id, 'banner_uma': uma_banner.id, 'banner_support': None, 'number_of_pulls': 5}
            ]},
            format='json',
        )
        self.assertEqual(res.status_code, 200)
        self.assertTrue(UserPlannedBanner.objects.filter(id=keep.id).exists())
        self.assertFalse(UserPlannedBanner.objects.filter(id=drop.id).exists())

    # ownership ────────────────────────────────────────────────────────────────

    def test_patch_cannot_update_another_users_banner(self):
        """Sending an id that belongs to a different user returns 404."""
        uma_banner = make_uma_banner()
        other_user = make_user('otheruser')
        other_banner = UserPlannedBanner.objects.create(
            user=other_user, banner_uma=uma_banner, number_of_pulls=5
        )
        res = self.client.patch(
            '/calculator-data',
            {'user_planned_banner_data': [
                {'id': other_banner.id, 'banner_uma': uma_banner.id, 'banner_support': None, 'number_of_pulls': 99}
            ]},
            format='json',
        )
        self.assertEqual(res.status_code, 404)
        other_banner.refresh_from_db()
        self.assertEqual(other_banner.number_of_pulls, 5)  # unchanged

    # serializer validation ────────────────────────────────────────────────────

    def test_patch_both_banner_types_returns_400(self):
        """Providing both banner_uma and banner_support violates the XOR constraint."""
        uma_banner = make_uma_banner()
        support_banner = make_support_banner()
        res = self.client.patch(
            '/calculator-data',
            {'user_planned_banner_data': [
                {
                    'banner_uma': uma_banner.id,
                    'banner_support': support_banner.id,
                    'number_of_pulls': 5,
                }
            ]},
            format='json',
        )
        self.assertEqual(res.status_code, 400)

    def test_patch_neither_banner_type_returns_400(self):
        """Omitting both banner fields is invalid even though both are optional individually."""
        res = self.client.patch(
            '/calculator-data',
            {'user_planned_banner_data': [
                {'banner_uma': None, 'banner_support': None, 'number_of_pulls': 5}
            ]},
            format='json',
        )
        self.assertEqual(res.status_code, 400)

    # auth ─────────────────────────────────────────────────────────────────────

    def test_patch_unauthenticated_returns_401(self):
        res = APIClient().patch('/calculator-data', {}, format='json')
        self.assertEqual(res.status_code, 401)

    # NOTE: transaction.atomic() in update_calculator_data only rolls back on
    # an unhandled *exception*, not on an early `return Response(...)`. If stats
    # save succeeds but a banner update then returns a 4xx, the stats change is
    # already committed. This is a known limitation in the current implementation.


# ── Analytics Tests ───────────────────────────────────────────────────────────

class AnalyticsReportEmptyTests(TestCase):
    """build_analytics_report() must survive a completely empty database."""

    def test_empty_db_returns_zeroes_without_errors(self):
        report = build_analytics_report()
        self.assertEqual(report['total_users'], 0)
        self.assertEqual(report['engaged_users'], 0)
        self.assertEqual(report['engaged_pct'], 0.0)
        for product in report['paid_products']:
            self.assertEqual(product['count'], 0)
            self.assertEqual(product['pct_of_total'], 0.0)
            self.assertEqual(product['pct_of_engaged'], 0.0)
        for resource in report['resource_averages']:
            self.assertEqual(resource['avg'], 0)
        self.assertEqual(report['popular_uma_banners'], [])
        self.assertEqual(report['popular_support_banners'], [])


class AnalyticsReportScenarioTests(TestCase):
    """One seeded user base, asserted against every report section.

    The scenario:
      - whale:   both paid flags, Club Rank A, 3000 carats, plans Uma X (10)
                 and Support Y (5)
      - dolphin: training pass only, Club Rank B, 1000 carats, plans Uma X (20)
      - planner: default stats, engaged ONLY through planning Uma Z (5)
      - lurker:  registered but never touched anything (not engaged)
      - staff:   admin account with paid flags and a 100-pull plan — must be
                 invisible to every metric
    """

    @classmethod
    def setUpTestData(cls):
        # income_amount drives display order: B (100) must sort before A (200)
        club_b = ClubRank.objects.create(name='B', income_amount=100)
        club_a = ClubRank.objects.create(name='A', income_amount=200)

        cls.whale = CustomUser.objects.create_user(
            username='whale', password='x',
            daily_carat=True, training_pass=True,
            club_rank=club_a, current_carat=3000,
        )
        cls.dolphin = CustomUser.objects.create_user(
            username='dolphin', password='x',
            training_pass=True, club_rank=club_b, current_carat=1000,
        )
        cls.planner = CustomUser.objects.create_user(username='planner', password='x')
        cls.lurker = CustomUser.objects.create_user(username='lurker', password='x')
        cls.staff = CustomUser.objects.create_user(
            username='staff', password='x', is_staff=True,
            daily_carat=True, training_pass=True,
        )

        timeline = make_timeline()
        uma_x = make_uma_banner(timeline, name='Uma X')
        uma_z = make_uma_banner(timeline, name='Uma Z')
        support_y = make_support_banner(timeline, name='Support Y')

        UserPlannedBanner.objects.create(user=cls.whale, banner_uma=uma_x, number_of_pulls=10)
        UserPlannedBanner.objects.create(user=cls.whale, banner_support=support_y, number_of_pulls=5)
        UserPlannedBanner.objects.create(user=cls.dolphin, banner_uma=uma_x, number_of_pulls=20)
        UserPlannedBanner.objects.create(user=cls.planner, banner_uma=uma_z, number_of_pulls=5)
        UserPlannedBanner.objects.create(user=cls.staff, banner_uma=uma_z, number_of_pulls=100)

        cls.report = build_analytics_report()

    def test_user_counts_exclude_staff(self):
        self.assertEqual(self.report['total_users'], 4)

    def test_engaged_counts_flag_rank_and_banner_users(self):
        # whale + dolphin (stats) + planner (banner only); lurker excluded
        self.assertEqual(self.report['engaged_users'], 3)
        self.assertEqual(self.report['engaged_pct'], 75.0)

    def test_paid_product_percentages(self):
        daily, training = self.report['paid_products'][0], self.report['paid_products'][1]
        self.assertEqual(daily['label'], 'Daily Carat Pack')
        self.assertEqual(daily['count'], 1)          # whale only (staff ignored)
        self.assertEqual(daily['pct_of_total'], 25.0)
        self.assertEqual(daily['pct_of_engaged'], 33.3)
        self.assertEqual(training['label'], 'Training Pass')
        self.assertEqual(training['count'], 2)       # whale + dolphin
        self.assertEqual(training['pct_of_total'], 50.0)
        self.assertEqual(training['pct_of_engaged'], 66.7)

    def test_club_rank_distribution_ordered_by_income_with_not_set(self):
        club = next(d for d in self.report['rank_distributions']
                    if d['label'] == 'Club Rank')
        names = [row['name'] for row in club['rows']]
        self.assertEqual(names, ['B', 'A', 'Not set'])  # income order, not alphabetical
        counts = {row['name']: row['count'] for row in club['rows']}
        self.assertEqual(counts, {'B': 1, 'A': 1, 'Not set': 2})

    def test_unused_rank_type_reports_everyone_not_set(self):
        team_trials = next(d for d in self.report['rank_distributions']
                           if d['label'] == 'Team Trials')
        self.assertEqual(team_trials['rows'],
                         [{'name': 'Not set', 'count': 4, 'pct_of_total': 100.0}])

    def test_resource_averages_use_engaged_denominator(self):
        carats = next(r for r in self.report['resource_averages']
                      if r['label'] == 'Carats')
        # (3000 + 1000 + 0) / 3 engaged users — lurker's zeroes not averaged in
        self.assertEqual(carats['avg'], 1333.3)

    def test_uma_banner_popularity_ranked_and_staff_free(self):
        top, second = self.report['popular_uma_banners']
        self.assertEqual(top['name'], 'Uma X')
        self.assertEqual(top['planners'], 2)
        self.assertEqual(top['total_pulls'], 30)
        self.assertEqual(top['avg_pulls'], 15.0)
        # staff's 100-pull plan on Uma Z must not appear anywhere
        self.assertEqual(second['name'], 'Uma Z')
        self.assertEqual(second['planners'], 1)
        self.assertEqual(second['total_pulls'], 5)

    def test_support_banner_popularity(self):
        (only,) = self.report['popular_support_banners']
        self.assertEqual(only['name'], 'Support Y')
        self.assertEqual(only['planners'], 1)
        self.assertEqual(only['total_pulls'], 5)


# Rendering admin templates resolves {% static %} tags; the production
# whitenoise manifest storage requires collectstatic, which never runs in
# tests. Any test class that renders admin pages swaps in plain storage.
PLAIN_TEST_STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}


@override_settings(STORAGES=PLAIN_TEST_STORAGES)
class AnalyticsDashboardViewTests(TestCase):
    """Access control and response formats for /admin/analytics/."""

    def setUp(self):
        self.url = reverse('admin-analytics')

    def _staff_client(self):
        staff = CustomUser.objects.create_user(
            username='staffer', password='x', is_staff=True)
        self.client.force_login(staff)

    def test_anonymous_redirected_to_admin_login(self):
        res = self.client.get(self.url)
        self.assertEqual(res.status_code, 302)
        self.assertIn('/admin/login/', res.url)

    def test_non_staff_user_redirected_not_served(self):
        self.client.force_login(make_user('regular'))
        res = self.client.get(self.url)
        self.assertEqual(res.status_code, 302)
        self.assertIn('/admin/login/', res.url)

    def test_staff_user_gets_dashboard(self):
        self._staff_client()
        res = self.client.get(self.url)
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'Daily Carat Pack')
        self.assertContains(res, 'Download CSV')

    def test_csv_download(self):
        self._staff_client()
        res = self.client.get(self.url, {'format': 'csv'})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res['Content-Type'], 'text/csv')
        self.assertIn('attachment; filename="analytics-', res['Content-Disposition'])
        body = res.content.decode()
        self.assertIn('Paid Products', body)
        self.assertIn('Popular Uma Banners', body)


# ── Admin UX Tests ────────────────────────────────────────────────────────────

@override_settings(STORAGES=PLAIN_TEST_STORAGES)
class AdminSmokeTests(TestCase):
    """Changelist and add pages render for a superuser.

    Catches admin config mistakes (bad list_display refs, broken fieldsets,
    autocomplete targets without search_fields) that only surface on render.
    """

    CONTENT_URL_NAMES = [
        'admin:calculatorapi_bannertimeline',
        'admin:calculatorapi_banneruma',
        'admin:calculatorapi_bannersupport',
        'admin:calculatorapi_uma',
        'admin:calculatorapi_supportcard',
        'admin:calculatorapi_gameevent',
        'admin:calculatorapi_eventreward',
        'admin:calculatorapi_championsmeeting',
        'admin:calculatorapi_leagueofheroes',
        'admin:calculatorapi_clubrank',
    ]

    @classmethod
    def setUpTestData(cls):
        cls.superuser = CustomUser.objects.create_superuser(
            username='boss', password='x')

    def setUp(self):
        self.client.force_login(self.superuser)

    def test_changelists_render(self):
        for base in self.CONTENT_URL_NAMES:
            with self.subTest(url=f'{base}_changelist'):
                res = self.client.get(reverse(f'{base}_changelist'))
                self.assertEqual(res.status_code, 200)

    def test_add_forms_render(self):
        for base in self.CONTENT_URL_NAMES:
            with self.subTest(url=f'{base}_add'):
                res = self.client.get(reverse(f'{base}_add'))
                self.assertEqual(res.status_code, 200)

    def test_index_shows_friendly_names(self):
        res = self.client.get(reverse('admin:index'))
        self.assertContains(res, 'Uma Musume Data')      # app section heading
        self.assertContains(res, 'Uma banners')          # was "Banner umas"
        self.assertContains(res, 'League of Heroes events')
        self.assertNotContains(res, 'League of heroess')  # the old plural bug

    def test_join_models_not_registered_top_level(self):
        # Edited via inlines only — their changelists should not exist.
        for name in ['umasonumabanner', 'supportsonsupportbanner',
                     'championsmeetingumarecommendation']:
            with self.subTest(model=name):
                with self.assertRaises(NoReverseMatch):
                    reverse(f'admin:calculatorapi_{name}_changelist')


@override_settings(STORAGES=PLAIN_TEST_STORAGES)
class ContentEditorPermissionTests(TestCase):
    """The "Content editors" group can manage content but never user data."""

    @classmethod
    def setUpTestData(cls):
        call_command('create_content_editor_group', stdout=StringIO())
        cls.editor = CustomUser.objects.create_user(
            username='editor', password='x', is_staff=True)
        cls.editor.groups.add(Group.objects.get(name='Content editors'))

    def setUp(self):
        self.client.force_login(self.editor)

    def test_editor_can_open_banner_changelist(self):
        res = self.client.get(reverse('admin:calculatorapi_banneruma_changelist'))
        self.assertEqual(res.status_code, 200)

    def test_editor_can_open_rank_changelist(self):
        res = self.client.get(reverse('admin:calculatorapi_clubrank_changelist'))
        self.assertEqual(res.status_code, 200)

    def test_editor_cannot_open_user_changelist(self):
        res = self.client.get(reverse('admin:calculatorapi_customuser_changelist'))
        self.assertEqual(res.status_code, 403)

    def test_editor_cannot_open_planned_banner_changelist(self):
        res = self.client.get(
            reverse('admin:calculatorapi_userplannedbanner_changelist'))
        self.assertEqual(res.status_code, 403)

    def test_editor_index_hides_user_models(self):
        res = self.client.get(reverse('admin:index'))
        self.assertNotContains(
            res, reverse('admin:calculatorapi_customuser_changelist'))
        self.assertNotContains(res, 'User planned banners')


class ContentEditorGroupCommandTests(TestCase):
    """create_content_editor_group is idempotent and scoped to content only."""

    def test_command_is_idempotent(self):
        call_command('create_content_editor_group', stdout=StringIO())
        call_command('create_content_editor_group', stdout=StringIO())
        self.assertEqual(Group.objects.filter(name='Content editors').count(), 1)
        group = Group.objects.get(name='Content editors')
        # 18 content models x 4 permissions (add/change/delete/view)
        self.assertEqual(group.permissions.count(), 72)

    def test_command_grants_no_user_data_permissions(self):
        call_command('create_content_editor_group', stdout=StringIO())
        codenames = set(
            Group.objects.get(name='Content editors')
            .permissions.values_list('codename', flat=True)
        )
        for forbidden in ['change_customuser', 'delete_customuser',
                          'change_userplannedbanner', 'view_userplannedbanner',
                          'change_token']:
            self.assertNotIn(forbidden, codenames)


# ── Changelog Endpoint Tests ──────────────────────────────────────────────────

class ChangelogEndpointTests(TestCase):
    """The public /changelog endpoint lists entries newest-first with nested,
    ordered changes; writes stay admin-only."""

    def setUp(self):
        # Two entries out of date order so we can assert sorting.
        older = ChangelogEntry.objects.create(
            title='Initial release', version='v1.0',
            date=datetime.date(2026, 7, 1),
        )
        newer = ChangelogEntry.objects.create(
            title='Changelog added', version='v1.1',
            date=datetime.date(2026, 7, 16),
        )
        # Create changes out of `order` so we can assert they come back sorted.
        ChangelogChange.objects.create(
            entry=newer, category=ChangelogChange.CHANGED,
            text='Faster banner sorting.', order=2,
        )
        ChangelogChange.objects.create(
            entry=newer, category=ChangelogChange.ADDED,
            text='Changelog page.', order=0,
        )
        self.newer, self.older = newer, older

    def test_list_is_public_and_newest_first(self):
        res = APIClient().get('/changelog')
        self.assertEqual(res.status_code, 200)
        titles = [e['title'] for e in res.json()]
        self.assertEqual(titles, ['Changelog added', 'Initial release'])

    def test_nested_changes_are_ordered(self):
        res = APIClient().get('/changelog')
        newest = res.json()[0]
        # Sorted by ChangelogChange.Meta.ordering ("order", "id").
        self.assertEqual(
            [c['order'] for c in newest['changes']], [0, 2]
        )
        self.assertEqual(
            [c['category'] for c in newest['changes']], ['added', 'changed']
        )

    def test_retrieve_is_public(self):
        res = APIClient().get(f'/changelog/{self.newer.id}')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()['version'], 'v1.1')

    def test_writes_require_admin(self):
        # Guests and non-admin users cannot create entries.
        guest = APIClient().post('/changelog', {'title': 'x', 'date': '2026-07-17'})
        self.assertIn(guest.status_code, (401, 403))
        user_client, _ = auth_client(make_user())
        res = user_client.post('/changelog', {'title': 'x', 'date': '2026-07-17'})
        self.assertIn(res.status_code, (401, 403))

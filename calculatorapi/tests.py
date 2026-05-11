import datetime

from django.test import TestCase
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from calculatorapi.models import (
    CustomUser,
    ClubRank, TeamTrialsRank, ChampionsMeetingRank, LeagueOfHeroesRank,
    BannerTimeline, BannerUma, BannerSupport, UserPlannedBanner,
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


def make_timeline(name='Test Timeline'):
    now = timezone.now()
    return BannerTimeline.objects.create(
        name=name,
        start_date=now,
        end_date=now + datetime.timedelta(days=30),
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

    def test_unauthenticated_returns_401(self):
        res = APIClient().get('/calculator-data')
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

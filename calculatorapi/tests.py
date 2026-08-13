"""
Test suite for calculatorapi.

Four of pylint's size heuristics are switched off for this module, and only
this module. They measure things that are virtues in a test file and defects
in a production one:

  too-many-lines                 one suite per app, kept together so a reader
                                 greps one file; splitting it into a package to
                                 satisfy a 1000-line default would scatter
                                 related cases without making any of them clearer
  too-many-arguments             fixture factories take a parameter per field
  too-many-positional-arguments  they are called positionally, by design
  too-many-instance-attributes   a setUp that builds a scenario assigns one
                                 attribute per object under test

Everything else pylint checks still applies here.
"""

# pylint: disable=too-many-lines,too-many-arguments,too-many-positional-arguments
# pylint: disable=too-many-instance-attributes

import csv
import datetime
import os
import shutil
import tempfile
from io import StringIO
from unittest.mock import patch

from django.contrib.auth.models import Group
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import NoReverseMatch, reverse
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from calculatorapi import image_library, support_backfill
from calculatorapi.image_library import (
    image_prefixes,
    invalidate,
    is_valid_key,
    list_images,
    listing_is_cached,
    normalize_prefix,
)
from calculatorapi.analytics import build_analytics_report
from calculatorapi.ledger import AMOUNT_FIELDS, build_income_ledger
from calculatorapi.views.ledger import IncomeLedgerRowSerializer
from calculatorapi.predictions import (
    PREDICTION_FACTOR,
    GAME_EVENT_END_DATE_BUFFER,
    build_game_event_date_map,
    apply_schedule_offsets,
    compute_effective_dates,
    game_event_effective_dates,
    game_event_confirmed_dates,
    build_effective_date_map,
    build_effective_date_maps,
    build_anniversary_event_date_map,
)
from calculatorapi.eligibility import build_first_jp_date_maps, is_eligible
from calculatorapi.management.commands.create_content_editor_group import CONTENT_MODELS
from calculatorapi.models import (
    CustomUser, Uma, SupportCard,
    ClubRank, TeamTrialsRank, ChampionsMeetingRank, LeagueOfHeroesRank,
    BannerTimeline, BannerUma, BannerSupport, UserPlannedBanner,
    ChampionsMeeting, LeagueOfHeroes, GameEvent,
    ChangelogEntry, ChangelogChange,
    SocialAccount,
    CalculationConstants,
    AnniversaryEvent, AnniversaryEventBanner, AnniversaryEventProduct,
    UserPlannedPurchase, UmasOnUmaBanner, SupportsOnSupportBanner,
    BannerCategory,
)

# Smallest valid PNG (1x1, transparent). ImageField runs Pillow over uploads,
# so the upload-vs-library test needs real image bytes, not arbitrary content.
PNG_1PX = (
    b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
    b'\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01'
    b'\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82'
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_ranks():
    """Create one of each rank type with zero income — minimal valid FKs for CustomUser."""
    club = ClubRank.objects.create(name='None', income_amount=0)
    tt = TeamTrialsRank.objects.create(name='None', income_amount=0)
    cm = ChampionsMeetingRank.objects.create(name='None', income_amount=0)
    loh = LeagueOfHeroesRank.objects.create(name='None', income_amount=0)
    return club, tt, cm, loh


def make_user(username='testuser', password='testpass123', is_staff=False):
    """Create a CustomUser with all required FK ranks set.

    `is_staff` matters for /login, which is staff-only now that ordinary
    accounts sign in through Google/Discord.
    """
    club, tt, cm, loh = make_ranks()
    return CustomUser.objects.create_user(
        username=username,
        password=password,
        email=f'{username}@test.com',
        first_name='Test',
        last_name='User',
        is_staff=is_staff,
        club_rank=club,
        team_trials_rank=tt,
        champions_meeting_rank=cm,
        league_of_heroes_rank=loh,
    )


def make_timeline(name='Test Timeline', jp_start_date=None, jp_end_date=None,
                  global_start_date=None, global_end_date=None,
                  schedule_offset_days=0):
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
        schedule_offset_days=schedule_offset_days,
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
                           global_end_date=None, schedule_offset_days=0):
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
        schedule_offset_days=schedule_offset_days,
        track='Tokyo', surface_type='Turf', distance='Long', length='2400m',
        track_condition='Good', season='Spring', weather='Sunny', direction='Right',
        speed_recommendation=0, stamina_recommendation=0, power_recommendation=0,
        guts_recommendation=0, wit_recommendation=0,
    )


def make_league_of_heroes(name='Test LoH', jp_start_date=None, jp_end_date=None,
                          global_start_date=None, global_end_date=None,
                          schedule_offset_days=0):
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
        schedule_offset_days=schedule_offset_days,
    )


def make_game_event(name='Test Event', banner_timeline=None, **reward_fields):
    """Create a GameEvent, optionally linked to a BannerTimeline. Dates are
    always derived from banner_timeline (or null when unlinked) — GameEvent
    has no date fields of its own. Reward amounts (carat_amount,
    carats_throughout, etc.) can be passed as kwargs; they default to 0."""
    return GameEvent.objects.create(name=name, banner_timeline=banner_timeline, **reward_fields)


def make_anniversary_event(name='Test Anniversary', event_type='anniversary',
                           jp_cutoff_date=None, parts=(), products=()):
    """Create an AnniversaryEvent, its banner-part links and its products.

    `parts` is an iterable of BannerTimeline (linked as Part 1, 2, ... in order).
    `products` is an iterable of kwargs dicts for AnniversaryEventProduct.
    Dates come entirely from the linked parts -- the event has none of its own.
    """
    event = AnniversaryEvent.objects.create(
        name=name, event_type=event_type, jp_cutoff_date=jp_cutoff_date,
    )
    for index, timeline in enumerate(parts, start=1):
        AnniversaryEventBanner.objects.create(
            anniversary_event=event, banner_timeline=timeline, part_number=index,
        )
    for product_kwargs in products:
        AnniversaryEventProduct.objects.create(anniversary_event=event, **product_kwargs)
    return event


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

    # register ─────────────────────────────────────────────────────────────────

    def test_register_endpoint_no_longer_exists(self):
        """Public sign-up was removed when accounts moved to Google/Discord."""
        res = self.client.post('/register', {
            'username': 'newuser', 'password': 'StrongPass123!',
            'email': 'new@test.com', 'first_name': 'New', 'last_name': 'User',
        }, format='json')
        self.assertEqual(res.status_code, 404)
        self.assertFalse(CustomUser.objects.filter(username='newuser').exists())

    def test_register_route_is_not_reversible(self):
        with self.assertRaises(NoReverseMatch):
            reverse('register')

    # login (staff only) ───────────────────────────────────────────────────────

    def test_staff_login_returns_200_and_token(self):
        make_user('staffuser', 'correctpass', is_staff=True)
        res = self.client.post('/login', {'username': 'staffuser', 'password': 'correctpass'}, format='json')
        self.assertEqual(res.status_code, 200)
        self.assertIn('token', res.data)

    def test_non_staff_login_rejected_despite_correct_password(self):
        """Ordinary accounts must go through a provider, even if a password
        somehow remains set on the row."""
        make_user('loginuser', 'correctpass')
        res = self.client.post('/login', {'username': 'loginuser', 'password': 'correctpass'}, format='json')
        self.assertEqual(res.status_code, 400)
        self.assertNotIn('token', res.data)

    def test_non_staff_rejection_is_indistinguishable_from_wrong_password(self):
        """Same status AND same body, so /login can't be used to discover which
        usernames exist."""
        make_user('loginuser', 'correctpass')
        valid_pw = self.client.post('/login', {'username': 'loginuser', 'password': 'correctpass'}, format='json')
        wrong_pw = self.client.post('/login', {'username': 'loginuser', 'password': 'wrongpass'}, format='json')
        no_such_user = self.client.post('/login', {'username': 'nobody', 'password': 'whatever'}, format='json')
        self.assertEqual(valid_pw.status_code, wrong_pw.status_code, no_such_user.status_code)
        self.assertEqual(valid_pw.data, wrong_pw.data)
        self.assertEqual(valid_pw.data, no_such_user.data)

    def test_login_wrong_password_returns_400(self):
        make_user('staffuser', 'correctpass', is_staff=True)
        res = self.client.post('/login', {'username': 'staffuser', 'password': 'wrongpass'}, format='json')
        self.assertEqual(res.status_code, 400)

    def test_login_nonexistent_user_returns_400(self):
        res = self.client.post('/login', {'username': 'nobody', 'password': 'whatever'}, format='json')
        self.assertEqual(res.status_code, 400)

    def test_social_user_with_unusable_password_cannot_login(self):
        """A social account has no usable password; an empty/blank attempt must
        not slip through Django's authenticate()."""
        user = make_user('socialuser')
        user.set_unusable_password()
        user.save()
        for attempt in ('', '!', 'testpass123'):
            res = self.client.post('/login', {'username': 'socialuser', 'password': attempt}, format='json')
            self.assertEqual(res.status_code, 400, f'password {attempt!r} was accepted')

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


# Swaps out whitenoise's manifest static storage, which raises on any admin
# template that references a static file unless collectstatic has been run.
# Defined here rather than beside its first user so every test class below can
# reach it.
PLAIN_TEST_STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}


def _dt(y, m, d):
    return datetime.datetime(y, m, d, tzinfo=_UTC)


def _predicted(anchor_global_start, jp_gap_days, offset_days=0):
    """Predicted global start for a row whose JP start is `jp_gap_days` after
    the anchor's, plus any schedule offset already applied.

    Derived from PREDICTION_FACTOR rather than hardcoded, so retuning the factor
    doesn't mean rewriting every expectation in this file. The one deliberate
    exception is test_fixed_anchor_worked_example, which pins concrete numbers
    on purpose — that's what makes it a worked example."""
    return (anchor_global_start
            + datetime.timedelta(days=jp_gap_days) * PREDICTION_FACTOR
            + datetime.timedelta(days=offset_days))


def _iso(value):
    """Format a datetime exactly as DRF's DateTimeField renders it on the wire."""
    text = value.isoformat()
    return text[:-6] + 'Z' if text.endswith('+00:00') else text


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
        # Δjp = 30d × 0.664 = 19.92d -> 2025-06-20 22:04:48; banner runs 7d.
        # Deliberately hardcoded: this is the one test that pins the arithmetic,
        # so retuning PREDICTION_FACTOR should fail here and nowhere else.
        self.assertEqual(out["start_date"], datetime.datetime(2025, 6, 20, 22, 4, 48, tzinfo=_UTC))
        self.assertEqual(out["end_date"], datetime.datetime(2025, 6, 27, 22, 4, 48, tzinfo=_UTC))
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
        self.assertEqual(out["start_date"], _predicted(_dt(2025, 6, 1), 30))
        self.assertIsNone(out["end_date"])
        self.assertTrue(out["is_predicted"])


# ── Schedule offsets (pure, DB-free) ──────────────────────────────────────────

def _entry(start, end=None, is_predicted=True, offset_days=0, anchor_start=None):
    """Build one effective-date map entry by hand, matching the shape
    compute_effective_dates produces.

    `anchor_start` defaults to None — i.e. "this map records no anchor", which
    is how a hand-built map behaves, so the tests below that don't care about
    anchors read exactly as they did before it existed.
    """
    return {
        "start_date": start,
        "end_date": end,
        "is_predicted": is_predicted,
        "offset_days": offset_days,
        "applied_offset_days": 0,
        "anchor_start": anchor_start,
    }


class ScheduleOffsetUnitTests(TestCase):
    """Directly exercises apply_schedule_offsets on hand-built maps (no DB).

    An offset pushes its own row AND every dated row after it, across every
    content type at once, and offsets stack.
    """

    def test_offset_shifts_the_row_carrying_it(self):
        emap = {1: _entry(_dt(2025, 8, 24), _dt(2025, 8, 31), offset_days=7)}
        apply_schedule_offsets([emap])
        self.assertEqual(emap[1]['start_date'], _dt(2025, 8, 31))
        self.assertEqual(emap[1]['applied_offset_days'], 7)

    def test_rows_before_the_offset_are_unchanged(self):
        emap = {
            1: _entry(_dt(2025, 8, 10)),
            2: _entry(_dt(2025, 8, 24), offset_days=7),
        }
        apply_schedule_offsets([emap])
        self.assertEqual(emap[1]['start_date'], _dt(2025, 8, 10))
        self.assertEqual(emap[1]['applied_offset_days'], 0)

    def test_rows_after_the_offset_shift_by_the_same_amount(self):
        emap = {
            1: _entry(_dt(2025, 8, 24), offset_days=7),
            2: _entry(_dt(2025, 9, 7)),
            3: _entry(_dt(2025, 9, 21)),
        }
        apply_schedule_offsets([emap])
        self.assertEqual(emap[2]['start_date'], _dt(2025, 9, 14))
        self.assertEqual(emap[3]['start_date'], _dt(2025, 9, 28))

    def test_offsets_stack(self):
        emap = {
            1: _entry(_dt(2025, 8, 24), offset_days=7),
            2: _entry(_dt(2025, 9, 12), offset_days=3),
            3: _entry(_dt(2025, 9, 21)),
        }
        apply_schedule_offsets([emap])
        self.assertEqual(emap[1]['applied_offset_days'], 7)
        # Row 2 gets row 1's +7 as well as its own +3.
        self.assertEqual(emap[2]['applied_offset_days'], 10)
        self.assertEqual(emap[2]['start_date'], _dt(2025, 9, 22))
        self.assertEqual(emap[3]['applied_offset_days'], 10)
        self.assertEqual(emap[3]['start_date'], _dt(2025, 10, 1))

    def test_end_date_shifts_by_the_same_amount(self):
        emap = {1: _entry(_dt(2025, 8, 24), _dt(2025, 8, 31), offset_days=7)}
        apply_schedule_offsets([emap])
        # Both ends move together, so the run length is preserved.
        self.assertEqual(emap[1]['start_date'], _dt(2025, 8, 31))
        self.assertEqual(emap[1]['end_date'], _dt(2025, 9, 7))

    def test_null_end_date_stays_null(self):
        emap = {1: _entry(_dt(2025, 8, 24), None, offset_days=7)}
        apply_schedule_offsets([emap])
        self.assertEqual(emap[1]['start_date'], _dt(2025, 8, 31))
        self.assertIsNone(emap[1]['end_date'])

    def test_confirmed_row_after_an_offset_is_never_shifted(self):
        emap = {
            1: _entry(_dt(2025, 8, 24), offset_days=7),
            2: _entry(_dt(2025, 9, 7), is_predicted=False),
        }
        apply_schedule_offsets([emap])
        self.assertEqual(emap[2]['start_date'], _dt(2025, 9, 7))
        self.assertEqual(emap[2]['applied_offset_days'], 0)

    def test_confirmed_rows_own_offset_does_not_cascade(self):
        """The self-healing property. Once a slipped row is confirmed it becomes
        the anchor, so its real date already carries the slip — a still-live
        offset would count the same delay twice."""
        emap = {
            1: _entry(_dt(2025, 8, 24), is_predicted=False, offset_days=7),
            2: _entry(_dt(2025, 9, 7)),
        }
        apply_schedule_offsets([emap])
        self.assertEqual(emap[2]['start_date'], _dt(2025, 9, 7))
        self.assertEqual(emap[2]['applied_offset_days'], 0)

    def test_offset_crosses_content_types(self):
        """One shared calendar: a banner offset moves later Champions Meetings
        and League of Heroes events too, unlike anchors which stay per-model."""
        banners = {1: _entry(_dt(2025, 8, 24), offset_days=7)}
        meetings = {1: _entry(_dt(2025, 9, 2))}
        leagues = {1: _entry(_dt(2025, 9, 5))}
        apply_schedule_offsets([banners, meetings, leagues])
        self.assertEqual(meetings[1]['start_date'], _dt(2025, 9, 9))
        self.assertEqual(leagues[1]['start_date'], _dt(2025, 9, 12))

    def test_offset_from_another_content_type_stacks(self):
        banners = {1: _entry(_dt(2025, 8, 24), offset_days=7), 2: _entry(_dt(2025, 9, 21))}
        leagues = {1: _entry(_dt(2025, 9, 12), offset_days=3)}
        apply_schedule_offsets([banners, leagues])
        # The banner at 2025-09-21 is behind both the banner +7 and the LoH +3.
        self.assertEqual(banners[2]['applied_offset_days'], 10)
        self.assertEqual(banners[2]['start_date'], _dt(2025, 10, 1))

    def test_unresolved_rows_are_untouched(self):
        emap = {
            1: _entry(_dt(2025, 8, 24), offset_days=7),
            2: _entry(None, None, is_predicted=False),
        }
        apply_schedule_offsets([emap])
        self.assertIsNone(emap[2]['start_date'])
        self.assertEqual(emap[2]['applied_offset_days'], 0)

    def test_offset_on_a_row_with_no_resolved_date_is_ignored(self):
        """Nothing to order it against, so it can't say what comes 'after' it."""
        emap = {
            1: _entry(None, None, is_predicted=False, offset_days=7),
            2: _entry(_dt(2025, 9, 7)),
        }
        apply_schedule_offsets([emap])
        self.assertEqual(emap[2]['start_date'], _dt(2025, 9, 7))

    def test_negative_offset_pulls_dates_earlier(self):
        emap = {
            1: _entry(_dt(2025, 8, 24), offset_days=-7),
            2: _entry(_dt(2025, 9, 7)),
        }
        apply_schedule_offsets([emap])
        self.assertEqual(emap[1]['start_date'], _dt(2025, 8, 17))
        self.assertEqual(emap[2]['start_date'], _dt(2025, 8, 31))

    def test_no_offsets_leaves_everything_alone(self):
        emap = {1: _entry(_dt(2025, 8, 24), _dt(2025, 8, 31))}
        apply_schedule_offsets([emap])
        self.assertEqual(emap[1]['start_date'], _dt(2025, 8, 24))
        self.assertEqual(emap[1]['end_date'], _dt(2025, 8, 31))
        self.assertEqual(emap[1]['applied_offset_days'], 0)

    def test_offset_at_or_before_the_targets_anchor_is_not_applied(self):
        """The anchor's global date is a fact, and the prediction was measured
        forward from it — so a slip that happened before it is already inside
        the number being shifted here. Applying it again double-counts."""
        banners = {1: _entry(_dt(2025, 8, 24), offset_days=7)}
        # Predicted from an anchor that sits AFTER the banner slip.
        leagues = {1: _entry(_dt(2025, 10, 1), anchor_start=_dt(2025, 9, 1))}
        apply_schedule_offsets([banners, leagues])
        self.assertEqual(leagues[1]['start_date'], _dt(2025, 10, 1))
        self.assertEqual(leagues[1]['applied_offset_days'], 0)

    def test_offset_after_the_targets_anchor_still_applies(self):
        """The other half of the rule: a slip the anchor could not have known
        about is genuinely new, so it must still cascade."""
        banners = {1: _entry(_dt(2025, 9, 15), offset_days=7)}
        leagues = {1: _entry(_dt(2025, 10, 1), anchor_start=_dt(2025, 9, 1))}
        apply_schedule_offsets([banners, leagues])
        self.assertEqual(leagues[1]['start_date'], _dt(2025, 10, 8))
        self.assertEqual(leagues[1]['applied_offset_days'], 7)

    def test_anchor_filter_is_per_map_not_global(self):
        """Each map is filtered by its OWN anchor. A banner predicted off an
        early anchor still takes the slip that a later-anchored LoH ignores."""
        banners = {
            1: _entry(_dt(2025, 8, 24), offset_days=7, anchor_start=_dt(2025, 6, 1)),
            2: _entry(_dt(2025, 10, 1), anchor_start=_dt(2025, 6, 1)),
        }
        leagues = {1: _entry(_dt(2025, 10, 1), anchor_start=_dt(2025, 9, 1))}
        apply_schedule_offsets([banners, leagues])
        self.assertEqual(banners[2]['applied_offset_days'], 7)
        self.assertEqual(leagues[1]['applied_offset_days'], 0)

    def test_build_effective_date_maps_does_not_double_count_a_late_anchor(self):
        """End-to-end regression for the League of Heroes shape: a model whose
        only globally-dated row sits AFTER a banner slip, with that row's date
        taken from the already-slip-corrected calendar. Every later row of that
        model used to inherit the slip through the anchor and then be shifted by
        it again — a constant ~7-day lateness against the source spreadsheet."""
        make_timeline(
            name='Anchor',
            jp_start_date=_dt(2025, 1, 1), jp_end_date=_dt(2025, 1, 8),
            global_start_date=_dt(2025, 6, 1), global_end_date=_dt(2025, 6, 8),
        )
        make_timeline(
            name='Slipped',
            jp_start_date=_dt(2025, 1, 31), jp_end_date=_dt(2025, 2, 7),
            schedule_offset_days=7,
        )
        # The LoH anchor's global date is late enough to already contain the
        # banner's +7 (the banner resolves to ~2025-06-28 once shifted).
        make_league_of_heroes(
            name='LoH Anchor',
            jp_start_date=_dt(2025, 2, 1), jp_end_date=_dt(2025, 2, 8),
            global_start_date=_dt(2025, 8, 1), global_end_date=_dt(2025, 8, 8),
        )
        make_league_of_heroes(
            name='LoH Later',
            jp_start_date=_dt(2025, 3, 3), jp_end_date=_dt(2025, 3, 10),
        )

        maps = build_effective_date_maps()
        later = maps[LeagueOfHeroes][LeagueOfHeroes.objects.get(name='LoH Later').id]

        # Pure anchor math, with NO offset on top.
        self.assertEqual(later['start_date'], _predicted(_dt(2025, 8, 1), 30))
        self.assertEqual(later['applied_offset_days'], 0)

    def test_build_effective_date_maps_applies_offsets_across_models(self):
        """The ORM wrapper: per-model anchors, one shared offset pass."""
        make_timeline(
            name='Anchor',
            jp_start_date=_dt(2025, 1, 1), jp_end_date=_dt(2025, 1, 8),
            global_start_date=_dt(2025, 6, 1), global_end_date=_dt(2025, 6, 8),
        )
        # Predicted off the banner anchor, then pushed 7 days by its own offset.
        make_timeline(
            name='Slipped',
            jp_start_date=_dt(2025, 1, 31), jp_end_date=_dt(2025, 2, 7),
            schedule_offset_days=7,
        )
        # A Champions Meeting predicted off its OWN anchor to a date after the
        # banner slip, so it inherits the +7 on top.
        make_champions_meeting(
            name='CM Anchor', cm_number=1,
            jp_start_date=_dt(2025, 2, 1), jp_end_date=_dt(2025, 2, 8),
            global_start_date=_dt(2025, 6, 10), global_end_date=_dt(2025, 6, 17),
        )
        make_champions_meeting(
            name='CM Later', cm_number=2,
            jp_start_date=_dt(2025, 3, 3), jp_end_date=_dt(2025, 3, 10),
        )

        maps = build_effective_date_maps()
        banner = maps[BannerTimeline][BannerTimeline.objects.get(name='Slipped').id]
        meeting = maps[ChampionsMeeting][ChampionsMeeting.objects.get(name='CM Later').id]

        self.assertEqual(banner['start_date'], _predicted(_dt(2025, 6, 1), 30, offset_days=7))
        self.assertEqual(banner['applied_offset_days'], 7)
        self.assertEqual(meeting['start_date'], _predicted(_dt(2025, 6, 10), 30, offset_days=7))
        self.assertEqual(meeting['applied_offset_days'], 7)


class GameEventPredictionTests(TestCase):
    """game_event_effective_dates/game_event_confirmed_dates: GameEvent has no
    date fields of its own, so these resolve purely via the linked
    BannerTimeline's own (already-built) effective-date map."""

    def test_confirmed_banner_gives_end_date_plus_buffer(self):
        timeline = make_timeline(
            name='Confirmed',
            global_start_date=_dt(2025, 6, 1), global_end_date=_dt(2025, 6, 8),
        )
        event = make_game_event(banner_timeline=timeline)
        emap = build_effective_date_map()
        out = game_event_effective_dates(event, emap)
        self.assertEqual(out['start_date'], _dt(2025, 6, 1))
        self.assertEqual(out['end_date'], _dt(2025, 6, 8) + GAME_EVENT_END_DATE_BUFFER)
        self.assertFalse(out['is_predicted'])

    def test_predicted_banner_propagates_is_predicted(self):
        make_timeline(
            name='Anchor',
            jp_start_date=_dt(2025, 1, 1), jp_end_date=_dt(2025, 1, 8),
            global_start_date=_dt(2025, 6, 1), global_end_date=_dt(2025, 6, 8),
        )
        predicted_tl = make_timeline(
            name='Predicted',
            jp_start_date=_dt(2025, 1, 31), jp_end_date=_dt(2025, 2, 7),
        )
        event = make_game_event(banner_timeline=predicted_tl)
        emap = build_effective_date_map()
        out = game_event_effective_dates(event, emap)
        # Banner runs 7d from its predicted start; the event's end trails by the buffer.
        predicted_start = _predicted(_dt(2025, 6, 1), 30)
        self.assertTrue(out['is_predicted'])
        self.assertEqual(out['start_date'], predicted_start)
        self.assertEqual(out['end_date'],
                         predicted_start + datetime.timedelta(days=7) + GAME_EVENT_END_DATE_BUFFER)

    def test_unlinked_event_resolves_to_null(self):
        event = make_game_event(banner_timeline=None)
        emap = build_effective_date_map()
        out = game_event_effective_dates(event, emap)
        self.assertIsNone(out['start_date'])
        self.assertIsNone(out['end_date'])
        self.assertFalse(out['is_predicted'])

    def test_linked_but_unresolvable_banner_resolves_to_null(self):
        # A banner with neither JP nor global dates has no resolvable entry.
        timeline = make_timeline(name='No dates at all')
        timeline.global_start_date = None
        timeline.global_end_date = None
        timeline.save()
        event = make_game_event(banner_timeline=timeline)
        emap = build_effective_date_map()
        out = game_event_effective_dates(event, emap)
        self.assertIsNone(out['start_date'])
        self.assertFalse(out['is_predicted'])

    def test_confirmed_dates_never_predicts(self):
        # game_event_confirmed_dates (used by the standalone /events route)
        # must show null rather than a prediction for a JP-only banner.
        make_timeline(
            name='Anchor',
            jp_start_date=_dt(2025, 1, 1), jp_end_date=_dt(2025, 1, 8),
            global_start_date=_dt(2025, 6, 1), global_end_date=_dt(2025, 6, 8),
        )
        predicted_tl = make_timeline(
            name='Predicted',
            jp_start_date=_dt(2025, 1, 31), jp_end_date=_dt(2025, 2, 7),
        )
        event = make_game_event(banner_timeline=predicted_tl)
        event = GameEvent.objects.select_related('banner_timeline').get(pk=event.pk)
        out = game_event_confirmed_dates(event)
        self.assertIsNone(out['start_date'])
        self.assertFalse(out['is_predicted'])

    def test_confirmed_dates_reads_raw_banner_dates(self):
        timeline = make_timeline(
            name='Confirmed',
            global_start_date=_dt(2025, 6, 1), global_end_date=_dt(2025, 6, 8),
        )
        event = make_game_event(banner_timeline=timeline)
        event = GameEvent.objects.select_related('banner_timeline').get(pk=event.pk)
        out = game_event_confirmed_dates(event)
        self.assertEqual(out['start_date'], _dt(2025, 6, 1))
        self.assertEqual(out['end_date'], _dt(2025, 6, 8) + GAME_EVENT_END_DATE_BUFFER)
        self.assertFalse(out['is_predicted'])

    def test_confirmed_dates_unlinked_is_null(self):
        event = make_game_event(banner_timeline=None)
        out = game_event_confirmed_dates(event)
        self.assertIsNone(out['start_date'])
        self.assertFalse(out['is_predicted'])


class GameEventBannerTimelineDeletionTests(TestCase):
    """GameEvent.banner_timeline is SET_NULL, not CASCADE -- an event's own
    content (image, reward amounts) outlives its linked banner."""

    def test_deleting_banner_timeline_sets_game_event_banner_timeline_null(self):
        timeline = make_timeline(name='Doomed Banner')
        event = make_game_event(name='Survives', banner_timeline=timeline, carat_amount=100)

        timeline.delete()

        event.refresh_from_db()
        self.assertIsNone(event.banner_timeline_id)
        self.assertTrue(GameEvent.objects.filter(pk=event.pk).exists())
        self.assertEqual(event.carat_amount, 100)


class CalculationConstantsTests(TestCase):
    """The singleton holding every tunable number the projection uses."""

    def test_load_creates_one_row_and_returns_it_thereafter(self):
        first = CalculationConstants.load()
        second = CalculationConstants.load()
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(CalculationConstants.objects.count(), 1)

    def test_saving_a_second_instance_overwrites_the_first(self):
        # save() pins the pk, so a second row cannot exist even from the shell.
        CalculationConstants.load()
        CalculationConstants(pull_cost_carats=999).save()
        self.assertEqual(CalculationConstants.objects.count(), 1)
        self.assertEqual(CalculationConstants.load().pull_cost_carats, 999)

    def test_delete_is_refused(self):
        constants = CalculationConstants.load()
        constants.delete()
        self.assertEqual(CalculationConstants.objects.count(), 1)

    def test_defaults_match_the_current_calibration(self):
        # A fresh database must start correct rather than zeroed.
        constants = CalculationConstants.load()
        self.assertEqual(constants.daily_base_carats, 75)
        self.assertEqual(constants.weekly_bonus_carats, 150)
        self.assertEqual(constants.pull_cost_carats, 150)
        # 1800/month = the 60/day the projection currently uses. The sheet says
        # 3000; closing that gap is a deliberate parity change, not a default.
        self.assertEqual(constants.misc_earnings_monthly, 1800)
        self.assertEqual(float(constants.prediction_factor), PREDICTION_FACTOR)
        self.assertEqual(
            constants.game_event_end_buffer_days, GAME_EVENT_END_DATE_BUFFER.days
        )

    def test_endpoint_serves_the_constants_as_numbers(self):
        res = APIClient().get('/calculator-data')
        self.assertEqual(res.status_code, 200)
        payload = res.data['calculation_constants']
        self.assertEqual(payload['daily_base_carats'], 75)
        # Decimals must arrive as numbers, not DRF's default strings: the client
        # multiplies by them, and "0.664" * 2 is a silent NaN in JavaScript.
        self.assertIsInstance(payload['prediction_factor'], float)
        self.assertIsInstance(payload['throughout_decay_k'], float)
        self.assertNotIn('id', payload)

    def test_edited_value_reaches_the_endpoint(self):
        constants = CalculationConstants.load()
        constants.misc_earnings_monthly = 4200
        constants.save()
        res = APIClient().get('/calculator-data')
        self.assertEqual(res.data['calculation_constants']['misc_earnings_monthly'], 4200)

    def test_prediction_factor_drives_predicted_dates(self):
        # The whole point of making it editable: changing it must move the dates
        # /calculator-data serves, with no deploy.
        make_timeline(
            name='Anchor',
            jp_start_date=_dt(2025, 1, 1), jp_end_date=_dt(2025, 1, 8),
            global_start_date=_dt(2025, 6, 1), global_end_date=_dt(2025, 6, 8),
        )
        make_timeline(
            name='Predicted',
            jp_start_date=_dt(2025, 1, 31), jp_end_date=_dt(2025, 2, 7),
        )
        constants = CalculationConstants.load()
        constants.prediction_factor = '1.000'
        constants.save()

        emap = build_effective_date_map()
        predicted = next(e for e in emap.values() if e['is_predicted'])
        # At a factor of 1.0 the 30-day JP gap maps to a 30-day global gap.
        self.assertEqual(predicted['start_date'], _dt(2025, 6, 1) + datetime.timedelta(days=30))

    def test_game_event_buffer_is_configurable(self):
        timeline = make_timeline(
            name='Confirmed',
            global_start_date=_dt(2025, 6, 1), global_end_date=_dt(2025, 6, 8),
        )
        make_game_event(banner_timeline=timeline, carat_amount=100)
        constants = CalculationConstants.load()
        constants.game_event_end_buffer_days = 9
        constants.save()

        events = GameEvent.objects.select_related('banner_timeline').all()
        emap = build_game_event_date_map(events, build_effective_date_map())
        entry = next(iter(emap.values()))
        self.assertEqual(entry['end_date'], _dt(2025, 6, 8) + datetime.timedelta(days=9))

    def test_pure_functions_still_run_without_the_database_value(self):
        # compute_effective_dates keeps a module-constant default so it stays
        # DB-free for direct unit tests.
        rows = [{
            'id': 1,
            'jp_start_date': _dt(2025, 1, 1), 'jp_end_date': _dt(2025, 1, 8),
            'global_start_date': _dt(2025, 6, 1), 'global_end_date': _dt(2025, 6, 8),
            'schedule_offset_days': 0,
        }]
        out = compute_effective_dates(rows)
        self.assertEqual(out[1]['start_date'], _dt(2025, 6, 1))


@override_settings(STORAGES=PLAIN_TEST_STORAGES)
class CalculationConstantsAdminTests(TestCase):
    """The singleton admin page. Its list → add → edit flow is deliberately
    non-standard, and a broken fieldset only surfaces on render."""

    @classmethod
    def setUpTestData(cls):
        cls.superuser = CustomUser.objects.create_superuser(username='boss', password='x')

    def setUp(self):
        self.client.force_login(self.superuser)

    def test_changelist_redirects_straight_to_the_form(self):
        res = self.client.get(reverse('admin:calculatorapi_calculationconstants_changelist'))
        self.assertEqual(res.status_code, 302)
        constants = CalculationConstants.load()
        self.assertEqual(
            res.url,
            reverse('admin:calculatorapi_calculationconstants_change',
                    args=(constants.pk,)),
        )

    def test_change_form_renders_every_fieldset(self):
        # A field named in `fieldsets` that doesn't exist on the model raises
        # here rather than at import time.
        constants = CalculationConstants.load()
        res = self.client.get(
            reverse('admin:calculatorapi_calculationconstants_change',
                    args=(constants.pk,))
        )
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'Daily income')
        self.assertContains(res, 'Global date prediction')

    def test_add_is_refused_once_the_row_exists(self):
        CalculationConstants.load()
        res = self.client.get(reverse('admin:calculatorapi_calculationconstants_add'))
        self.assertEqual(res.status_code, 403)

    def test_delete_is_refused(self):
        constants = CalculationConstants.load()
        res = self.client.get(
            reverse('admin:calculatorapi_calculationconstants_delete',
                    args=(constants.pk,))
        )
        self.assertEqual(res.status_code, 403)

    def test_content_editors_get_no_permission_on_it(self):
        # It is left out of CONTENT_MODELS on purpose: these numbers move every
        # user's projection, and some of them move banner dates.
        call_command('create_content_editor_group', stdout=StringIO())
        editor = make_user(username='editor', is_staff=True)
        editor.groups.add(Group.objects.get(name='Content editors'))
        self.assertFalse(editor.has_perm('calculatorapi.change_calculationconstants'))


class LedgerTests(TestCase):
    """build_income_ledger: the flat dated timeline the projection queries.

    It computes no income — it places rows on the calendar. So these pin dates,
    ordering, and which rows exist at all; the amounts only need to survive the
    trip intact."""

    def _one_row(self):
        """The ledger's single row, asserting there is exactly one.

        Preferred over `row, = self._ledger()`: a wrong count fails as a
        readable assertion rather than a ValueError, and the expected count
        becomes part of what each test states.
        """
        rows = self._ledger()
        self.assertEqual(len(rows), 1)
        return rows[0]

    def _ledger(self):
        """Build the ledger the same way /calculator-data does."""
        date_maps = build_effective_date_maps()
        emap = date_maps[BannerTimeline]
        events = GameEvent.objects.select_related('banner_timeline').all()
        return build_income_ledger(
            game_events=events,
            game_event_emap=build_game_event_date_map(events, emap),
            race_sources=(
                ('champions_meeting', ChampionsMeeting.objects.all(),
                 date_maps[ChampionsMeeting]),
                ('league_of_heroes', LeagueOfHeroes.objects.all(),
                 date_maps[LeagueOfHeroes]),
            ),
        )

    def test_event_row_is_dated_at_its_banner_start_and_carries_amounts(self):
        timeline = make_timeline(
            name='Confirmed',
            global_start_date=_dt(2025, 6, 1), global_end_date=_dt(2025, 6, 8),
        )
        make_game_event(banner_timeline=timeline, carat_amount=1200,
                        uma_ticket_amount=3, ssr_shard_amount=5)
        row = self._one_row()
        self.assertEqual(row['kind'], 'event')
        self.assertEqual(row['date'], _dt(2025, 6, 1))
        self.assertEqual(row['carats'], 1200)
        self.assertEqual(row['uma_tickets'], 3)
        self.assertEqual(row['ssr_shards'], 5)
        # Untouched amounts are present as zeros, never absent.
        self.assertEqual(row['sr_crystals'], 0)

    def test_throughout_end_is_the_banner_end_not_the_event_end(self):
        # The event's own resolved end trails its banner by the buffer, but the
        # decay curve runs over the BANNER. Emitting it pre-stripped is what
        # stops the client re-deriving it from its own copy of the constant.
        timeline = make_timeline(
            name='Confirmed',
            global_start_date=_dt(2025, 6, 1), global_end_date=_dt(2025, 6, 8),
        )
        make_game_event(banner_timeline=timeline, carats_throughout=900)
        row = self._one_row()
        self.assertEqual(row['carats_throughout'], 900)
        self.assertEqual(row['throughout_end'], _dt(2025, 6, 8))

    def test_all_zero_event_is_omitted(self):
        timeline = make_timeline(
            name='Confirmed',
            global_start_date=_dt(2025, 6, 1), global_end_date=_dt(2025, 6, 8),
        )
        make_game_event(banner_timeline=timeline)
        self.assertEqual(self._ledger(), [])

    def test_undated_rows_are_omitted(self):
        # An unlinked event and a race event with no resolvable dates have no
        # position on the calendar, so they are dropped rather than emitted null.
        make_game_event(banner_timeline=None, carat_amount=500)
        make_champions_meeting(name='No dates', global_start_date=None,
                               global_end_date=None,
                               jp_start_date=_dt(2025, 1, 1),
                               jp_end_date=_dt(2025, 1, 8))
        self.assertEqual(self._ledger(), [])

    def test_race_rows_are_dated_at_end_and_carry_no_amounts(self):
        make_champions_meeting(
            name='CM', global_start_date=_dt(2025, 6, 1),
            global_end_date=_dt(2025, 6, 8),
        )
        make_league_of_heroes(
            name='LoH', global_start_date=_dt(2025, 7, 1),
            global_end_date=_dt(2025, 7, 8),
        )
        rows = self._ledger()
        self.assertEqual(len(rows), 2)
        cm, loh = rows[0], rows[1]
        self.assertEqual((cm['kind'], cm['date']),
                         ('champions_meeting', _dt(2025, 6, 8)))
        self.assertEqual((loh['kind'], loh['date']),
                         ('league_of_heroes', _dt(2025, 7, 8)))
        # Amounts stay zero: what a placement pays depends on the user's rank.
        for row in (cm, loh):
            self.assertEqual(row['carats'], 0)
            self.assertEqual(row['uma_tickets'], 0)

    def test_past_events_are_included(self):
        # Deliberate: the ledger is a set of dated facts with no "as of today"
        # gate. The sheet bakes one into its CM/LoH columns; we apply it
        # client-side instead so the whole calculation shares one anchor.
        make_champions_meeting(
            name='Long gone', global_start_date=_dt(2020, 1, 1),
            global_end_date=_dt(2020, 1, 8),
        )
        row = self._one_row()
        self.assertEqual(row['date'], _dt(2020, 1, 8))

    def test_rows_are_sorted_by_date(self):
        late = make_timeline(name='Late', global_start_date=_dt(2025, 9, 1),
                             global_end_date=_dt(2025, 9, 8))
        early = make_timeline(name='Early', global_start_date=_dt(2025, 3, 1),
                              global_end_date=_dt(2025, 3, 8))
        make_game_event(name='Late event', banner_timeline=late, carat_amount=1)
        make_game_event(name='Early event', banner_timeline=early, carat_amount=1)
        make_champions_meeting(name='Mid', global_start_date=_dt(2025, 6, 1),
                               global_end_date=_dt(2025, 6, 8))
        self.assertEqual(
            [row['name'] for row in self._ledger()],
            ['Early event', 'Mid', 'Late event'],
        )

    def test_schedule_offset_moves_ledger_dates(self):
        # The offset is applied while the date maps are built, so the ledger
        # inherits it without knowing it exists.
        make_timeline(
            name='Anchor',
            jp_start_date=_dt(2025, 1, 1), jp_end_date=_dt(2025, 1, 8),
            global_start_date=_dt(2025, 6, 1), global_end_date=_dt(2025, 6, 8),
        )
        delayed = make_timeline(
            name='Delayed',
            jp_start_date=_dt(2025, 1, 31), jp_end_date=_dt(2025, 2, 7),
            schedule_offset_days=5,
        )
        make_game_event(banner_timeline=delayed, carat_amount=100)
        row = self._one_row()
        self.assertEqual(row['date'], _predicted(_dt(2025, 6, 1), 30, offset_days=5))
        self.assertTrue(row['is_predicted'])


class LedgerSerializerTests(TestCase):
    def test_serializer_emits_every_amount_field(self):
        # ledger.AMOUNT_FIELDS is what fills the zeros on every row; the
        # serializer is what puts them on the wire. If one grows a field the
        # other doesn't, the client silently reads undefined.
        declared = set(IncomeLedgerRowSerializer().get_fields())
        self.assertTrue(set(AMOUNT_FIELDS).issubset(declared))

    def test_endpoint_serializes_ledger_rows(self):
        timeline = make_timeline(
            name='Confirmed',
            global_start_date=_dt(2025, 6, 1), global_end_date=_dt(2025, 6, 8),
        )
        make_game_event(banner_timeline=timeline, carat_amount=1200,
                        carats_throughout=900)
        res = APIClient().get('/calculator-data')
        self.assertEqual(res.status_code, 200)
        row, = res.data['income_ledger']
        self.assertEqual(row['date'], _iso(_dt(2025, 6, 1)))
        self.assertEqual(row['throughout_end'], _iso(_dt(2025, 6, 8)))
        self.assertEqual(row['carats'], 1200)
        self.assertEqual(row['kind'], 'event')


_EXPECTED_GET_KEYS = {
    'club_rank_data', 'team_trials_rank_data', 'champions_meeting_rank_data',
    'league_of_heroes_rank_data', 'banner_uma_data', 'banner_support_data',
    'user_planned_banner_data', 'champions_meeting_data', 'league_of_heroes_event_data',
    'events_data', 'user_stats_data', 'banner_timeline_data',
    'anniversary_event_data', 'user_planned_purchase_data',
    'income_ledger', 'calculation_constants',
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
        self.assertEqual(res.data['user_planned_purchase_data'], [])

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

        expected_start = _iso(_predicted(_dt(2025, 6, 1), 30))

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

    def test_schedule_offset_is_consistent_across_all_paths(self):
        """Same shape as the prediction-consistency test above: an offset banner
        must report the SAME shifted date at top level, nested in banner_uma_data,
        and two levels deep inside user_planned_banner_data."""
        make_timeline(
            name='Anchor',
            jp_start_date=_dt(2025, 1, 1), jp_end_date=_dt(2025, 1, 8),
            global_start_date=_dt(2025, 6, 1), global_end_date=_dt(2025, 6, 8),
        )
        offset_tl = make_timeline(
            name='Slipped',
            jp_start_date=_dt(2025, 1, 31), jp_end_date=_dt(2025, 2, 7),
            schedule_offset_days=7,
        )
        uma_banner = make_uma_banner(timeline=offset_tl)
        UserPlannedBanner.objects.create(
            user=self.user, banner_uma=uma_banner, number_of_pulls=3
        )

        res = self.client.get('/calculator-data')

        # Predicted off the anchor, then pushed 7 days by the offset; the 7-day
        # run length is preserved because both ends move together.
        shifted_start = _predicted(_dt(2025, 6, 1), 30, offset_days=7)
        expected_start = _iso(shifted_start)
        expected_end = _iso(shifted_start + datetime.timedelta(days=7))

        top = next(t for t in res.data['banner_timeline_data'] if t['id'] == offset_tl.id)
        self.assertEqual(top['start_date'], expected_start)
        self.assertEqual(top['end_date'], expected_end)
        self.assertTrue(top['is_predicted'])
        self.assertEqual(top['schedule_offset_days'], 7)
        self.assertEqual(top['applied_offset_days'], 7)

        nested_uma = next(
            b for b in res.data['banner_uma_data']
            if b['banner_timeline']['id'] == offset_tl.id
        )
        self.assertEqual(nested_uma['banner_timeline']['start_date'], expected_start)

        planned_tl = res.data['user_planned_banner_data'][0]['banner_uma']['banner_timeline']
        self.assertEqual(planned_tl['start_date'], expected_start)
        self.assertEqual(planned_tl['applied_offset_days'], 7)

    def test_schedule_offset_cascades_to_later_rows_of_every_content_type(self):
        """One shared calendar: a banner offset also pushes later Champions
        Meetings and League of Heroes events, while earlier rows stay put."""
        make_timeline(
            name='Anchor',
            jp_start_date=_dt(2025, 1, 1), jp_end_date=_dt(2025, 1, 8),
            global_start_date=_dt(2025, 6, 1), global_end_date=_dt(2025, 6, 8),
        )
        # Predicted off the anchor and carrying the +7.
        make_timeline(
            name='Slipped',
            jp_start_date=_dt(2025, 1, 31), jp_end_date=_dt(2025, 2, 7),
            schedule_offset_days=7,
        )
        # A shorter JP gap puts this BEFORE the slip point, so it stays untouched.
        earlier_tl = make_timeline(
            name='Earlier',
            jp_start_date=_dt(2025, 1, 21), jp_end_date=_dt(2025, 1, 28),
        )
        # CM/LoH each predict off their OWN anchor, both landing after the slip.
        make_champions_meeting(
            name='CM Anchor', cm_number=1,
            jp_start_date=_dt(2025, 2, 1), jp_end_date=_dt(2025, 2, 8),
            global_start_date=_dt(2025, 6, 10), global_end_date=_dt(2025, 6, 17),
        )
        later_cm = make_champions_meeting(
            name='CM Later', cm_number=2,
            jp_start_date=_dt(2025, 3, 3), jp_end_date=_dt(2025, 3, 10),
        )
        make_league_of_heroes(
            name='LoH Anchor',
            jp_start_date=_dt(2025, 2, 1), jp_end_date=_dt(2025, 2, 8),
            global_start_date=_dt(2025, 6, 10), global_end_date=_dt(2025, 6, 17),
        )
        later_loh = make_league_of_heroes(
            name='LoH Later',
            jp_start_date=_dt(2025, 3, 3), jp_end_date=_dt(2025, 3, 10),
        )

        res = self.client.get('/calculator-data')

        earlier = next(t for t in res.data['banner_timeline_data'] if t['id'] == earlier_tl.id)
        self.assertEqual(earlier['start_date'], _iso(_predicted(_dt(2025, 6, 1), 20)))
        self.assertEqual(earlier['applied_offset_days'], 0)

        # Both predict off their own anchors, land after the slip, inherit the +7.
        inherited = _iso(_predicted(_dt(2025, 6, 10), 30, offset_days=7))

        cm = next(c for c in res.data['champions_meeting_data'] if c['id'] == later_cm.id)
        self.assertEqual(cm['start_date'], inherited)
        self.assertEqual(cm['applied_offset_days'], 7)

        loh = next(e for e in res.data['league_of_heroes_event_data'] if e['id'] == later_loh.id)
        self.assertEqual(loh['start_date'], inherited)
        self.assertEqual(loh['applied_offset_days'], 7)

    def test_confirmed_row_ignores_its_own_offset(self):
        """A confirmed date is a fact — the offset must not move it, and must
        not cascade either (otherwise it double-counts once it anchors)."""
        confirmed_tl = make_timeline(
            name='Confirmed but offset',
            jp_start_date=_dt(2025, 1, 1), jp_end_date=_dt(2025, 1, 8),
            global_start_date=_dt(2025, 6, 1), global_end_date=_dt(2025, 6, 8),
            schedule_offset_days=7,
        )
        later_tl = make_timeline(
            name='Later',
            jp_start_date=_dt(2025, 1, 31), jp_end_date=_dt(2025, 2, 7),
        )

        res = self.client.get('/calculator-data')

        confirmed = next(t for t in res.data['banner_timeline_data'] if t['id'] == confirmed_tl.id)
        self.assertEqual(confirmed['start_date'], '2025-06-01T00:00:00Z')
        self.assertEqual(confirmed['applied_offset_days'], 0)

        later = next(t for t in res.data['banner_timeline_data'] if t['id'] == later_tl.id)
        self.assertEqual(later['start_date'], _iso(_predicted(_dt(2025, 6, 1), 30)))
        self.assertEqual(later['applied_offset_days'], 0)

    def test_game_event_inherits_its_banners_offset_plus_the_buffer(self):
        make_timeline(
            name='Anchor',
            jp_start_date=_dt(2025, 1, 1), jp_end_date=_dt(2025, 1, 8),
            global_start_date=_dt(2025, 6, 1), global_end_date=_dt(2025, 6, 8),
        )
        offset_tl = make_timeline(
            name='Slipped',
            jp_start_date=_dt(2025, 1, 31), jp_end_date=_dt(2025, 2, 7),
            schedule_offset_days=7,
        )
        event = make_game_event(name='Slipped Event', banner_timeline=offset_tl)

        res = self.client.get('/calculator-data')
        entry = next(e for e in res.data['events_data'] if e['id'] == event.id)

        # The banner's 7-day run shifts whole by the offset; the event's end
        # still trails it by the usual 4-day buffer.
        shifted_start = _predicted(_dt(2025, 6, 1), 30, offset_days=7)
        self.assertEqual(entry['start_date'], _iso(shifted_start))
        self.assertEqual(entry['end_date'], _iso(
            shifted_start + datetime.timedelta(days=7) + GAME_EVENT_END_DATE_BUFFER))
        self.assertEqual(entry['applied_offset_days'], 7)

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
        self.assertEqual(entry['start_date'], _iso(_predicted(_dt(2025, 6, 1), 30)))

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
        self.assertEqual(entry['start_date'], _iso(_predicted(_dt(2025, 6, 1), 30)))

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

    def test_game_event_exposes_resolved_and_predicted_fields(self):
        timeline = make_timeline(
            name='Confirmed Banner',
            global_start_date=_dt(2025, 6, 1), global_end_date=_dt(2025, 6, 8),
        )
        event = make_game_event(
            name='Linked Event', banner_timeline=timeline,
            carat_amount=80, carats_throughout=1050,
        )
        res = self.client.get('/calculator-data')
        entry = next(e for e in res.data['events_data'] if e['id'] == event.id)
        for key in ('start_date', 'end_date', 'is_predicted', 'banner_timeline'):
            self.assertIn(key, entry)
        self.assertEqual(entry['start_date'], '2025-06-01T00:00:00Z')
        # end_date trails the banner's own end_date by GAME_EVENT_END_DATE_BUFFER (4 days).
        self.assertEqual(entry['end_date'], '2025-06-12T00:00:00Z')
        self.assertFalse(entry['is_predicted'])
        self.assertEqual(entry['banner_timeline'], timeline.id)
        self.assertEqual(entry['carat_amount'], 80)
        self.assertEqual(entry['carats_throughout'], 1050)

    def test_game_event_predicts_via_linked_banner_timeline(self):
        make_timeline(
            name='Anchor',
            jp_start_date=_dt(2025, 1, 1), jp_end_date=_dt(2025, 1, 8),
            global_start_date=_dt(2025, 6, 1), global_end_date=_dt(2025, 6, 8),
        )
        predicted_tl = make_timeline(
            name='Predicted',
            jp_start_date=_dt(2025, 1, 31), jp_end_date=_dt(2025, 2, 7),
        )
        event = make_game_event(name='Predicted Event', banner_timeline=predicted_tl)
        res = self.client.get('/calculator-data')
        entry = next(e for e in res.data['events_data'] if e['id'] == event.id)
        # Banner runs 7d from its predicted start, then the event's +4d buffer.
        predicted_start = _predicted(_dt(2025, 6, 1), 30)
        self.assertTrue(entry['is_predicted'])
        self.assertEqual(entry['start_date'], _iso(predicted_start))
        self.assertEqual(entry['end_date'], _iso(
            predicted_start + datetime.timedelta(days=7) + GAME_EVENT_END_DATE_BUFFER))

    def test_game_event_with_no_banner_timeline_resolves_null_dates(self):
        event = make_game_event(name='Unlinked Event', banner_timeline=None)
        res = self.client.get('/calculator-data')
        entry = next(e for e in res.data['events_data'] if e['id'] == event.id)
        self.assertIsNone(entry['start_date'])
        self.assertIsNone(entry['end_date'])
        self.assertFalse(entry['is_predicted'])
        self.assertIsNone(entry['banner_timeline'])


# ── Reference Endpoint Tests ──────────────────────────────────────────────────

class ReferenceEndpointGuestAccessTests(TestCase):
    """Read-only reference endpoints are open to guests."""

    def test_reference_reads_return_200_for_guests(self):
        client = APIClient()
        for url in (
            '/clubranks', '/teamtrialranks', '/championsmeetingranks',
            '/leagueofheroesranks', '/leagueofheroes', '/events',
        ):
            with self.subTest(url=url):
                self.assertEqual(client.get(url).status_code, 200)

    def test_event_writes_still_require_admin(self):
        # Guests (and non-admin users) must not be able to write reference data.
        res = APIClient().post('/events', {'name': 'x'})
        self.assertIn(res.status_code, (401, 403))

    def test_events_endpoint_serves_confirmed_only_no_prediction(self):
        # The standalone /events route must never predict -- a JP-only banner
        # should show null dates here, even though the same event predicts
        # through /calculator-data (test_game_event_predicts_via_linked_banner_timeline).
        make_timeline(
            name='Anchor',
            jp_start_date=_dt(2025, 1, 1), jp_end_date=_dt(2025, 1, 8),
            global_start_date=_dt(2025, 6, 1), global_end_date=_dt(2025, 6, 8),
        )
        predicted_tl = make_timeline(
            name='Predicted',
            jp_start_date=_dt(2025, 1, 31), jp_end_date=_dt(2025, 2, 7),
        )
        event = make_game_event(name='Predicted Event', banner_timeline=predicted_tl)
        res = APIClient().get('/events')
        entry = next(e for e in res.data if e['id'] == event.id)
        self.assertIsNone(entry['start_date'])
        self.assertIsNone(entry['end_date'])
        self.assertFalse(entry['is_predicted'])

    def test_standalone_routes_are_unaffected_by_schedule_offsets(self):
        """Offsets ride on top of predictions, and the standalone routes serve
        confirmed dates only — so they must not shift. Same two-tier split as
        test_events_endpoint_serves_confirmed_only_no_prediction above."""
        confirmed_tl = make_timeline(
            name='Confirmed',
            jp_start_date=_dt(2025, 1, 1), jp_end_date=_dt(2025, 1, 8),
            global_start_date=_dt(2025, 6, 1), global_end_date=_dt(2025, 6, 8),
            schedule_offset_days=7,
        )
        event = make_game_event(name='Confirmed Event', banner_timeline=confirmed_tl)
        loh = make_league_of_heroes(
            name='Confirmed LoH',
            global_start_date=_dt(2025, 6, 10), global_end_date=_dt(2025, 6, 17),
            schedule_offset_days=7,
        )

        events_res = APIClient().get('/events')
        entry = next(e for e in events_res.data if e['id'] == event.id)
        self.assertEqual(entry['start_date'], '2025-06-01T00:00:00Z')
        self.assertEqual(entry['applied_offset_days'], 0)

        loh_res = APIClient().get('/leagueofheroes')
        loh_entry = next(e for e in loh_res.data if e['id'] == loh.id)
        self.assertEqual(loh_entry['start_date'], '2025-06-10T00:00:00Z')
        self.assertEqual(loh_entry['applied_offset_days'], 0)


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

    def test_invalid_banner_rolls_back_stats_saved_earlier_in_the_same_patch(self):
        """A partly-invalid PATCH must persist nothing.

        Regression: `return`ing a Response from inside `transaction.atomic()`
        exits the block normally, so Django committed. Stats are written before
        banners, so a rejected banner used to leave the stats change behind —
        the exact split state the transaction is there to prevent.
        """
        res = self.client.patch(
            '/calculator-data',
            {
                'user_stats_data': {'current_carat': 4242},
                # Neither banner_uma nor banner_support — fails validation.
                'user_planned_banner_data': [{'number_of_pulls': 10}],
            },
            format='json',
        )
        self.assertEqual(res.status_code, 400)
        self.user.refresh_from_db()
        self.assertNotEqual(self.user.current_carat, 4242)

    def test_patch_stats_updates_misc_earnings_toggle(self):
        # misc_earnings defaults to True; confirm the serializer accepts and
        # persists a toggle-off through the same PATCH path as the other stats.
        self.assertTrue(self.user.misc_earnings)
        res = self.client.patch(
            '/calculator-data',
            {'user_stats_data': {'misc_earnings': False}},
            format='json',
        )
        self.assertEqual(res.status_code, 200)
        self.user.refresh_from_db()
        self.assertFalse(self.user.misc_earnings)

    def test_patch_stats_updates_pull_strategy_toggles(self):
        # The three toggles added for the Settings menu round-trip through the
        # same partial-PATCH path. Confirm their defaults, then flip each and
        # verify it persists.
        self.assertFalse(self.user.monthly_shop_tickets)
        self.assertFalse(self.user.discounted_paid_pulls)
        self.assertTrue(self.user.full_price_paid_pulls)
        res = self.client.patch(
            '/calculator-data',
            {'user_stats_data': {
                'monthly_shop_tickets': True,
                'discounted_paid_pulls': True,
                'full_price_paid_pulls': False,
            }},
            format='json',
        )
        self.assertEqual(res.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.monthly_shop_tickets)
        self.assertTrue(self.user.discounted_paid_pulls)
        self.assertFalse(self.user.full_price_paid_pulls)

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


# ── Selector Planner Tests ────────────────────────────────────────────────────

class SelectorEligibilityTests(TestCase):
    """A card's JP release date is derived from its earliest banner appearance."""

    def setUp(self):
        self.old_timeline = make_timeline(
            name='Old', jp_start_date=timezone.make_aware(datetime.datetime(2024, 1, 31)),
            global_start_date=None, global_end_date=None,
        )
        self.new_timeline = make_timeline(
            name='New', jp_start_date=timezone.make_aware(datetime.datetime(2026, 2, 14)),
            global_start_date=None, global_end_date=None,
        )

    def _uma_on(self, timeline, name):
        uma = Uma.objects.create(name=name)
        UmasOnUmaBanner.objects.create(
            uma=uma, banner_uma=make_uma_banner(timeline, name=f'{name} banner')
        )
        return uma

    def test_first_jp_date_is_the_earliest_banner_appearance(self):
        uma = self._uma_on(self.new_timeline, 'Rerun Uma')
        # Same uma also appeared on the older banner — the earliest wins.
        UmasOnUmaBanner.objects.create(
            uma=uma, banner_uma=make_uma_banner(self.old_timeline, name='Rerun original')
        )
        uma_dates, _ = build_first_jp_date_maps()
        self.assertEqual(uma_dates[uma.id].date(), datetime.date(2024, 1, 31))

    def test_cards_with_no_banner_are_absent_not_null(self):
        orphan = Uma.objects.create(name='Never Featured')
        uma_dates, _ = build_first_jp_date_maps()
        self.assertNotIn(orphan.id, uma_dates)

    def test_support_cards_get_their_own_map(self):
        card = SupportCard.objects.create(name='Test SSR', game_id=30184)
        SupportsOnSupportBanner.objects.create(
            support_card=card,
            banner_support=make_support_banner(self.old_timeline, name='SSR banner'),
        )
        _, support_dates = build_first_jp_date_maps()
        self.assertEqual(support_dates[card.id].date(), datetime.date(2024, 1, 31))

    def test_cutoff_is_inclusive(self):
        # Sakura Bakushin O debuted exactly on the 3rd Anniversary's cutoff and
        # the source sheet lists her as selectable — the boundary is IN.
        on_cutoff = timezone.make_aware(datetime.datetime(2024, 1, 31))
        self.assertTrue(is_eligible(on_cutoff, datetime.date(2024, 1, 31)))

    def test_card_released_after_cutoff_is_ineligible(self):
        after = timezone.make_aware(datetime.datetime(2024, 2, 1))
        self.assertFalse(is_eligible(after, datetime.date(2024, 1, 31)))

    def test_null_cutoff_means_unrestricted(self):
        self.assertTrue(is_eligible(timezone.now(), None))

    def test_unknown_release_date_is_ineligible_under_a_real_cutoff(self):
        # Conservative: claiming a selector covers a card it can't is worse than
        # hiding one it could.
        self.assertFalse(is_eligible(None, datetime.date(2024, 1, 31)))


class AnniversaryEventDateTests(TestCase):
    """A campaign spans its banner parts rather than owning dates."""

    def test_dates_span_earliest_start_to_latest_end(self):
        now = timezone.now()
        part1 = make_timeline(
            name='Part 1', global_start_date=now,
            global_end_date=now + datetime.timedelta(days=10),
        )
        part2 = make_timeline(
            name='Part 2', global_start_date=now + datetime.timedelta(days=5),
            global_end_date=now + datetime.timedelta(days=30),
        )
        event = make_anniversary_event(parts=[part1, part2])

        emap = build_effective_date_maps()[BannerTimeline]
        resolved = build_anniversary_event_date_map([event], emap)[event.id]

        self.assertEqual(resolved['start_date'], part1.global_start_date)
        self.assertEqual(resolved['end_date'], part2.global_end_date)
        self.assertFalse(resolved['is_predicted'])

    def test_one_predicted_part_makes_the_whole_campaign_predicted(self):
        now = timezone.now()
        # Anchor: a confirmed JP+global pair the predictor can measure from.
        make_timeline(
            name='Anchor',
            jp_start_date=timezone.make_aware(datetime.datetime(2022, 1, 1)),
            jp_end_date=timezone.make_aware(datetime.datetime(2022, 1, 14)),
            global_start_date=now, global_end_date=now + datetime.timedelta(days=14),
        )
        confirmed = make_timeline(
            name='Confirmed part', global_start_date=now,
            global_end_date=now + datetime.timedelta(days=10),
        )
        predicted = make_timeline(
            name='Predicted part',
            jp_start_date=timezone.make_aware(datetime.datetime(2022, 6, 1)),
            jp_end_date=timezone.make_aware(datetime.datetime(2022, 6, 14)),
            global_start_date=None, global_end_date=None,
        )
        event = make_anniversary_event(parts=[confirmed, predicted])

        emap = build_effective_date_maps()[BannerTimeline]
        resolved = build_anniversary_event_date_map([event], emap)[event.id]

        self.assertTrue(resolved['is_predicted'])

    def test_campaign_with_no_parts_resolves_to_null_dates(self):
        event = make_anniversary_event(parts=[])
        emap = build_effective_date_maps()[BannerTimeline]
        resolved = build_anniversary_event_date_map([event], emap)[event.id]

        self.assertIsNone(resolved['start_date'])
        self.assertIsNone(resolved['end_date'])
        self.assertFalse(resolved['is_predicted'])


class AnniversaryEventApiTests(TestCase):
    """The campaign payload and the banner strip it attaches to."""

    def setUp(self):
        self.user = make_user()
        self.client, _ = auth_client(self.user)
        self.timeline = make_timeline(name='3rd Anniv Part 1')
        self.event = make_anniversary_event(
            name='3rd Anniversary',
            jp_cutoff_date=datetime.date(2024, 1, 31),
            parts=[self.timeline],
            products=[
                {'product_type': 'carat_pack', 'name': '7500 Carat Pack',
                 'usd_cost': 70, 'paid_carat_amount': 7500,
                 'webstore_multiplier': '1.10', 'max_quantity': 3, 'order': 1},
                {'product_type': 'uma_selector', 'name': '$21 Uma Selector',
                 'usd_cost': 21, 'paid_carat_amount': 1500, 'order': 2},
            ],
        )

    def test_products_are_serialized_with_numeric_money(self):
        # Asserted against the RENDERED payload, not res.data: res.data still
        # holds Decimals and dates, and the point here is the wire format the
        # browser actually parses.
        event = self.client.get('/calculator-data').json()['anniversary_event_data'][0]
        pack = next(p for p in event['products'] if p['product_type'] == 'carat_pack')

        # JSON numbers, not DRF's default Decimal-as-string — the client does
        # arithmetic on these directly.
        self.assertEqual(pack['usd_cost'], 70.0)
        self.assertEqual(pack['webstore_multiplier'], 1.10)
        self.assertIsInstance(pack['usd_cost'], float)
        self.assertEqual(pack['paid_carat_amount'], 7500)
        self.assertEqual(pack['max_quantity'], 3)

    def test_product_inherits_the_campaign_cutoff(self):
        event = self.client.get('/calculator-data').json()['anniversary_event_data'][0]
        selector = next(p for p in event['products'] if p['product_type'] == 'uma_selector')

        self.assertEqual(selector['jp_cutoff_date'], '2024-01-31')
        # The raw override stays null — this cutoff came from the campaign.
        self.assertIsNone(selector['jp_cutoff_date_override'])

    def test_product_override_beats_the_campaign_cutoff(self):
        AnniversaryEventProduct.objects.create(
            anniversary_event=self.event, product_type='support_selector',
            name='$70 SSR Selector', usd_cost=70, paid_carat_amount=7500,
            jp_cutoff_date=datetime.date(2023, 1, 1),
        )
        event = self.client.get('/calculator-data').json()['anniversary_event_data'][0]
        selector = next(p for p in event['products'] if p['name'] == '$70 SSR Selector')

        self.assertEqual(selector['jp_cutoff_date'], '2023-01-01')

    def test_banner_carries_its_campaign_and_part_number(self):
        res = self.client.get('/calculator-data')
        timeline = next(
            t for t in res.data['banner_timeline_data'] if t['id'] == self.timeline.id
        )
        self.assertEqual(timeline['anniversary_event']['name'], '3rd Anniversary')
        self.assertEqual(timeline['anniversary_event']['part_number'], 1)

    def test_unattached_banner_reports_no_campaign(self):
        loose = make_timeline(name='Ordinary banner')
        res = self.client.get('/calculator-data')
        timeline = next(
            t for t in res.data['banner_timeline_data'] if t['id'] == loose.id
        )
        self.assertIsNone(timeline['anniversary_event'])

    def test_campaigns_are_public(self):
        res = APIClient().get('/calculator-data')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.data['anniversary_event_data']), 1)


class UserPlannedPurchaseTests(TestCase):
    """The PATCH upsert and the selector-target validation behind it."""

    def setUp(self):
        self.user = make_user()
        self.client, _ = auth_client(self.user)
        self.timeline = make_timeline(
            name='Anniv', jp_start_date=timezone.make_aware(datetime.datetime(2024, 2, 14)),
        )
        self.event = make_anniversary_event(
            name='3rd Anniversary',
            jp_cutoff_date=datetime.date(2024, 1, 31),
            parts=[self.timeline],
        )
        self.pack = AnniversaryEventProduct.objects.create(
            anniversary_event=self.event, product_type='carat_pack',
            name='7500 Carat Pack', usd_cost=70, paid_carat_amount=7500,
            max_quantity=3,
        )
        self.uma_selector = AnniversaryEventProduct.objects.create(
            anniversary_event=self.event, product_type='uma_selector',
            name='$21 Uma Selector', usd_cost=21, paid_carat_amount=1500,
        )
        # An uma old enough for the cutoff, and one too new for it.
        self.eligible_uma = self._uma_first_seen('Eligible', datetime.datetime(2023, 6, 1))
        self.late_uma = self._uma_first_seen('Too New', datetime.datetime(2024, 6, 1))

    def _uma_first_seen(self, name, when):
        timeline = make_timeline(
            name=f'{name} debut', jp_start_date=timezone.make_aware(when),
        )
        uma = Uma.objects.create(name=name)
        UmasOnUmaBanner.objects.create(
            uma=uma, banner_uma=make_uma_banner(timeline, name=f'{name} banner')
        )
        return uma

    def _patch(self, purchases):
        return self.client.patch(
            '/calculator-data',
            {'user_planned_purchase_data': purchases},
            format='json',
        )

    def test_creates_a_pack_purchase(self):
        res = self._patch([{'product': self.pack.id, 'quantity': 2}])
        self.assertEqual(res.status_code, 200)

        purchase = UserPlannedPurchase.objects.get(user=self.user)
        self.assertEqual(purchase.product_id, self.pack.id)
        self.assertEqual(purchase.quantity, 2)

    def test_updates_an_existing_purchase_by_id(self):
        self._patch([{'product': self.pack.id, 'quantity': 1}])
        existing = UserPlannedPurchase.objects.get(user=self.user)

        res = self._patch([{'id': existing.id, 'product': self.pack.id, 'quantity': 3}])
        self.assertEqual(res.status_code, 200)

        existing.refresh_from_db()
        self.assertEqual(existing.quantity, 3)
        self.assertEqual(UserPlannedPurchase.objects.filter(user=self.user).count(), 1)

    def test_empty_list_clears_the_plan(self):
        self._patch([{'product': self.pack.id, 'quantity': 1}])
        res = self._patch([])

        self.assertEqual(res.status_code, 200)
        self.assertEqual(UserPlannedPurchase.objects.filter(user=self.user).count(), 0)

    def test_absent_key_leaves_the_plan_alone(self):
        self._patch([{'product': self.pack.id, 'quantity': 1}])
        res = self.client.patch(
            '/calculator-data', {'user_stats_data': {'current_carat': 500}}, format='json'
        )

        self.assertEqual(res.status_code, 200)
        self.assertEqual(UserPlannedPurchase.objects.filter(user=self.user).count(), 1)

    def test_cannot_update_another_users_purchase(self):
        other = make_user(username='someone-else')
        theirs = UserPlannedPurchase.objects.create(
            user=other, product=self.pack, quantity=1
        )
        res = self._patch([{'id': theirs.id, 'product': self.pack.id, 'quantity': 9}])

        self.assertEqual(res.status_code, 404)
        theirs.refresh_from_db()
        self.assertEqual(theirs.quantity, 1)

    def test_accepts_an_eligible_selector_target(self):
        res = self._patch([
            {'product': self.uma_selector.id, 'quantity': 1,
             'target_uma': self.eligible_uma.id}
        ])
        self.assertEqual(res.status_code, 200)

    def test_rejects_a_target_released_after_the_cutoff(self):
        res = self._patch([
            {'product': self.uma_selector.id, 'quantity': 1,
             'target_uma': self.late_uma.id}
        ])
        self.assertEqual(res.status_code, 400)
        self.assertEqual(UserPlannedPurchase.objects.filter(user=self.user).count(), 0)

    def _save_target(self, uma):
        """Save a selector pick and hand back the stored row."""
        res = self._patch([
            {'product': self.uma_selector.id, 'quantity': 1, 'target_uma': uma.id}
        ])
        self.assertEqual(res.status_code, 200)
        return UserPlannedPurchase.objects.get(user=self.user)

    def _tighten_cutoff_past(self, uma_first_seen):
        """Move the campaign cutoff back so an already-saved pick is now too new."""
        self.event.jp_cutoff_date = uma_first_seen
        self.event.save(update_fields=['jp_cutoff_date'])

    def test_grandfathers_a_saved_target_when_the_cutoff_moves(self):
        # The production regression: a pick legal when it was made (the campaign
        # had a later cutoff, or none at all) must not start rejecting the whole
        # PATCH once an editor or a backfill tightens that cutoff.
        saved = self._save_target(self.eligible_uma)
        self._tighten_cutoff_past(datetime.date(2023, 1, 1))

        res = self._patch([
            {'id': saved.id, 'product': self.uma_selector.id, 'quantity': 1,
             'target_uma': self.eligible_uma.id}
        ])

        self.assertEqual(res.status_code, 200)
        saved.refresh_from_db()
        self.assertEqual(saved.target_uma_id, self.eligible_uma.id)

    def test_a_grandfathered_row_does_not_block_the_rest_of_the_plan(self):
        # The reason the regression was severe: one stale pick took stats and
        # banners down with it, because the whole PATCH shares one transaction.
        saved = self._save_target(self.eligible_uma)
        self._tighten_cutoff_past(datetime.date(2023, 1, 1))

        res = self.client.patch(
            '/calculator-data',
            {
                'user_stats_data': {'current_carat': 4321},
                'user_planned_purchase_data': [
                    {'id': saved.id, 'product': self.uma_selector.id,
                     'quantity': 1, 'target_uma': self.eligible_uma.id}
                ],
            },
            format='json',
        )

        self.assertEqual(res.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.current_carat, 4321)

    def test_still_rejects_a_changed_target_under_a_tightened_cutoff(self):
        # Grandfathering covers the stored pairing only — editing the row is the
        # user acting now, and gets checked against the cutoff as it stands.
        saved = self._save_target(self.eligible_uma)
        self._tighten_cutoff_past(datetime.date(2023, 1, 1))

        res = self._patch([
            {'id': saved.id, 'product': self.uma_selector.id, 'quantity': 1,
             'target_uma': self.late_uma.id}
        ])

        self.assertEqual(res.status_code, 400)
        saved.refresh_from_db()
        self.assertEqual(saved.target_uma_id, self.eligible_uma.id)

    def test_grandfathering_does_not_survive_moving_to_another_campaign(self):
        # Same target, different campaign — a new pairing, so the destination
        # campaign's cutoff applies rather than the one it was saved under.
        saved = self._save_target(self.eligible_uma)
        stricter = make_anniversary_event(
            name='1st Anniversary',
            jp_cutoff_date=datetime.date(2022, 1, 31),
            parts=[make_timeline(
                name='1st Anniv',
                jp_start_date=timezone.make_aware(datetime.datetime(2022, 2, 14)),
            )],
        )
        other_selector = AnniversaryEventProduct.objects.create(
            anniversary_event=stricter, product_type='uma_selector',
            name='$21 Uma Selector', usd_cost=21, paid_carat_amount=1500,
        )

        res = self._patch([
            {'id': saved.id, 'product': other_selector.id, 'quantity': 1,
             'target_uma': self.eligible_uma.id}
        ])

        self.assertEqual(res.status_code, 400)

    def test_rejects_a_target_on_a_carat_pack(self):
        res = self._patch([
            {'product': self.pack.id, 'quantity': 1, 'target_uma': self.eligible_uma.id}
        ])
        self.assertEqual(res.status_code, 400)

    def test_rejects_a_support_target_on_an_uma_selector(self):
        card = SupportCard.objects.create(name='An SSR', game_id=30001)
        res = self._patch([
            {'product': self.uma_selector.id, 'quantity': 1, 'target_support': card.id}
        ])
        self.assertEqual(res.status_code, 400)

    def test_a_failed_row_rolls_back_the_whole_patch(self):
        # Stats are written before purchases; an invalid purchase must undo them.
        res = self.client.patch(
            '/calculator-data',
            {
                'user_stats_data': {'current_carat': 12345},
                'user_planned_purchase_data': [
                    {'product': self.uma_selector.id, 'target_uma': self.late_uma.id}
                ],
            },
            format='json',
        )
        self.assertEqual(res.status_code, 400)
        self.user.refresh_from_db()
        self.assertNotEqual(self.user.current_carat, 12345)

    def test_purchases_are_scoped_to_the_requesting_user(self):
        other = make_user(username='not-me')
        UserPlannedPurchase.objects.create(user=other, product=self.pack, quantity=5)
        self._patch([{'product': self.pack.id, 'quantity': 1}])

        res = self.client.get('/calculator-data')
        self.assertEqual(len(res.data['user_planned_purchase_data']), 1)
        self.assertEqual(res.data['user_planned_purchase_data'][0]['quantity'], 1)


class ReservedCopiesTests(TestCase):
    """reserved_copies rides along on the existing planned-banner payload."""

    def setUp(self):
        self.user = make_user()
        self.client, _ = auth_client(self.user)
        self.banner = make_uma_banner()

    def test_defaults_to_zero_and_round_trips(self):
        res = self.client.patch(
            '/calculator-data',
            {'user_planned_banner_data': [
                {'banner_uma': self.banner.id, 'number_of_pulls': 100}
            ]},
            format='json',
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(UserPlannedBanner.objects.get(user=self.user).reserved_copies, 0)

        planned = UserPlannedBanner.objects.get(user=self.user)
        res = self.client.patch(
            '/calculator-data',
            {'user_planned_banner_data': [
                {'id': planned.id, 'banner_uma': self.banner.id,
                 'number_of_pulls': 100, 'reserved_copies': 2}
            ]},
            format='json',
        )
        self.assertEqual(res.status_code, 200)
        planned.refresh_from_db()
        self.assertEqual(planned.reserved_copies, 2)

        res = self.client.get('/calculator-data')
        self.assertEqual(res.data['user_planned_banner_data'][0]['reserved_copies'], 2)


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
        'admin:calculatorapi_championsmeeting',
        'admin:calculatorapi_leagueofheroes',
        'admin:calculatorapi_clubrank',
        'admin:calculatorapi_anniversaryevent',
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
        # Derived from CONTENT_MODELS rather than hardcoded: the point of this
        # test is idempotency (running twice doesn't double up), not the size of
        # the list, and a literal here has to be hand-bumped for every new
        # content model.
        expected = len(CONTENT_MODELS) * 4  # add / change / delete / view
        self.assertEqual(group.permissions.count(), expected)

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


# ── PII Purge Command Tests ───────────────────────────────────────────────────

class PurgeUserPiiTests(TestCase):
    """`purge_user_pii` retires personal data from the old password-based
    sign-up while leaving staff logins working."""

    def setUp(self):
        self.user = make_user('olduser', 'oldpassword')
        self.staff = make_user('adminuser', 'adminpass', is_staff=True)

    def _run(self, **opts):
        out = StringIO()
        call_command('purge_user_pii', no_input=True, stdout=out, **opts)
        return out.getvalue()

    def test_dry_run_changes_nothing(self):
        output = self._run(dry_run=True)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, 'olduser@test.com')
        self.assertTrue(self.user.has_usable_password())
        self.assertIn('Dry run', output)

    def test_purge_blanks_non_staff_pii(self):
        self._run()
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, '')
        self.assertEqual(self.user.first_name, '')
        self.assertEqual(self.user.last_name, '')

    def test_purge_makes_password_unusable(self):
        self._run()
        self.user.refresh_from_db()
        self.assertFalse(self.user.has_usable_password())
        self.assertFalse(self.user.check_password('oldpassword'))

    def test_purged_user_cannot_login(self):
        self._run()
        res = APIClient().post(
            '/login', {'username': 'olduser', 'password': 'oldpassword'}, format='json')
        self.assertEqual(res.status_code, 400)

    def test_purge_deletes_non_staff_tokens(self):
        _client, token = auth_client(self.user)
        self._run()
        self.assertFalse(Token.objects.filter(key=token.key).exists())

    def test_staff_account_is_untouched(self):
        _client, staff_token = auth_client(self.staff)
        self._run()
        self.staff.refresh_from_db()
        self.assertEqual(self.staff.email, 'adminuser@test.com')
        self.assertTrue(self.staff.has_usable_password())
        self.assertTrue(Token.objects.filter(key=staff_token.key).exists())
        res = APIClient().post(
            '/login', {'username': 'adminuser', 'password': 'adminpass'}, format='json')
        self.assertEqual(res.status_code, 200)

    def test_purge_preserves_saved_plans(self):
        """Plans stay in the database — the accounts just become unreachable."""
        timeline = make_timeline()
        banner = BannerUma.objects.create(name='B', banner_timeline=timeline)
        UserPlannedBanner.objects.create(user=self.user, banner_uma=banner, number_of_pulls=10)
        self._run()
        self.assertEqual(UserPlannedBanner.objects.filter(user=self.user).count(), 1)

    def test_purge_is_idempotent(self):
        self._run()
        self._run()
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, '')
        self.assertFalse(self.user.has_usable_password())

    def test_social_users_survive_purge(self):
        """A social account has no PII to begin with; the purge must not break
        its ability to sign in (its token is deleted, but the link remains)."""
        social_user = CustomUser.objects.create_user(username='user_abc123')
        social_user.set_unusable_password()
        social_user.save()
        link = SocialAccount.objects.create(
            user=social_user, provider='google', subject_id='SUB-XYZ')
        self._run()
        self.assertTrue(SocialAccount.objects.filter(pk=link.pk).exists())
        self.assertEqual(SocialAccount.objects.get(pk=link.pk).user_id, social_user.pk)


@override_settings(STORAGES=PLAIN_TEST_STORAGES)
class SocialAccountAdminTests(TestCase):
    """Linked accounts are visible but not editable, and the one identifying
    value we hold is never rendered."""

    def setUp(self):
        self.superuser = CustomUser.objects.create_superuser(
            username='root', password='x')
        self.client.force_login(self.superuser)
        self.link = SocialAccount.objects.create(
            user=make_user('user_abc123'), provider='google', subject_id='SECRET-SUB-999')

    def test_changelist_renders(self):
        res = self.client.get(reverse('admin:calculatorapi_socialaccount_changelist'))
        self.assertEqual(res.status_code, 200)

    def test_subject_id_is_not_exposed_in_changelist(self):
        res = self.client.get(reverse('admin:calculatorapi_socialaccount_changelist'))
        self.assertNotContains(res, 'SECRET-SUB-999')

    def test_subject_id_is_not_exposed_on_change_page(self):
        res = self.client.get(
            reverse('admin:calculatorapi_socialaccount_change', args=[self.link.pk]))
        self.assertNotContains(res, 'SECRET-SUB-999')

    def test_add_page_is_forbidden(self):
        res = self.client.get(reverse('admin:calculatorapi_socialaccount_add'))
        self.assertEqual(res.status_code, 403)

    def test_link_cannot_be_edited_via_post(self):
        other = make_user('user_victim')
        self.client.post(
            reverse('admin:calculatorapi_socialaccount_change', args=[self.link.pk]),
            {'user': other.pk, 'provider': 'discord', 'subject_id': 'HIJACK'})
        self.link.refresh_from_db()
        self.assertEqual(self.link.subject_id, 'SECRET-SUB-999')
        self.assertEqual(self.link.provider, 'google')

    def test_user_admin_no_longer_offers_email_or_name_fields(self):
        res = self.client.get(
            reverse('admin:calculatorapi_customuser_change', args=[self.superuser.pk]))
        self.assertEqual(res.status_code, 200)
        self.assertNotContains(res, 'name="email"')
        self.assertNotContains(res, 'name="first_name"')


# ── Image Library / Picker Tests ──────────────────────────────────────────────

class ImageLibraryTests(TestCase):
    """The bucket-listing layer behind the admin's 'choose existing image' picker."""

    def setUp(self):
        # The listing cache is process-wide locmem and would otherwise leak
        # between tests (and from the widget rendering in AdminSmokeTests).
        cache.clear()

    def test_prefixes_are_derived_from_every_image_field(self):
        self.assertEqual(
            image_prefixes(),
            frozenset({
                'umas/', 'support_cards/', 'banner_timelines/',
                'game_events/', 'champions_meetings/', 'league_of_heroes/',
                'anniversary_events/',
            }),
        )

    def test_lists_only_image_files_sorted_by_name(self):
        listing = ([], ['b.png', 'notes.txt', 'A.jpg', 'c.webp'])
        with patch.object(image_library, 'default_storage') as storage:
            storage.listdir.return_value = listing
            storage.url.side_effect = lambda key: f'https://cdn.test/{key}'
            images = list_images('umas/')

        self.assertEqual([i['name'] for i in images], ['A.jpg', 'b.png', 'c.webp'])
        self.assertEqual(images[0]['key'], 'umas/A.jpg')
        self.assertEqual(images[0]['url'], 'https://cdn.test/umas/A.jpg')

    def test_second_call_is_served_from_cache(self):
        with patch.object(image_library, 'default_storage') as storage:
            storage.listdir.return_value = ([], ['a.png'])
            storage.url.return_value = 'https://cdn.test/umas/a.png'
            list_images('umas/')
            list_images('umas/')
            self.assertEqual(storage.listdir.call_count, 1)

    def test_bucket_failure_degrades_to_empty_and_is_not_cached(self):
        """A dead bucket must not 500 the admin, and must not poison the cache."""
        with patch.object(image_library, 'default_storage') as storage:
            storage.listdir.side_effect = OSError('no credentials')
            # assertLogs both asserts the failure is reported and keeps the
            # expected traceback out of the test runner's output.
            with self.assertLogs('calculatorapi.image_library', 'WARNING'):
                self.assertEqual(list_images('umas/'), [])
            self.assertFalse(listing_is_cached('umas/'))
            # A later call retries rather than serving the failure.
            self.assertEqual(storage.listdir.call_count, 1)
            with self.assertLogs('calculatorapi.image_library', 'WARNING'):
                list_images('umas/')
            self.assertEqual(storage.listdir.call_count, 2)

    def test_empty_folder_is_distinguishable_from_a_failed_listing(self):
        with patch.object(image_library, 'default_storage') as storage:
            storage.listdir.return_value = ([], [])
            self.assertEqual(list_images('umas/'), [])
            self.assertTrue(listing_is_cached('umas/'))

    def test_invalidate_forces_a_refetch(self):
        with patch.object(image_library, 'default_storage') as storage:
            storage.listdir.return_value = ([], ['a.png'])
            storage.url.return_value = 'https://cdn.test/umas/a.png'
            list_images('umas/')
            invalidate('umas/')
            list_images('umas/')
            self.assertEqual(storage.listdir.call_count, 2)

    def test_prefix_normalization_collapses_equivalent_spellings(self):
        self.assertEqual(normalize_prefix('umas'), 'umas/')
        self.assertEqual(normalize_prefix('/umas/'), 'umas/')
        self.assertEqual(normalize_prefix(''), '')
        self.assertEqual(normalize_prefix(None), '')

    def test_key_validation_rejects_anything_outside_the_image_folders(self):
        self.assertTrue(is_valid_key('umas/Special Week.png'))
        self.assertTrue(is_valid_key('support_cards/x.WEBP'))
        for bad in [
            '',                                # nothing picked
            '/umas/x.png',                     # absolute
            'umas/../../secrets/x.png',        # traversal
            'private/x.png',                   # folder not backing an ImageField
            'umas/notes.txt',                  # not an image
            'db.sqlite3',                      # bare path
        ]:
            with self.subTest(key=bad):
                self.assertFalse(is_valid_key(bad))


@override_settings(STORAGES=PLAIN_TEST_STORAGES)
class ImageLibraryEndpointTests(TestCase):
    """/admin/image-library/ — staff-only, allow-listed folders."""

    @classmethod
    def setUpTestData(cls):
        cls.superuser = CustomUser.objects.create_superuser(username='boss', password='x')

    def setUp(self):
        cache.clear()
        self.url = reverse('admin-image-library')

    def test_anonymous_is_redirected_to_admin_login(self):
        res = self.client.get(self.url, {'prefix': 'umas/'})
        self.assertEqual(res.status_code, 302)
        self.assertIn('/admin/login/', res.url)

    def test_non_staff_user_is_redirected_not_served(self):
        self.client.force_login(make_user('regular'))
        res = self.client.get(self.url, {'prefix': 'umas/'})
        self.assertEqual(res.status_code, 302)
        self.assertIn('/admin/login/', res.url)

    def test_unknown_folder_is_rejected(self):
        self.client.force_login(self.superuser)
        for prefix in ['', 'private/', '../', 'staticfiles/']:
            with self.subTest(prefix=prefix):
                res = self.client.get(self.url, {'prefix': prefix})
                self.assertEqual(res.status_code, 400)
                self.assertEqual(res.json()['images'], [])

    def test_staff_gets_the_folder_listing(self):
        self.client.force_login(self.superuser)
        with patch.object(image_library, 'default_storage') as storage:
            storage.listdir.return_value = ([], ['a.png'])
            storage.url.return_value = 'https://cdn.test/umas/a.png'
            res = self.client.get(self.url, {'prefix': 'umas/'})

        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body['prefix'], 'umas/')
        self.assertTrue(body['available'])
        self.assertEqual([i['key'] for i in body['images']], ['umas/a.png'])
        self.assertIn('support_cards/', body['folders'])

    def test_unreachable_bucket_reports_unavailable_rather_than_erroring(self):
        self.client.force_login(self.superuser)
        with patch.object(image_library, 'default_storage') as storage:
            storage.listdir.side_effect = OSError('boom')
            with self.assertLogs('calculatorapi.image_library', 'WARNING'):
                res = self.client.get(self.url, {'prefix': 'umas/'})

        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.json()['available'])

    def test_refresh_bypasses_the_cache(self):
        self.client.force_login(self.superuser)
        with patch.object(image_library, 'default_storage') as storage:
            storage.listdir.return_value = ([], ['a.png'])
            storage.url.return_value = 'https://cdn.test/umas/a.png'
            self.client.get(self.url, {'prefix': 'umas/'})
            self.client.get(self.url, {'prefix': 'umas/'})
            self.assertEqual(storage.listdir.call_count, 1)
            self.client.get(self.url, {'prefix': 'umas/', 'refresh': '1'})
            self.assertEqual(storage.listdir.call_count, 2)


class SpacesImagePickerFormTests(TestCase):
    """Saving a library choice writes the bucket key straight onto the field."""

    @classmethod
    def setUpClass(cls):
        # The upload test writes a real file through FileSystemStorage, and
        # MEDIA_ROOT is unset in settings (media lives in Spaces), which would
        # dump an "umas/" directory into backend/. Point it at a temp dir for
        # the duration and delete it afterwards.
        cls._media = tempfile.mkdtemp()
        cls._overrides = override_settings(
            STORAGES=PLAIN_TEST_STORAGES, MEDIA_ROOT=cls._media)
        cls._overrides.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._overrides.disable()
        shutil.rmtree(cls._media, ignore_errors=True)

    @classmethod
    def setUpTestData(cls):
        cls.superuser = CustomUser.objects.create_superuser(username='boss', password='x')

    def setUp(self):
        cache.clear()
        self.client.force_login(self.superuser)
        self.add_url = reverse('admin:calculatorapi_uma_add')

    def test_picked_key_is_saved_without_uploading_anything(self):
        res = self.client.post(self.add_url, {
            'name': 'Special Week',
            'image': '',                                   # no upload
            'image-library-key': 'umas/Special Week.png',   # picked in the modal
        })
        self.assertEqual(res.status_code, 302)  # 302 == saved; 200 == redisplayed with errors
        self.assertEqual(Uma.objects.get(name='Special Week').image.name,
                         'umas/Special Week.png')

    def test_key_outside_the_library_is_rejected_with_a_form_error(self):
        res = self.client.post(self.add_url, {
            'name': 'Sneaky',
            'image': '',
            'image-library-key': '../../etc/passwd.png',
        })
        self.assertEqual(res.status_code, 200)
        self.assertFalse(Uma.objects.filter(name='Sneaky').exists())
        self.assertContains(res, 'not in the media library')

    def test_an_upload_wins_over_a_simultaneous_library_pick(self):
        """Both submitted at once must keep the file the editor actually chose."""
        upload = SimpleUploadedFile('new.png', PNG_1PX, content_type='image/png')
        res = self.client.post(self.add_url, {
            'name': 'Uploader',
            'image': upload,
            'image-library-key': 'umas/Some Other.png',
        })
        self.assertEqual(res.status_code, 302)
        saved = Uma.objects.get(name='Uploader').image.name
        self.assertNotEqual(saved, 'umas/Some Other.png')
        self.assertIn('new', saved)

    def test_no_pick_leaves_an_existing_image_untouched(self):
        uma = Uma.objects.create(name='Keeper', image='umas/Keeper.png')
        res = self.client.post(
            reverse('admin:calculatorapi_uma_change', args=[uma.pk]),
            {'name': 'Keeper renamed', 'image': '', 'image-library-key': ''})
        self.assertEqual(res.status_code, 302)
        uma.refresh_from_db()
        self.assertEqual(uma.name, 'Keeper renamed')
        self.assertEqual(uma.image.name, 'umas/Keeper.png')

    def test_change_form_renders_the_picker_for_every_image_admin(self):
        for base in ['bannertimeline', 'uma', 'supportcard', 'gameevent',
                     'championsmeeting', 'leagueofheroes']:
            with self.subTest(model=base):
                res = self.client.get(reverse(f'admin:calculatorapi_{base}_add'))
                self.assertEqual(res.status_code, 200)
                self.assertContains(res, 'spaces-picker')
                self.assertContains(res, 'name="image-library-key"')
                self.assertContains(res, 'spaces-image-picker.js')


class BannerCategoryTests(TestCase):
    """The stored category, and the two commands that populate it."""

    def _timeline(self, name, jp_start, **kwargs):
        return BannerTimeline.objects.create(
            name=name,
            jp_start_date=timezone.make_aware(datetime.datetime(*jp_start)),
            jp_end_date=timezone.make_aware(datetime.datetime(*jp_start) +
                                            datetime.timedelta(days=10)),
            **kwargs)

    def _with_umas(self, timeline, *names):
        banner = BannerUma.objects.create(banner_timeline=timeline, name=' + '.join(names))
        for name in names:
            uma, _ = Uma.objects.get_or_create(name=name)
            UmasOnUmaBanner.objects.create(banner_uma=banner, uma=uma)
        return banner

    def _with_supports(self, timeline, *names):
        banner = BannerSupport.objects.create(banner_timeline=timeline,
                                              name=' + '.join(names))
        for name in names:
            card, _ = SupportCard.objects.get_or_create(name=name)
            SupportsOnSupportBanner.objects.create(banner_support=banner,
                                                   support_card=card)
        return banner

    def test_defaults_to_standard(self):
        timeline = self._timeline('Plain', (2024, 1, 1))
        self.assertEqual(timeline.banner_category, BannerCategory.STANDARD)

    def test_classify_sets_revival_on_many_umas_and_no_supports(self):
        revival = self._timeline('A + B + C', (2025, 4, 30))
        self._with_umas(revival, 'A', 'B', 'C')

        call_command('classify_banner_categories', '--no-input', stdout=StringIO())

        revival.refresh_from_db()
        self.assertEqual(revival.banner_category, BannerCategory.GOLDEN_WEEK_REVIVAL)

    def test_classify_leaves_a_two_uma_banner_alone(self):
        """The concurrent standard banner shares the window and must not be swept up."""
        standard = self._timeline('D + E', (2025, 4, 30))
        self._with_umas(standard, 'D', 'E')
        self._with_supports(standard, 'S1', 'S2')

        call_command('classify_banner_categories', '--no-input', stdout=StringIO())

        standard.refresh_from_db()
        self.assertEqual(standard.banner_category, BannerCategory.STANDARD)

    def test_classify_ignores_many_umas_that_also_have_supports(self):
        """Zero supports is half the rule — three umas alone must not qualify."""
        timeline = self._timeline('F + G + H', (2025, 6, 1))
        self._with_umas(timeline, 'F', 'G', 'H')
        self._with_supports(timeline, 'S3')

        call_command('classify_banner_categories', '--no-input', stdout=StringIO())

        timeline.refresh_from_db()
        self.assertEqual(timeline.banner_category, BannerCategory.STANDARD)

    def test_classify_is_idempotent(self):
        revival = self._timeline('A + B + C', (2025, 4, 30))
        self._with_umas(revival, 'A', 'B', 'C')

        call_command('classify_banner_categories', '--no-input', stdout=StringIO())
        second = StringIO()
        call_command('classify_banner_categories', '--no-input', stdout=second)

        self.assertIn('Nothing to change', second.getvalue())
        revival.refresh_from_db()
        self.assertEqual(revival.banner_category, BannerCategory.GOLDEN_WEEK_REVIVAL)

    def test_classify_dry_run_writes_nothing(self):
        revival = self._timeline('A + B + C', (2025, 4, 30))
        self._with_umas(revival, 'A', 'B', 'C')

        call_command('classify_banner_categories', '--dry-run', stdout=StringIO())

        revival.refresh_from_db()
        self.assertEqual(revival.banner_category, BannerCategory.STANDARD)

    def test_classify_reports_reruns_without_applying_them(self):
        rerun = self._timeline('Gentildonna (Rerun)', (2026, 1, 1))

        out = StringIO()
        call_command('classify_banner_categories', '--no-input', stdout=out)

        self.assertIn('Rerun candidates', out.getvalue())
        rerun.refresh_from_db()
        self.assertEqual(rerun.banner_category, BannerCategory.STANDARD)

    def test_repair_launch_banner_links_umas_parsed_from_the_name(self):
        launch = self._timeline('Special Week + Tokai Teio + Oguri Cap', (2021, 2, 24))
        for name in ['Special Week', 'Tokai Teio', 'Oguri Cap']:
            Uma.objects.create(name=name)

        call_command('repair_launch_banner', '--no-input', stdout=StringIO())

        banner = launch.uma_banners.get()
        self.assertCountEqual(
            [u.name for u in banner.umas.all()],
            ['Special Week', 'Tokai Teio', 'Oguri Cap'])

    def test_repair_launch_banner_is_idempotent(self):
        launch = self._timeline('Special Week', (2021, 2, 24))
        Uma.objects.create(name='Special Week')

        call_command('repair_launch_banner', '--no-input', stdout=StringIO())
        call_command('repair_launch_banner', '--no-input', stdout=StringIO())

        self.assertEqual(launch.uma_banners.count(), 1)

    def test_repair_launch_banner_will_not_create_missing_uma_records(self):
        launch = self._timeline('Special Week + Nonexistent Unit', (2021, 2, 24))
        Uma.objects.create(name='Special Week')

        out = StringIO()
        call_command('repair_launch_banner', '--no-input', stdout=out)

        self.assertIn('Nonexistent Unit', out.getvalue())
        self.assertFalse(Uma.objects.filter(name='Nonexistent Unit').exists())
        self.assertEqual(launch.uma_banners.get().umas.count(), 1)

    def test_category_is_serialized_to_the_timeline_payload(self):
        timeline = self._timeline('A + B + C', (2025, 4, 30),
                                  banner_category=BannerCategory.GOLDEN_WEEK_REVIVAL)
        self._with_umas(timeline, 'A', 'B', 'C')

        res = self.client.get('/calculator-data')

        self.assertEqual(res.status_code, 200)
        row = next(t for t in res.json()['banner_timeline_data']
                   if t['id'] == timeline.pk)
        self.assertEqual(row['banner_category'], 'golden_week_revival')


class SupportBackfillTests(TestCase):
    """
    The race-prep support backfill and the launch banner's support half.

    Both read timeline_master.csv, so these tests point the module at a
    temporary CSV of their own rather than depending on the real file's
    contents — which change whenever a banner is added.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.csv_path = os.path.join(self.tmp, 'timeline_master.csv')
        patcher = patch.object(support_backfill, 'TIMELINE_MASTER', self.csv_path)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _write_csv(self, rows):
        """rows: (jp_start, banner_type, uma, supports-joined)."""
        with open(self.csv_path, 'w', newline='', encoding='utf-8') as handle:
            writer = csv.writer(handle)
            writer.writerow(['JP Start Date', 'Banner Type', 'Banner Uma', 'Banner Support'])
            writer.writerows(rows)

    def _timeline(self, name, jp_start, **kwargs):
        return BannerTimeline.objects.create(
            name=name,
            jp_start_date=timezone.make_aware(datetime.datetime(*jp_start)),
            jp_end_date=timezone.make_aware(datetime.datetime(*jp_start) +
                                            datetime.timedelta(days=10)),
            **kwargs)

    def _cards(self, *names):
        for name in names:
            SupportCard.objects.get_or_create(name=name)

    # ── resolve_support_cards ────────────────────────────────────────────────

    def test_resolves_names_case_insensitively(self):
        self._cards('Super Creek')
        found, missing = support_backfill.resolve_support_cards(['super creek'])
        self.assertEqual([c.name for c in found], ['Super Creek'])
        self.assertEqual(missing, [])

    def test_resolves_the_known_spelling_differences(self):
        # "K.S. Miracle" needs no alias — normalize() drops the periods so it
        # and the card's own "K.S.Miracle" collapse together. The other two are
        # genuine aliases, shared with the fixture pipeline.
        self._cards('K.S.Miracle', 'Tamamo Cross', 'Tazuna Hayakawa')
        found, missing = support_backfill.resolve_support_cards(
            ['K.S. Miracle', 'Tamano Cross', 'Tazuna'])
        self.assertEqual(missing, [])
        self.assertEqual(
            sorted(c.name for c in found),
            ['K.S.Miracle', 'Tamamo Cross', 'Tazuna Hayakawa'])

    def test_resolves_a_rerun_token_to_the_base_card(self):
        self._cards('Super Creek')
        found, missing = support_backfill.resolve_support_cards(['Super Creek (Rerun)'])
        self.assertEqual([c.name for c in found], ['Super Creek'])
        self.assertEqual(missing, [])

    def test_duplicate_names_resolve_to_the_lowest_game_id(self):
        # SupportCard.name is deliberately not unique — production holds four
        # rows named "Grass Wonder" (different rarities/reprints). game_id is
        # the real identity, the CSV carries only names, so the collision is
        # resolved by the same rule the fixture pipeline uses. Without this the
        # backfill would link an arbitrary rarity.
        SupportCard.objects.create(name='Grass Wonder', game_id=30200)
        wanted = SupportCard.objects.create(name='Grass Wonder', game_id=30100)
        SupportCard.objects.create(name='Grass Wonder', game_id=30300)

        found, missing = support_backfill.resolve_support_cards(['Grass Wonder'])

        self.assertEqual(missing, [])
        self.assertEqual([c.pk for c in found], [wanted.pk])

    def test_a_null_game_id_sorts_ahead_of_a_real_one(self):
        # Mirrors the pipeline's `gid = ... or 0`.
        wanted = SupportCard.objects.create(name='Nameless', game_id=None)
        SupportCard.objects.create(name='Nameless', game_id=30001)

        found, _ = support_backfill.resolve_support_cards(['Nameless'])

        self.assertEqual([c.pk for c in found], [wanted.pk])

    def test_reports_an_unknown_name_rather_than_guessing(self):
        # The guard against fuzzy matching: a similarity check offered
        # "Hishi Miracle" as the runner-up for "K.S. Miracle".
        self._cards('Hishi Miracle')
        found, missing = support_backfill.resolve_support_cards(['K.S. Miracle'])
        self.assertEqual(found, [])
        self.assertEqual(missing, ['K.S. Miracle'])

    def test_resolves_a_card_that_is_on_no_banner(self):
        # Such a card is invisible to the public API, so the command must look
        # at SupportCard directly or it would wrongly report it missing.
        self._cards('Orphan Card')
        found, _ = support_backfill.resolve_support_cards(['Orphan Card'])
        self.assertEqual([c.name for c in found], ['Orphan Card'])

    # ── backfill_race_prep_supports ──────────────────────────────────────────

    def test_attaches_the_support_cards_and_sets_the_category(self):
        timeline = self._timeline('Satono Crown', (2023, 12, 11))
        self._cards('Super Creek', 'Tokai Teio')
        self._write_csv([('2023-12-11', '2', 'Satono Crown', 'Super Creek + Tokai Teio')])

        call_command('backfill_race_prep_supports', '--no-input')

        timeline.refresh_from_db()
        banner = timeline.support_banners.get()
        self.assertEqual(banner.name, 'Race Prep Support')
        self.assertEqual(
            sorted(banner.support_cards.values_list('name', flat=True)),
            ['Super Creek', 'Tokai Teio'])
        self.assertEqual(timeline.banner_category, BannerCategory.RACE_PREP_SUPPORT)

    def test_ignores_rows_that_are_not_race_prep(self):
        timeline = self._timeline('Ordinary', (2023, 12, 11))
        self._cards('Super Creek')
        self._write_csv([('2023-12-11', '1', 'Ordinary', 'Super Creek')])

        call_command('backfill_race_prep_supports', '--no-input')

        timeline.refresh_from_db()
        self.assertFalse(timeline.support_banners.exists())
        self.assertEqual(timeline.banner_category, BannerCategory.STANDARD)

    def test_dry_run_writes_nothing(self):
        timeline = self._timeline('Satono Crown', (2023, 12, 11))
        self._cards('Super Creek')
        self._write_csv([('2023-12-11', '2', 'Satono Crown', 'Super Creek')])

        call_command('backfill_race_prep_supports', '--dry-run')

        timeline.refresh_from_db()
        self.assertFalse(timeline.support_banners.exists())
        self.assertEqual(timeline.banner_category, BannerCategory.STANDARD)

    def test_is_idempotent(self):
        self._timeline('Satono Crown', (2023, 12, 11))
        self._cards('Super Creek')
        self._write_csv([('2023-12-11', '2', 'Satono Crown', 'Super Creek')])

        call_command('backfill_race_prep_supports', '--no-input')
        call_command('backfill_race_prep_supports', '--no-input')

        self.assertEqual(BannerSupport.objects.count(), 1)
        self.assertEqual(SupportsOnSupportBanner.objects.count(), 1)

    def test_skips_a_whole_banner_when_one_card_is_unknown(self):
        # Half a batch is worse than none: it would look complete in the UI
        # while quietly under-representing the banner.
        timeline = self._timeline('Satono Crown', (2023, 12, 11))
        self._cards('Super Creek')
        self._write_csv([('2023-12-11', '2', 'Satono Crown', 'Super Creek + Nonesuch')])

        call_command('backfill_race_prep_supports', '--no-input')

        timeline.refresh_from_db()
        self.assertFalse(timeline.support_banners.exists())
        self.assertEqual(timeline.banner_category, BannerCategory.STANDARD)

    def test_never_creates_support_cards(self):
        self._timeline('Satono Crown', (2023, 12, 11))
        self._write_csv([('2023-12-11', '2', 'Satono Crown', 'Nonesuch')])

        call_command('backfill_race_prep_supports', '--no-input')

        self.assertEqual(SupportCard.objects.count(), 0)

    def test_survives_a_csv_row_with_no_matching_timeline(self):
        self._cards('Super Creek')
        self._write_csv([('2023-12-11', '2', 'Ghost', 'Super Creek')])

        call_command('backfill_race_prep_supports', '--no-input')

        self.assertEqual(BannerSupport.objects.count(), 0)

    # ── repair_launch_banner, support half ───────────────────────────────────

    def test_launch_repair_links_supports_alongside_umas(self):
        self._timeline('Special Week + Tokai Teio', (2021, 2, 24))
        Uma.objects.create(name='Special Week')
        Uma.objects.create(name='Tokai Teio')
        self._cards('Super Creek', 'Tazuna Hayakawa')
        self._write_csv([('2021-02-24', '-2', '', 'Super Creek + Tazuna')])

        call_command('repair_launch_banner', '--no-input')

        timeline = BannerTimeline.objects.get()
        self.assertEqual(timeline.uma_banners.get().umas.count(), 2)
        support = timeline.support_banners.get()
        self.assertEqual(support.name, 'Launch Support')
        self.assertEqual(
            sorted(support.support_cards.values_list('name', flat=True)),
            ['Super Creek', 'Tazuna Hayakawa'])

    def test_launch_repair_completes_a_row_that_already_has_its_umas(self):
        # Production is in exactly this state: the uma half was applied before
        # the support half existed, so an early return would strand it.
        timeline = self._timeline('Special Week', (2021, 2, 24))
        uma = Uma.objects.create(name='Special Week')
        banner = BannerUma.objects.create(banner_timeline=timeline, name='Special Week')
        UmasOnUmaBanner.objects.create(banner_uma=banner, uma=uma)
        self._cards('Super Creek')
        self._write_csv([('2021-02-24', '-2', '', 'Super Creek')])

        call_command('repair_launch_banner', '--no-input')

        self.assertEqual(timeline.uma_banners.count(), 1)
        self.assertEqual(timeline.support_banners.get().support_cards.count(), 1)

    def test_launch_repair_links_what_it_can_when_a_card_is_missing(self):
        # Unlike a race-prep batch, the launch banner is a one-off: 19 of 20
        # cards is materially better than nothing, and the gap is reported.
        self._timeline('Special Week', (2021, 2, 24))
        Uma.objects.create(name='Special Week')
        self._cards('Super Creek')
        self._write_csv([('2021-02-24', '-2', '', 'Super Creek + Grass Wonder')])

        call_command('repair_launch_banner', '--no-input')

        support = BannerTimeline.objects.get().support_banners.get()
        self.assertEqual(
            list(support.support_cards.values_list('name', flat=True)), ['Super Creek'])

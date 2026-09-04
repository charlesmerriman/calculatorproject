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
# pylint: disable=too-many-public-methods
# pylint: disable=too-many-instance-attributes

import csv
import datetime
import json
import os
import shutil
import tempfile
from io import StringIO
from unittest.mock import patch
from urllib.parse import parse_qs, urlencode, urlparse

from django.contrib.auth.models import Group
from django.core import signing
from django.core.exceptions import ValidationError
from django.db import IntegrityError, models, transaction
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import RequestFactory, TestCase, override_settings
from django.urls import NoReverseMatch, reverse
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from calculatorapi import image_library, public_payload_cache, support_backfill
from calculatorapi.management.commands.sync_changelog import (
    load_entries as load_changelog_entries,
)
from calculatorapi.image_library import (
    image_prefixes,
    invalidate,
    is_valid_key,
    list_images,
    listing_is_cached,
    normalize_prefix,
)
from calculatorapi.analytics import build_analytics_report
from calculatorapi.visits import (
    VISITOR_HASH_RETENTION_DAYS,
    build_visit_report,
    record_visit,
)
from calculatorapi.ledger import AMOUNT_FIELDS, build_income_ledger
from calculatorapi.views.ledger import IncomeLedgerRowSerializer
from calculatorapi.views.social_auth import STATE_SALT
from calculatorapi.views.calculation_constants import CalculationConstantsSerializer
from calculatorapi.views.user_planned_banner import UserPlannedBannerSerializer
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
    build_scenario_date_map,
)
from calculatorapi.eligibility import build_first_jp_date_maps, is_eligible
from calculatorapi.management.commands.create_content_editor_group import CONTENT_MODELS
from calculatorapi.admin_patreon_import import apply_patreon_import, parse_patreon_csv
from calculatorapi import patreon_api
from calculatorapi.models import (
    CustomUser, Uma, SupportCard,
    ClubRank, TeamTrialsRank, ChampionsMeetingRank, LeagueOfHeroesRank,
    BannerTimeline, BannerUma, BannerSupport, BannerStepUp, UserPlannedBanner,
    ChampionsMeeting, LeagueOfHeroes, GameEvent, Scenario,
    ChangelogEntry, ChangelogChange,
    SocialAccount,
    CalculationConstants,
    AnniversaryEvent, AnniversaryEventBanner, AnniversaryEventProduct,
    UserPlannedPurchase, UserStepUpSelection,
    UmasOnUmaBanner, SupportsOnSupportBanner,
    BannerCategory,
    DailyVisit, MonthlyVisit, VisitorHash,
    Feedback, MESSAGE_MAX_LENGTH,
    PatreonTier, PatreonSupporter, PatreonCredentials,
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


def make_step_up_banner(event=None, timeline=None, name='Test Step-Up',
                        card_type='support', banner_count=3, order=0):
    """Create a BannerStepUp, wiring a campaign and a Part if none is given.

    The two FKs must agree (the timeline has to be one of the campaign's parts),
    so building one implies building the other -- which is exactly the coupling
    BannerStepUp.clean() enforces.
    """
    if timeline is None:
        timeline = make_timeline(name=f'{name} Window')
    if event is None:
        event = make_anniversary_event(name=f'{name} Campaign', parts=(timeline,))
    return BannerStepUp.objects.create(
        anniversary_event=event, banner_timeline=timeline, name=name,
        card_type=card_type, banner_count=banner_count, order=order,
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


def make_scenario(name='Test Scenario', banner_timeline=None, image=None):
    """Create a Scenario, optionally linked to its launch BannerTimeline.

    A scenario's start comes from that banner and it has NO end date at all --
    it stays playable after release, so there is nothing for an end to mean.
    `image` is routinely None: scenarios get entered before their art exists.
    """
    return Scenario.objects.create(
        name=name, banner_timeline=banner_timeline, image=image,
    )


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


def _dt(y, m, d, hour=0, minute=0, second=0):
    """A UTC datetime. Time-of-day defaults to midnight — most fixtures only
    care about the calendar day — but is available for the cases that turn on
    it, e.g. a confirmed global window running 22:00 -> 21:59:59."""
    return datetime.datetime(y, m, d, hour, minute, second, tzinfo=_UTC)


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
        # Paid tier only — the free tier earns no shards from the pass.
        self.assertEqual(constants.training_pass_paid_ssr_shards, 1)
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


class CalculationConstantsSerializerTests(TestCase):
    def test_every_decimal_constant_serializes_as_a_number(self):
        """No constant may reach the client as a decimal STRING.

        DRF serializes DecimalField as a string by default, and the client feeds
        these straight into arithmetic where `"0.003" * 500` is a silent NaN
        rather than an error. Each such field therefore needs an explicit
        FloatField on the serializer — easy to forget when adding one, and
        invisible until a number goes wrong somewhere unrelated. This walks the
        model instead of naming fields, so it covers constants added later.
        """
        data = CalculationConstantsSerializer(CalculationConstants.load()).data
        decimal_fields = [
            field.name for field in CalculationConstants._meta.get_fields()
            if isinstance(field, models.DecimalField)
        ]
        self.assertTrue(decimal_fields, "expected some DecimalField constants")

        stringly = [name for name in decimal_fields if isinstance(data[name], str)]
        self.assertEqual(
            stringly, [],
            f"these reach the client as strings; add serializers.FloatField(): {stringly}",
        )


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

    def test_race_rows_are_dated_at_end_less_lead_time_and_carry_no_amounts(self):
        # A Champions Meeting settles its placements 24h before its window
        # closes; League of Heroes has no lead time. The gap between the two is
        # the only place these otherwise identical kinds diverge, so it is
        # asserted side by side rather than in separate tests.
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
                         ('champions_meeting', _dt(2025, 6, 7)))
        self.assertEqual((loh['kind'], loh['date']),
                         ('league_of_heroes', _dt(2025, 7, 8)))
        # Amounts stay zero: what a placement pays depends on the user's rank.
        for row in (cm, loh):
            self.assertEqual(row['carats'], 0)
            self.assertEqual(row['uma_tickets'], 0)

    def test_cm_lead_time_keeps_the_time_of_day(self):
        # Confirmed global windows run 22:00 -> 21:59:59, not midnight to
        # midnight. The lead time is a timedelta off the resolved end, so it
        # shifts the whole instant and must NOT truncate to a date — a CM
        # closing at 21:59:59 settles at 21:59:59 the previous day.
        make_champions_meeting(
            name='CM', global_start_date=_dt(2025, 6, 1, 22, 0, 0),
            global_end_date=_dt(2025, 6, 8, 21, 59, 59),
        )
        self.assertEqual(self._one_row()['date'], _dt(2025, 6, 7, 21, 59, 59))

    def test_past_events_are_included(self):
        # Deliberate: the ledger is a set of dated facts with no "as of today"
        # gate. The sheet bakes one into its CM/LoH columns; we apply it
        # client-side instead so the whole calculation shares one anchor.
        make_champions_meeting(
            name='Long gone', global_start_date=_dt(2020, 1, 1),
            global_end_date=_dt(2020, 1, 8),
        )
        row = self._one_row()
        self.assertEqual(row['date'], _dt(2020, 1, 7))

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
    'banner_step_up_data',
    'user_planned_banner_data', 'champions_meeting_data', 'league_of_heroes_event_data',
    'events_data', 'user_stats_data', 'banner_timeline_data',
    'anniversary_event_data', 'scenario_data', 'user_planned_purchase_data',
    'user_step_up_selection_data',
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
        self.assertTrue(self.user.monthly_shop_tickets)
        self.assertTrue(self.user.discounted_paid_pulls)
        self.assertTrue(self.user.full_price_paid_pulls)
        res = self.client.patch(
            '/calculator-data',
            {'user_stats_data': {
                'monthly_shop_tickets': False,
                'discounted_paid_pulls': False,
                'full_price_paid_pulls': False,
            }},
            format='json',
        )
        self.assertEqual(res.status_code, 200)
        self.user.refresh_from_db()
        self.assertFalse(self.user.monthly_shop_tickets)
        self.assertFalse(self.user.discounted_paid_pulls)
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

class BannerStepUpTests(TestCase):
    """The step-up model, its constraint, and how it reaches the API."""

    def setUp(self):
        self.user = make_user()
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_max_steps_is_five_per_banner_sold(self):
        # The real ceiling on a plan. The sheet's own 35-step cap is an artifact
        # of its lookup table's extent, and with at most 3 banners never binds.
        self.assertEqual(make_step_up_banner(banner_count=1).max_steps, 5)
        self.assertEqual(make_step_up_banner(banner_count=3).max_steps, 15)

    def test_clean_rejects_a_timeline_from_another_campaign(self):
        # The two FKs are both load-bearing: the timeline dates the row, the
        # campaign supplies the cutoff. A mismatch would date a step-up off an
        # unrelated window and silently project the wrong income.
        part = make_timeline(name='Campaign Part')
        event = make_anniversary_event(name='Campaign', parts=(part,))
        stranger = make_timeline(name='Unrelated Banner')

        step_up = BannerStepUp(
            anniversary_event=event, banner_timeline=stranger, name='Bad',
        )
        with self.assertRaises(ValidationError) as ctx:
            step_up.full_clean()
        self.assertIn('banner_timeline', ctx.exception.error_dict)

    def test_clean_accepts_a_timeline_that_is_one_of_the_campaign_parts(self):
        part_one = make_timeline(name='Part 1')
        part_two = make_timeline(name='Part 2')
        event = make_anniversary_event(name='Campaign', parts=(part_one, part_two))

        step_up = BannerStepUp(
            anniversary_event=event, banner_timeline=part_two, name='Good',
            card_type='support', banner_count=3,
        )
        step_up.full_clean()  # must not raise

    def test_planned_row_accepts_a_step_up_as_its_only_target(self):
        step_up = make_step_up_banner()
        row = UserPlannedBanner.objects.create(
            user=self.user, banner_step_up=step_up, number_of_pulls=10,
        )
        self.assertEqual(row.banner_target, step_up)

    def test_constraint_rejects_two_targets_including_the_new_one(self):
        step_up = make_step_up_banner()
        uma_banner = make_uma_banner()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                UserPlannedBanner.objects.create(
                    user=self.user, banner_uma=uma_banner,
                    banner_step_up=step_up, number_of_pulls=1,
                )

    def test_constraint_still_rejects_a_row_with_no_target(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                UserPlannedBanner.objects.create(user=self.user, number_of_pulls=1)

    def test_str_counts_steps_not_pulls_on_a_step_up_row(self):
        # number_of_pulls is deliberately overloaded; the noun has to follow.
        step_up = make_step_up_banner(name='5th Anniversary SSR Select Step-Up')
        row = UserPlannedBanner.objects.create(
            user=self.user, banner_step_up=step_up, number_of_pulls=10,
        )
        self.assertIn('10 steps', str(row))

    def test_calculator_data_serves_step_up_banners(self):
        make_step_up_banner(name='5th Anniversary SSR Select Step-Up',
                            card_type='support', banner_count=3)

        res = self.client.get('/calculator-data')

        self.assertEqual(res.status_code, 200)
        rows = res.data['banner_step_up_data']
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row['name'], '5th Anniversary SSR Select Step-Up')
        self.assertEqual(row['card_type'], 'support')
        # Derived server-side so the count and the rule stay together.
        self.assertEqual(row['max_steps'], 15)
        # Nested exactly like its uma/support peers -- that shared shape is what
        # lets the client resolve all three kinds through one code path.
        self.assertIn('banner_timeline', row)
        self.assertIn('start_date', row['banner_timeline'])

    def test_step_up_row_folds_in_its_campaign_cutoff(self):
        # A step-up's candidates are back-catalogue cards bounded by the
        # campaign's cutoff. Folded in the same way campaign products fold it,
        # so a row can show the bound without joining the campaign itself.
        part = make_timeline(name='Part 2')
        event = make_anniversary_event(
            name='5th Anniversary', jp_cutoff_date=datetime.date(2026, 1, 30),
            parts=(part,),
        )
        make_step_up_banner(event=event, timeline=part)

        res = self.client.get('/calculator-data')

        # Serialized as an ISO string, the same shape the campaign products
        # emit theirs in.
        self.assertEqual(
            res.data['banner_step_up_data'][0]['jp_cutoff_date'], '2026-01-30',
        )

    def test_planned_step_up_round_trips_through_patch(self):
        step_up = make_step_up_banner()
        payload = {
            'user_planned_banner_data': [
                {'number_of_pulls': 10, 'reserved_copies': 0,
                 'banner_uma': None, 'banner_support': None,
                 'banner_step_up': step_up.id},
            ],
            # Sent alongside because a PATCH body missing a collection leaves it
            # alone -- an omitted one would make this pass without saving.
            'user_planned_purchase_data': [],
        }
        res = self.client.patch('/calculator-data', payload, format='json')
        self.assertEqual(res.status_code, 200)

        saved = UserPlannedBanner.objects.get(user=self.user)
        self.assertEqual(saved.banner_step_up_id, step_up.id)
        self.assertIsNone(saved.banner_uma_id)

        # And it comes back nested, not as a bare id.
        got = self.client.get('/calculator-data')
        row = got.data['user_planned_banner_data'][0]
        self.assertEqual(row['banner_step_up']['id'], step_up.id)

    def test_patch_rejects_a_row_with_two_targets(self):
        step_up = make_step_up_banner()
        uma_banner = make_uma_banner()
        res = self.client.patch('/calculator-data', {
            'user_planned_banner_data': [
                {'number_of_pulls': 1, 'reserved_copies': 0,
                 'banner_uma': uma_banner.id, 'banner_support': None,
                 'banner_step_up': step_up.id},
            ],
            'user_planned_purchase_data': [],
        }, format='json')
        # A readable 400 rather than a 500 from the database constraint.
        self.assertEqual(res.status_code, 400)

    def test_partial_update_keeps_the_existing_target(self):
        # _replace_user_rows patches with partial=True. A body that names only
        # number_of_pulls must not read as "no target provided".
        step_up = make_step_up_banner()
        row = UserPlannedBanner.objects.create(
            user=self.user, banner_step_up=step_up, number_of_pulls=5,
        )
        serializer = UserPlannedBannerSerializer(
            row, data={'number_of_pulls': 10}, partial=True,
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_planned_step_up_sorts_by_its_own_timeline(self):
        # planned_effective_start has to follow the third FK too; without that
        # branch a step-up row resolves to None and sorts to the front.
        early = make_timeline(
            name='Early',
            global_start_date=_dt(2030, 1, 1), global_end_date=_dt(2030, 1, 20),
        )
        late = make_timeline(
            name='Late',
            global_start_date=_dt(2030, 6, 1), global_end_date=_dt(2030, 6, 20),
        )
        event = make_anniversary_event(name='Campaign', parts=(early, late))
        late_step_up = make_step_up_banner(event=event, timeline=late)

        UserPlannedBanner.objects.create(
            user=self.user, banner_uma=make_uma_banner(timeline=early),
            number_of_pulls=1,
        )
        UserPlannedBanner.objects.create(
            user=self.user, banner_step_up=late_step_up, number_of_pulls=1,
        )

        res = self.client.get('/calculator-data')
        rows = res.data['user_planned_banner_data']
        self.assertEqual(len(rows), 2)
        # The step-up dates off June, so it sorts second -- not first, which is
        # where an unresolved (None) key would put it.
        self.assertIsNotNone(rows[1]['banner_step_up'])


class UserStepUpSelectionTests(TestCase):
    """The ten cards a user intends to pick at a step-up, and the rules on them.

    Nothing here should ever affect a projected number -- these tests exist to
    prove the record round-trips and that the constraints hold, not that any
    carat total moved. See UserStepUpSelection's docstring.
    """

    def setUp(self):
        self.user = make_user()
        self.client, _ = auth_client(self.user)
        self.event = make_anniversary_event(
            name='5th Anniversary',
            jp_cutoff_date=datetime.date(2026, 1, 30),
            parts=[make_timeline(name='5th Part 2')],
        )
        part = self.event.banner_links.first().banner_timeline
        self.uma_step_up = make_step_up_banner(
            event=self.event, timeline=part, name='5th ★3 Select Step-Up',
            card_type='uma', banner_count=2,
        )
        self.support_step_up = make_step_up_banner(
            event=self.event, timeline=part, name='5th SSR Select Step-Up',
            card_type='support', banner_count=3,
        )
        # One uma inside the cutoff and one released after it.
        self.eligible_uma = self._uma_first_seen('Kiseki', datetime.datetime(2025, 6, 1))
        self.other_uma = self._uma_first_seen('Buena Vista', datetime.datetime(2025, 8, 1))
        self.late_uma = self._uma_first_seen('Too New', datetime.datetime(2026, 6, 1))
        self.eligible_support = self._support_first_seen(
            'Matikanefukukitaru', 30286, datetime.datetime(2025, 6, 1)
        )

    def _uma_first_seen(self, name, when):
        timeline = make_timeline(
            name=f'{name} debut', jp_start_date=timezone.make_aware(when),
        )
        uma = Uma.objects.create(name=name)
        UmasOnUmaBanner.objects.create(
            uma=uma, banner_uma=make_uma_banner(timeline, name=f'{name} banner')
        )
        return uma

    def _support_first_seen(self, name, game_id, when):
        timeline = make_timeline(
            name=f'{name} debut', jp_start_date=timezone.make_aware(when),
        )
        card = SupportCard.objects.create(name=name, game_id=game_id)
        SupportsOnSupportBanner.objects.create(
            support_card=card,
            banner_support=make_support_banner(timeline, name=f'{name} banner'),
        )
        return card

    def _patch(self, selections):
        return self.client.patch(
            '/calculator-data',
            {'user_step_up_selection_data': selections},
            format='json',
        )

    def _slot(self, **overrides):
        """A valid uma-step-up selection row, id-less as the client sends them."""
        row = {
            'banner_step_up': self.uma_step_up.id,
            'uma': self.eligible_uma.id,
            'slot': 1,
        }
        row.update(overrides)
        return row

    # ── Constraints ──────────────────────────────────────────────────────

    def test_constraint_rejects_a_row_with_no_card(self):
        # An empty slot is an ABSENT row, not a row with both FKs null.
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                UserStepUpSelection.objects.create(
                    user=self.user, banner_step_up=self.uma_step_up, slot=1,
                )

    def test_constraint_rejects_a_row_with_both_cards(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                UserStepUpSelection.objects.create(
                    user=self.user, banner_step_up=self.uma_step_up, slot=1,
                    uma=self.eligible_uma, support=self.eligible_support,
                )

    def test_constraint_rejects_two_cards_in_one_slot(self):
        UserStepUpSelection.objects.create(
            user=self.user, banner_step_up=self.uma_step_up, slot=1,
            uma=self.eligible_uma,
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                UserStepUpSelection.objects.create(
                    user=self.user, banner_step_up=self.uma_step_up, slot=1,
                    uma=self.other_uma,
                )

    def test_the_same_slot_is_free_on_a_different_step_up(self):
        UserStepUpSelection.objects.create(
            user=self.user, banner_step_up=self.uma_step_up, slot=1,
            uma=self.eligible_uma,
        )
        UserStepUpSelection.objects.create(
            user=self.user, banner_step_up=self.support_step_up, slot=1,
            support=self.eligible_support,
        )  # must not raise

    def test_the_same_slot_is_free_for_a_different_user(self):
        other = make_user(username='other')
        UserStepUpSelection.objects.create(
            user=self.user, banner_step_up=self.uma_step_up, slot=1,
            uma=self.eligible_uma,
        )
        UserStepUpSelection.objects.create(
            user=other, banner_step_up=self.uma_step_up, slot=1,
            uma=self.eligible_uma,
        )  # must not raise

    def test_constraint_rejects_a_second_step_five_target(self):
        UserStepUpSelection.objects.create(
            user=self.user, banner_step_up=self.uma_step_up, slot=1,
            uma=self.eligible_uma, is_target=True,
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                UserStepUpSelection.objects.create(
                    user=self.user, banner_step_up=self.uma_step_up, slot=2,
                    uma=self.other_uma, is_target=True,
                )

    def test_many_non_targets_are_unconstrained(self):
        # The target constraint is a PARTIAL index -- is_target=False rows must
        # not collide with each other.
        for slot in range(1, 11):
            UserStepUpSelection.objects.create(
                user=self.user, banner_step_up=self.uma_step_up, slot=slot,
                uma=self.eligible_uma,
            )
        self.assertEqual(UserStepUpSelection.objects.filter(user=self.user).count(), 10)

    def test_clean_rejects_a_support_card_on_an_uma_step_up(self):
        row = UserStepUpSelection(
            user=self.user, banner_step_up=self.uma_step_up, slot=1,
            support=self.eligible_support,
        )
        with self.assertRaises(ValidationError) as ctx:
            row.full_clean()
        self.assertIn('support', ctx.exception.error_dict)

    def test_deleting_a_card_removes_the_selection(self):
        # CASCADE rather than SET_NULL: a nulled FK would leave a row that
        # exactly_one_selection_card forbids. The UI derives empty slots from
        # missing rows, so this still reads as "slot 4 is free".
        UserStepUpSelection.objects.create(
            user=self.user, banner_step_up=self.uma_step_up, slot=4,
            uma=self.eligible_uma,
        )
        self.eligible_uma.delete()
        self.assertEqual(UserStepUpSelection.objects.filter(user=self.user).count(), 0)

    # ── API: writing ─────────────────────────────────────────────────────

    def test_patch_creates_selections(self):
        res = self._patch([
            self._slot(slot=1),
            self._slot(slot=2, uma=self.eligible_uma.id, is_target=True),
        ])
        self.assertEqual(res.status_code, 200)
        rows = UserStepUpSelection.objects.filter(user=self.user).order_by('slot')
        self.assertEqual([r.slot for r in rows], [1, 2])
        self.assertEqual([r.is_target for r in rows], [False, True])

    def test_patch_replaces_wholesale_when_rows_carry_no_id(self):
        self._patch([self._slot(slot=1), self._slot(slot=2)])
        res = self._patch([self._slot(slot=7)])
        self.assertEqual(res.status_code, 200)
        rows = UserStepUpSelection.objects.filter(user=self.user)
        self.assertEqual([r.slot for r in rows], [7])

    def test_moving_a_card_between_slots_does_not_trip_the_unique_constraint(self):
        # The reason the client sends id-less rows. With ids this would be a
        # row-by-row update, transiently duplicating slot 2 and 500ing.
        self._patch([
            self._slot(slot=1, uma=self.eligible_uma.id),
            self._slot(slot=2, uma=self.other_uma.id),
        ])
        res = self._patch([
            self._slot(slot=1, uma=self.other_uma.id),
            self._slot(slot=2, uma=self.eligible_uma.id),
        ])
        self.assertEqual(res.status_code, 200)
        by_slot = {
            r.slot: r.uma_id
            for r in UserStepUpSelection.objects.filter(user=self.user)
        }
        self.assertEqual(by_slot, {1: self.other_uma.id, 2: self.eligible_uma.id})

    def test_empty_list_clears_every_selection(self):
        self._patch([self._slot(slot=1)])
        res = self._patch([])
        self.assertEqual(res.status_code, 200)
        self.assertEqual(UserStepUpSelection.objects.filter(user=self.user).count(), 0)

    def test_absent_key_leaves_selections_alone(self):
        self._patch([self._slot(slot=1)])
        res = self.client.patch(
            '/calculator-data', {'user_stats_data': {'current_carat': 500}},
            format='json',
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(UserStepUpSelection.objects.filter(user=self.user).count(), 1)

    # ── API: validation ──────────────────────────────────────────────────

    def test_rejects_a_support_card_on_an_uma_step_up(self):
        res = self._patch([{
            'banner_step_up': self.uma_step_up.id,
            'support': self.eligible_support.id, 'slot': 1,
        }])
        self.assertEqual(res.status_code, 400)

    def test_rejects_an_uma_on_a_support_step_up(self):
        res = self._patch([{
            'banner_step_up': self.support_step_up.id,
            'uma': self.eligible_uma.id, 'slot': 1,
        }])
        self.assertEqual(res.status_code, 400)

    def test_rejects_a_row_naming_no_card(self):
        res = self._patch([{'banner_step_up': self.uma_step_up.id, 'slot': 1}])
        self.assertEqual(res.status_code, 400)

    def test_rejects_a_slot_outside_one_to_ten(self):
        for bad_slot in (0, 11):
            res = self._patch([self._slot(slot=bad_slot)])
            self.assertEqual(res.status_code, 400, f'slot {bad_slot} should 400')

    def test_rejects_a_card_released_after_the_cutoff(self):
        res = self._patch([self._slot(uma=self.late_uma.id)])
        self.assertEqual(res.status_code, 400)
        self.assertEqual(UserStepUpSelection.objects.filter(user=self.user).count(), 0)

    def test_a_null_cutoff_admits_everything(self):
        self.event.jp_cutoff_date = None
        self.event.save()
        res = self._patch([self._slot(uma=self.late_uma.id)])
        self.assertEqual(res.status_code, 200)

    def test_a_stored_pick_survives_the_cutoff_being_narrowed(self):
        """The lockout guard. Cutoffs are reference data that editors correct as
        real JP dates surface; re-checking untouched picks would 400 the whole
        PATCH -- taking the user's stats and banners with it -- over a change
        they did not make and cannot see.
        """
        self.event.jp_cutoff_date = None
        self.event.save()
        self.assertEqual(self._patch([self._slot(uma=self.late_uma.id)]).status_code, 200)

        # An editor now narrows the cutoff, making that stored pick ineligible.
        self.event.jp_cutoff_date = datetime.date(2026, 1, 30)
        self.event.save()

        res = self._patch([self._slot(uma=self.late_uma.id)])
        self.assertEqual(res.status_code, 200)
        self.assertEqual(UserStepUpSelection.objects.filter(user=self.user).count(), 1)

    def test_grandfathering_does_not_admit_a_new_ineligible_pick(self):
        # Only what is already stored is forgiven; a fresh late pick is refused.
        self._patch([self._slot(slot=1, uma=self.eligible_uma.id)])
        res = self._patch([
            self._slot(slot=1, uma=self.eligible_uma.id),
            self._slot(slot=2, uma=self.late_uma.id),
        ])
        self.assertEqual(res.status_code, 400)

    def test_a_rejected_row_rolls_the_whole_patch_back(self):
        self._patch([self._slot(slot=1)])
        res = self.client.patch(
            '/calculator-data',
            {
                'user_stats_data': {'current_carat': 9999},
                'user_step_up_selection_data': [self._slot(uma=self.late_uma.id)],
            },
            format='json',
        )
        self.assertEqual(res.status_code, 400)
        self.user.refresh_from_db()
        self.assertNotEqual(self.user.current_carat, 9999)
        # And the pre-existing selection is still there.
        self.assertEqual(UserStepUpSelection.objects.filter(user=self.user).count(), 1)

    # ── API: reading ─────────────────────────────────────────────────────

    def test_calculator_data_serves_the_users_selections(self):
        self._patch([self._slot(slot=3, is_target=True)])
        res = self.client.get('/calculator-data')
        self.assertEqual(res.status_code, 200)
        rows = res.data['user_step_up_selection_data']
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['banner_step_up'], self.uma_step_up.id)
        self.assertEqual(rows[0]['uma'], self.eligible_uma.id)
        self.assertEqual(rows[0]['slot'], 3)
        self.assertTrue(rows[0]['is_target'])

    def test_a_guest_gets_an_empty_selection_list(self):
        UserStepUpSelection.objects.create(
            user=self.user, banner_step_up=self.uma_step_up, slot=1,
            uma=self.eligible_uma,
        )
        res = APIClient().get('/calculator-data')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data['user_step_up_selection_data'], [])

    def test_selections_are_scoped_to_their_owner(self):
        other = make_user(username='other')
        UserStepUpSelection.objects.create(
            user=other, banner_step_up=self.uma_step_up, slot=1,
            uma=self.eligible_uma,
        )
        res = self.client.get('/calculator-data')
        self.assertEqual(res.data['user_step_up_selection_data'], [])

    def test_whole_body_round_trip(self):
        """Every collection in one PATCH, as the client actually saves.

        A repro that omits a collection returns a false 200 and hides a failing
        row, so this sends all of them.
        """
        uma_banner = make_uma_banner(name='Planner Banner')
        res = self.client.patch(
            '/calculator-data',
            {
                'user_stats_data': {'current_paid_carat': 5000},
                'user_planned_banner_data': [
                    {'banner_uma': uma_banner.id, 'number_of_pulls': 30,
                     'reserved_copies': 0},
                ],
                'user_planned_purchase_data': [],
                'user_step_up_selection_data': [
                    self._slot(slot=1),
                    self._slot(slot=2, is_target=True),
                ],
            },
            format='json',
        )
        self.assertEqual(res.status_code, 200, res.data)

        self.user.refresh_from_db()
        self.assertEqual(self.user.current_paid_carat, 5000)
        self.assertEqual(UserPlannedBanner.objects.filter(user=self.user).count(), 1)
        self.assertEqual(UserStepUpSelection.objects.filter(user=self.user).count(), 2)

        # And it reads back through the same endpoint.
        body = self.client.get('/calculator-data').data
        self.assertEqual(len(body['user_step_up_selection_data']), 2)
        self.assertEqual(len(body['user_planned_banner_data']), 1)


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


class ScenarioDateTests(TestCase):
    """A scenario borrows its launch banner's START, and has no end at all."""

    def test_start_comes_from_the_launch_banner_and_there_is_no_end(self):
        now = timezone.now()
        banner = make_timeline(
            name='Launch banner', global_start_date=now,
            global_end_date=now + datetime.timedelta(days=14),
        )
        scenario = make_scenario(banner_timeline=banner)

        emap = build_effective_date_maps()[BannerTimeline]
        resolved = build_scenario_date_map([scenario], emap)[scenario.id]

        self.assertEqual(resolved['start_date'], banner.global_start_date)
        # The banner ends; the scenario does not. Borrowing the banner's end
        # would invent an expiry the scenario has never had.
        self.assertIsNone(resolved['end_date'])
        self.assertFalse(resolved['is_predicted'])

    def test_prediction_and_offset_propagate_from_the_banner(self):
        now = timezone.now()
        # Anchor: a confirmed JP+global pair the predictor can measure from.
        make_timeline(
            name='Anchor',
            jp_start_date=timezone.make_aware(datetime.datetime(2022, 1, 1)),
            jp_end_date=timezone.make_aware(datetime.datetime(2022, 1, 14)),
            global_start_date=now, global_end_date=now + datetime.timedelta(days=14),
        )
        predicted = make_timeline(
            name='Predicted launch banner',
            jp_start_date=timezone.make_aware(datetime.datetime(2022, 6, 1)),
            jp_end_date=timezone.make_aware(datetime.datetime(2022, 6, 14)),
            global_start_date=None, global_end_date=None,
        )
        scenario = make_scenario(banner_timeline=predicted)

        emap = build_effective_date_maps()[BannerTimeline]
        resolved = build_scenario_date_map([scenario], emap)[scenario.id]

        self.assertTrue(resolved['is_predicted'])
        self.assertEqual(resolved['start_date'], emap[predicted.id]['start_date'])
        self.assertEqual(
            resolved['applied_offset_days'], emap[predicted.id]['applied_offset_days']
        )
        self.assertIsNone(resolved['end_date'])

    def test_unlinked_scenario_resolves_to_a_null_start(self):
        scenario = make_scenario(banner_timeline=None)
        emap = build_effective_date_maps()[BannerTimeline]
        resolved = build_scenario_date_map([scenario], emap)[scenario.id]

        self.assertIsNone(resolved['start_date'])
        self.assertIsNone(resolved['end_date'])
        self.assertFalse(resolved['is_predicted'])


class ScenarioApiTests(TestCase):
    """/calculator-data serves scenarios, start-only and image-optional."""

    def setUp(self):
        self.client = APIClient()

    def test_scenario_payload_has_a_start_and_no_end_date_key_at_all(self):
        now = timezone.now()
        banner = make_timeline(
            name='Launch banner', global_start_date=now,
            global_end_date=now + datetime.timedelta(days=14),
        )
        scenario = make_scenario(name='Hashire! Mecha Umamusume',
                                 banner_timeline=banner)

        response = self.client.get('/calculator-data')
        row = next(
            r for r in response.data['scenario_data'] if r['id'] == scenario.id
        )

        self.assertEqual(row['name'], 'Hashire! Mecha Umamusume')
        self.assertIsNotNone(row['start_date'])
        # Absent, not null. A structurally-always-null end_date would invite a
        # consumer to render a range that does not exist -- see
        # StartInstantDateMixin.
        self.assertNotIn('end_date', row)

    def test_banner_timeline_is_emitted_as_a_bare_id_for_band_pinning(self):
        now = timezone.now()
        banner = make_timeline(name='Launch banner', global_start_date=now)
        scenario = make_scenario(banner_timeline=banner)

        response = self.client.get('/calculator-data')
        row = next(
            r for r in response.data['scenario_data'] if r['id'] == scenario.id
        )

        # The frontend pins the scenario's band directly above this banner's
        # planner row, so it needs the id rather than a nested banner.
        self.assertEqual(row['banner_timeline'], banner.id)

    def test_scenario_without_an_image_still_serves(self):
        # The normal state while a scenario is being entered -- art lands later.
        now = timezone.now()
        banner = make_timeline(name='Launch banner', global_start_date=now)
        scenario = make_scenario(banner_timeline=banner, image=None)

        response = self.client.get('/calculator-data')
        row = next(
            r for r in response.data['scenario_data'] if r['id'] == scenario.id
        )

        self.assertIsNone(row['image'])
        self.assertIsNotNone(row['start_date'])

    def test_unlinked_scenario_serves_with_a_null_start(self):
        scenario = make_scenario(banner_timeline=None)

        response = self.client.get('/calculator-data')
        row = next(
            r for r in response.data['scenario_data'] if r['id'] == scenario.id
        )

        self.assertIsNone(row['start_date'])

    def test_guests_can_read_scenarios(self):
        now = timezone.now()
        banner = make_timeline(name='Launch banner', global_start_date=now)
        make_scenario(banner_timeline=banner)

        response = self.client.get('/calculator-data')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['scenario_data']), 1)


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
        self.assertIsNone(resolved['main_start_date'])
        self.assertIsNone(resolved['end_date'])
        self.assertFalse(resolved['is_predicted'])

    def test_main_start_date_is_part_2_for_an_anniversary(self):
        """Part 1 is the run-up; the anniversary itself is Part 2."""
        now = timezone.now()
        part1 = make_timeline(
            name='Run-up', global_start_date=now,
            global_end_date=now + datetime.timedelta(days=10),
        )
        part2 = make_timeline(
            name='The anniversary',
            global_start_date=now + datetime.timedelta(days=10),
            global_end_date=now + datetime.timedelta(days=30),
        )
        event = make_anniversary_event(parts=[part1, part2])

        emap = build_effective_date_maps()[BannerTimeline]
        resolved = build_anniversary_event_date_map([event], emap)[event.id]

        # The campaign still OPENS at Part 1 -- packs and the run-up rewards are
        # real -- but the event it is named after starts at Part 2.
        self.assertEqual(resolved['start_date'], part1.global_start_date)
        self.assertEqual(resolved['main_start_date'], part2.global_start_date)
        self.assertEqual(resolved['end_date'], part2.global_end_date)

    def test_main_start_date_picks_part_2_by_number_not_by_date(self):
        """The 5th Anniversary's Part 4 opens before its Part 3.

        Concurrent banners, which is how the source sheet records them. Ordering
        the parts by date would therefore not put Part 2 second, so the selection
        has to key on part_number.
        """
        now = timezone.now()
        timelines = [
            make_timeline(
                name=f'Part {number}',
                global_start_date=now + datetime.timedelta(days=offset),
                global_end_date=now + datetime.timedelta(days=offset + 10),
            )
            for number, offset in [(1, 0), (2, 10), (3, 30), (4, 20)]
        ]
        event = make_anniversary_event(parts=[])
        for number, timeline in enumerate(timelines, start=1):
            AnniversaryEventBanner.objects.create(
                anniversary_event=event, banner_timeline=timeline,
                part_number=number,
            )

        emap = build_effective_date_maps()[BannerTimeline]
        resolved = build_anniversary_event_date_map([event], emap)[event.id]

        self.assertEqual(resolved['main_start_date'], timelines[1].global_start_date)

    def test_main_start_date_falls_back_when_there_is_no_part_2(self):
        """The 0.5th Anniversary's shape: its Part 2 banner has no timeline row.

        Only the Part 3 link resolves, and that one part is the whole campaign as
        far as the app can see -- so it supplies both dates rather than leaving
        the campaign unplaceable.
        """
        now = timezone.now()
        part3 = make_timeline(
            name='Only surviving part', global_start_date=now,
            global_end_date=now + datetime.timedelta(days=11),
        )
        event = make_anniversary_event(parts=[])
        AnniversaryEventBanner.objects.create(
            anniversary_event=event, banner_timeline=part3, part_number=3,
        )

        emap = build_effective_date_maps()[BannerTimeline]
        resolved = build_anniversary_event_date_map([event], emap)[event.id]

        self.assertEqual(resolved['main_start_date'], part3.global_start_date)
        self.assertEqual(resolved['start_date'], part3.global_start_date)

    def test_main_start_date_falls_back_when_only_a_part_1_is_linked(self):
        now = timezone.now()
        part1 = make_timeline(
            name='Run-up only', global_start_date=now,
            global_end_date=now + datetime.timedelta(days=10),
        )
        event = make_anniversary_event(parts=[part1])

        emap = build_effective_date_maps()[BannerTimeline]
        resolved = build_anniversary_event_date_map([event], emap)[event.id]

        self.assertEqual(resolved['main_start_date'], part1.global_start_date)

    def test_a_new_year_campaign_keeps_its_opening_as_its_main_start(self):
        """Only anniversaries run a Part 1 run-up.

        A New Year campaign's Part 1 IS the New Year banner (New Years 2025 =
        Katsuragi Ace + Mr. C.B.), so moving it to Part 2 would place it on the
        follow-up banner instead of the event.
        """
        now = timezone.now()
        part1 = make_timeline(
            name='New Year banner', global_start_date=now,
            global_end_date=now + datetime.timedelta(days=14),
        )
        part2 = make_timeline(
            name='Follow-up',
            global_start_date=now + datetime.timedelta(days=9),
            global_end_date=now + datetime.timedelta(days=20),
        )
        event = make_anniversary_event(
            name='New Years 2025', event_type='new_year', parts=[part1, part2],
        )

        emap = build_effective_date_maps()[BannerTimeline]
        resolved = build_anniversary_event_date_map([event], emap)[event.id]

        self.assertEqual(resolved['main_start_date'], part1.global_start_date)
        self.assertEqual(resolved['start_date'], part1.global_start_date)


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

    def test_campaign_emits_a_main_start_date_alongside_its_window(self):
        """The wire carries the event's own start, not just the campaign's."""
        part2 = make_timeline(
            name='3rd Anniv Part 2',
            global_start_date=self.timeline.global_end_date,
            global_end_date=self.timeline.global_end_date + datetime.timedelta(days=20),
        )
        AnniversaryEventBanner.objects.create(
            anniversary_event=self.event, banner_timeline=part2, part_number=2,
        )

        event = self.client.get('/calculator-data').json()['anniversary_event_data'][0]

        self.assertEqual(event['start_date'], _iso(self.timeline.global_start_date))
        self.assertEqual(event['main_start_date'], _iso(part2.global_start_date))
        self.assertEqual(event['end_date'], _iso(part2.global_end_date))

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

    def test_banner_carries_its_step_ups_for_the_timeline_chip(self):
        BannerStepUp.objects.create(
            banner_timeline=self.timeline, anniversary_event=self.event,
            name='3rd Anniversary Star-3 Select Step-Up',
            card_type='uma', banner_count=1,
        )
        BannerStepUp.objects.create(
            banner_timeline=self.timeline, anniversary_event=self.event,
            name='3rd Anniversary SSR Select Step-Up',
            card_type='support', banner_count=2,
        )
        res = self.client.get('/calculator-data')
        timeline = next(
            t for t in res.data['banner_timeline_data'] if t['id'] == self.timeline.id
        )

        by_type = {s['card_type']: s for s in timeline['banner_step_ups']}
        self.assertEqual(by_type['uma']['banner_count'], 1)
        self.assertEqual(by_type['support']['banner_count'], 2)
        # A summary, not the full record: nesting banner_timeline here would send
        # each timeline back inside itself.
        self.assertNotIn('banner_timeline', by_type['uma'])

    def test_banner_with_no_step_ups_reports_an_empty_list(self):
        loose = make_timeline(name='Ordinary banner')
        res = self.client.get('/calculator-data')
        timeline = next(
            t for t in res.data['banner_timeline_data'] if t['id'] == loose.id
        )
        self.assertEqual(timeline['banner_step_ups'], [])

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

    def test_csv_survives_a_planned_banner_with_no_confirmed_dates(self):
        """Regression: Download CSV used to 500 on any predicted banner.

        _banner_popularity() reports the CONFIRMED global dates, which are null
        until a banner is announced, so this fired as soon as one person planned
        anything in the future — the normal case, not an edge case.
        """
        timeline = make_timeline()
        timeline.global_start_date = None
        timeline.global_end_date = None
        timeline.save()
        UserPlannedBanner.objects.create(
            user=make_user('planner'),
            banner_uma=make_uma_banner(timeline, name='Unannounced'),
            number_of_pulls=10,
        )

        self._staff_client()
        res = self.client.get(self.url, {'format': 'csv'})
        self.assertEqual(res.status_code, 200)
        self.assertIn('Unannounced', res.content.decode())

    def _seed_traffic(self):
        DailyVisit.objects.create(
            date=timezone.localdate(), page_views=7, unique_visitors=3)
        MonthlyVisit.objects.create(
            month=timezone.localdate().replace(day=1),
            page_views=7, unique_visitors=2)

    def test_dashboard_includes_traffic_sections(self):
        self._seed_traffic()
        self._staff_client()
        res = self.client.get(self.url)
        self.assertContains(res, 'Site traffic')
        self.assertContains(res, 'by month')

    def test_csv_includes_traffic_sections(self):
        self._seed_traffic()
        self._staff_client()
        body = self.client.get(self.url, {'format': 'csv'}).content.decode()
        self.assertIn('Site Traffic', body)
        # The monthly column is a true monthly-active count and is therefore
        # SMALLER than the sum of the daily uniques. The qualifier in the header
        # is what stops a reader treating that gap as a bug.
        self.assertIn('Unique visitors (counted once per month)', body)


# ── Visit Tracking Tests ──────────────────────────────────────────────────────

class VisitRecordingTests(TestCase):
    """record_visit()'s counting, deduplication and bot filtering.

    Every test pins the calendar date rather than using the real one: the
    monthly behaviour is the interesting part, and a suite that happened to run
    on the 31st would otherwise straddle a month boundary and fail at random.
    """

    # Mid-month, so ±1 day never crosses a boundary by accident.
    DAY = datetime.date(2026, 3, 15)

    def setUp(self):
        self.factory = RequestFactory()

    def _hit(self, ip='203.0.113.5', agent='Mozilla/5.0', forwarded=None, day=None):
        """One beacon request on `day`. `forwarded` sets X-Forwarded-For."""
        headers = {'REMOTE_ADDR': ip, 'HTTP_USER_AGENT': agent}
        if forwarded is not None:
            headers['HTTP_X_FORWARDED_FOR'] = forwarded
        request = self.factory.post('/visit', **headers)
        with patch('calculatorapi.visits.timezone.localdate',
                   return_value=day or self.DAY):
            return record_visit(request)

    def _daily(self, day=None):
        row = DailyVisit.objects.get(date=day or self.DAY)
        return row.page_views, row.unique_visitors

    def _monthly(self, month=None):
        row = MonthlyVisit.objects.get(month=month or self.DAY.replace(day=1))
        return row.page_views, row.unique_visitors

    def test_first_visit_creates_both_counter_rows(self):
        self.assertTrue(self._hit())
        self.assertEqual(self._daily(), (1, 1))
        self.assertEqual(self._monthly(), (1, 1))

    def test_repeat_visitor_adds_a_view_but_not_a_visitor(self):
        self._hit()
        self._hit()
        self._hit()
        self.assertEqual(self._daily(), (3, 1))
        self.assertEqual(self._monthly(), (3, 1))
        # One day, one hash: the unique constraint is doing the deduplication.
        self.assertEqual(VisitorHash.objects.count(), 1)

    def test_different_ip_counts_as_a_new_visitor(self):
        self._hit(ip='203.0.113.5')
        self._hit(ip='198.51.100.9')
        self.assertEqual(self._daily(), (2, 2))
        self.assertEqual(self._monthly(), (2, 2))

    def test_different_user_agent_counts_as_a_new_visitor(self):
        self._hit(agent='Mozilla/5.0')
        self._hit(agent='Mozilla/5.0 (different device)')
        self.assertEqual(self._daily(), (2, 2))

    def test_forwarded_for_wins_over_remote_addr(self):
        """Without this the load balancer's IP is all we ever see in production.

        Both hits arrive from the same REMOTE_ADDR — as they would behind App
        Platform's proxy — but carry different client addresses. If X-Forwarded-For
        were ignored they would collapse into one visitor.
        """
        self._hit(ip='10.0.0.1', forwarded='203.0.113.5')
        self._hit(ip='10.0.0.1', forwarded='198.51.100.9')
        self.assertEqual(self._daily(), (2, 2))

    def test_forwarded_for_uses_the_first_entry(self):
        """"client, proxy1, proxy2" — the client is the leftmost entry."""
        self._hit(ip='10.0.0.1', forwarded='203.0.113.5, 10.0.0.2, 10.0.0.3')
        self._hit(ip='10.0.0.1', forwarded='203.0.113.5, 10.9.9.9')
        self.assertEqual(self._daily(), (2, 1))

    def test_bots_are_not_counted_at_all(self):
        for agent in ['Googlebot/2.1', 'python-urllib/3.11', 'curl/8.0',
                      'HeadlessChrome/120', 'Some Crawler']:
            self.assertFalse(self._hit(agent=agent), agent)
        self.assertFalse(DailyVisit.objects.exists())
        self.assertFalse(MonthlyVisit.objects.exists())

    def test_no_identifying_data_is_stored(self):
        """The privacy contract, asserted rather than assumed."""
        self._hit(ip='203.0.113.5', agent='Mozilla/5.0 (SecretDevice)')
        stored = VisitorHash.objects.get()
        self.assertNotIn('203.0.113.5', stored.visitor_hash)
        self.assertNotIn('SecretDevice', stored.visitor_hash)
        self.assertEqual(len(stored.visitor_hash), 32)

    # ── The monthly-unique semantics ─────────────────────────────────────────

    def test_returning_on_another_day_counts_once_for_the_month(self):
        """The whole point of a month-scoped hash: a real monthly-active count.

        Two days, one person. Each day sees a unique visitor; the month sees one.
        """
        self._hit(day=self.DAY)
        self._hit(day=self.DAY + datetime.timedelta(days=1))

        self.assertEqual(self._daily(self.DAY), (1, 1))
        self.assertEqual(self._daily(self.DAY + datetime.timedelta(days=1)), (1, 1))
        # 2 page views, but ONE visitor — not the sum of the daily uniques.
        self.assertEqual(self._monthly(), (2, 1))

    def test_the_same_visitor_is_new_again_next_month(self):
        """The link breaks at the boundary, which is the privacy property."""
        self._hit(day=datetime.date(2026, 3, 31))
        self._hit(day=datetime.date(2026, 4, 1))

        self.assertEqual(self._monthly(datetime.date(2026, 3, 1)), (1, 1))
        self.assertEqual(self._monthly(datetime.date(2026, 4, 1)), (1, 1))

    def test_hash_is_stable_within_a_month_and_changes_across_months(self):
        self._hit(day=datetime.date(2026, 3, 2))
        self._hit(day=datetime.date(2026, 3, 28))
        march = set(VisitorHash.objects.values_list('visitor_hash', flat=True))
        self.assertEqual(len(march), 1, 'same visitor, same month, same hash')

        self._hit(day=datetime.date(2026, 4, 2))
        everything = set(VisitorHash.objects.values_list('visitor_hash', flat=True))
        self.assertEqual(len(everything), 2, 'new month, unrelated hash')

    def test_two_visitors_across_overlapping_days(self):
        """A mixed month: A on two days, B on one. Three views, two people."""
        day_two = self.DAY + datetime.timedelta(days=1)
        self._hit(ip='203.0.113.5', day=self.DAY)
        self._hit(ip='198.51.100.9', day=self.DAY)
        self._hit(ip='203.0.113.5', day=day_two)

        self.assertEqual(self._daily(self.DAY), (2, 2))
        self.assertEqual(self._daily(day_two), (1, 1))
        # Sum of daily uniques would say 3; the honest answer is 2.
        self.assertEqual(self._monthly(), (3, 2))


class VisitReportTests(TestCase):
    """build_visit_report()'s windowing and monthly figures."""

    def test_empty_db_reports_no_traffic(self):
        report = build_visit_report()
        self.assertEqual(report['daily'], [])
        self.assertEqual(report['monthly'], [])

    def test_daily_window_excludes_older_rows(self):
        today = timezone.localdate()
        DailyVisit.objects.create(date=today, page_views=5, unique_visitors=2)
        DailyVisit.objects.create(
            date=today - datetime.timedelta(days=40), page_views=99, unique_visitors=50)

        daily = build_visit_report(days=30)['daily']
        self.assertEqual([row['date'] for row in daily], [today])

    def test_monthly_rows_come_from_the_monthly_counters(self):
        MonthlyVisit.objects.create(
            month=datetime.date(2026, 3, 1), page_views=16, unique_visitors=5)
        MonthlyVisit.objects.create(
            month=datetime.date(2026, 4, 1), page_views=1, unique_visitors=1)

        by_month = {
            row['month'].strftime('%Y-%m'): row
            for row in build_visit_report()['monthly']
        }
        self.assertEqual(by_month['2026-03']['page_views'], 16)
        self.assertEqual(by_month['2026-03']['unique_visitors'], 5)
        self.assertEqual(by_month['2026-04']['page_views'], 1)

    def test_monthly_window_is_limited(self):
        for month in range(1, 13):
            MonthlyVisit.objects.create(
                month=datetime.date(2025, month, 1), page_views=1, unique_visitors=1)

        self.assertEqual(len(build_visit_report(months=6)['monthly']), 6)


class VisitBeaconEndpointTests(TestCase):
    """POST /visit — the public write-only beacon."""

    def setUp(self):
        self.url = reverse('site-visit')
        # DRF throttles through the cache, which is shared across tests in a
        # run; without this a neighbouring test's hits could throttle ours.
        cache.clear()

    def test_anonymous_post_is_accepted_and_counted(self):
        res = self.client.post(self.url, HTTP_USER_AGENT='Mozilla/5.0')
        self.assertEqual(res.status_code, 204)
        self.assertEqual(res.content, b'')
        self.assertEqual(DailyVisit.objects.get().page_views, 1)

    def test_get_is_not_allowed(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_bot_gets_the_same_204_but_is_not_counted(self):
        """The response must not reveal that the bot filter fired."""
        res = self.client.post(self.url, HTTP_USER_AGENT='Googlebot/2.1')
        self.assertEqual(res.status_code, 204)
        self.assertFalse(DailyVisit.objects.exists())

    def test_repeated_hits_are_eventually_throttled(self):
        # 60/hour, so the 61st is refused. Guards the one thing standing
        # between an open counter and anyone who wants to run it up.
        for _ in range(60):
            self.client.post(self.url, HTTP_USER_AGENT='Mozilla/5.0')
        res = self.client.post(self.url, HTTP_USER_AGENT='Mozilla/5.0')
        self.assertEqual(res.status_code, 429)


class PruneVisitorHashesCommandTests(TestCase):
    """The housekeeping command must never touch the permanent counters."""

    def setUp(self):
        self.today = timezone.localdate()
        self.old_date = self.today - datetime.timedelta(days=120)
        DailyVisit.objects.create(
            date=self.old_date, page_views=50, unique_visitors=20)
        MonthlyVisit.objects.create(
            month=self.old_date.replace(day=1), page_views=50, unique_visitors=12)
        VisitorHash.objects.create(date=self.old_date, visitor_hash='a' * 32)
        VisitorHash.objects.create(date=self.today, visitor_hash='b' * 32)

    def test_prunes_old_hashes_but_keeps_the_counters(self):
        call_command('prune_visitor_hashes', stdout=StringIO())
        self.assertEqual(
            list(VisitorHash.objects.values_list('date', flat=True)),
            [self.today],
        )
        # The whole point: the historical numbers survive their scratch data.
        self.assertEqual(DailyVisit.objects.get(date=self.old_date).page_views, 50)
        self.assertEqual(
            MonthlyVisit.objects.get(month=self.old_date.replace(day=1)).unique_visitors,
            12,
        )

    def test_default_retention_cannot_break_a_month_in_progress(self):
        """Guards the invariant the docstring warns about.

        The monthly check asks "any row for this hash since the 1st?", so the
        window has to outlast a month by a clear margin — otherwise a visitor
        whose earlier rows were pruned mid-month gets counted twice.
        """
        self.assertGreaterEqual(VISITOR_HASH_RETENTION_DAYS, 45)

    def test_dry_run_changes_nothing(self):
        call_command('prune_visitor_hashes', '--dry-run', stdout=StringIO())
        self.assertEqual(VisitorHash.objects.count(), 2)

    def test_exits_cleanly_when_there_is_nothing_to_prune(self):
        out = StringIO()
        call_command('prune_visitor_hashes', '--days', '3650', stdout=out)
        self.assertIn('Nothing to prune', out.getvalue())
        self.assertEqual(VisitorHash.objects.count(), 2)


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
        'admin:calculatorapi_bannerstepup',
        'admin:calculatorapi_uma',
        'admin:calculatorapi_supportcard',
        'admin:calculatorapi_gameevent',
        'admin:calculatorapi_championsmeeting',
        'admin:calculatorapi_leagueofheroes',
        'admin:calculatorapi_clubrank',
        'admin:calculatorapi_anniversaryevent',
        'admin:calculatorapi_scenario',
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


# ── Changelog Sync Command Tests ──────────────────────────────────────────────

class ShippedChangelogFileTests(TestCase):
    """The committed changelog.yaml must always validate.

    This is the guard that keeps a broken file off production. `sync_changelog`
    runs on the path that starts the web service and deliberately exits 0 on a
    file it cannot read, so without this test a mistake would go unnoticed until
    someone spotted the changelog page missing an entry.
    """

    def test_shipped_file_validates(self):
        entries = load_changelog_entries()
        self.assertTrue(entries, 'changelog.yaml should hold at least one entry')

    def test_shipped_entries_are_complete(self):
        for entry in load_changelog_entries():
            self.assertTrue(entry['key'])
            self.assertTrue(entry['title'])
            self.assertIsInstance(entry['date'], datetime.date)


class SyncChangelogCommandTests(TestCase):
    """`sync_changelog` writes the file's entries and nothing else."""

    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.directory)
        self.path = os.path.join(self.directory, 'changelog.yaml')

    def _write(self, text):
        with open(self.path, 'w', encoding='utf-8') as handle:
            handle.write(text)

    def _run(self, **opts):
        out = StringIO()
        call_command('sync_changelog', file=self.path, stdout=out, **opts)
        return out.getvalue()

    ONE_ENTRY = (
        '- key: open-beta\n'
        '  date: 2026-09-01\n'
        '  title: "Open beta"\n'
        '  version: "v1.0"\n'
        '  changes:\n'
        '    - added: "First line."\n'
        '    - fixed: "Second line."\n'
    )

    def test_creates_entry_with_changes_in_file_order(self):
        self._write(self.ONE_ENTRY)
        self._run()
        entry = ChangelogEntry.objects.get(key='open-beta')
        self.assertEqual(entry.title, 'Open beta')
        self.assertEqual(entry.version, 'v1.0')
        self.assertEqual(entry.date, datetime.date(2026, 9, 1))
        # order is assigned from position, which is what the API sorts on.
        self.assertEqual(
            [(c.category, c.text, c.order) for c in entry.changes.all()],
            [('added', 'First line.', 0), ('fixed', 'Second line.', 1)],
        )

    def test_second_run_is_a_no_op(self):
        self._write(self.ONE_ENTRY)
        self._run()
        output = self._run()
        # Idempotence matters: this runs on every container start, not just on
        # a deploy that changed the file.
        self.assertIn('0 created, 0 updated, 1 unchanged', output)
        self.assertEqual(ChangelogEntry.objects.count(), 1)
        self.assertEqual(ChangelogChange.objects.count(), 2)

    def test_edited_entry_is_rewritten_and_stale_lines_removed(self):
        self._write(self.ONE_ENTRY)
        self._run()
        self._write(
            '- key: open-beta\n'
            '  date: 2026-09-02\n'
            '  title: "Open beta, renamed"\n'
            '  changes:\n'
            '    - changed: "Only line now."\n'
        )
        self._run()
        entry = ChangelogEntry.objects.get(key='open-beta')
        self.assertEqual(entry.title, 'Open beta, renamed')
        self.assertEqual(entry.date, datetime.date(2026, 9, 2))
        self.assertEqual(entry.version, '')
        # Change lines are replaced wholesale, so a deleted line really goes.
        self.assertEqual(
            [(c.category, c.text) for c in entry.changes.all()],
            [('changed', 'Only line now.')],
        )

    def test_hand_written_entries_are_untouched(self):
        # An entry authored in the admin has no key and must survive a sync
        # unchanged — the file is not authoritative over the whole table.
        manual = ChangelogEntry.objects.create(
            title='Written in the admin', date=datetime.date(2026, 8, 1),
        )
        ChangelogChange.objects.create(
            entry=manual, category=ChangelogChange.ADDED, text='Kept.',
        )
        self._write(self.ONE_ENTRY)
        self._run()
        manual.refresh_from_db()
        self.assertEqual(manual.title, 'Written in the admin')
        self.assertEqual(manual.changes.count(), 1)
        self.assertEqual(ChangelogEntry.objects.count(), 2)

    def test_two_hand_written_entries_can_coexist(self):
        # `key` is unique, so an unkeyed entry must store NULL rather than "" —
        # otherwise the second one written in the admin is an IntegrityError.
        ChangelogEntry.objects.create(title='One', date=datetime.date(2026, 8, 1))
        ChangelogEntry.objects.create(title='Two', date=datetime.date(2026, 8, 2))
        self.assertEqual(ChangelogEntry.objects.filter(key__isnull=True).count(), 2)

    def test_dry_run_writes_nothing(self):
        self._write(self.ONE_ENTRY)
        output = self._run(dry_run=True)
        self.assertIn('would create open-beta', output)
        self.assertEqual(ChangelogEntry.objects.count(), 0)

    def test_invalid_file_writes_nothing_and_exits_zero(self):
        # The deploy path. A bad patch note must not stop the API booting, so
        # the command reports and returns rather than raising.
        self._write('- key: "not a slug!"\n  date: nonsense\n')
        output = self._run()
        self.assertIn('did not validate', output)
        self.assertEqual(ChangelogEntry.objects.count(), 0)

    def test_strict_exits_non_zero_on_an_invalid_file(self):
        # The local/CI path, where a silent pass is the failure mode.
        self._write('- key: dupe\n  title: A\n  date: 2026-01-01\n'
                    '- key: dupe\n  title: B\n  date: 2026-01-02\n')
        with self.assertRaises(SystemExit):
            self._run(strict=True)
        self.assertEqual(ChangelogEntry.objects.count(), 0)

    def test_unknown_category_is_rejected(self):
        self._write('- key: k\n  title: T\n  date: 2026-01-01\n'
                    '  changes:\n    - invented: "nope"\n')
        output = self._run()
        self.assertIn("unknown category 'invented'", output)
        self.assertEqual(ChangelogEntry.objects.count(), 0)


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

    def test_patreon_emails_survive_an_ordinary_purge(self):
        """Supporters are not accounts. A routine run must not wipe the field
        the admin uses to tell them apart — that needs asking for."""
        supporter = PatreonSupporter.objects.create(
            display_name='Rhondal', email='rtibplays@gmail.com')
        output = self._run()
        supporter.refresh_from_db()
        self.assertEqual(supporter.email, 'rtibplays@gmail.com')
        self.assertIn('--include-patreon', output)

    def test_include_patreon_blanks_supporter_emails(self):
        supporter = PatreonSupporter.objects.create(
            display_name='Rhondal', email='rtibplays@gmail.com',
            is_public=True, patron_since=datetime.date(2025, 1, 1))
        self._run(include_patreon=True)
        supporter.refresh_from_db()
        self.assertEqual(supporter.email, '')
        # Blanked, not deleted — the thank-you list and its consent survive.
        self.assertTrue(supporter.is_public)
        self.assertEqual(supporter.patron_since, datetime.date(2025, 1, 1))

    def test_include_patreon_dry_run_changes_nothing(self):
        supporter = PatreonSupporter.objects.create(
            display_name='Rhondal', email='rtibplays@gmail.com')
        self._run(dry_run=True, include_patreon=True)
        supporter.refresh_from_db()
        self.assertEqual(supporter.email, 'rtibplays@gmail.com')

    def test_include_patreon_runs_with_no_accounts_left_to_purge(self):
        """The account purge is a one-shot; the supporter lever must still work
        long after every account has already been scrubbed."""
        CustomUser.objects.filter(is_staff=False).delete()
        supporter = PatreonSupporter.objects.create(
            display_name='Rhondal', email='rtibplays@gmail.com')
        self._run(include_patreon=True)
        supporter.refresh_from_db()
        self.assertEqual(supporter.email, '')

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
                'anniversary_events/', 'step_up_banners/', 'scenarios/',
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


class SupportVariantResolutionTests(TestCase):
    """
    Which of several same-named SupportCard rows a banner actually features.

    Split from SupportBackfillTests because these exercise the resolver alone —
    no CSV, no commands, no database beyond the cards themselves.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.source_path = os.path.join(self.tmp, 'support_cards_source.json')
        patcher = patch.object(
            support_backfill, 'SUPPORT_CARDS_SOURCE', self.source_path)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self._write_source({})

    def _write_source(self, releases, name=None):
        """releases: {game_id: "YYYY-MM-DD"} — the shape resolve_variant reads."""
        with open(self.source_path, 'w', encoding='utf-8') as handle:
            json.dump(
                [{'id': game_id, 'release_ja': released, 'name_en': name}
                 for game_id, released in releases.items()],
                handle)
        support_backfill.clear_source_cache(self.source_path)

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

    def test_duplicate_names_fall_back_to_the_lowest_ssr_without_dates(self):
        # SupportCard.name is deliberately not unique — production holds four
        # rows named "Grass Wonder" (different rarities/reprints). With no
        # release date for any of them there is no honest way to choose, so the
        # rule degrades to the lowest SSR: still a guess, but always a card a
        # banner could actually feature.
        SupportCard.objects.create(name='Grass Wonder', game_id=30200)
        wanted = SupportCard.objects.create(name='Grass Wonder', game_id=30100)
        SupportCard.objects.create(name='Grass Wonder', game_id=30300)

        found, missing = support_backfill.resolve_support_cards(['Grass Wonder'])

        self.assertEqual(missing, [])
        self.assertEqual([c.pk for c in found], [wanted.pk])

    def test_never_resolves_to_an_r_card_when_an_ssr_exists(self):
        # THE BUG THIS RULE REPLACED: the old "lowest game_id" wins picked the
        # R variant every time, because 1xxxx sorts under 3xxxx. It put twenty
        # R cards on the production launch banner.
        SupportCard.objects.create(name='Special Week', game_id=10001)
        wanted = SupportCard.objects.create(name='Special Week', game_id=30001)

        found, _ = support_backfill.resolve_support_cards(['Special Week'])

        self.assertEqual([c.pk for c in found], [wanted.pk])

    def test_a_real_ssr_beats_a_null_game_id(self):
        # The old rule sorted a null game_id as 0, which made it beat every real
        # card. A row with no game_id cannot be shown to be banner-eligible, so
        # a known SSR is strictly the better answer.
        SupportCard.objects.create(name='Nameless', game_id=None)
        wanted = SupportCard.objects.create(name='Nameless', game_id=30001)

        found, _ = support_backfill.resolve_support_cards(['Nameless'])

        self.assertEqual([c.pk for c in found], [wanted.pk])

    def test_a_name_with_no_game_ids_at_all_still_resolves(self):
        # Rows predating the game_id backfill must keep working — refusing them
        # would turn a working batch into a skipped one.
        wanted = SupportCard.objects.create(name='Ancient', game_id=None)
        SupportCard.objects.create(name='Ancient', game_id=None)

        found, missing = support_backfill.resolve_support_cards(['Ancient'])

        self.assertEqual(missing, [])
        self.assertEqual([c.pk for c in found], [wanted.pk])

    # ── resolve_variant's date tiers ─────────────────────────────────────────

    def test_picks_the_ssr_that_debuted_on_the_banner(self):
        SupportCard.objects.create(name='Agnes Digital', game_id=30085)
        wanted = SupportCard.objects.create(name='Agnes Digital', game_id=30297)
        self._write_source({30085: '2022-02-08', 30297: '2026-04-30'})

        found, _ = support_backfill.resolve_support_cards(
            ['Agnes Digital'], datetime.date(2026, 4, 30))

        self.assertEqual([c.pk for c in found], [wanted.pk])

    def test_a_rerun_takes_the_most_recent_card_that_already_existed(self):
        # No card debuts on a rerun's date, so tier 2 decides: the newest
        # variant released on or before it.
        SupportCard.objects.create(name='Nice Nature', game_id=30054)
        wanted = SupportCard.objects.create(name='Nice Nature', game_id=30138)
        SupportCard.objects.create(name='Nice Nature', game_id=30239)
        self._write_source(
            {30054: '2021-08-20', 30138: '2023-03-29', 30239: '2025-01-31'})

        found, _ = support_backfill.resolve_support_cards(
            ['Nice Nature'], datetime.date(2024, 6, 1))

        self.assertEqual([c.pk for c in found], [wanted.pk])

    def test_refuses_two_candidates_released_too_close_together(self):
        # Inside the 14-day margin there is no confident answer, and a wrong
        # link here silently moves the card's selector eligibility.
        SupportCard.objects.create(name='Twins', game_id=30100)
        SupportCard.objects.create(name='Twins', game_id=30101)
        self._write_source({30100: '2024-01-01', 30101: '2024-01-08'})

        found, missing = support_backfill.resolve_support_cards(
            ['Twins'], datetime.date(2024, 6, 1))

        self.assertEqual(found, [])
        self.assertEqual(missing, ['Twins'])

    def test_refuses_when_the_card_that_debuted_here_is_not_in_the_database(self):
        # THE TRAP the guard exists for. The source says 30293 launched on this
        # banner, but only the older reprint is in the database — so tier 2
        # would answer 30248, which reads as a confident correct answer and is
        # not. Every 2026 banner locally is in exactly this state.
        SupportCard.objects.create(name='Daring Tact', game_id=10120)
        SupportCard.objects.create(name='Daring Tact', game_id=30248)
        self._write_source(
            {30248: '2025-04-10', 30293: '2026-03-30'}, name='Daring Tact')

        found, missing = support_backfill.resolve_support_cards(
            ['Daring Tact'], datetime.date(2026, 3, 30))

        self.assertEqual(found, [])
        self.assertEqual(missing, ['Daring Tact'])

    def test_accepts_the_debut_card_once_it_exists(self):
        # The other half of the guard: adding the row unblocks the same call.
        SupportCard.objects.create(name='Daring Tact', game_id=30248)
        wanted = SupportCard.objects.create(name='Daring Tact', game_id=30293)
        self._write_source(
            {30248: '2025-04-10', 30293: '2026-03-30'}, name='Daring Tact')

        found, _ = support_backfill.resolve_support_cards(
            ['Daring Tact'], datetime.date(2026, 3, 30))

        self.assertEqual([c.pk for c in found], [wanted.pk])

    def test_refuses_candidates_that_all_postdate_the_banner(self):
        # A banner cannot feature a card that does not exist yet.
        SupportCard.objects.create(name='Future', game_id=30100)
        SupportCard.objects.create(name='Future', game_id=30200)
        self._write_source({30100: '2026-01-01', 30200: '2026-06-01'})

        found, missing = support_backfill.resolve_support_cards(
            ['Future'], datetime.date(2025, 1, 1))

        self.assertEqual(found, [])
        self.assertEqual(missing, ['Future'])

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

        # Same treatment for the release-date source the variant tiers read.
        # The module caches parsed source data per path, so pointing at a temp
        # file both isolates these tests and keeps the real file's cache intact.
        self.source_path = os.path.join(self.tmp, 'support_cards_source.json')
        source_patcher = patch.object(
            support_backfill, 'SUPPORT_CARDS_SOURCE', self.source_path)
        source_patcher.start()
        self.addCleanup(source_patcher.stop)
        self._write_source({})

        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _write_csv(self, rows):
        """rows: (jp_start, banner_type, uma, supports-joined)."""
        with open(self.csv_path, 'w', newline='', encoding='utf-8') as handle:
            writer = csv.writer(handle)
            writer.writerow(['JP Start Date', 'Banner Type', 'Banner Uma', 'Banner Support'])
            writer.writerows(rows)

    def _write_source(self, releases, name=None):
        """releases: {game_id: "YYYY-MM-DD"} — the shape resolve_variant reads."""
        with open(self.source_path, 'w', encoding='utf-8') as handle:
            json.dump(
                [{'id': game_id, 'release_ja': released, 'name_en': name}
                 for game_id, released in releases.items()],
                handle)
        # Drop any parse cached from an earlier write in the same test.
        support_backfill.clear_source_cache(self.source_path)

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

    def test_launch_repair_links_the_ssr_not_the_r(self):
        # The regression guard for what put 20 R cards into production. Both
        # rarities of the same name exist, exactly as they do in prod.
        self._timeline('Special Week', (2021, 2, 24))
        Uma.objects.create(name='Special Week')
        SupportCard.objects.create(name='Special Week', game_id=10001)
        wanted = SupportCard.objects.create(name='Special Week', game_id=30001)
        self._write_source({10001: '2021-02-24', 30001: '2021-02-24'})
        self._write_csv([('2021-02-24', '-2', '', 'Special Week')])

        call_command('repair_launch_banner', '--no-input')

        support = BannerTimeline.objects.get().support_banners.get()
        self.assertEqual(
            list(support.support_cards.values_list('pk', flat=True)), [wanted.pk])


class FixSupportCardVariantsTests(TestCase):
    """
    The repair for banner links pointing at an R card instead of its SSR.

    These build the production shape deliberately: a banner whose linked card
    shares its name with a higher-rarity card released the same day.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.source_path = os.path.join(self.tmp, 'support_cards_source.json')
        patcher = patch.object(
            support_backfill, 'SUPPORT_CARDS_SOURCE', self.source_path)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self._write_source({10001: '2021-02-24', 30001: '2021-02-24'})

    def _write_source(self, releases, name=None):
        with open(self.source_path, 'w', encoding='utf-8') as handle:
            json.dump(
                [{'id': game_id, 'release_ja': released, 'name_en': name}
                 for game_id, released in releases.items()],
                handle)
        support_backfill.clear_source_cache(self.source_path)

    def _banner(self, jp_start=(2021, 2, 24), name='Launch Support'):
        timeline = BannerTimeline.objects.create(
            name='Launch',
            jp_start_date=timezone.make_aware(datetime.datetime(*jp_start)),
            jp_end_date=timezone.make_aware(
                datetime.datetime(*jp_start) + datetime.timedelta(days=7)))
        return BannerSupport.objects.create(banner_timeline=timeline, name=name)

    def _link(self, banner, card):
        return SupportsOnSupportBanner.objects.create(
            banner_support=banner, support_card=card)

    def test_repoints_an_r_link_to_the_ssr(self):
        banner = self._banner()
        r_card = SupportCard.objects.create(name='Special Week', game_id=10001)
        ssr = SupportCard.objects.create(name='Special Week', game_id=30001)
        link = self._link(banner, r_card)

        call_command('fix_support_card_variants', '--no-input')

        link.refresh_from_db()
        self.assertEqual(link.support_card_id, ssr.pk)

    def test_leaves_ssr_links_alone(self):
        banner = self._banner()
        ssr = SupportCard.objects.create(name='Special Week', game_id=30001)
        link = self._link(banner, ssr)

        call_command('fix_support_card_variants', '--no-input')

        link.refresh_from_db()
        self.assertEqual(link.support_card_id, ssr.pk)

    def test_is_idempotent(self):
        # What makes it safe to leave wired up as a POST_DEPLOY job.
        banner = self._banner()
        r_card = SupportCard.objects.create(name='Special Week', game_id=10001)
        ssr = SupportCard.objects.create(name='Special Week', game_id=30001)
        self._link(banner, r_card)

        call_command('fix_support_card_variants', '--no-input')
        call_command('fix_support_card_variants', '--no-input')

        self.assertEqual(
            list(banner.support_cards.values_list('pk', flat=True)), [ssr.pk])

    def test_dry_run_writes_nothing(self):
        banner = self._banner()
        r_card = SupportCard.objects.create(name='Special Week', game_id=10001)
        SupportCard.objects.create(name='Special Week', game_id=30001)
        link = self._link(banner, r_card)

        call_command('fix_support_card_variants', '--dry-run')

        link.refresh_from_db()
        self.assertEqual(link.support_card_id, r_card.pk)

    def test_drops_the_r_link_when_the_banner_already_has_the_ssr(self):
        # Re-pointing would otherwise show the card twice on the tile; there is
        # no unique constraint on the join to stop it.
        banner = self._banner()
        r_card = SupportCard.objects.create(name='Special Week', game_id=10001)
        ssr = SupportCard.objects.create(name='Special Week', game_id=30001)
        self._link(banner, r_card)
        self._link(banner, ssr)

        call_command('fix_support_card_variants', '--no-input')

        self.assertEqual(
            list(banner.support_cards.values_list('pk', flat=True)), [ssr.pk])

    def test_leaves_a_link_alone_when_no_ssr_exists(self):
        # A LINKING job: it must not invent the missing card.
        banner = self._banner()
        r_card = SupportCard.objects.create(name='Orphan R', game_id=10099)
        link = self._link(banner, r_card)

        out = StringIO()
        call_command('fix_support_card_variants', '--no-input', stdout=out)

        link.refresh_from_db()
        self.assertEqual(link.support_card_id, r_card.pk)
        self.assertIn('Orphan R', out.getvalue())
        self.assertEqual(SupportCard.objects.filter(name='Orphan R').count(), 1)

    def test_leaves_a_link_alone_when_the_debut_ssr_is_missing(self):
        # The production risk this command must not take: quietly "repairing"
        # a 2026 banner onto a 2025 reprint because the real card was never
        # added. It reports instead, and the row stays as it was.
        banner = self._banner(jp_start=(2026, 3, 30), name='Daring Tact')
        r_card = SupportCard.objects.create(name='Daring Tact', game_id=10120)
        SupportCard.objects.create(name='Daring Tact', game_id=30248)
        self._write_source(
            {30248: '2025-04-10', 30293: '2026-03-30'}, name='Daring Tact')
        link = self._link(banner, r_card)

        out = StringIO()
        call_command('fix_support_card_variants', '--no-input', stdout=out)

        link.refresh_from_db()
        self.assertEqual(link.support_card_id, r_card.pk)
        # Names the card to add, rather than just declaring defeat.
        self.assertIn('30293', out.getvalue())

    def test_reports_a_link_whose_card_has_no_game_id(self):
        banner = self._banner()
        card = SupportCard.objects.create(name='Unknown Rarity', game_id=None)
        link = self._link(banner, card)

        out = StringIO()
        call_command('fix_support_card_variants', '--no-input', stdout=out)

        link.refresh_from_db()
        self.assertEqual(link.support_card_id, card.pk)
        self.assertIn('no game_id', out.getvalue())


CANONICAL_REDIRECT = "https://app.example.com/auth/callback"
DEV_REDIRECT = "http://localhost:5173/auth/callback"
UNLISTED_REDIRECT = "https://attacker.example.net/auth/callback"


@override_settings(
    GOOGLE_OAUTH_CLIENT_ID="test-google-client",
    GOOGLE_OAUTH_CLIENT_SECRET="test-google-secret",
    DISCORD_OAUTH_CLIENT_ID="test-discord-client",
    DISCORD_OAUTH_CLIENT_SECRET="test-discord-secret",
    OAUTH_REDIRECT_URI=CANONICAL_REDIRECT,
    OAUTH_ALLOWED_REDIRECT_URIS=frozenset([CANONICAL_REDIRECT, DEV_REDIRECT]),
)
class SocialAuthRedirectUriTests(TestCase):
    """The allowlisted `redirect_uri` parameter on /auth/<provider>/start.

    It exists so `npm run dev:live` -- a local Vite server talking to a deployed
    backend -- can complete a sign-in on localhost instead of being bounced to
    the deployed site. The allowlist is the security boundary: without it the
    endpoint would mail authorization codes to any address a caller named.
    """

    def _start(self, provider="google", redirect_uri=None):
        url = f"/auth/{provider}/start"
        if redirect_uri is not None:
            url += "?" + urlencode({"redirect_uri": redirect_uri})
        return self.client.get(url)

    @staticmethod
    def _redirect_param(response):
        """The redirect_uri the provider consent URL actually carries."""
        authorize_url = response.json()["authorize_url"]
        return parse_qs(urlparse(authorize_url).query)["redirect_uri"][0]

    def test_start_without_the_parameter_uses_the_canonical_uri(self):
        """The deployed SPA sends no parameter; its behaviour must not change."""
        response = self._start()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._redirect_param(response), CANONICAL_REDIRECT)

    def test_start_accepts_an_allowlisted_uri(self):
        response = self._start(redirect_uri=DEV_REDIRECT)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._redirect_param(response), DEV_REDIRECT)

    def test_start_rejects_an_unlisted_uri(self):
        """The whole point: an arbitrary address must not be honoured."""
        response = self._start(redirect_uri=UNLISTED_REDIRECT)

        self.assertEqual(response.status_code, 400)

    def test_an_unlisted_uri_is_refused_rather_than_silently_defaulted(self):
        """Falling back to the canonical URI would look like a working login
        that mysteriously lands somewhere else. Fail loudly instead."""
        response = self._start(redirect_uri=UNLISTED_REDIRECT)

        self.assertNotIn("authorize_url", response.json())

    def test_rejected_uri_is_not_echoed_back_to_the_caller(self):
        response = self._start(redirect_uri=UNLISTED_REDIRECT)

        self.assertNotIn(UNLISTED_REDIRECT, json.dumps(response.json()))

    def test_allowlist_is_enforced_for_discord_too(self):
        self.assertEqual(
            self._start(provider="discord", redirect_uri=UNLISTED_REDIRECT).status_code,
            400,
        )
        self.assertEqual(
            self._start(provider="discord", redirect_uri=DEV_REDIRECT).status_code,
            200,
        )

    def test_completion_exchanges_with_the_uri_the_login_started_with(self):
        """Providers bind the code to the redirect_uri, so the token request has
        to repeat the one used at the start -- not the canonical default."""
        state = self._start(redirect_uri=DEV_REDIRECT).json()["state"]

        with patch("calculatorapi.oauth.exchange_code", return_value="sub-1") as mocked:
            response = self.client.post(
                "/auth/social",
                {"provider": "google", "code": "CODE", "state": state},
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 201)
        mocked.assert_called_once_with("google", "CODE", DEV_REDIRECT)

    def test_completion_uses_the_canonical_uri_when_none_was_requested(self):
        state = self._start().json()["state"]

        with patch("calculatorapi.oauth.exchange_code", return_value="sub-2") as mocked:
            self.client.post(
                "/auth/social",
                {"provider": "google", "code": "CODE", "state": state},
                content_type="application/json",
            )

        mocked.assert_called_once_with("google", "CODE", CANONICAL_REDIRECT)

    def test_a_state_predating_the_redirect_field_still_completes(self):
        """A login in flight while this release deploys carries a state with no
        "r". It was started against the canonical URI, so it must finish there
        rather than 400 on a field that did not exist when it was minted."""
        legacy_state = signing.dumps({"p": "google", "n": "nonce"}, salt=STATE_SALT)

        with patch("calculatorapi.oauth.exchange_code", return_value="sub-3") as mocked:
            response = self.client.post(
                "/auth/social",
                {"provider": "google", "code": "CODE", "state": legacy_state},
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 201)
        mocked.assert_called_once_with("google", "CODE", CANONICAL_REDIRECT)

    def test_the_redirect_uri_cannot_be_swapped_by_tampering_with_the_state(self):
        """The signature is what makes the sealed URI trustworthy on return."""
        forged = signing.dumps(
            {"p": "google", "n": "nonce", "r": UNLISTED_REDIRECT},
            salt="some-other-salt",
        )

        with patch("calculatorapi.oauth.exchange_code") as mocked:
            response = self.client.post(
                "/auth/social",
                {"provider": "google", "code": "CODE", "state": forged},
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 400)
        mocked.assert_not_called()

    def test_a_state_minted_for_one_provider_is_not_replayable_against_another(self):
        """Pre-existing guarantee; the payload refactor must not have lost it."""
        state = self._start(provider="google", redirect_uri=DEV_REDIRECT).json()["state"]

        with patch("calculatorapi.oauth.exchange_code") as mocked:
            response = self.client.post(
                "/auth/social",
                {"provider": "discord", "code": "CODE", "state": state},
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 400)
        mocked.assert_not_called()


@override_settings(
    GOOGLE_OAUTH_CLIENT_ID="test-google-client",
    GOOGLE_OAUTH_CLIENT_SECRET="test-google-secret",
    OAUTH_REDIRECT_URI=CANONICAL_REDIRECT,
    OAUTH_ALLOWED_REDIRECT_URIS=frozenset([CANONICAL_REDIRECT]),
)
class SocialAuthDefaultAllowlistTests(TestCase):
    """With no extra URIs configured -- the default for any deployment that has
    not opted in -- the endpoint behaves exactly as it did before."""

    def test_localhost_is_not_allowed_by_default(self):
        response = self.client.get(
            "/auth/google/start?" + urlencode({"redirect_uri": DEV_REDIRECT})
        )

        self.assertEqual(response.status_code, 400)

    def test_the_canonical_uri_is_always_allowed_even_if_named_explicitly(self):
        response = self.client.get(
            "/auth/google/start?" + urlencode({"redirect_uri": CANONICAL_REDIRECT})
        )

        self.assertEqual(response.status_code, 200)


class FeedbackEndpointTests(TestCase):
    """POST /feedback — the public form's write-only endpoint.

    Mirrors VisitBeaconEndpointTests above: both are unauthenticated, throttled
    write endpoints, and both deliberately hide whether a filter fired.
    """

    def setUp(self):
        self.url = reverse('submit-feedback')
        # DRF throttles through the shared cache; without this a neighbouring
        # test's hits could throttle ours. Same reason as the visit beacon.
        cache.clear()

    def test_guest_submission_is_stored(self):
        res = self.client.post(self.url, {
            'category': 'bug',
            'message': 'The timeline scrolls past the last banner.',
            'source_path': '/app/timeline',
        })
        self.assertEqual(res.status_code, 201)
        entry = Feedback.objects.get()
        self.assertEqual(entry.category, 'bug')
        self.assertEqual(entry.source_path, '/app/timeline')
        # The defining property of a guest submission.
        self.assertIsNone(entry.user)
        self.assertFalse(entry.is_resolved)

    def test_signed_in_submission_is_linked_to_the_account(self):
        user = CustomUser.objects.create_user(
            username='user_a3f9c1', password='x')
        token = Token.objects.create(user=user)
        res = self.client.post(
            self.url,
            {'category': 'feature', 'message': 'Add a dark mode toggle.'},
            HTTP_AUTHORIZATION=f'Token {token.key}',
        )
        self.assertEqual(res.status_code, 201)
        self.assertEqual(Feedback.objects.get().user, user)

    def test_honeypot_returns_success_but_stores_nothing(self):
        """The response must not reveal that the spam filter fired.

        Same contract as the beacon's bot filter: telling the caller it was
        rejected tells whoever is probing which field to stop filling.
        """
        res = self.client.post(self.url, {
            'category': 'other',
            'message': 'buy cheap carats at example.com',
            'website': 'http://example.com',
        })
        self.assertEqual(res.status_code, 201)
        self.assertFalse(Feedback.objects.exists())

    def test_client_cannot_attribute_its_message_to_another_account(self):
        """`user` is not a writable field — the view sets it from the request."""
        victim = CustomUser.objects.create_user(username='victim', password='x')
        res = self.client.post(self.url, {
            'category': 'other',
            'message': 'Not from the victim.',
            'user': victim.pk,
            'is_resolved': True,
        })
        self.assertEqual(res.status_code, 201)
        entry = Feedback.objects.get()
        self.assertIsNone(entry.user)
        self.assertFalse(entry.is_resolved)

    def test_empty_message_is_rejected(self):
        res = self.client.post(self.url, {'category': 'bug', 'message': '   '})
        self.assertEqual(res.status_code, 400)
        self.assertFalse(Feedback.objects.exists())

    def test_over_length_message_is_rejected_cleanly(self):
        res = self.client.post(self.url, {
            'category': 'bug',
            'message': 'x' * (MESSAGE_MAX_LENGTH + 1),
        })
        self.assertEqual(res.status_code, 400)
        self.assertFalse(Feedback.objects.exists())

    def test_get_is_not_allowed(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_repeated_submissions_are_eventually_throttled(self):
        # 10/hour, so the 11th is refused. This is the only thing between an
        # open write endpoint and someone filling the table overnight.
        for i in range(10):
            self.client.post(
                self.url, {'category': 'other', 'message': f'report {i}'})
        res = self.client.post(
            self.url, {'category': 'other', 'message': 'one too many'})
        self.assertEqual(res.status_code, 429)

    def test_purging_a_user_keeps_their_feedback(self):
        """SET_NULL, not CASCADE — purge_user_pii must not destroy reports."""
        user = CustomUser.objects.create_user(username='leaving', password='x')
        Feedback.objects.create(
            category='bug', message='Still useful after the account goes.',
            user=user)
        user.delete()
        entry = Feedback.objects.get()
        self.assertIsNone(entry.user)
        self.assertEqual(entry.message, 'Still useful after the account goes.')


# ── Patreon supporters ────────────────────────────────────────────────────────

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


class PatreonSupporterEndpointTests(TestCase):
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


class PatreonCsvImportTests(TestCase):
    """The importer's two jobs: reconcile the roster, and touch nothing else."""

    def test_parse_reads_only_name_email_tier_and_status(self):
        upload = patreon_csv(
            ("Rhondal", "rtibplays@gmail.com", "rhondal", "Active patron", "Junior Class"),
        )
        rows = parse_patreon_csv(upload)
        self.assertEqual(rows, [{
            "display_name": "Rhondal",
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
class PatreonImportAdminViewTests(TestCase):
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


class SetPatreonTierOrderCommandTests(TestCase):
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


# ── Patreon API sync ──────────────────────────────────────────────────────────

def patreon_member(name, tier_id=None, status="active_patron", pledge_start=None, email=None):
    """One member resource, shaped like Patreon's JSON:API response."""
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
            }
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


class FakeResponse:  # pylint: disable=too-few-public-methods
    """Stands in for a requests.Response in the client tests."""

    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


@override_settings(PATREON_CLIENT_ID="cid", PATREON_CLIENT_SECRET="csecret")
class PatreonApiClientTests(TestCase):
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
class PatreonSyncCommandTests(TestCase):
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


class PatreonSyncEndpointTests(TestCase):
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
class PatreonSyncAdminViewTests(TestCase):
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


class PublicPayloadCacheTests(TestCase):
    """The server-side cache behind GET /calculator-data.

    -> calculatorapi/public_payload_cache.py
    """

    def setUp(self):
        # The cache outlives a test -- it is process memory, and TestCase's
        # rollback does not touch it. Clear it so each case starts on a miss.
        cache.clear()
        self.user = make_user()
        self.client, self.token = auth_client(self.user)
        self.timeline = make_timeline(name='Cached Banner')
        self.uma_banner = make_uma_banner(timeline=self.timeline)

    def test_first_request_populates_the_cache(self):
        self.assertIsNone(public_payload_cache.read())
        res = APIClient().get('/calculator-data')
        self.assertEqual(res.status_code, 200)
        self.assertIsNotNone(public_payload_cache.read())

    def test_second_guest_request_costs_no_queries(self):
        APIClient().get('/calculator-data')
        # The whole point: a warm cache answers a guest without touching the DB.
        with self.assertNumQueries(0):
            res = APIClient().get('/calculator-data')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(set(res.data.keys()), _EXPECTED_GET_KEYS)

    def test_cached_response_matches_an_uncached_one(self):
        cold = APIClient().get('/calculator-data').data
        warm = APIClient().get('/calculator-data').data
        self.assertEqual(json.dumps(cold, default=str),
                         json.dumps(warm, default=str))

    def test_content_write_invalidates(self):
        APIClient().get('/calculator-data')
        self.assertIsNotNone(public_payload_cache.read())
        make_timeline(name='Newly Added')
        self.assertIsNone(public_payload_cache.read())

    def test_content_delete_invalidates(self):
        APIClient().get('/calculator-data')
        self.timeline.delete()
        self.assertIsNone(public_payload_cache.read())

    def test_a_new_banner_shows_up_on_the_next_request(self):
        # The invalidation the content editor actually cares about.
        first = APIClient().get('/calculator-data')
        names = [t['name'] for t in first.data['banner_timeline_data']]
        self.assertNotIn('Second Banner', names)

        make_timeline(name='Second Banner')

        second = APIClient().get('/calculator-data')
        names = [t['name'] for t in second.data['banner_timeline_data']]
        self.assertIn('Second Banner', names)

    def test_a_visit_row_does_not_invalidate(self):
        # Visits are written on EVERY page view. If they invalidated, the cache
        # would be cleared continuously and never serve anything.
        APIClient().get('/calculator-data')
        DailyVisit.objects.create(
            date=timezone.localdate(), page_views=1, unique_visitors=1)
        self.assertIsNotNone(public_payload_cache.read())

    def test_a_user_plan_write_does_not_invalidate(self):
        # User-scoped rows are never part of the cached half, so saving a plan
        # must not throw away the catalogue for everyone else.
        APIClient().get('/calculator-data')
        UserPlannedBanner.objects.create(
            user=self.user, banner_uma=self.uma_banner, number_of_pulls=5)
        self.assertIsNotNone(public_payload_cache.read())

    def test_signed_in_rows_are_never_served_to_a_guest(self):
        """The one that matters: no user's data may reach the shared cache."""
        UserPlannedBanner.objects.create(
            user=self.user, banner_uma=self.uma_banner, number_of_pulls=5)
        # The SIGNED-IN request populates the cache first.
        cache.clear()
        signed_in = self.client.get('/calculator-data')
        self.assertEqual(len(signed_in.data['user_planned_banner_data']), 1)

        guest = APIClient().get('/calculator-data')
        self.assertIsNone(guest.data['user_stats_data'])
        self.assertEqual(guest.data['user_planned_banner_data'], [])
        self.assertEqual(guest.data['user_planned_purchase_data'], [])
        self.assertEqual(guest.data['user_step_up_selection_data'], [])

    def test_signed_in_rows_merge_over_a_guest_cached_payload(self):
        # The reverse order: a guest warms the cache, then a signed-in user must
        # still get their own rows merged in rather than the guest's empties.
        APIClient().get('/calculator-data')
        UserPlannedBanner.objects.create(
            user=self.user, banner_uma=self.uma_banner, number_of_pulls=7)

        res = self.client.get('/calculator-data')
        self.assertEqual(len(res.data['user_planned_banner_data']), 1)
        self.assertEqual(
            res.data['user_planned_banner_data'][0]['number_of_pulls'], 7)
        self.assertIsNotNone(res.data['user_stats_data'])
        # ...and the catalogue still came through with it.
        self.assertTrue(res.data['banner_timeline_data'])

    def test_one_user_never_sees_another_users_rows_from_the_cache(self):
        UserPlannedBanner.objects.create(
            user=self.user, banner_uma=self.uma_banner, number_of_pulls=5)
        self.client.get('/calculator-data')

        other = make_user('otheruser')
        other_client, _ = auth_client(other)
        res = other_client.get('/calculator-data')
        self.assertEqual(res.data['user_planned_banner_data'], [])

    def test_cached_payload_carries_every_expected_key(self):
        # A key missing from the cached half would only show up for guests.
        APIClient().get('/calculator-data')
        cached = json.loads(public_payload_cache.read())
        self.assertEqual(set(cached.keys()), _EXPECTED_GET_KEYS)

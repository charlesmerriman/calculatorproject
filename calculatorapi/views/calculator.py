from rest_framework.viewsets import ViewSet
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework import permissions, status
from django.db import transaction
from calculatorapi.eligibility import build_first_jp_date_maps
from calculatorapi.ledger import (
    KIND_CHAMPIONS_MEETING,
    KIND_LEAGUE_OF_HEROES,
    build_income_ledger,
)
from calculatorapi.predictions import (
    build_anniversary_event_date_map,
    build_effective_date_maps,
    build_game_event_date_map,
    effective_sort_key,
    planned_effective_start,
)
from calculatorapi.models import (
    CalculationConstants,
    ClubRank, TeamTrialsRank, ChampionsMeetingRank, LeagueOfHeroesRank,
    UserPlannedBanner, UserPlannedPurchase, BannerUma, BannerSupport, BannerStepUp,
    ChampionsMeeting, LeagueOfHeroes, GameEvent, BannerTimeline,
    AnniversaryEvent
)
from calculatorapi.views.rank_viewsets import (
    ClubRankSerializer,
    TeamTrialsRankSerializer,
    ChampionsMeetingRankSerializer,
    LeagueOfHeroesRankSerializer,
)
from calculatorapi.views.user_planned_banner import UserPlannedBannerSerializer
from calculatorapi.views.user import UserStatsSerializer
from calculatorapi.views.banner_uma import BannerUmaSerializer
from calculatorapi.views.banner_support import BannerSupportSerializer
from calculatorapi.views.banner_step_up import BannerStepUpSerializer
from calculatorapi.views.champions_meeting import ChampionsMeetingSerializer
from calculatorapi.views.league_of_heroes import LeagueOfHeroesSerializer
from calculatorapi.views.game_event import GameEventSerializer
from calculatorapi.views.banner_timeline import BannerTimelineForViewingSerializer
from calculatorapi.views.anniversary_event import AnniversaryEventSerializer
from calculatorapi.views.ledger import IncomeLedgerRowSerializer
from calculatorapi.views.calculation_constants import CalculationConstantsSerializer
from calculatorapi.views.user_planned_purchase import UserPlannedPurchaseSerializer


def _replace_user_rows(rows, *, model, serializer_class, user, missing_message):
    """Reconcile one of the PATCH body's user-owned collections against the DB.

    The contract every such collection shares:

      * key absent from the body (rows is None) -> leave the collection alone
      * []                                      -> delete every row
      * row carrying an id                      -> partial update, 404 if the
                                                   id isn't this user's
      * row without an id                       -> create, owned by this user

    Returns an error Response to bail out with, or None on success. The caller
    runs inside transaction.atomic(), so returning early rolls back whatever
    earlier collections had already written -- a half-saved plan is worse than
    a rejected one.
    """
    if rows is None:
        return None

    incoming_ids = [row["id"] for row in rows if "id" in row]
    model.objects.filter(user=user).exclude(id__in=incoming_ids).delete()

    for row in rows:
        row_id = row.get("id")
        if row_id:
            try:
                instance = model.objects.get(id=row_id, user=user)
            except model.DoesNotExist:
                return Response({"error": missing_message},
                                status=status.HTTP_404_NOT_FOUND)
            serializer = serializer_class(instance, data=row, partial=True)
        else:
            serializer = serializer_class(data=row)

        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        serializer.save(user=user)

    return None


class CalculatorViewSet(ViewSet):
    def get_permissions(self):
        # GET serves mostly reference data, so guests may read it; the PATCH
        # writes to request.user's rows and stays account-only.
        if self.action == "get_calculator_data":
            return [permissions.AllowAny()]
        return [permissions.IsAuthenticated()]

    @action(detail=False, methods=["get"], url_path="calculator-data")
    def get_calculator_data(self, request):
        # pylint: disable=too-many-locals
        #
        # This endpoint's job IS to assemble the whole payload: every local is a
        # named section of the response, and most carry a comment explaining
        # which anchor resolved its dates. Splitting it to satisfy a locals
        # count would scatter that reasoning across helpers that each run once,
        # in order, and would touch the app's most-used public route for no
        # behavioural gain.
        club_rank_data = ClubRank.objects.all()
        team_trials_rank_data = TeamTrialsRank.objects.all()
        champions_meeting_rank_data = ChampionsMeetingRank.objects.all()
        league_of_heroes_rank_data = LeagueOfHeroesRank.objects.all()

        # Resolve every timeline's effective (confirmed-or-predicted) global
        # dates once. Banner ordering now keys off these resolved dates rather
        # than a DB column, so we sort in Python (the sets are small). Champions
        # Meetings and League of Heroes events get their own maps — each content
        # type predicts against its own anchor, so rows are never mixed.
        # Resolved together in one call because schedule offsets DO span content
        # types (one shared calendar) — see predictions.apply_schedule_offsets.
        date_maps = build_effective_date_maps()
        emap = date_maps[BannerTimeline]
        cm_emap = date_maps[ChampionsMeeting]
        loh_emap = date_maps[LeagueOfHeroes]

        banner_uma_data = sorted(
            BannerUma.objects.select_related("banner_timeline"),
            key=lambda b: effective_sort_key(emap.get(b.banner_timeline_id)),
        )
        banner_support_data = sorted(
            BannerSupport.objects.select_related("banner_timeline"),
            key=lambda b: effective_sort_key(emap.get(b.banner_timeline_id)),
        )
        # Sorted through the same emap as its two peers — a step-up dates itself
        # off an ordinary BannerTimeline (its campaign's Part 2), so it needs no
        # prediction of its own. anniversary_event is joined for the cutoff the
        # serializer folds in.
        banner_step_up_data = sorted(
            BannerStepUp.objects.select_related(
                "banner_timeline", "anniversary_event"
            ),
            key=lambda b: effective_sort_key(emap.get(b.banner_timeline_id)),
        )
        # Campaigns own no dates — resolved by spanning the BannerTimeline parts
        # they link to, reusing the emap above rather than predicting afresh.
        anniversary_event_data = AnniversaryEvent.objects.prefetch_related(
            "banner_links", "products"
        )
        anniversary_emap = build_anniversary_event_date_map(
            anniversary_event_data, emap
        )
        anniversary_event_data = sorted(
            anniversary_event_data,
            key=lambda ev: effective_sort_key(anniversary_emap.get(ev.id)),
        )

        # Selector eligibility keys off each card's earliest JP banner. Built
        # once here and handed to every serializer that nests a card, because
        # resolving it per card would be an N+1 across the whole catalogue.
        uma_first_jp_dates, support_first_jp_dates = build_first_jp_date_maps()
        card_context = {
            "uma_first_jp_dates": uma_first_jp_dates,
            "support_first_jp_dates": support_first_jp_dates,
        }

        # Guests get the full reference payload but no user-scoped data:
        # an empty plan and null stats (the frontend seeds local defaults).
        if request.user.is_authenticated:
            user_planned_banner_data = sorted(
                UserPlannedBanner.objects.filter(user=request.user).select_related(
                    "banner_uma__banner_timeline",
                    "banner_support__banner_timeline",
                    "banner_step_up__banner_timeline",
                    "banner_step_up__anniversary_event",
                ),
                key=lambda pb: effective_sort_key(planned_effective_start(pb, emap)),
            )
            # Ordered by their campaign's resolved start so the planner renders
            # chronologically without re-deriving dates client-side.
            user_planned_purchase_data = sorted(
                UserPlannedPurchase.objects.filter(user=request.user).select_related(
                    "product__anniversary_event"
                ),
                key=lambda pp: effective_sort_key(
                    anniversary_emap.get(pp.product.anniversary_event_id)
                ),
            )
            user_stats_data = UserStatsSerializer(request.user).data
        else:
            user_planned_banner_data = UserPlannedBanner.objects.none()
            user_planned_purchase_data = UserPlannedPurchase.objects.none()
            user_stats_data = None
        events_data = GameEvent.objects.select_related("banner_timeline").all()
        # GameEvent has no dates of its own — resolved via the BannerTimeline
        # emap already built above (reusing it, not a new anchor computation).
        game_event_emap = build_game_event_date_map(events_data, emap)
        events_data = sorted(
            events_data,
            key=lambda ge: effective_sort_key(game_event_emap.get(ge.id)),
        )
        champions_meeting_data = sorted(
            ChampionsMeeting.objects.all(),
            key=lambda cm: effective_sort_key(cm_emap.get(cm.id)),
        )
        league_of_heroes_event_data = sorted(
            LeagueOfHeroes.objects.all(),
            key=lambda loh: effective_sort_key(loh_emap.get(loh.id)),
        )
        banner_timeline_data = sorted(
            BannerTimeline.objects.prefetch_related(
                "uma_banners",
                "support_banners",
                # Prefetched so the attached-campaign strip costs no extra query
                # per banner (195 rows would otherwise be 195 lookups).
                "anniversary_links__anniversary_event",
                # Same reason: the step-up chip would otherwise be one lookup
                # per timeline row.
                "step_up_banners",
            ),
            key=lambda t: effective_sort_key(emap.get(t.id)),
        )

        # The income ledger: every reward instant on one flat, date-sorted
        # timeline, which the projection queries for cumulative totals instead of
        # accruing income window by window. Built from the querysets and date maps
        # already in hand above — no extra queries, and no prediction of its own.
        income_ledger = build_income_ledger(
            game_events=events_data,
            game_event_emap=game_event_emap,
            race_sources=(
                (KIND_CHAMPIONS_MEETING, champions_meeting_data, cm_emap),
                (KIND_LEAGUE_OF_HEROES, league_of_heroes_event_data, loh_emap),
            ),
        )

        response = {
            "club_rank_data": ClubRankSerializer(club_rank_data, many=True).data,
            "team_trials_rank_data": TeamTrialsRankSerializer(team_trials_rank_data, many=True).data,
            "champions_meeting_rank_data": ChampionsMeetingRankSerializer(champions_meeting_rank_data, many=True).data,
            "league_of_heroes_rank_data": LeagueOfHeroesRankSerializer(league_of_heroes_rank_data, many=True).data,
            "banner_uma_data": BannerUmaSerializer(
                banner_uma_data, many=True,
                context={"effective_dates": emap, **card_context}
            ).data,
            "banner_support_data": BannerSupportSerializer(
                banner_support_data, many=True,
                context={"effective_dates": emap, **card_context}
            ).data,
            "banner_step_up_data": BannerStepUpSerializer(
                banner_step_up_data, many=True,
                context={"effective_dates": emap}
            ).data,
            "user_planned_banner_data": UserPlannedBannerSerializer(
                user_planned_banner_data, many=True,
                # No "request" in context on purpose: with it, DRF's ImageField
                # emits absolute URLs via request.build_absolute_uri(), which
                # behind the prod reverse proxy point at the wrong (internal/http)
                # host and break the nested banner images. Every other serializer
                # here omits request and emits relative /media/... URLs that the
                # frontend/ingress resolves correctly — keep this one consistent.
                context={"effective_dates": emap, **card_context},
            ).data,
            "user_planned_purchase_data": UserPlannedPurchaseSerializer(
                user_planned_purchase_data, many=True
            ).data,
            "anniversary_event_data": AnniversaryEventSerializer(
                anniversary_event_data, many=True,
                context={"effective_dates": anniversary_emap}
            ).data,
            "champions_meeting_data": ChampionsMeetingSerializer(
                champions_meeting_data, many=True, context={"effective_dates": cm_emap}
            ).data,
            "league_of_heroes_event_data": LeagueOfHeroesSerializer(
                league_of_heroes_event_data, many=True, context={"effective_dates": loh_emap}
            ).data,
            "events_data": GameEventSerializer(
                events_data, many=True, context={"effective_dates": game_event_emap}
            ).data,
            "income_ledger": IncomeLedgerRowSerializer(income_ledger, many=True).data,
            # Every tunable number the projection uses. Served on each request so
            # an admin edit takes effect on the next page load without a deploy.
            "calculation_constants": CalculationConstantsSerializer(
                CalculationConstants.load()
            ).data,
            "user_stats_data": user_stats_data,
            "banner_timeline_data": BannerTimelineForViewingSerializer(
                banner_timeline_data, many=True,
                context={"effective_dates": emap, **card_context}
            ).data,
        }

        return Response(response, status=status.HTTP_200_OK)

    @action(detail=False, methods=["patch"], url_path="calculator-data")
    def update_calculator_data(self, request):
        # Wrap everything in a transaction so a mid-update failure doesn't leave
        # stats saved but banners half-updated (or vice versa).
        #
        # set_rollback is load-bearing: `return`ing a Response from inside an
        # atomic block exits the context manager NORMALLY, so Django commits.
        # Without this the rejected half of a partly-invalid PATCH would be
        # rolled back but the accepted half would persist -- which is exactly
        # the state this transaction exists to prevent.
        with transaction.atomic():
            error = self._apply_updates(request)
            if error is not None:
                transaction.set_rollback(True)
                return error

        return Response({"message": "Data updated successfully"}, status=status.HTTP_200_OK)

    @staticmethod
    def _apply_updates(request):
        """Apply every section of the PATCH body. Returns an error Response or None.

        Order matters only in that stats are cheapest to validate; all three
        sections stand or fall together via the caller's transaction.
        """
        user = request.user

        user_stats_data = request.data.get("user_stats_data")
        if user_stats_data:
            serializer = UserStatsSerializer(user, data=user_stats_data, partial=True)
            if not serializer.is_valid():
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
            serializer.save()

        collections = (
            ("user_planned_banner_data", UserPlannedBanner,
             UserPlannedBannerSerializer, "Banner not found"),
            ("user_planned_purchase_data", UserPlannedPurchase,
             UserPlannedPurchaseSerializer, "Purchase not found"),
        )
        for key, model, serializer_class, missing_message in collections:
            error = _replace_user_rows(
                request.data.get(key),
                model=model,
                serializer_class=serializer_class,
                user=user,
                missing_message=missing_message,
            )
            if error is not None:
                return error

        return None

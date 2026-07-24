from rest_framework.viewsets import ViewSet
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework import permissions, status
from django.db import transaction
from calculatorapi.predictions import (
    build_effective_date_map,
    build_game_event_date_map,
    effective_sort_key,
    planned_effective_start,
)
from calculatorapi.models import (
    ClubRank, TeamTrialsRank, ChampionsMeetingRank, LeagueOfHeroesRank,
    UserPlannedBanner, BannerUma, BannerSupport,
    ChampionsMeeting, LeagueOfHeroes, GameEvent, BannerTimeline
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
from calculatorapi.views.champions_meeting import ChampionsMeetingSerializer
from calculatorapi.views.league_of_heroes import LeagueOfHeroesSerializer
from calculatorapi.views.game_event import GameEventSerializer
from calculatorapi.views.banner_timeline import BannerTimelineForViewingSerializer


class CalculatorViewSet(ViewSet):
    def get_permissions(self):
        # GET serves mostly reference data, so guests may read it; the PATCH
        # writes to request.user's rows and stays account-only.
        if self.action == "get_calculator_data":
            return [permissions.AllowAny()]
        return [permissions.IsAuthenticated()]

    @action(detail=False, methods=["get"], url_path="calculator-data")
    def get_calculator_data(self, request):
        club_rank_data = ClubRank.objects.all()
        team_trials_rank_data = TeamTrialsRank.objects.all()
        champions_meeting_rank_data = ChampionsMeetingRank.objects.all()
        league_of_heroes_rank_data = LeagueOfHeroesRank.objects.all()

        # Resolve every timeline's effective (confirmed-or-predicted) global
        # dates once. Banner ordering now keys off these resolved dates rather
        # than a DB column, so we sort in Python (the sets are small). Champions
        # Meetings and League of Heroes events get their own maps — each content
        # type predicts against its own anchor, so rows are never mixed.
        emap = build_effective_date_map()
        cm_emap = build_effective_date_map(ChampionsMeeting)
        loh_emap = build_effective_date_map(LeagueOfHeroes)

        banner_uma_data = sorted(
            BannerUma.objects.select_related("banner_timeline"),
            key=lambda b: effective_sort_key(emap.get(b.banner_timeline_id)),
        )
        banner_support_data = sorted(
            BannerSupport.objects.select_related("banner_timeline"),
            key=lambda b: effective_sort_key(emap.get(b.banner_timeline_id)),
        )
        # Guests get the full reference payload but no user-scoped data:
        # an empty plan and null stats (the frontend seeds local defaults).
        if request.user.is_authenticated:
            user_planned_banner_data = sorted(
                UserPlannedBanner.objects.filter(user=request.user).select_related(
                    "banner_uma__banner_timeline", "banner_support__banner_timeline"
                ),
                key=lambda pb: effective_sort_key(planned_effective_start(pb, emap)),
            )
            user_stats_data = UserStatsSerializer(request.user).data
        else:
            user_planned_banner_data = UserPlannedBanner.objects.none()
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
            BannerTimeline.objects.prefetch_related("uma_banners", "support_banners"),
            key=lambda t: effective_sort_key(emap.get(t.id)),
        )

        response = {
            "club_rank_data": ClubRankSerializer(club_rank_data, many=True).data,
            "team_trials_rank_data": TeamTrialsRankSerializer(team_trials_rank_data, many=True).data,
            "champions_meeting_rank_data": ChampionsMeetingRankSerializer(champions_meeting_rank_data, many=True).data,
            "league_of_heroes_rank_data": LeagueOfHeroesRankSerializer(league_of_heroes_rank_data, many=True).data,
            "banner_uma_data": BannerUmaSerializer(
                banner_uma_data, many=True, context={"effective_dates": emap}
            ).data,
            "banner_support_data": BannerSupportSerializer(
                banner_support_data, many=True, context={"effective_dates": emap}
            ).data,
            "user_planned_banner_data": UserPlannedBannerSerializer(
                user_planned_banner_data, many=True,
                # No "request" in context on purpose: with it, DRF's ImageField
                # emits absolute URLs via request.build_absolute_uri(), which
                # behind the prod reverse proxy point at the wrong (internal/http)
                # host and break the nested banner images. Every other serializer
                # here omits request and emits relative /media/... URLs that the
                # frontend/ingress resolves correctly — keep this one consistent.
                context={"effective_dates": emap},
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
            "user_stats_data": user_stats_data,
            "banner_timeline_data": BannerTimelineForViewingSerializer(
                banner_timeline_data, many=True, context={"effective_dates": emap}
            ).data,
        }

        return Response(response, status=status.HTTP_200_OK)

    @action(detail=False, methods=["patch"], url_path="calculator-data")
    def update_calculator_data(self, request):
        user = request.user

        # Wrap everything in a transaction so a mid-update failure doesn't
        # leave stats saved but banners half-updated (or vice versa).
        with transaction.atomic():
            user_stats_data = request.data.get("user_stats_data")
            if user_stats_data:
                user_stats_serializer = UserStatsSerializer(user, data=user_stats_data, partial=True)
                if user_stats_serializer.is_valid():
                    user_stats_serializer.save()
                else:
                    return Response(user_stats_serializer.errors, status=status.HTTP_400_BAD_REQUEST)

            user_planned_banner_data = request.data.get("user_planned_banner_data")
            if user_planned_banner_data is not None:
                incoming_ids = [b["id"] for b in user_planned_banner_data if "id" in b]
                UserPlannedBanner.objects.filter(user=user).exclude(id__in=incoming_ids).delete()

                for banner_data in user_planned_banner_data:
                    banner_id = banner_data.get("id")
                    if banner_id:
                        try:
                            banner = UserPlannedBanner.objects.get(id=banner_id, user=user)
                            serializer = UserPlannedBannerSerializer(banner, data=banner_data, partial=True)
                            if serializer.is_valid():
                                serializer.save()
                            else:
                                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
                        except UserPlannedBanner.DoesNotExist:
                            return Response({"error": "Banner not found"}, status=status.HTTP_404_NOT_FOUND)
                    else:
                        serializer = UserPlannedBannerSerializer(data=banner_data)
                        if serializer.is_valid():
                            serializer.save(user=user)
                        else:
                            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        return Response({"message": "Data updated successfully"}, status=status.HTTP_200_OK)

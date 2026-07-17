"""
Admin configuration, organized for a non-technical content editor.

Layout of this file:
  1. Site branding
  2. Shared helpers (image thumbnails)
  3. Inlines (children edited on their parent's page)
  4. Game content admins (what the "Content editors" group manages)
  5. Rank / income tables
  6. User data admins (owner-only; hidden from content editors by permissions)

The three join models (UmasOnUmaBanner, SupportsOnSupportBanner,
ChampionsMeetingUmaRecommendation) are deliberately NOT registered top-level —
they are edited through inlines on their parent pages. The "Content editors"
group (see management/commands/create_content_editor_group.py) still needs
permissions on them for the inlines to save.
"""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.utils.html import format_html

from .models import (
    CustomUser, Uma, SupportCard, UserPlannedBanner,
    TeamTrialsRank, ClubRank, ChampionsMeetingRank, LeagueOfHeroesRank,
    BannerTimeline, BannerUma, BannerSupport,
    ChampionsMeeting, ChampionsMeetingUmaRecommendation,
    SupportsOnSupportBanner, UmasOnUmaBanner,
    GameEvent, EventReward, LeagueOfHeroes,
    ChangelogEntry, ChangelogChange,
)

# ── 1. Site branding ─────────────────────────────────────────────────────────

admin.site.site_header = "Uma Calculator Admin"
admin.site.site_title = "Uma Calculator Admin"
admin.site.index_title = "Content management"

# Custom index adds a "Reports" box linking to the analytics dashboard
# (templates/admin/custom_index.html extends the default index).
admin.site.index_template = "admin/custom_index.html"


# ── 2. Shared helpers ────────────────────────────────────────────────────────

class ImagePreviewMixin:  # pylint: disable=too-few-public-methods
    """Adds a small image thumbnail for models with an `image` field."""

    @admin.display(description="Preview")
    def image_preview(self, obj):
        # Guard: .url raises if no file is attached.
        if obj.image:
            return format_html(
                '<img src="{}" style="height: 48px; border-radius: 4px;" />',
                obj.image.url,
            )
        return "—"


# ── 3. Inlines ───────────────────────────────────────────────────────────────

class BannerUmaInline(admin.TabularInline):
    """Uma banners listed on their timeline; click through to edit the umas."""
    model = BannerUma
    fields = ("name", "free_pulls")
    show_change_link = True  # renders a "Change" link to the banner's own page
    extra = 0


class BannerSupportInline(admin.TabularInline):
    """Support card banners listed on their timeline."""
    model = BannerSupport
    fields = ("name", "free_pulls")
    show_change_link = True
    extra = 0


class UmaOnBannerInline(admin.TabularInline):
    """The umas featured on an uma banner, edited on the banner page."""
    model = UmasOnUmaBanner
    autocomplete_fields = ("uma",)  # searchable picker instead of a 200-item dropdown
    extra = 1


class SupportOnBannerInline(admin.TabularInline):
    """The support cards featured on a support banner."""
    model = SupportsOnSupportBanner
    autocomplete_fields = ("support_card",)
    extra = 1


class EventRewardInline(admin.TabularInline):
    """An event's dated reward entries, edited on the event page."""
    model = EventReward
    fields = (
        "name", "date", "carat_amount",
        "uma_ticket_amount", "support_ticket_amount",
        "ssr_crystal_amount", "sr_crystal_amount",
        "ssr_shard_amount", "sr_shard_amount",
    )
    extra = 1


class RecommendedUmaInline(admin.TabularInline):
    """Recommended umas for a Champions Meeting."""
    model = ChampionsMeetingUmaRecommendation
    autocomplete_fields = ("uma",)
    extra = 1


class ChangelogChangeInline(admin.TabularInline):
    """The individual change lines of a changelog entry, edited on its page."""
    model = ChangelogChange
    fields = ("order", "category", "text")
    extra = 1


# ── 4. Game content ──────────────────────────────────────────────────────────

@admin.register(BannerTimeline)
class BannerTimelineAdmin(ImagePreviewMixin, admin.ModelAdmin):
    list_display = ("name", "jp_start_date", "global_start_date", "global_end_date")
    date_hierarchy = "global_start_date"
    ordering = ("-global_start_date",)
    search_fields = ("name",)  # also powers the autocomplete on banner admins
    readonly_fields = ("image_preview",)
    inlines = (BannerUmaInline, BannerSupportInline)
    # Editors always fill the JP dates; global dates only once the banner is
    # confirmed (they're left blank until then, and the app predicts them).
    fieldsets = (
        (None, {"fields": ("name", "image", "image_preview")}),
        ("JP server dates (always known)", {"fields": ("jp_start_date", "jp_end_date")}),
        ("Global server dates (fill when confirmed)", {"fields": ("global_start_date", "global_end_date")}),
    )


@admin.register(BannerUma)
class BannerUmaAdmin(admin.ModelAdmin):
    list_display = ("name", "banner_timeline", "free_pulls")
    list_select_related = ("banner_timeline",)
    ordering = ("-banner_timeline__global_start_date",)
    search_fields = ("name",)
    autocomplete_fields = ("banner_timeline",)
    inlines = (UmaOnBannerInline,)


@admin.register(BannerSupport)
class BannerSupportAdmin(admin.ModelAdmin):
    list_display = ("name", "banner_timeline", "free_pulls")
    list_select_related = ("banner_timeline",)
    ordering = ("-banner_timeline__global_start_date",)
    search_fields = ("name",)
    autocomplete_fields = ("banner_timeline",)
    inlines = (SupportOnBannerInline,)


@admin.register(Uma)
class UmaAdmin(ImagePreviewMixin, admin.ModelAdmin):
    list_display = ("image_preview", "name")
    list_display_links = ("name",)
    ordering = ("name",)
    search_fields = ("name",)  # required: autocomplete source for banner inlines
    readonly_fields = ("image_preview",)


@admin.register(SupportCard)
class SupportCardAdmin(ImagePreviewMixin, admin.ModelAdmin):
    list_display = ("image_preview", "name")
    list_display_links = ("name",)
    ordering = ("name",)
    search_fields = ("name",)  # required: autocomplete source for banner inlines
    readonly_fields = ("image_preview",)


@admin.register(GameEvent)
class GameEventAdmin(ImagePreviewMixin, admin.ModelAdmin):
    list_display = ("name", "start_date", "end_date")
    date_hierarchy = "start_date"
    ordering = ("-start_date",)
    search_fields = ("name",)  # required: autocomplete source for EventRewardAdmin
    readonly_fields = ("image_preview",)
    inlines = (EventRewardInline,)


@admin.register(EventReward)
class EventRewardAdmin(admin.ModelAdmin):
    """Kept top-level for browsing/searching all rewards across events."""
    list_display = ("name", "event", "date", "carat_amount")
    list_select_related = ("event",)
    date_hierarchy = "date"
    ordering = ("-date",)
    search_fields = ("name", "event__name")
    autocomplete_fields = ("event",)


@admin.register(ChampionsMeeting)
class ChampionsMeetingAdmin(ImagePreviewMixin, admin.ModelAdmin):
    list_display = ("name", "cm_number", "start_date", "end_date")
    date_hierarchy = "start_date"
    ordering = ("-start_date",)
    search_fields = ("name",)
    readonly_fields = ("image_preview",)
    fieldsets = (
        (None, {
            "fields": ("name", "cm_number", "start_date", "end_date",
                       "image", "image_preview"),
        }),
        ("Track details", {
            "fields": ("track", "surface_type", "distance", "length",
                       "track_condition", "season", "weather", "direction"),
        }),
        ("Stat recommendations", {
            "fields": ("speed_recommendation", "stamina_recommendation",
                       "power_recommendation", "guts_recommendation",
                       "wit_recommendation"),
        }),
    )
    inlines = (RecommendedUmaInline,)


@admin.register(ChangelogEntry)
class ChangelogEntryAdmin(admin.ModelAdmin):
    list_display = ("title", "version", "date")
    date_hierarchy = "date"
    ordering = ("-date",)
    search_fields = ("title",)
    inlines = (ChangelogChangeInline,)


@admin.register(LeagueOfHeroes)
class LeagueOfHeroesAdmin(ImagePreviewMixin, admin.ModelAdmin):
    list_display = ("name", "start_date", "end_date")
    date_hierarchy = "start_date"
    ordering = ("-start_date",)
    search_fields = ("name",)
    readonly_fields = ("image_preview",)


# ── 5. Rank / income tables ──────────────────────────────────────────────────

@admin.register(ClubRank)
class ClubRankAdmin(admin.ModelAdmin):
    list_display = ("name", "income_amount")
    ordering = ("income_amount",)


@admin.register(TeamTrialsRank)
class TeamTrialsRankAdmin(admin.ModelAdmin):
    list_display = ("name", "income_amount")
    ordering = ("income_amount",)


@admin.register(ChampionsMeetingRank)
class ChampionsMeetingRankAdmin(admin.ModelAdmin):
    list_display = ("name", "income_amount", "uma_ticket_amount",
                    "support_ticket_amount", "ssr_shard_amount", "sr_shard_amount")
    ordering = ("income_amount",)


@admin.register(LeagueOfHeroesRank)
class LeagueOfHeroesRankAdmin(admin.ModelAdmin):
    list_display = ("name", "income_amount", "uma_ticket_amount",
                    "support_ticket_amount", "ssr_shard_amount", "sr_shard_amount")
    ordering = ("income_amount",)


# ── 6. User data (owner-only) ────────────────────────────────────────────────

@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    """
    Django's stock UserAdmin (proper password handling, permission editors)
    extended with a collapsed section for the calculator's stat fields.
    """
    list_display = ("username", "email", "is_staff", "date_joined")
    fieldsets = UserAdmin.fieldsets + (
        ("Calculator stats", {
            "classes": ("collapse",),
            "fields": (
                "club_rank", "team_trials_rank",
                "champions_meeting_rank", "league_of_heroes_rank",
                "daily_carat", "training_pass",
                "current_carat", "current_paid_carat",
                "uma_ticket", "support_ticket",
                "ssr_crystals", "sr_crystals", "ssr_shards", "sr_shards",
            ),
        }),
    )


@admin.register(UserPlannedBanner)
class UserPlannedBannerAdmin(admin.ModelAdmin):
    list_display = ("user", "banner_uma", "banner_support", "number_of_pulls")
    list_select_related = ("user", "banner_uma", "banner_support")
    search_fields = ("user__username",)

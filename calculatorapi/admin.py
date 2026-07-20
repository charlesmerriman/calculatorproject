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

# unfold's ModelAdmin has a deeper class hierarchy than pylint's default
# max-parents of 7 — every admin in this file trips it, so disable once here.
# pylint: disable=too-many-ancestors

from django.contrib import admin
from django.contrib.auth.admin import GroupAdmin as BaseGroupAdmin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import Group
from django.db.models import Count
from django.utils.html import format_html
# django-unfold themes the admin, but only for admins that inherit its base
# classes — a plain admin.ModelAdmin would render unstyled under unfold's
# templates. Hence every ModelAdmin/TabularInline below extends unfold's.
from unfold.admin import ModelAdmin, TabularInline
from unfold.forms import AdminPasswordChangeForm, UserChangeForm, UserCreationForm

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

class BannerUmaInline(TabularInline):
    """Uma banners listed on their timeline; click through to edit the umas."""
    model = BannerUma
    fields = ("name", "free_pulls")
    show_change_link = True  # renders a "Change" link to the banner's own page
    extra = 0


class BannerSupportInline(TabularInline):
    """Support card banners listed on their timeline."""
    model = BannerSupport
    fields = ("name", "free_pulls")
    show_change_link = True
    extra = 0


class UmaOnBannerInline(TabularInline):
    """The umas featured on an uma banner, edited on the banner page."""
    model = UmasOnUmaBanner
    autocomplete_fields = ("uma",)  # searchable picker instead of a 200-item dropdown
    extra = 1


class SupportOnBannerInline(TabularInline):
    """The support cards featured on a support banner."""
    model = SupportsOnSupportBanner
    autocomplete_fields = ("support_card",)
    extra = 1


class EventRewardInline(TabularInline):
    """An event's dated reward entries, edited on the event page."""
    model = EventReward
    fields = (
        "name", "date", "carat_amount",
        "uma_ticket_amount", "support_ticket_amount",
        "ssr_crystal_amount", "sr_crystal_amount",
        "ssr_shard_amount", "sr_shard_amount",
    )
    extra = 1


class RecommendedUmaInline(TabularInline):
    """Recommended umas for a Champions Meeting."""
    model = ChampionsMeetingUmaRecommendation
    autocomplete_fields = ("uma",)
    extra = 1


class ChangelogChangeInline(TabularInline):
    """The individual change lines of a changelog entry, edited on its page."""
    model = ChangelogChange
    fields = ("order", "category", "text")
    extra = 1


# ── 4. Game content ──────────────────────────────────────────────────────────

class GlobalDatesFilter(admin.SimpleListFilter):
    """
    Sidebar filter on the timeline list: has the global run been confirmed?
    Mirrors the app's own logic — a timeline without a global_start_date is
    served to users with dates *predicted* from the JP schedule.
    """
    title = "global dates"
    parameter_name = "global_dates"

    def lookups(self, request, model_admin):
        return (
            ("confirmed", "Confirmed"),
            ("predicted", "Predicted (awaiting confirmation)"),
        )

    def queryset(self, request, queryset):
        if self.value() == "confirmed":
            return queryset.filter(global_start_date__isnull=False)
        if self.value() == "predicted":
            return queryset.filter(global_start_date__isnull=True)
        return queryset


class GlobalDatesStatusMixin:  # pylint: disable=too-few-public-methods
    """
    Adds a Confirmed/Predicted status badge column, shared by every JP-first
    content admin (banners, Champions Meetings, League of Heroes). A row with a
    global_start_date is confirmed; without one the app predicts its dates from
    the JP schedule.
    """

    @admin.display(description="Status", ordering="global_start_date")
    def global_dates_status(self, obj):
        # Inline styles (not admin CSS classes) so the badge renders the same
        # under any admin theme.
        if obj.global_start_date:
            color, background, label = "#166534", "#dcfce7", "Confirmed"
        else:
            color, background, label = "#92400e", "#fef3c7", "Predicted"
        return format_html(
            '<span style="color: {}; background: {}; padding: 2px 8px; '
            'border-radius: 9999px; font-weight: 600;">{}</span>',
            color, background, label,
        )


@admin.register(BannerTimeline)
class BannerTimelineAdmin(GlobalDatesStatusMixin, ImagePreviewMixin, ModelAdmin):
    list_display = ("name", "jp_start_date", "global_start_date",
                    "global_end_date", "global_dates_status")
    list_filter = (GlobalDatesFilter,)
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


class PlannedByColumnMixin:  # pylint: disable=too-few-public-methods
    """
    Adds a sortable "Planned by" column: how many users have this banner in
    their pull plan. Counting happens in SQL (one annotation, no N+1) and the
    `ordering=` mapping is what makes the column header sortable.
    """

    def get_queryset(self, request):
        # Reverse FK from UserPlannedBanner (no related_name → default name).
        return super().get_queryset(request).annotate(
            planned_count=Count("userplannedbanner"))

    @admin.display(description="Planned by", ordering="planned_count")
    def planned_by(self, obj):
        return f"{obj.planned_count} user{'' if obj.planned_count == 1 else 's'}"


@admin.register(BannerUma)
class BannerUmaAdmin(PlannedByColumnMixin, ModelAdmin):
    list_display = ("name", "banner_timeline", "free_pulls", "planned_by")
    list_select_related = ("banner_timeline",)
    ordering = ("-banner_timeline__global_start_date",)
    search_fields = ("name",)
    autocomplete_fields = ("banner_timeline",)
    inlines = (UmaOnBannerInline,)


@admin.register(BannerSupport)
class BannerSupportAdmin(PlannedByColumnMixin, ModelAdmin):
    list_display = ("name", "banner_timeline", "free_pulls", "planned_by")
    list_select_related = ("banner_timeline",)
    ordering = ("-banner_timeline__global_start_date",)
    search_fields = ("name",)
    autocomplete_fields = ("banner_timeline",)
    inlines = (SupportOnBannerInline,)


@admin.register(Uma)
class UmaAdmin(ImagePreviewMixin, ModelAdmin):
    list_display = ("image_preview", "name")
    list_display_links = ("name",)
    ordering = ("name",)
    search_fields = ("name",)  # required: autocomplete source for banner inlines
    readonly_fields = ("image_preview",)


@admin.register(SupportCard)
class SupportCardAdmin(ImagePreviewMixin, ModelAdmin):
    list_display = ("image_preview", "name", "game_id")
    list_display_links = ("name",)
    ordering = ("name",)
    search_fields = ("name",)  # required: autocomplete source for banner inlines
    readonly_fields = ("image_preview",)


@admin.register(GameEvent)
class GameEventAdmin(ImagePreviewMixin, ModelAdmin):
    list_display = ("name", "start_date", "end_date")
    date_hierarchy = "start_date"
    ordering = ("-start_date",)
    search_fields = ("name",)  # required: autocomplete source for EventRewardAdmin
    readonly_fields = ("image_preview",)
    inlines = (EventRewardInline,)


@admin.register(EventReward)
class EventRewardAdmin(ModelAdmin):
    """Kept top-level for browsing/searching all rewards across events."""
    list_display = ("name", "event", "date", "carat_amount")
    list_select_related = ("event",)
    date_hierarchy = "date"
    ordering = ("-date",)
    search_fields = ("name", "event__name")
    autocomplete_fields = ("event",)


@admin.register(ChampionsMeeting)
class ChampionsMeetingAdmin(GlobalDatesStatusMixin, ImagePreviewMixin, ModelAdmin):
    list_display = ("name", "cm_number", "jp_start_date", "global_start_date",
                    "global_end_date", "global_dates_status")
    list_filter = (GlobalDatesFilter,)
    date_hierarchy = "global_start_date"
    ordering = ("-global_start_date",)
    search_fields = ("name",)
    readonly_fields = ("image_preview",)
    # Editors always fill the JP dates; global dates only once the meeting is
    # confirmed (they're left blank until then, and the app predicts them).
    fieldsets = (
        (None, {
            "fields": ("name", "cm_number", "image", "image_preview"),
        }),
        ("JP server dates (always known)", {
            "fields": ("jp_start_date", "jp_end_date"),
        }),
        ("Global server dates (fill when confirmed)", {
            "fields": ("global_start_date", "global_end_date"),
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
class ChangelogEntryAdmin(ModelAdmin):
    list_display = ("title", "version", "date")
    date_hierarchy = "date"
    ordering = ("-date",)
    search_fields = ("title",)
    inlines = (ChangelogChangeInline,)


@admin.register(LeagueOfHeroes)
class LeagueOfHeroesAdmin(GlobalDatesStatusMixin, ImagePreviewMixin, ModelAdmin):
    list_display = ("name", "jp_start_date", "global_start_date",
                    "global_end_date", "global_dates_status")
    list_filter = (GlobalDatesFilter,)
    date_hierarchy = "global_start_date"
    ordering = ("-global_start_date",)
    search_fields = ("name",)
    readonly_fields = ("image_preview",)
    # Editors always fill the JP dates; global dates only once the event is
    # confirmed (they're left blank until then, and the app predicts them).
    fieldsets = (
        (None, {"fields": ("name", "image", "image_preview")}),
        ("JP server dates (always known)", {"fields": ("jp_start_date", "jp_end_date")}),
        ("Global server dates (fill when confirmed)", {"fields": ("global_start_date", "global_end_date")}),
    )


# ── 5. Rank / income tables ──────────────────────────────────────────────────

# `list_editable` turns the changelist into an editable grid: every rank's
# amounts can be updated on one screen with a single Save. The `name` column
# stays non-editable because it is the link to the detail page (a Django
# requirement: editable fields can't be in list_display_links).

@admin.register(ClubRank)
class ClubRankAdmin(ModelAdmin):
    list_display = ("name", "income_amount")
    list_editable = ("income_amount",)
    ordering = ("income_amount",)


@admin.register(TeamTrialsRank)
class TeamTrialsRankAdmin(ModelAdmin):
    list_display = ("name", "income_amount")
    list_editable = ("income_amount",)
    ordering = ("income_amount",)


@admin.register(ChampionsMeetingRank)
class ChampionsMeetingRankAdmin(ModelAdmin):
    list_display = ("name", "income_amount", "uma_ticket_amount",
                    "support_ticket_amount", "ssr_shard_amount", "sr_shard_amount")
    list_editable = ("income_amount", "uma_ticket_amount",
                     "support_ticket_amount", "ssr_shard_amount", "sr_shard_amount")
    ordering = ("income_amount",)


@admin.register(LeagueOfHeroesRank)
class LeagueOfHeroesRankAdmin(ModelAdmin):
    list_display = ("name", "income_amount", "uma_ticket_amount",
                    "support_ticket_amount", "ssr_shard_amount", "sr_shard_amount")
    list_editable = ("income_amount", "uma_ticket_amount",
                     "support_ticket_amount", "ssr_shard_amount", "sr_shard_amount")
    ordering = ("income_amount",)


# ── 6. User data (owner-only) ────────────────────────────────────────────────

@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin, ModelAdmin):
    """
    Django's stock UserAdmin (proper password handling, permission editors)
    extended with a collapsed section for the calculator's stat fields.
    """
    # Unfold's variants of the auth forms — same behavior, themed widgets.
    form = UserChangeForm
    add_form = UserCreationForm
    change_password_form = AdminPasswordChangeForm
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
class UserPlannedBannerAdmin(ModelAdmin):
    list_display = ("user", "banner_uma", "banner_support", "number_of_pulls")
    list_select_related = ("user", "banner_uma", "banner_support")
    search_fields = ("user__username",)


# Group is registered by django.contrib.auth with a plain ModelAdmin;
# re-register it on unfold's base class so it picks up the theme.
admin.site.unregister(Group)


@admin.register(Group)
class GroupAdmin(BaseGroupAdmin, ModelAdmin):
    pass

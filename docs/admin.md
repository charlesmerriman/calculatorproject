# Django Admin — developer notes

How the admin is built and the rules you must follow when extending it.

This is the **developer** view. For the client-facing guide to *using* the admin as a
content editor, see [content-editing.md](content-editing.md).

---

## django-unfold theming

The admin is themed with **django-unfold**.

**Every `ModelAdmin` and `TabularInline` in `admin.py` must inherit unfold's base classes**
(from `unfold.admin`), or it renders completely unstyled. This is the single most common
mistake when adding a new admin class.

`unfold` must sit **before** `django.contrib.admin` in `INSTALLED_APPS` — its `ready()`
swaps in `UnfoldAdminSite`, which is what enables the dashboard callback.

All theme configuration lives in the `UNFOLD` settings dict in `settings.py`:

- **Brand palette** — `COLORS["primary"]` is a gold ramp anchored on the frontend's
  `#E6D28A` (`--color-brand`), so admin buttons, links and active-nav match the app.
- **Curated sidebar** — `SIDEBAR["navigation"]` replaces unfold's auto-generated app list
  with task-based groups (Banners, Events & competitions, Characters, Income tables,
  Site content, Users & access), each with Material Symbols icons.
  **A newly registered model must be added here or it will not appear in the sidebar.**
  It stays reachable by URL, which makes this easy to miss.
- **Dashboard + environment badge** — `DASHBOARD_CALLBACK` and `ENVIRONMENT` point at
  `calculatorapi/admin_dashboard.py`. The dashboard callback injects headline KPI cards
  (reusing `analytics.build_analytics_report()`) rendered by
  `templates/admin/custom_index.html`; the environment callback shows a Local/Production
  badge driven by `DEBUG`.

---

## Structure for non-technical editors

`calculatorapi/admin.py` is customized throughout: model and field `verbose_name`s (app
section "Uma Musume Data"), inlines (timeline → banners; banner → featured umas/cards;
Champions Meeting → recommended umas), autocomplete pickers, image previews, and
`CustomUser` mounted on Django's `UserAdmin`.

- `GameEvent`'s reward amounts are plain fields on its own edit page (a "Rewards"
  fieldset), **not** an inline — a `GameEvent` carries at most one reward package.
- The three M2M join models are edited only via inlines; they are not registered
  top-level.
- `create_content_editor_group` builds a "Content editors" group with permissions for
  game content and rank tables only. Editor accounts see nothing else.

```bash
python manage.py create_content_editor_group   # create or refresh the group
```

---

## Image fields: picker as well as upload

Every `ImageField` admin mixes in `SpacesImagePickerMixin`
(`calculatorapi/admin_image_picker.py`), which adds a **"Choose from library"** button
opening a modal grid of what is already in the Spaces bucket.

**Why this works with no extra model:** an `ImageField` stores the **bucket key as a plain
string**, and `S3Boto3Storage` builds the CDN URL on read. So selecting an existing image
is just assigning that string (`setattr(instance, "image", key)`) — no upload, no copy,
no new table.

- Listing logic lives in `calculatorapi/image_library.py` — pure logic: cached
  `default_storage.listdir`, 5-minute TTL, busted on upload.
- It is served to the modal by the staff-only `/admin/image-library/` endpoint, whose
  `?prefix=` is **allow-listed** against the `upload_to` values derived from the models.
- **The mixin takes no configuration.** Image fields and their folders are read off the
  model, so a new `ImageField` is covered automatically and no fieldsets need editing.

Two deliberate behaviours:
- A file upload always beats a simultaneous library pick.
- A bucket that cannot be reached degrades to upload-only rather than 500ing the change form.

---

## Changelist extras

- Banner lists carry a sortable **SQL-annotated "Planned by" column** (count of users
  planning each banner).
- The four rank tables use `list_editable` grids for fast bulk editing.
- `BannerTimeline`, `ChampionsMeeting` and `LeagueOfHeroes` each show a
  **Confirmed/Predicted** global-dates badge (shared `GlobalDatesStatusMixin`) with a
  matching `GlobalDatesFilter`, and split JP/Global date fieldsets.
- `ChampionsMeetingAdmin` and `LeagueOfHeroesAdmin` are deliberately the same page
  section for section — same fieldsets, same schedule-offset block, same **Track details**
  and **Stat recommendations** groups — because the two models hold the same data and
  render through the same timeline card. Keep them in step when editing either.
  (`ChampionsMeetingAdmin` additionally carries the `RecommendedUmaInline`.)

---

## Analytics dashboard

`/admin/analytics/` (staff-only, linked from the admin index) shows aggregate usage
stats — paid-product adoption (`daily_carat` / `training_pass`), rank distributions,
resource averages, popular planned banners — plus a `?format=csv` export.

Aggregation logic is in `calculatorapi/analytics.py` (pure ORM, unit-tested); the view is
wrapped with `admin.site.admin_view()` in `urls.py`. Only aggregates are exposed, never
per-user rows, and staff accounts are excluded from all metrics.

Full metric definitions: [analytics.md](analytics.md).

---

## Local gotcha

The local Django server runs with `DEBUG=False` and `collectstatic` has never been run
locally, so **every admin template page 500s on :8000** (whitenoise manifest storage,
"Missing staticfiles manifest entry"). API endpoints are unaffected.

To render admin pages locally, run a second server with the manifest bypassed:

```bash
DEBUG=True python manage.py runserver 8001 --noreload
```

Django tests that render admin templates need an `@override_settings(STORAGES=...)` swap
to plain `StaticFilesStorage` — see `AnalyticsDashboardViewTests` in `tests.py`.

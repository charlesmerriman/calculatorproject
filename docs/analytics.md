# Analytics Dashboard

A staff-only page inside the Django admin that answers questions like *"what
percentage of users pay for the Daily Carat Pack?"* and *"which banners are
people planning to roll on?"* using data the app already stores. Nothing new
is collected — the dashboard aggregates the stats and pull plans that
logged-in users save through the calculator.

## Where to find it

- **Local dev**: <http://localhost:8000/admin/analytics/>
- **Production**: `https://<your-domain>/admin/analytics/`
- There is also a **Reports → Analytics dashboard** link at the top of the
  admin home page (`/admin/`).

You must be signed in to the Django admin with a **staff** account. To create
one:

```bash
# Local dev
python manage.py createsuperuser

# Production (DigitalOcean): open the API component's Console tab and run
python manage.py createsuperuser
```

## Privacy boundaries

- Only **aggregates** are shown: counts, percentages, averages. The page never
  displays usernames, emails, or any individual user's plan.
- **Staff accounts are excluded** from every metric, so admin/test accounts
  don't skew the numbers.
- **Guests are invisible**: anonymous users plan entirely in the browser and
  never send data to the server, so they can't be counted.
- This use of planning data is disclosed in the site's Privacy Policy
  ("How We Use Your Information").

## Reading the numbers

### Total vs. engaged users

Every stat on a new account defaults to *off/zero/none*, so accounts that
registered but never touched the calculator would drag every percentage down.
The dashboard therefore reports two denominators:

- **Total users** — every non-staff account.
- **Engaged users** — accounts that changed at least one calculator setting
  (a rank, a resource amount, a paid-product toggle) **or** planned at least
  one banner.

Percentages are shown against both. "% of engaged" is usually the more honest
answer to "what share of our *actual* users do X?".

### Paid products

Adoption of the two purchasable income sources — **Daily Carat Pack**
(`daily_carat`) and **Training Pass** (`training_pass`). A user "has" the
product if the toggle is on in their income settings right now.

### Rank distributions

For each income rank type (Team Trials, Club Rank, Champion's Meeting, League
of Heroes): how many users selected each rank. Rows are ordered by the rank's
income amount (game progression order); **Not set** counts users who never
picked one.

### Average current resources

Mean of each resource field (carats, tickets, crystals, shards) across
**engaged users only**.

### Popular banners

Separate tables for Uma and Support banners, ranked by:

- **Planners** — how many distinct users have this banner in their plan (the
  primary popularity signal)
- **Total pulls** — the sum of pulls everyone has budgeted for it
- **Avg pulls** — total pulls ÷ plan rows (how invested each planner is)

## CSV export & tracking trends over time

The **Download CSV** button (or `?format=csv`) exports every table into a
single dated file (`analytics-YYYY-MM-DD.csv`) that opens directly in Google
Sheets or Excel — use it for charts or to share numbers.

The dashboard is a **snapshot**: it shows the state of the database at the
moment you load it, and no history is stored server-side. To track trends
(e.g. "is Training Pass adoption growing?"), download the CSV on a regular
schedule — the first of each month works well — and keep the files. The dated
filenames make it easy to build a trend spreadsheet later.

## Implementation notes (for developers)

- All aggregation lives in `calculatorapi/analytics.py`
  (`build_analytics_report()`), pure ORM queries with no HTTP concerns.
- The view (`calculatorapi/views/analytics.py`) is wrapped with
  `admin.site.admin_view()` in `calculatorproject/urls.py`, which enforces the
  staff-only requirement and redirects everyone else to the admin login.
- Tests cover the aggregation math, access control, and CSV response — see the
  `Analytics*` test classes in `calculatorapi/tests.py`.

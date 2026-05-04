# Uma Musume Carat Calculator — Backend

A REST API that powers a gacha resource planner for Uma Musume Pretty Derby. Authenticated users receive a personalized forecast of how many carats and tickets they will accumulate before each planned banner's start date, based on their in-game ranks and upcoming event schedules.

## Tech Stack

| Tool | Purpose |
|---|---|
| Django 6 | Web framework and ORM |
| Django REST Framework | API views, serializers, token authentication |
| drf-spectacular | Auto-generated OpenAPI schema |
| PostgreSQL (prod) / SQLite (dev) | Database, selected via `DATABASE_URL` env var using `dj-database-url` |
| gunicorn | WSGI server for production |
| whitenoise | Static file serving without a separate web server |
| DigitalOcean App Platform | Hosting (configured in `.do/app.yaml`) |

## Architecture

### Django app structure

There is one app: `calculatorapi`. Models and views each live in a subdirectory with one file per entity, keeping diffs small and files focused.

```
calculatorapi/
  models/        # One model per file
  views/         # One serializer + ViewSet (or APIView) per file
  fixtures/      # JSON seed data for reference/rank tables
```

### Aggregated data endpoint

`GET /calculator-data` returns a single payload containing all reference data, the user's current stats, their planned banners, event schedules, and banner timelines. This design avoids N+1 fetch chains from the client — the frontend only needs one request on mount.

`PATCH /calculator-data` uses an upsert pattern: rows with `id` are updated, rows without `id` are created, and any rows absent from the payload are deleted. User stats are updated in the same request.

### Data model highlights

| Model | Purpose |
|---|---|
| `CustomUser` | Extends `AbstractUser`; stores current carat/ticket counts and rank FK references |
| `BannerTimeline` | A time window grouping one or more gacha banners |
| `BannerUma` / `BannerSupport` | Gacha banners with M2M relationships to Uma/SupportCard via through tables |
| `UserPlannedBanner` | A user's pull plan — FK to either `banner_uma` or `banner_support` (never both), plus `number_of_pulls` |
| `GameEvent` / `EventReward` | In-game events with dated reward schedules used in the resource projection |
| `ChampionsMeeting` | Racing event with track metadata and per-stat Uma recommendations |
| `*Rank` tables | `ClubRank`, `TeamTrialsRank`, `ChampionsMeetingRank`, `LeagueOfHeroesRank` — income amounts per rank tier |

`UserPlannedBanner` has a DB-level check constraint that enforces exactly one of `banner_uma` / `banner_support` is non-null at all times.

### URL routing

Manual routes:
- `POST /login`, `POST /register`, `POST /logout`
- `GET /calculator-data`, `PATCH /calculator-data`

SimpleRouter-registered read-only ViewSets:
- `/teamtrialranks`, `/clubranks`, `/championsmeetingranks`, `/leagueofheroesranks`
- `/events`, `/eventrewards`

## Local Setup

```bash
cd backend

# Create and activate a virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run migrations
python manage.py migrate

# Seed the database with reference data
bash seed_database.sh

# Start the dev server
python manage.py runserver
```

Other useful commands:

```bash
python manage.py test      # Run tests
pylint calculatorapi/ calculatorproject/  # Lint
python manage.py makemigrations          # After model changes
```

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `DJANGO_SECRET_KEY` | Production | Django secret key |
| `DATABASE_URL` | Production | PostgreSQL connection string; falls back to `db.sqlite3` if unset |
| `DEBUG` | Optional | `"True"` or `"False"` (default `"False"` in production) |

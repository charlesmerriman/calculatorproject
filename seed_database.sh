#!/bin/bash
set -e

echo "Loading fixtures..."

# Rank tables — no FK dependencies, load first
python3 manage.py loaddata calculatorapi/fixtures/clubRanks.json
python3 manage.py loaddata calculatorapi/fixtures/teamTrialsRanks.json
python3 manage.py loaddata calculatorapi/fixtures/championsMeetingRanks.json
python3 manage.py loaddata calculatorapi/fixtures/leagueOfHeroesRanks.json

# Core content tables — no FK dependencies
python3 manage.py loaddata calculatorapi/fixtures/umas.json
python3 manage.py loaddata calculatorapi/fixtures/supportCards.json
python3 manage.py loaddata calculatorapi/fixtures/bannerTimelines.json
python3 manage.py loaddata calculatorapi/fixtures/championsMeetings.json
python3 manage.py loaddata calculatorapi/fixtures/leagueOfHeroes.json
python3 manage.py loaddata calculatorapi/fixtures/gameEvents.json
python3 manage.py loaddata calculatorapi/fixtures/changelogEntries.json

# Models with FK dependencies
python3 manage.py loaddata calculatorapi/fixtures/bannerUmas.json
python3 manage.py loaddata calculatorapi/fixtures/bannerSupports.json
python3 manage.py loaddata calculatorapi/fixtures/changelogChanges.json

# M2M through tables — both sides of the relationship must already exist
python3 manage.py loaddata calculatorapi/fixtures/umasOnUmaBanner.json
python3 manage.py loaddata calculatorapi/fixtures/supportsOnSupportBanner.json

echo "Fixtures loaded."

# Anniversary campaigns are seeded by command rather than fixture: they attach
# to banner timelines by JP start date, so they must run AFTER bannerTimelines
# is loaded. Idempotent — safe to re-run on its own.
echo "Seeding anniversary campaigns..."
python3 manage.py seed_anniversary_campaigns

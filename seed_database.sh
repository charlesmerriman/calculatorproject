#!/bin/bash
set -e

read -p "This will wipe db.sqlite3 and all migrations. Continue? [y/N] " confirm
if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
    echo "Aborted."
    exit 1
fi

rm db.sqlite3
rm -rf ./calculatorapi/migrations
python3 manage.py makemigrations calculatorapi
python3 manage.py migrate

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

# Models with FK dependencies
python3 manage.py loaddata calculatorapi/fixtures/bannerUmas.json
python3 manage.py loaddata calculatorapi/fixtures/bannerSupports.json
python3 manage.py loaddata calculatorapi/fixtures/eventRewards.json

# M2M through tables — both sides of the relationship must already exist
python3 manage.py loaddata calculatorapi/fixtures/umasOnUmaBanner.json
python3 manage.py loaddata calculatorapi/fixtures/supportsOnSupportBanner.json

echo "Fixtures loaded."
python3 manage.py createsuperuser

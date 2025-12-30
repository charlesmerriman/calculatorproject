#!/bin/bash
set -e

rm db.sqlite3
rm -rf ./calculatorapi/migrations
python3 manage.py makemigrations calculatorapi
python3 manage.py migrate
python3 manage.py loaddata championsMeetingRanks
python3 manage.py loaddata clubRanks
python3 manage.py loaddata teamTrialsRanks
python3 manage.py loaddata customUsers
python3 manage.py loaddata bannerTags
python3 manage.py loaddata bannerTypes
python3 manage.py loaddata banners
python3 manage.py loaddata userPlannedBanners

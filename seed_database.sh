#!/bin/bash
set -e

rm db.sqlite3
rm -rf ./calculatorapi/migrations
python3 manage.py makemigrations calculatorapi
python3 manage.py migrate
python3 manage.py createsuperuser
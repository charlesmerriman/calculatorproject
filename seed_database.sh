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
python3 manage.py createsuperuser
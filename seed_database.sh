#!/bin/bash

rm db.sqlite3
rm -rf ./calculatorapi/migrations
python3 manage.py migrate
python3 manage.py makemigrations calculatorapi
python3 manage.py migrate calculatorapi
python3 manage.py loaddata users
python3 manage.py loaddata tokens


#!/bin/sh
set -eu

flask --app app:create_app init-db
flask --app app:create_app ensure-admin
exec gunicorn \
  --bind 0.0.0.0:8000 \
  --workers "${GUNICORN_WORKERS:-2}" \
  --threads "${GUNICORN_THREADS:-4}" \
  --timeout 45 \
  --access-logfile - \
  --error-logfile - \
  --capture-output \
  "app:create_app()"

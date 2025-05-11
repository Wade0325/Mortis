# backend/celery_worker.py
from app.core.celery_app import celery_app
# This script is intended to be run with the celery worker command:
# celery -A celery_worker.celery_app worker -l INFO -P eventlet (or gevent)
# Make sure this file is in Python's path, or adjust -A path.
# Typically, you run this from the `backend` directory.
# Example: celery -A app.core.celery_app worker -l INFO
# (The `include` in celery_app.py should make tasks discoverable)

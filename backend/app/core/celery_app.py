# backend/app/core/celery_app.py
from celery import Celery
from .config import settings

celery_app = Celery(
    "worker",  # Default name for the worker
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    # Path to the module where tasks are defined
    include=['app.tasks.transcription_tasks']
)
celery_app.conf.update(
    task_track_started=True,
    # Optional: Configure other Celery settings if needed
    # result_expires=3600,
)

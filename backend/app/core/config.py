# backend/app/core/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict
import os
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"
    REDIS_PUB_SUB_URL: str = "redis://localhost:6379/0"
    # Add other global configurations if needed
settings = Settings()
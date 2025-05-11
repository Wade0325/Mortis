# backend/app/api/settings_router.py (or a new app/schemas/settings_schemas.py)
from pydantic import BaseModel
from typing import List, Optional
from fastapi import APIRouter, HTTPException
from app.services import config_service


class SettingsResponse(BaseModel):
    google_api_key: Optional[str]
    google_selected_model: Optional[str]
    google_available_models: List[str]
    prompt: str


class SettingsUpdateRequest(BaseModel):
    google_api_key: Optional[str] = None
    google_selected_model: Optional[str] = None
    prompt: Optional[str] = None


class TestGoogleApiRequest(BaseModel):
    api_key: str
    model_name: str


class TestApiResponse(BaseModel):
    success: bool
    message: str


router = APIRouter(
    prefix="/api/settings",
    tags=["settings"],
)


@router.get("/", response_model=SettingsResponse)
async def get_settings_route():
    return config_service.get_all_settings()


@router.post("/", response_model=SettingsResponse)
async def update_settings_route(payload: SettingsUpdateRequest):
    try:
        updated_settings = config_service.update_settings(
            google_api_key=payload.google_api_key,
            google_selected_model=payload.google_selected_model,
            prompt=payload.prompt
        )
        return updated_settings
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to update settings: {str(e)}")


@router.post("/test_google_api", response_model=TestApiResponse)
async def test_google_api_route(payload: TestGoogleApiRequest):
    return config_service.test_google_api(api_key=payload.api_key, model_name=payload.model_name)

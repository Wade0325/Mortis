# backend/main.py
from app.core.app_setup import app # Import the FastAPI app instance
from app.api import settings_router, transcribe_router # Import your API routers
# Mount the routers
app.include_router(settings_router.router)
app.include_router(transcribe_router.router)
if __name__ == "__main__":
    import uvicorn
    # This is for direct execution, e.g. `python main.py`
    # For production, use `uvicorn main:app --host 0.0.0.0 --port 8000 --reload`
    uvicorn.run(app, host="0.0.0.0", port=8000)
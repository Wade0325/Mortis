# backend/app/core/app_setup.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
app = FastAPI(title="Mortis Transcription API", version="1.0.0")
# CORS (Cross-Origin Resource Sharing) Middleware
# TODO: Adjust origins for production
origins = [
    "http://localhost:3000",  # Default React dev port
    "http://127.0.0.1:3000",
    # Add other origins as needed
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"], # Allows all methods
    allow_headers=["*"], # Allows all headers
)
@app.get("/api/health")
async def health_check():
    return {"status": "ok"}
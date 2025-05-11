# backend/app/api/transcribe_router.py
from fastapi import APIRouter, HTTPException, UploadFile, File, Request, Form, Depends
from fastapi.responses import StreamingResponse, FileResponse
from app.tasks.transcription_tasks import run_transcription_pipeline
from app.services import config_service, format_converter_service # Assuming format_converter_service is created
from app.core.redis_client import get_async_redis_client # Use async for SSE
import uuid
import os
import tempfile
import shutil
import json
import asyncio
from typing import List, Dict, Any, Optional
from pydantic import BaseModel


router = APIRouter(
    prefix="/api/transcribe",
    tags=["transcription"],
)

# --- Helper for saving uploaded files temporarily ---
TEMP_UPLOAD_DIR = "temp_uploads" # Create this dir in backend root, or use tempfile.gettempdir()
os.makedirs(TEMP_UPLOAD_DIR, exist_ok=True)

async def save_upload_file_tmp(upload_file: UploadFile) -> str:
    try:
        # Use a unique prefix to help identify these files for cleanup
        fd, temp_path = tempfile.mkstemp(suffix=f"_{upload_file.filename}", prefix="fastapi_temp_upload_", dir=TEMP_UPLOAD_DIR)
        with os.fdopen(fd, "wb") as tmp:
            shutil.copyfileobj(upload_file.file, tmp)
        return temp_path
    finally:
        await upload_file.close() # Ensure file is closed

# --- Pydantic Models for this router ---
class TranscriptionStartResponse(BaseModel):
    task_id: str
    # celery_task_id: str # Optionally return Celery's internal task ID for backend debugging

class DownloadRequest(BaseModel):
    transcription_text_srt: str # Changed from transcription_text_lrc
    format: str # "lrc", "srt", "vtt", "txt"
    original_filename: Optional[str] = None # Made optional, filename can be generated if not provided


# --- API Endpoints ---
@router.post("/start", response_model=TranscriptionStartResponse)
async def start_transcription_route(files: List[UploadFile] = File(...)):
    if not files:
        raise HTTPException(status_code=400, detail="No audio files uploaded.")

    # For simplicity, this example processes the first file.
    # Modify if multiple file batch processing is intended for a single task.
    # Or, create one Celery task per file.
    upload_file = files[0]
    if not upload_file.filename:
        raise HTTPException(status_code=400, detail="Uploaded file has no name.")

    # Save the uploaded file to a temporary path that Celery task can access
    try:
        temp_file_path = await save_upload_file_tmp(upload_file)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save uploaded file: {str(e)}")


    task_id = str(uuid.uuid4().hex)
    current_settings = config_service.get_all_settings() # Get a snapshot of settings

    # Dispatch to Celery
    # Pass list of paths, even if it's one, for consistency with Celery task signature
    celery_task = run_transcription_pipeline.delay(
        task_id=task_id,
        file_paths=[temp_file_path],
        settings_snapshot=current_settings
    )

    return TranscriptionStartResponse(
        task_id=task_id,
        # celery_task_id=celery_task.id
    )


async def sse_event_generator(task_id: str, request: Request, redis_client: Any): # redis_client is aioredis.Redis
    async with redis_client.pubsub() as pubsub:
        await pubsub.subscribe(f"task_events:{task_id}")
        # First, send a confirmation that SSE is connected
        yield f"event: system_log\ndata: {json.dumps({'message': 'SSE connection established.'})}\n\n"
        try:
            while True:
                if await request.is_disconnected():
                    print(f"SSE client for task {task_id} disconnected.")
                    break # Exit loop if client disconnects

                # Listen for messages from Redis Pub/Sub
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0) # 1s timeout
                if message and message["type"] == "message":
                    data_str = message['data']
                    try:
                        event_payload = json.loads(data_str)
                        event_type = event_payload.get("type", "message") # Default event type for safety
                        yield f"event: {event_type}\ndata: {data_str}\n\n"

                        if event_type == "finish" or event_type == "error": # Stop streaming after these final events
                            print(f"SSE stream for task {task_id} ending due to '{event_type}' event.")
                            
                    except json.JSONDecodeError:
                        # If data is not valid JSON, send it as a raw message or log an error
                        yield f"event: raw_message\ndata: {json.dumps({'content': data_str})}\n\n"
                        print(f"Warning: Received non-JSON message on Redis for task {task_id}: {data_str}")

                await asyncio.sleep(0.01) # Small delay to prevent tight loop if no messages

        except asyncio.CancelledError:
            print(f"SSE generator for task {task_id} was cancelled (client likely disconnected).")
        finally:
            print(f"Cleaning up SSE generator for task {task_id}. Unsubscribing from Redis.")
            await pubsub.unsubscribe(f"task_events:{task_id}")


@router.get("/stream/{task_id}")
async def stream_task_events_route(
    task_id: str,
    request: Request, # FastAPI injects the request object
    redis_client = Depends(get_async_redis_client) # Dependency injection for async Redis
):
    return StreamingResponse(
        sse_event_generator(task_id, request, redis_client),
        media_type="text/event-stream",
        headers={ # Advise browsers not to cache SSE streams
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no", # For Nginx, if used as reverse proxy
            "Connection": "keep-alive",
        }
    )

# Create backend/app/services/format_converter_service.py
# (移植原 ui_handlers.py 中的 LRC -> SRT/VTT 轉換邏輯)
# --- backend/app/services/format_converter_service.py ---
# import re # (already imported in orchestrator, ensure it's here if used directly)
# def _parse_lrc_time(time_str): ... (from ui_handlers)
# def _format_timestamp_for_subtitle(seconds, format_type='srt'): ... (from ui_handlers, renamed)
# def convert_lrc_to_srt_content(lrc_text, duration=3): ...
# def convert_lrc_to_vtt_content(lrc_text, duration=3): ...
# (Make sure these functions are self-contained or import necessary helpers)
# For this step, I'll assume these functions are available in format_converter_service.py
# Example content for format_converter_service.py:

# Continuing backend/app/api/transcribe_router.py

@router.post("/download")
async def download_transcription_file_route(payload: DownloadRequest):
    if not payload.transcription_text_srt:
        raise HTTPException(status_code=400, detail="No transcription text (SRT) provided.")

    output_text = ""
    file_extension = ".txt" # Default extension
    media_type = "text/plain"

    if payload.format == "srt":
        output_text = payload.transcription_text_srt
        file_extension = ".srt"
        media_type = "application/x-subrip" # More specific media type for SRT
    elif payload.format == "lrc":
        output_text = format_converter_service.convert_srt_to_lrc(payload.transcription_text_srt)
        file_extension = ".lrc"
        media_type = "text/plain" # No standard MIME for LRC, text/plain is common
    elif payload.format == "vtt":
        output_text = format_converter_service.convert_srt_to_vtt(payload.transcription_text_srt)
        file_extension = ".vtt"
        media_type = "text/vtt"
    elif payload.format == "txt":
        output_text = format_converter_service.convert_srt_to_txt(payload.transcription_text_srt)
        file_extension = ".txt"
        media_type = "text/plain"
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported format: {payload.format}. Supported: srt, lrc, vtt, txt.")

    # Create filename
    base_name = os.path.splitext(payload.original_filename)[0] if payload.original_filename else "transcription"
    download_filename = f"{base_name}{file_extension}"

    # Use tempfile to serve the content, FastAPI's FileResponse handles cleanup for NamedTemporaryFile
    try:
        # Create a named temporary file to pass its path to FileResponse
        # Delete=False is important so FileResponse can read it before it's auto-deleted on close
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=file_extension, encoding="utf-8-sig") as tmp_file:
            tmp_file.write(output_text)
            temp_file_path = tmp_file.name

        return FileResponse(
            path=temp_file_path,
            filename=download_filename,
            media_type=media_type,
            background=tempfile.NamedTemporaryFile(tmp_file.name) # Ensures cleanup after response
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to prepare download file: {str(e)}")

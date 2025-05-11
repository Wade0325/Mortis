# backend/app/tasks/transcription_tasks.py
from app.core.celery_app import celery_app
from app.services.transcription_orchestrator import TranscriptionOrchestrator
from app.core.redis_client import get_sync_redis_client # Get synchronous client
import json
import os
from typing import Dict, Any, List

def _publish_event_to_redis(task_id: str, event_data: Dict[str, Any]):
    """Helper to publish events to Redis Pub/Sub for a given task_id."""
    redis_client = get_sync_redis_client()
    channel = f"task_events:{task_id}"
    try:
        redis_client.publish(channel, json.dumps(event_data))
    except Exception as e:
        # Log this error, perhaps to Celery logger or a file,
        # as it means frontend won't get this specific update.
        print(f"ERROR publishing event to Redis for task {task_id}: {e} (Event: {event_data.get('type')})")


@celery_app.task(bind=True, name="app.tasks.transcription_tasks.run_transcription_pipeline")
def run_transcription_pipeline(self, task_id: str, file_paths: List[str], settings_snapshot: Dict[str, Any]):
    """
    Celery task to run the audio transcription pipeline.
    `task_id` is our custom ID for SSE streaming.
    `self.request.id` is Celery's internal task ID.
    """
    # Define the log callback for the orchestrator
    def orchestrator_log_callback(event_type: str, data: Dict[str, Any]):
        _publish_event_to_redis(task_id, {"type": event_type, **data})

    orchestrator_log_callback("log", {"message": f"Celery Task {self.request.id} (SSE Task ID: {task_id}) started for files: {file_paths}."})

    # Ensure essential settings are present
    google_api_key = settings_snapshot.get("google_api_key")
    google_model = settings_snapshot.get("google_selected_model")
    prompt = settings_snapshot.get("prompt")

    if not all([google_api_key, google_model, prompt is not None]): # prompt can be empty string
        error_msg = "Celery Task: Missing required settings (API Key, Model, or Prompt)."
        orchestrator_log_callback("error", {"message": error_msg})
        _publish_event_to_redis(task_id, {"type": "finish"}) # Ensure finish event is sent
        # We can raise an exception here to mark Celery task as FAILED
        raise ValueError(error_msg)

    temp_audio_files_to_clean_by_celery = list(file_paths) # Keep track of files passed to task

    try:
        orchestrator = TranscriptionOrchestrator(
            api_key=google_api_key,
            model_name=google_model,
            prompt=prompt,
            log_callback=orchestrator_log_callback
        )

        # Assuming for now the orchestrator handles one primary audio file.
        # If multiple files are passed, this logic needs adjustment or orchestrator needs to loop.
        if not file_paths:
            orchestrator_log_callback("error", {"message": "No file paths provided to transcription task."})
            _publish_event_to_redis(task_id, {"type": "finish"})
            raise ValueError("No file paths provided.")

        primary_audio_path = file_paths[0] # Take the first file
        original_filename = os.path.basename(primary_audio_path)

        final_lrc_content = orchestrator.process_audio(primary_audio_path)

        if final_lrc_content is not None:
            _publish_event_to_redis(task_id, {
                "type": "result",
                "data": {
                    "transcription_text_lrc": final_lrc_content,
                    "original_filename": original_filename
                }
            })
            # Celery task result (can be retrieved via Celery backend if needed)
            return {"status": "SUCCESS", "task_id": task_id, "lrc_length": len(final_lrc_content)}
        else:
            orchestrator_log_callback("error", {"message": "Transcription pipeline did not return content."})
            # Celery task result for failure
            return {"status": "FAILURE", "task_id": task_id, "reason": "No content from orchestrator"}

    except Exception as e:
        # import traceback
        # error_trace = traceback.format_exc()
        error_message = f"Celery Task {self.request.id} (SSE Task ID: {task_id}) failed: {str(e)}"
        orchestrator_log_callback("error", {"message": error_message})
        # orchestrator_log_callback("log", {"message": f"Traceback: {error_trace}"}) # Be careful with logging full tracebacks to client
        # Re-raise the exception so Celery marks the task as FAILED
        # This allows for retry mechanisms if configured, and proper state tracking in Celery backend.
        _publish_event_to_redis(task_id, {"type": "finish"}) # Ensure finish event on error too
        raise
    finally:
        # Always publish a "finish" event for SSE client
        _publish_event_to_redis(task_id, {"type": "finish"})
        orchestrator_log_callback("log", {"message": f"Celery Task {self.request.id} (SSE Task ID: {task_id}) processing finished."})

        # Cleanup temporary files that were created *before* calling this Celery task
        # (e.g., by FastAPI when receiving the upload).
        # The orchestrator cleans its own temp chunk files.
        for fp in temp_audio_files_to_clean_by_celery:
            # Add a more specific check, e.g., if files are in a known temp upload dir
            if os.path.exists(fp) and "fastapi_temp_upload_" in os.path.basename(fp):
                try:
                    os.remove(fp)
                    orchestrator_log_callback("log", {"message": f"Celery task cleaned up FastAPI temp file: {fp}"})
                except OSError as e_clean:
                    orchestrator_log_callback("warn", {"message": f"Celery task failed to clean up FastAPI temp file {fp}: {e_clean}"})
# backend/app/transcription_providers/gemini.py
import google.generativeai as genai
import os
import time
from .base import Transcriber, LogCallbackType
from typing import Optional
import sys

class GeminiTranscriber(Transcriber):
    def __init__(self, api_key: str, model_name: str, log_callback: LogCallbackType = None):
        super().__init__(api_key, model_name, log_callback)
        self.log_callback = log_callback # Explicitly set it on the instance for clarity/safety
        self.model: Optional[genai.GenerativeModel] = None
        try:
            genai.configure(api_key=self.api_key)
            self.model = genai.GenerativeModel(self.model_name) # Uses model_name directly
            self._log("log", {"message": f"Gemini API 配置成功，使用模型: {self.model_name}"})
            self.uploaded_files_info = {} # Store uploaded file info {gemini_file_name: genai.File}
        except Exception as e:
            self._log("error", {"message": f"Gemini 初始化失敗: {e}"})
            raise # Re-raise exception to be caught by orchestrator

    def _log(self, event_type: str, data: dict):
        # Ensure data is a dict, as expected by the callback
        if not isinstance(data, dict):
            print(f"[GEMINI_TRANSCRIBER_LOG_WARNING] _log called with non-dict data: {data}")
            log_data = {"message": str(data)}
        else:
            log_data = data

        # If it's an error, also print directly to Celery worker logs for easier debugging
        if event_type == "error":
            print(f"[GEMINI_TRANSCRIBER_ERROR] {log_data}")

        if self.log_callback:
            try:
                self.log_callback(event_type, log_data)
            except Exception as e_cb:
                # Log callback failure to stderr (Celery worker log)
                print(f"[GEMINI_TRANSCRIBER_LOG_CALLBACK_ERROR] Failed to send log via callback: {e_cb} | Original log: {event_type} - {log_data}", file=sys.stderr)

    def upload_file(self, file_path: str) -> Optional[genai.types.File]:
        filename = os.path.basename(file_path)
        print(f"upload_file: {filename}")
        self._log("log", {"message": f"開始上傳檔案到 Gemini: {filename}..."})
        try:
            # display_name helps identify the file in the Gemini console
            uploaded_file = genai.upload_file(path=file_path, display_name=filename)
            print(f"uploaded_file: {uploaded_file}")
            self._log("log", {"message": f"Gemini 檔案 '{filename}' 上傳中，等待處理... (ID: {uploaded_file.name})"})
            # Polling for ACTIVE state
            polling_interval = 5 # seconds
            max_wait_time = 300 # 5 minutes
            elapsed_time = 0
            while uploaded_file.state.name == "PROCESSING" and elapsed_time < max_wait_time:
                time.sleep(polling_interval)
                elapsed_time += polling_interval
                uploaded_file = genai.get_file(name=uploaded_file.name)
                print(f"uploaded_file: {uploaded_file}")
                self._log("log", {"message": f"Gemini 檔案 '{filename}' 狀態: {uploaded_file.state.name} (已等待 {elapsed_time}s)"})
            if uploaded_file.state.name != "ACTIVE":
                self._log("error", {
                    "message": f"Gemini 檔案 '{filename}' (ID: {uploaded_file.name}) 處理失敗或狀態非 ACTIVE: {uploaded_file.state.name}",
                    "file_id": uploaded_file.name,
                    "state": uploaded_file.state.name
                })
                # Consider deleting the file if it's in a failed state and won't be used
                try:
                    self._delete_service_file(uploaded_file.name)
                    self._log("log", {"message": f"已刪除 Gemini 中處理失敗的檔案: {uploaded_file.name}"})
                except Exception as del_e:
                    self._log("warn", {"message": f"嘗試刪除 Gemini 中處理失敗的檔案 {uploaded_file.name} 時發生錯誤: {del_e}"})
                return None # Indicate failure
            self._log("log", {"message": f"Gemini 檔案 '{filename}' (ID: {uploaded_file.name}) 處理完成，狀態: ACTIVE"})
            self.uploaded_files_info[uploaded_file.name] = uploaded_file # Store by Gemini file name (ID)
            return uploaded_file
        except Exception as e:
            self._log("error", {"message": f"上傳或處理檔案 '{filename}' 至 Gemini 失敗: {e}"})
            return None # Indicate failure
    def transcribe_file(self, uploaded_file_obj: genai.types.File, prompt: str) -> Optional[str]:
        if not self.model:
            self._log("error", {"message": "Gemini 模型未初始化，無法轉錄。"})
            return None
        original_filename = uploaded_file_obj.display_name or uploaded_file_obj.name
        self._log("log", {"message": f"請求 Gemini 轉錄檔案 '{original_filename}' (ID: {uploaded_file_obj.name})..."})
        try:
            # Constructing the content for Gemini API
            # The prompt should guide the model on how to process the audio.
            # The FileDataPart object contains the URI of the uploaded file.
            # The request can be a list of parts: [prompt_string, file_data_part]
            response = self.model.generate_content(
                [prompt, uploaded_file_obj],
                request_options={"timeout": 600} # 10 minutes timeout
            )
            if hasattr(response, 'text') and response.text:
                self._log("log", {"message": f"檔案 '{original_filename}' 轉錄成功。"})
                return response.text
            else:
                # Check for safety ratings or other reasons for no text
                if response.prompt_feedback and response.prompt_feedback.block_reason:
                     reason = response.prompt_feedback.block_reason.name
                     self._log("error", {"message": f"轉錄失敗：Gemini 因 '{reason}' 而阻擋了回應。"})
                else:
                    self._log("error", {"message": "轉錄失敗：Gemini 模型未返回預期文字，也無明確阻擋原因。"})
                return None
        except Exception as e:
            self._log("error", {"message": f"請求 Gemini 轉錄檔案 '{original_filename}' 時發生錯誤: {e}"})
            return None
    def _delete_service_file(self, file_id: str) -> None: # file_id is uploaded_file.name
        self._log("log", {"message": f"嘗試刪除 Gemini 檔案 (ID: {file_id})..."})
        try:
            genai.delete_file(name=file_id)
            self._log("log", {"message": f"Gemini 檔案 (ID: {file_id}) 已成功刪除。"})
        except Exception as e:
            # Log the error but don't necessarily re-raise if part of a larger cleanup
            self._log("error", {"message": f"刪除 Gemini 檔案 (ID: {file_id}) 時失敗: {e}"})
            # Re-raise if this method is called directly and failure is critical
            # raise
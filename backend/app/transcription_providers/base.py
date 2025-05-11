# backend/app/transcription_providers/base.py
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, Optional
LogCallbackType = Optional[Callable[[str, Dict[str, Any]], None]]
class Transcriber(ABC):
    def __init__(self, api_key: str, model_name: str, log_callback: LogCallbackType = None):
        self.api_key = api_key
        self.model_name = model_name
        self.uploaded_files_info: Dict[str, Any] = {}
        self._log_callback = log_callback
    def _log(self, event_type: str, data: Dict[str, Any]):
        if self._log_callback:
            self._log_callback(event_type, data)
        else: # Fallback to print if no callback is provided
            print(f"[{event_type.upper()}] {data.get('message', data)}")
    @abstractmethod
    def upload_file(self, file_path: str) -> Any:
        raise NotImplementedError
    @abstractmethod
    def transcribe_file(self, uploaded_file_obj: Any, prompt: str) -> Optional[str]:
        raise NotImplementedError
    @abstractmethod
    def _delete_service_file(self, file_id: str) -> None:
        raise NotImplementedError
    def cleanup_uploaded_files(self) -> int:
        if not self.uploaded_files_info:
            return 0
        total_to_clean = len(self.uploaded_files_info)
        self._log("log", {"message": f"開始清理 {total_to_clean} 個已上傳的服務端檔案..."})
        cleaned_count = 0
        # ... (rest of the cleanup logic from original, using self._log) ...
        file_ids_to_clean = list(self.uploaded_files_info.keys())
        for file_id in file_ids_to_clean:
            try:
                self._delete_service_file(file_id)
                del self.uploaded_files_info[file_id]
                cleaned_count += 1
            except Exception as delete_err:
                self._log("error", {"message": f"清理檔案 {file_id} 失敗: {delete_err}", "file_id": file_id})
        self._log("log", {"message": f"服務端檔案清理完畢 (成功刪除 {cleaned_count}/{total_to_clean} 個)。"})
        return cleaned_count
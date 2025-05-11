# backend/app/services/transcription_orchestrator.py
import os
import tempfile
import torch
import torchaudio
import re
import math
from typing import List, Dict, Optional, Callable, Any
from app.transcription_providers.gemini import GeminiTranscriber
from app.transcription_providers.base import Transcriber as BaseTranscriber # Alias to avoid confusion

# Log callback type definition (event_type: str, data: dict)
OrchestratorLogCallbackType = Callable[[str, Dict[str, Any]], None]

# Silero VAD setup (移植自 vad_processor.py)
# 確保模型只載入一次
VAD_MODEL = None
VAD_UTILS = None
TARGET_SAMPLE_RATE = 16000

def _load_vad_model(log_fn: OrchestratorLogCallbackType):
    global VAD_MODEL, VAD_UTILS
    if VAD_MODEL is not None:
        return True
    try:
        # Try newer silero-vad pip package interface first
        from silero_vad.utils_vad import get_speech_timestamps, read_audio, load_silero_vad
        VAD_MODEL = load_silero_vad()
        VAD_UTILS = {
            "get_speech_timestamps": get_speech_timestamps,
            "read_audio": read_audio
        }
        log_fn("log", {"message": "從 silero-vad pip 套件 (>=4.0) 載入 VAD 模型。"})
        return True
    except ImportError:
        log_fn("log", {"message": "silero-vad pip >= 4.0 未找到，嘗試 torch.hub..."})
        try:
            torch_hub_model, torch_hub_utils = torch.hub.load(
                repo_or_dir='snakers4/silero-vad',
                model='silero_vad',
                force_reload=False, # Use cache
                onnx=False, # Ensure PyTorch model
                trust_repo=True # Required for recent PyTorch versions
            )
            VAD_MODEL = torch_hub_model
            VAD_UTILS = {
                "get_speech_timestamps": torch_hub_utils[0], # get_speech_timestamps
                "read_audio": torch_hub_utils[2]            # read_audio
            }
            log_fn("log", {"message": "從 torch.hub 載入 Silero VAD 模型。"})
            return True
        except Exception as e_hub:
            log_fn("error", {"message": f"從 torch.hub 載入 Silero VAD 模型失敗: {e_hub}"})
    except Exception as e_load:
        log_fn("error", {"message": f"載入 Silero VAD 模型時發生非預期錯誤: {e_load}"})

    VAD_MODEL = None
    VAD_UTILS = None
    return False

# LRC Helper functions (移植自 vad_processor.py)
def _parse_lrc_time_to_seconds(time_str: str) -> Optional[float]:
    match = re.match(r'\[(\d{2}):(\d{2})\.(\d{2,3})\]', time_str)
    if match:
        m, s, cs_or_ms = map(int, match.groups())
        millis = cs_or_ms * 10 if len(match.group(3)) == 2 else cs_or_ms
        return m * 60 + s + millis / 1000.0
    return None

def _format_seconds_to_lrc(seconds: float) -> str:
    if seconds < 0: seconds = 0
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    centis = int(round((seconds - int(seconds)) * 100))
    if centis >= 100: # Handle rounding that pushes centis to 100
        centis = 0
        secs +=1
        if secs >= 60:
            secs = 0
            minutes += 1
    return f"[{minutes:02d}:{secs:02d}.{centis:02d}]"

def _adjust_lrc_timestamps(transcription_text: Optional[str], offset_seconds: float) -> str:
    if not isinstance(transcription_text, str) or offset_seconds == 0:
        return transcription_text or ""
    adjusted_lines = []
    for line in transcription_text.strip().split('\n'):
        match = re.match(r'(\[\d{2}:\d{2}\.\d{2,3}\])(.*)', line)
        if match:
            original_ts_str, text_content = match.groups()
            relative_time_sec = _parse_lrc_time_to_seconds(original_ts_str)
            if relative_time_sec is not None:
                absolute_time_sec = relative_time_sec + offset_seconds
                new_ts_str = _format_seconds_to_lrc(absolute_time_sec)
                adjusted_lines.append(new_ts_str + text_content)
            else:
                adjusted_lines.append(line) # Keep line if timestamp parsing fails
        else:
            adjusted_lines.append(line) # Keep line if no timestamp
    return "\n".join(adjusted_lines)


class TranscriptionOrchestrator:
    def __init__(self, api_key: str, model_name: str, prompt: str, log_callback: OrchestratorLogCallbackType):
        self.api_key = api_key
        self.model_name = model_name
        self.prompt = prompt
        self._log_callback = log_callback
        self.transcriber: Optional[BaseTranscriber] = None # Use the alias

        if not _load_vad_model(self._log_callback):
            raise RuntimeError("VAD 模型無法載入，無法進行轉錄編排。")
        # Initialize the specific transcriber (Gemini in this case)
        try:
            self.transcriber = GeminiTranscriber(
                api_key=self.api_key,
                model_name=self.model_name,
                log_callback=self._log_callback # Pass down the log callback
            )
        except Exception as e:
            self._log_callback("error", {"message": f"初始化 GeminiTranscriber 失敗: {e}"})
            raise # Re-raise to be caught by Celery task


    def _save_chunk_to_temp_file(self, audio_chunk_tensor: torch.Tensor, sample_rate: int) -> Optional[str]:
        """Saves audio chunk to a temporary WAV file and returns its path."""
        temp_file = None
        try:
            # Ensure tensor is 2D (channels, samples) and on CPU
            if audio_chunk_tensor.ndim == 1:
                audio_chunk_tensor = audio_chunk_tensor.unsqueeze(0)
            audio_chunk_tensor = audio_chunk_tensor.cpu()

            # Create a temporary file
            fd, temp_filepath = tempfile.mkstemp(suffix=".wav", prefix="audio_chunk_")
            os.close(fd) # Close the file descriptor, torchaudio.save will open it

            torchaudio.save(temp_filepath, audio_chunk_tensor, sample_rate)
            self._log_callback("log", {"message": f"音訊片段已儲存至暫存檔: {temp_filepath}"})
            return temp_filepath
        except Exception as e:
            self._log_callback("error", {"message": f"儲存音訊片段至暫存檔失敗: {e}"})
            if temp_filepath and os.path.exists(temp_filepath):
                os.remove(temp_filepath)
            return None


    def process_audio(
        self,
        input_audio_path: str,
        segment_duration_minutes: float = 6.0, # 原 vad_processor 參數
        min_reliable_silence_ms: int = 2000,
        vad_internal_min_silence_ms: int = 1000,
        speech_pad_ms: int = 50
    ) -> Optional[str]:
        if VAD_MODEL is None or VAD_UTILS is None or self.transcriber is None:
            self._log_callback("error", {"message": "VAD 或轉錄器未初始化，無法處理。"})
            return None
        if not os.path.exists(input_audio_path):
            self._log_callback("error", {"message": f"找不到輸入音檔: {input_audio_path}"})
            return None

        self._log_callback("progress", {"percentage": 5, "step_message": "載入音訊並進行 VAD..."})

        temp_chunk_files_to_clean = []
        all_transcriptions_lrc: List[str] = []

        try:
            # --- 1. 載入音訊和 VAD 偵測 ---
            read_audio_fn = VAD_UTILS["read_audio"]
            get_speech_timestamps_fn = VAD_UTILS["get_speech_timestamps"]

            wav_tensor = read_audio_fn(input_audio_path, sampling_rate=TARGET_SAMPLE_RATE)
            duration_seconds = wav_tensor.shape[-1] / TARGET_SAMPLE_RATE
            self._log_callback("log", {"message": f"已載入音檔: {input_audio_path}, 時長: {duration_seconds:.2f}s"})

            speech_timestamps: List[Dict[str, int]] = get_speech_timestamps_fn(
                wav_tensor, VAD_MODEL, sampling_rate=TARGET_SAMPLE_RATE,
                min_speech_duration_ms=250,
                min_silence_duration_ms=vad_internal_min_silence_ms,
                speech_pad_ms=speech_pad_ms
            )
            # Convert sample-based timestamps to seconds
            speech_timestamps_sec: List[Dict[str, float]] = []
            if speech_timestamps and 'start' in speech_timestamps[0] and isinstance(speech_timestamps[0]['start'], int):
                 speech_timestamps_sec = [{'start': ts['start'] / TARGET_SAMPLE_RATE, 'end': ts['end'] / TARGET_SAMPLE_RATE} for ts in speech_timestamps]
            elif speech_timestamps and 'start' in speech_timestamps[0]: # If already in seconds (less likely from silero directly)
                 speech_timestamps_sec = speech_timestamps
            else: # No speech detected by VAD
                 speech_timestamps_sec = []


            self._log_callback("log", {"message": f"VAD 找到 {len(speech_timestamps_sec)} 個（可能重疊的）語音片段。"})
            if not speech_timestamps_sec:
                self._log_callback("warn", {"message": "音檔中未偵測到語音。將嘗試轉錄整個檔案作為單一片段。"})
                # Treat the whole file as one speech segment
                speech_timestamps_sec = [{'start': 0.0, 'end': duration_seconds}]


            # --- 2. 計算可靠的靜音間隔 (用於切割點) ---
            min_reliable_silence_sec = min_reliable_silence_ms / 1000.0
            reliable_silence_gaps: List[Dict[str, float]] = [] # {'start', 'end', 'mid'}
            last_speech_end = 0.0
            for ts_idx, segment in enumerate(speech_timestamps_sec):
                gap_start = last_speech_end
                gap_end = segment['start']
                if gap_end > gap_start: # There is a silence
                    silence_duration = gap_end - gap_start
                    if silence_duration >= min_reliable_silence_sec:
                        reliable_silence_gaps.append({'start': gap_start, 'end': gap_end, 'mid': (gap_start + gap_end) / 2})
                last_speech_end = max(last_speech_end, segment['end'])
            # Check for silence after the last speech segment until file end
            if duration_seconds > last_speech_end:
                final_silence_duration = duration_seconds - last_speech_end
                if final_silence_duration >= min_reliable_silence_sec:
                    reliable_silence_gaps.append({'start': last_speech_end, 'end': duration_seconds, 'mid': (last_speech_end + duration_seconds) / 2})
            self._log_callback("log", {"message": f"找到 {len(reliable_silence_gaps)} 個可靠的靜音間隔 (>= {min_reliable_silence_sec:.2f}s)。"})


            # --- 3. 迭代處理片段並轉錄 ---
            current_segment_start_time = 0.0
            target_segment_duration_seconds = segment_duration_minutes * 60.0
            chunk_index = 0
            total_chunks_estimate = max(1, math.ceil(duration_seconds / target_segment_duration_seconds)) # Rough estimate for progress

            while current_segment_start_time < duration_seconds:
                chunk_index += 1
                self._log_callback("progress", {
                    "percentage": int(10 + 80 * (current_segment_start_time / duration_seconds)), # 10% to 90% for this loop
                    "step_message": f"處理音訊片段 {chunk_index}/{total_chunks_estimate}..."
                })

                # --- 確定此片段的結束時間 (切割點) ---
                # Target end time for this segment based on desired duration
                ideal_segment_end_time = current_segment_start_time + target_segment_duration_seconds
                actual_segment_end_time = duration_seconds # Default to end of file

                if ideal_segment_end_time < duration_seconds: # If not the last potential segment
                    # Find the first reliable silence gap *after* the ideal_segment_end_time
                    # and use its middle as the split point.
                    found_split_point = False
                    for gap in reliable_silence_gaps:
                        # Gap middle should be after ideal end, and also significantly after current start
                        if gap['mid'] >= ideal_segment_end_time and gap['mid'] > (current_segment_start_time + 1.0): # Ensure meaningful segment
                            actual_segment_end_time = gap['mid']
                            found_split_point = True
                            self._log_callback("log", {"message": f"片段 {chunk_index}: 目標切割時間 {ideal_segment_end_time:.2f}s, 找到靜音中點 {actual_segment_end_time:.2f}s 作為切割點。"})
                            break
                    if not found_split_point:
                        # If no suitable silence found after ideal time, extend to end of file for this chunk,
                        # or if speech_timestamps_sec is empty (whole file as one segment)
                        actual_segment_end_time = duration_seconds
                        self._log_callback("log", {"message": f"片段 {chunk_index}: 未找到合適靜音切割點，將處理至檔案末尾 ({actual_segment_end_time:.2f}s) 或下個強制切割點。"})
                else: # This is the last segment
                     actual_segment_end_time = duration_seconds
                     self._log_callback("log", {"message": f"片段 {chunk_index}: 處理最後的音訊片段至檔案末尾 ({actual_segment_end_time:.2f}s)。"})


                # --- 提取音訊片段張量 ---
                start_sample = int(current_segment_start_time * TARGET_SAMPLE_RATE)
                end_sample = int(actual_segment_end_time * TARGET_SAMPLE_RATE)
                # Ensure end_sample does not exceed tensor length
                end_sample = min(end_sample, wav_tensor.shape[-1])

                if start_sample >= end_sample : # Should not happen if logic is correct
                    self._log_callback("warn", {"message": f"片段 {chunk_index}: 起始取樣點 ({start_sample}) >= 結束取樣點 ({end_sample})，跳過此空片段。"})
                    current_segment_start_time = actual_segment_end_time
                    if current_segment_start_time >= duration_seconds and start_sample == end_sample : # If at the very end and no more data
                        break
                    continue


                audio_chunk_tensor = wav_tensor[:, start_sample:end_sample]
                self._log_callback("log", {"message": f"片段 {chunk_index}: 時間 [{current_segment_start_time:.2f}s - {actual_segment_end_time:.2f}s], 取樣點 [{start_sample} - {end_sample}]"})

                # --- 儲存片段到暫存檔 ---
                temp_chunk_path = self._save_chunk_to_temp_file(audio_chunk_tensor, TARGET_SAMPLE_RATE)
                if not temp_chunk_path:
                    # Error already logged by _save_chunk_to_temp_file
                    # Decide if we should stop or try to continue
                    self._log_callback("error", {"message": f"片段 {chunk_index} 儲存失敗，跳過此片段的轉錄。"})
                    current_segment_start_time = actual_segment_end_time
                    continue # Move to next segment
                temp_chunk_files_to_clean.append(temp_chunk_path)


                # --- 上傳並轉錄片段 ---
                self._log_callback("log", {"message": f"片段 {chunk_index}: 開始上傳和轉錄 {os.path.basename(temp_chunk_path)}..."})
                uploaded_file_obj = self.transcriber.upload_file(temp_chunk_path)
                if uploaded_file_obj:
                    transcription_result_for_chunk = self.transcriber.transcribe_file(
                        uploaded_file_obj, self.prompt
                    )
                    if transcription_result_for_chunk:
                        # 調整此片段轉錄結果的時間戳 (相對於整個音訊的 current_segment_start_time)
                        adjusted_chunk_lrc = _adjust_lrc_timestamps(
                            transcription_result_for_chunk, current_segment_start_time
                        )
                        all_transcriptions_lrc.append(adjusted_chunk_lrc)
                        self._log_callback("log", {"message": f"片段 {chunk_index} 轉錄並調整時間戳成功。"})
                    else:
                        self._log_callback("warn", {"message": f"片段 {chunk_index} 轉錄失敗或無內容。"})
                else:
                    self._log_callback("warn", {"message": f"片段 {chunk_index} 上傳失敗。"})


                # 更新下一個片段的開始時間
                current_segment_start_time = actual_segment_end_time

            # --- 4. 合併所有轉錄結果 ---
            final_transcription = "\n".join(filter(None, all_transcriptions_lrc)).strip()
            if not final_transcription:
                self._log_callback("warn", {"message": "所有片段處理完畢，但未產生任何轉錄內容。"})
                # return None # Or return empty string depending on desired behavior

            self._log_callback("progress", {"percentage": 95, "step_message": "轉錄完成，正在整理結果..."})
            return final_transcription

        except Exception as e:
            self._log_callback("error", {"message": f"音訊處理流程中發生嚴重錯誤: {e}"})
            # import traceback
            # self._log_callback("error", {"message": f"Traceback: {traceback.format_exc()}"})
            return None # Indicate overall failure
        finally:
            # --- 5. 清理 ---
            self._log_callback("log", {"message": "開始清理暫存音訊片段檔案..."})
            cleaned_temp_count = 0
            for f_path in temp_chunk_files_to_clean:
                try:
                    if os.path.exists(f_path):
                        os.remove(f_path)
                        cleaned_temp_count +=1
                except Exception as e_clean:
                    self._log_callback("warn", {"message": f"刪除暫存檔 {f_path} 失敗: {e_clean}"})
            self._log_callback("log", {"message": f"已清理 {cleaned_temp_count}/{len(temp_chunk_files_to_clean)} 個暫存片段檔案。"})

            # 清理 Transcriber 內部追蹤的服務端檔案 (如 Gemini File API 上的檔案)
            if self.transcriber:
                self.transcriber.cleanup_uploaded_files()
            self._log_callback("progress", {"percentage": 100, "step_message": "所有處理完成。"})

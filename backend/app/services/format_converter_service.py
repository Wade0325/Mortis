# backend/app/services/format_converter_service.py
import re
from typing import Optional

def _parse_lrc_time_for_subtitle(time_str: str) -> Optional[float]:
    """將 [mm:ss.xx] 或 [mm:ss.xxx] 格式轉換為總秒數"""
    match = re.match(r'\[(\d{2}):(\d{2})\.(\d{2,3})\]', time_str)
    if match:
        m, s, cs_or_ms = map(int, match.groups())
        millis = cs_or_ms * 10 if len(match.group(3)) == 2 else cs_or_ms
        return m * 60 + s + millis / 1000.0
    return None

def _format_timestamp_for_subtitle(seconds: float, format_type: str = 'srt') -> str:
    """將總秒數格式化為 HH:MM:SS,sss (srt) 或 HH:MM:SS.sss (vtt)"""
    if seconds < 0: seconds = 0
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millisecs = int(round((seconds - int(seconds)) * 1000)) # round to handle precision
    # Ensure millisecs doesn't exceed 999 due to rounding
    if millisecs > 999 : millisecs = 999

    sep = ',' if format_type == 'srt' else '.'
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{sep}{millisecs:03d}"

def convert_lrc_to_srt_content(lrc_text: str, line_duration: int = 3) -> str:
    """將 LRC 文本轉換為 SRT 格式 (使用固定時長)"""
    lines = lrc_text.strip().split('\n')
    srt_output = []
    counter = 1
    for line in lines:
        time_match = re.match(r'(\[\d{2}:\d{2}\.\d{2,3}\])(.*)', line)
        if time_match:
            time_tag, text = time_match.groups()
            start_time_sec = _parse_lrc_time_for_subtitle(time_tag)
            if start_time_sec is not None:
                end_time_sec = start_time_sec + line_duration
                start_str = _format_timestamp_for_subtitle(start_time_sec, 'srt')
                end_str = _format_timestamp_for_subtitle(end_time_sec, 'srt')
                srt_output.append(str(counter))
                srt_output.append(f"{start_str} --> {end_str}")
                srt_output.append(text.strip())
                srt_output.append("")  # 空行分隔
                counter += 1
    return "\n".join(srt_output)

def convert_lrc_to_vtt_content(lrc_text: str, line_duration: int = 3) -> str:
    """將 LRC 文本轉換為 VTT 格式 (使用固定時長)"""
    lines = lrc_text.strip().split('\n')
    vtt_output = ["WEBVTT", ""]
    for line in lines:
        time_match = re.match(r'(\[\d{2}:\d{2}\.\d{2,3}\])(.*)', line)
        if time_match:
            time_tag, text = time_match.groups()
            start_time_sec = _parse_lrc_time_for_subtitle(time_tag)
            if start_time_sec is not None:
                end_time_sec = start_time_sec + line_duration
                start_str = _format_timestamp_for_subtitle(start_time_sec, 'vtt')
                end_str = _format_timestamp_for_subtitle(end_time_sec, 'vtt')
                # VTT doesn't use sequence numbers in the same way as SRT for simple cases
                vtt_output.append(f"{start_str} --> {end_str}")
                vtt_output.append(text.strip())
                vtt_output.append("")  # 空行分隔
    return "\n".join(vtt_output)

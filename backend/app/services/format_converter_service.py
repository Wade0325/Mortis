# backend/app/services/format_converter_service.py
import re
from typing import Optional, List, Tuple

# --- SRT/VTT Time Parsing and Formatting --- #

def _parse_srt_timestamp_to_seconds(time_str: str) -> Optional[float]:
    """Converts HH:MM:SS,mmm string to total seconds."""
    match = re.match(r'(\d{2}):(\d{2}):(\d{2}),(\d{3})', time_str)
    if match:
        h, m, s, ms = map(int, match.groups())
        return h * 3600 + m * 60 + s + ms / 1000.0
    return None

def _format_seconds_to_srt_vtt_timestamp(seconds: float, format_type: str = 'srt') -> str:
    """Formats total seconds to HH:MM:SS,sss (srt) or HH:MM:SS.sss (vtt)."""
    if seconds < 0: seconds = 0
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int(round((seconds - int(seconds)) * 1000))
    
    if millis >= 1000: # Handle rounding that pushes millis to 1000 or more
        millis = 0
        secs += 1
        if secs >= 60:
            secs = 0
            minutes += 1
            if minutes >= 60:
                minutes = 0
                hours += 1
    
    separator = ',' if format_type == 'srt' else '.'
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{separator}{millis:03d}"

def _format_seconds_to_lrc_timestamp(seconds: float) -> str:
    """Formats total seconds to [mm:ss.xx] for LRC."""
    if seconds < 0: seconds = 0
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    # For LRC, it's common to use centiseconds (2 digits)
    centis = int(round((seconds - int(seconds)) * 100))
    if centis >= 100: # Handle rounding for centiseconds
        centis = 0
        secs += 1
        if secs >= 60:
            secs = 0
            minutes += 1
    return f"[{minutes:02d}:{secs:02d}.{centis:02d}]"

# --- SRT Parsing Helper --- #
class SRTEntry(Tuple[int, float, float, List[str]]):
    index: int
    start_time_sec: float
    end_time_sec: float
    text_lines: List[str]

def _parse_srt_content(srt_text: str) -> List[SRTEntry]:
    """Parses an SRT string into a list of SRTEntry objects."""
    if not srt_text.strip():
        return []
    
    entries: List[SRTEntry] = []
    srt_blocks_raw = re.split(r'\\n\\s*\\n', srt_text.strip())
    srt_blocks = [block.strip() for block in srt_blocks_raw if block.strip()]

    for block_str in srt_blocks:
        lines = block_str.split('\\n')
        if len(lines) < 3: # Index, Time, Text (at least one line)
            continue
        
        try:
            index = int(lines[0])
        except ValueError:
            continue # Invalid index
            
        time_line_match = re.match(r'(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})', lines[1])
        if not time_line_match:
            continue # Invalid time line
            
        start_time_str, end_time_str = time_line_match.groups()
        start_time_sec = _parse_srt_timestamp_to_seconds(start_time_str)
        end_time_sec = _parse_srt_timestamp_to_seconds(end_time_str)
        
        if start_time_sec is None or end_time_sec is None or end_time_sec < start_time_sec:
            continue # Invalid times
            
        text_lines = lines[2:]
        if not any(line.strip() for line in text_lines): # Skip if text is empty or only whitespace
            continue

        entries.append(SRTEntry((index, start_time_sec, end_time_sec, text_lines)))
    return entries

# --- Conversion Functions --- #

def convert_srt_to_lrc(srt_text: str) -> str:
    """Converts SRT formatted text to LRC format."""
    srt_entries = _parse_srt_content(srt_text)
    if not srt_entries:
        return ""
    
    lrc_lines = []
    for entry in srt_entries:
        # LRC typically uses the start time of the line.
        # And text is usually single line in LRC from multi-line SRT, join with space.
        lrc_time_tag = _format_seconds_to_lrc_timestamp(entry[1]) # entry[1] is start_time_sec
        text_content = " ".join(line.strip() for line in entry[3]) # entry[3] is text_lines
        lrc_lines.append(f"{lrc_time_tag}{text_content}")
        
    return "\n".join(lrc_lines)

def convert_srt_to_vtt(srt_text: str) -> str:
    """Converts SRT formatted text to VTT format."""
    srt_entries = _parse_srt_content(srt_text)
    
    vtt_output = ["WEBVTT", ""]
    if not srt_entries:
        return "WEBVTT\n"

    for entry in srt_entries:
        start_time_vtt = _format_seconds_to_srt_vtt_timestamp(entry[1], 'vtt') # entry[1] is start_time_sec
        end_time_vtt = _format_seconds_to_srt_vtt_timestamp(entry[2], 'vtt')   # entry[2] is end_time_sec
        
        vtt_output.append(f"{start_time_vtt} --> {end_time_vtt}")
        for text_line in entry[3]: # entry[3] is text_lines
            vtt_output.append(text_line.strip())
        vtt_output.append("") # Blank line after each cue
        
    return "\n".join(vtt_output)

# --- Functions to keep if direct TXT output from SRT is desired --- #
def convert_srt_to_txt(srt_text: str) -> str:
    """Converts SRT to plain text, stripping timestamps and indices."""
    srt_entries = _parse_srt_content(srt_text)
    if not srt_entries:
        return ""
    
    text_only_lines = []
    for entry in srt_entries:
        for text_line in entry[3]: # entry[3] is text_lines
            text_only_lines.append(text_line.strip())
            
    return "\n".join(text_only_lines)


# Old LRC parsing functions are removed as they are no longer primary.
# If needed for some other utility, they can be added back or placed elsewhere.

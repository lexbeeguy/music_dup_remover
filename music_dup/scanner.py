import os
import logging
from typing import List, Callable, Optional, Tuple, Dict, Any
from music_dup.db import Database
from music_dup.metadata import extract_audio_metadata
from music_dup.fingerprint import compute_fingerprint

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {
    ".mp3", ".m4a", ".flac", ".wav", ".wave", ".ogg",
    ".opus", ".aac", ".aiff", ".aif", ".wma", ".alac", ".mp4"
}


def find_audio_files(directory: str) -> List[str]:
    """Recursively collect all audio files matching supported extensions."""
    audio_files = []
    directory = os.path.abspath(directory)
    
    for root, _, files in os.walk(directory):
        for file in files:
            ext = os.path.splitext(file)[1].lower()
            if ext in SUPPORTED_EXTENSIONS:
                full_path = os.path.join(root, file)
                audio_files.append(full_path)
                
    return sorted(audio_files)


def scan_directory(
    directory: str,
    db: Database,
    progress_callback: Optional[Callable[[int, int, str, bool], None]] = None
) -> Dict[str, Any]:
    """
    Scan music directory, extracting metadata and computing chromaprint fingerprints.
    Uses SQLite database cache for fast rescanning.
    
    progress_callback(current, total, current_file, is_cached)
    """
    audio_files = find_audio_files(directory)
    total = len(audio_files)
    
    scanned_count = 0
    cached_count = 0
    new_scanned_count = 0
    failed_count = 0

    for idx, filepath in enumerate(audio_files, 1):
        try:
            filesize = os.path.getsize(filepath)
            mtime = os.path.getmtime(filepath)
            
            # 1. Fast cache check
            cached = db.get_cached_file(filepath, filesize, mtime)
            if cached and cached.get("fingerprint"):
                cached_count += 1
                if progress_callback:
                    progress_callback(idx, total, os.path.basename(filepath), True)
                continue

            # 2. Extract metadata & compute acoustic fingerprint
            meta = extract_audio_metadata(filepath)
            duration, fp, fp_method = compute_fingerprint(filepath)
            
            # If mutagen duration is 0, update from chromaprint duration
            if meta.duration <= 0 and duration > 0:
                meta.duration = duration
                meta.calculate_quality_score()

            # Save/update in database
            db.upsert_file(meta, fp, fp_method)
            new_scanned_count += 1

            if progress_callback:
                progress_callback(idx, total, os.path.basename(filepath), False)

        except Exception as e:
            logger.error(f"Error scanning {filepath}: {e}")
            failed_count += 1

    return {
        "total_files": total,
        "cached_count": cached_count,
        "new_scanned_count": new_scanned_count,
        "failed_count": failed_count,
    }

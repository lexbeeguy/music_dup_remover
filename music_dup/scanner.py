import os
import sys
import logging
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from typing import List, Callable, Optional, Tuple, Dict, Any
from music_dup.db import Database
from music_dup.metadata import extract_audio_metadata, AudioMetadata
from music_dup.fingerprint import compute_fingerprint

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {
    ".mp3", ".m4a", ".flac", ".wav", ".wave", ".ogg",
    ".opus", ".aac", ".aiff", ".aif", ".wma", ".alac", ".mp4"
}


def normalize_long_path(path: str) -> str:
    """Add Windows extended path prefix (\\\\?\\) if path length approaches MAX_PATH."""
    path = os.path.abspath(path)
    if os.name == 'nt' and len(path) > 240 and not path.startswith('\\\\?\\'):
        return '\\\\?\\' + path
    return path


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


def _process_file_worker(filepath: str) -> Tuple[str, Optional[AudioMetadata], Optional[str], Optional[str], Optional[str]]:
    """Worker task for parallel processing: extracts metadata & computes fingerprint."""
    try:
        norm_path = normalize_long_path(filepath)
        meta = extract_audio_metadata(norm_path)
        meta.filepath = filepath  # Preserve canonical path
        duration, fp, fp_method = compute_fingerprint(norm_path)
        
        if meta.duration <= 0 and duration > 0:
            meta.duration = duration
            meta.calculate_quality_score()
            
        return filepath, meta, fp, fp_method, None
    except Exception as e:
        return filepath, None, None, None, str(e)


def scan_directory(
    directory: str,
    db: Database,
    progress_callback: Optional[Callable[[int, int, str, bool], None]] = None,
    max_workers: Optional[int] = None
) -> Dict[str, Any]:
    """
    Scan music directory, extracting metadata and computing chromaprint fingerprints
    in parallel across CPU cores, with SQLite atomic batch commits.
    """
    audio_files = find_audio_files(directory)
    total = len(audio_files)
    
    cached_count = 0
    new_scanned_count = 0
    failed_count = 0

    uncached_files: List[str] = []

    # 1. Fast sequential cache check
    for idx, filepath in enumerate(audio_files, 1):
        try:
            norm_path = normalize_long_path(filepath)
            filesize = os.path.getsize(norm_path)
            mtime = os.path.getmtime(norm_path)
            
            cached = db.get_cached_file(filepath, filesize, mtime)
            if cached and cached.get("fingerprint"):
                cached_count += 1
                if progress_callback:
                    progress_callback(idx, total, os.path.basename(filepath), True)
            else:
                uncached_files.append(filepath)
        except Exception as e:
            logger.error(f"Error checking cache for {filepath}: {e}")
            failed_count += 1

    # 2. Parallel processing of uncached audio files
    if uncached_files:
        # In PyInstaller frozen bundle on Windows, ThreadPool avoids spawned process main issues
        ExecutorClass = ThreadPoolExecutor if getattr(sys, 'frozen', False) else ProcessPoolExecutor
        num_workers = max_workers or min(32, (os.cpu_count() or 4) + 4)

        processed_so_far = cached_count
        batch_queue: List[Tuple[AudioMetadata, str, str]] = []

        with ExecutorClass(max_workers=num_workers) as executor:
            for result in executor.map(_process_file_worker, uncached_files):
                processed_so_far += 1
                filepath, meta, fp, fp_method, err = result

                if err or not meta or not fp:
                    failed_count += 1
                    logger.error(f"Failed processing {filepath}: {err}")
                else:
                    new_scanned_count += 1
                    batch_queue.append((meta, fp, fp_method))

                    # Batch commit to database every 200 files
                    if len(batch_queue) >= 200:
                        db.upsert_files_batch(batch_queue)
                        batch_queue.clear()

                if progress_callback:
                    progress_callback(processed_so_far, total, os.path.basename(filepath), False)

            # Flush remaining batch queue
            if batch_queue:
                db.upsert_files_batch(batch_queue)
                batch_queue.clear()

    return {
        "total_files": total,
        "cached_count": cached_count,
        "new_scanned_count": new_scanned_count,
        "failed_count": failed_count,
    }

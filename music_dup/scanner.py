import os
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import List, Callable, Optional, Tuple, Dict, Any
from music_dup.db import Database
from music_dup.metadata import extract_audio_metadata, AudioMetadata
from music_dup.fingerprint import compute_fingerprint
from music_dup.paths import normalize_long_path

logger = logging.getLogger(__name__)

# Uncached files are written to the database in batches of this size.
DB_BATCH_SIZE = 200

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
    Scan a music folder: extract metadata and compute Chromaprint fingerprints
    for new or changed files, in parallel, and cache results in SQLite.

    Unchanged files (same path, size and mtime) are served from the cache.
    Cache entries for files under `directory` that no longer exist are pruned.

    progress_callback(current, total, filename, is_cached) is called once per file.
    """
    audio_files = find_audio_files(directory)
    total = len(audio_files)

    cached_count = 0
    new_scanned_count = 0
    failed_count = 0
    processed = 0
    uncached_files: List[str] = []

    def report(filepath: str, is_cached: bool):
        if progress_callback:
            progress_callback(processed, total, os.path.basename(filepath), is_cached)

    # 1. Fast sequential cache check
    for filepath in audio_files:
        try:
            norm_path = normalize_long_path(filepath)
            filesize = os.path.getsize(norm_path)
            mtime = os.path.getmtime(norm_path)

            cached = db.get_cached_file(filepath, filesize, mtime)
            if cached and cached.get("fingerprint"):
                cached_count += 1
                processed += 1
                report(filepath, True)
            else:
                uncached_files.append(filepath)
        except Exception as e:
            logger.error(f"Error checking cache for {filepath}: {e}")
            failed_count += 1
            processed += 1
            report(filepath, False)

    # 2. Fingerprint uncached files in parallel.
    # Threads are enough: the heavy work runs in separate fpcalc processes, so
    # threads keep every core busy without the Windows process-spawn overhead
    # (and they work the same inside the PyInstaller executable).
    if uncached_files:
        num_workers = max_workers or min(32, (os.cpu_count() or 4) + 4)
        batch: List[Tuple[AudioMetadata, str, str]] = []

        with ThreadPoolExecutor(max_workers=num_workers) as executor:
            for filepath, meta, fp, fp_method, err in executor.map(_process_file_worker, uncached_files):
                processed += 1
                if err or not meta or not fp:
                    failed_count += 1
                    logger.error(f"Failed processing {filepath}: {err}")
                else:
                    new_scanned_count += 1
                    batch.append((meta, fp, fp_method))
                    if len(batch) >= DB_BATCH_SIZE:
                        db.upsert_files_batch(batch)
                        batch.clear()
                report(filepath, False)

        if batch:
            db.upsert_files_batch(batch)

    # 3. Drop cache entries for files that were deleted or moved since the last scan
    removed_count = db.prune_missing_files(directory)

    return {
        "total_files": total,
        "cached_count": cached_count,
        "new_scanned_count": new_scanned_count,
        "failed_count": failed_count,
        "removed_count": removed_count,
    }

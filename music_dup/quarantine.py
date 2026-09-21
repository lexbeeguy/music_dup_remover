import os
import shutil
import logging
from typing import List, Dict, Any, Tuple
from music_dup.db import Database

logger = logging.getLogger(__name__)

DEFAULT_QUARANTINE_DIR = "quarantine"


def get_quarantine_target_path(
    original_path: str,
    base_scan_dir: str,
    quarantine_dir: str
) -> str:
    """
    Compute destination quarantine filepath while preserving relative subfolder hierarchy.
    """
    quarantine_dir = os.path.abspath(quarantine_dir)
    original_path = os.path.abspath(original_path)
    base_scan_dir = os.path.abspath(base_scan_dir)

    try:
        rel_path = os.path.relpath(original_path, base_scan_dir)
        if rel_path.startswith(".."):
            # Outside base scan dir: use basename
            rel_path = os.path.basename(original_path)
    except ValueError:
        rel_path = os.path.basename(original_path)

    dest_path = os.path.join(quarantine_dir, rel_path)
    
    # Handle collisions if file with same relative path already exists in quarantine
    if os.path.exists(dest_path):
        base, ext = os.path.splitext(dest_path)
        counter = 1
        while os.path.exists(f"{base}_dup{counter}{ext}"):
            counter += 1
        dest_path = f"{base}_dup{counter}{ext}"

    return dest_path


def quarantine_duplicates(
    db: Database,
    base_scan_dir: str,
    quarantine_dir: str = DEFAULT_QUARANTINE_DIR,
    dry_run: bool = False
) -> Dict[str, Any]:
    """
    Stage lower-quality duplicates into quarantine directory.
    """
    groups = db.get_duplicate_groups_summary()
    quarantine_plan: List[Dict[str, Any]] = []
    total_space_saved = 0

    for group in groups:
        gid = group["group_id"]
        master = group["master_file"]
        duplicates = group["all_files"][1:]  # Rank 2 and below

        for dup in duplicates:
            if dup["is_quarantined"]:
                continue  # Already quarantined

            orig_path = dup["filepath"]
            if not os.path.exists(orig_path):
                continue

            target_path = get_quarantine_target_path(orig_path, base_scan_dir, quarantine_dir)
            filesize = dup["filesize"]

            quarantine_plan.append({
                "file_id": dup["id"],
                "group_id": gid,
                "original_path": orig_path,
                "quarantine_path": target_path,
                "filesize": filesize,
                "title": dup.get("title") or os.path.basename(orig_path),
                "badge": dup["quality_badge"],
                "master_badge": master["quality_badge"]
            })
            total_space_saved += filesize

    moved_count = 0
    if not dry_run and quarantine_plan:
        os.makedirs(quarantine_dir, exist_ok=True)
        for item in quarantine_plan:
            orig = item["original_path"]
            target = item["quarantine_path"]
            
            # Ensure destination directory exists
            os.makedirs(os.path.dirname(target), exist_ok=True)

            try:
                shutil.move(orig, target)
                db.record_quarantine(item["file_id"], orig, target, item["group_id"])
                moved_count += 1
            except Exception as e:
                logger.error(f"Failed moving {orig} -> {target}: {e}")

    return {
        "dry_run": dry_run,
        "plan": quarantine_plan,
        "total_files": len(quarantine_plan),
        "moved_files": moved_count if not dry_run else 0,
        "total_space_saved": total_space_saved
    }


def restore_quarantined_files(
    db: Database,
    dry_run: bool = False
) -> Dict[str, Any]:
    """
    Restore all quarantined files back to their original file locations.
    """
    history = db.get_quarantine_history()
    restored_count = 0
    plan = []

    for item in history:
        file_id = item["file_id"]
        q_path = item["quarantine_path"]
        orig_path = item["original_path"]

        plan.append({
            "file_id": file_id,
            "original_path": orig_path,
            "quarantine_path": q_path,
            "title": item.get("title") or os.path.basename(orig_path)
        })

    if not dry_run and history:
        for item in history:
            file_id = item["file_id"]
            q_path = item["quarantine_path"]
            orig_path = item["original_path"]

            if os.path.exists(q_path):
                os.makedirs(os.path.dirname(orig_path), exist_ok=True)
                try:
                    shutil.move(q_path, orig_path)
                    db.record_restore(file_id, orig_path)
                    restored_count += 1
                except Exception as e:
                    logger.error(f"Failed restoring {q_path} -> {orig_path}: {e}")

    return {
        "dry_run": dry_run,
        "plan": plan,
        "total_files": len(plan),
        "restored_files": restored_count if not dry_run else 0
    }

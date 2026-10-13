import os
import shutil
import logging
from typing import List, Dict, Any, Optional, Set
from music_dup.db import Database
from music_dup.paths import normalize_long_path as _lp

logger = logging.getLogger(__name__)

DEFAULT_QUARANTINE_DIR = "quarantine"


def get_quarantine_target_path(
    original_path: str,
    base_scan_dir: str,
    quarantine_dir: str,
    reserved: Optional[Set[str]] = None,
) -> str:
    """
    Compute destination quarantine filepath while preserving relative subfolder hierarchy.

    `reserved` holds destinations already claimed by earlier files in the same
    batch, so two files that map to the same name don't overwrite each other.
    """
    reserved = reserved if reserved is not None else set()
    quarantine_dir = os.path.abspath(quarantine_dir)
    original_path = os.path.abspath(original_path)
    base_scan_dir = os.path.abspath(base_scan_dir)

    try:
        rel_path = os.path.relpath(original_path, base_scan_dir)
        if rel_path.startswith(".."):
            # Outside base scan dir: use basename
            rel_path = os.path.basename(original_path)
    except Exception:
        rel_path = os.path.basename(original_path)

    dest_path = os.path.join(quarantine_dir, rel_path)
    
    def taken(p: str) -> bool:
        return os.path.exists(_lp(p)) or os.path.normcase(p) in reserved

    # Handle collisions with files already in quarantine or claimed earlier in this batch
    if taken(dest_path):
        base, ext = os.path.splitext(dest_path)
        counter = 1
        while taken(f"{base}_dup{counter}{ext}"):
            counter += 1
        dest_path = f"{base}_dup{counter}{ext}"

    reserved.add(os.path.normcase(dest_path))
    return dest_path


def quarantine_duplicates(
    db: Database,
    base_scan_dir: str,
    quarantine_dir: str = DEFAULT_QUARANTINE_DIR,
    dry_run: bool = False,
    target_file_ids: Optional[List[int]] = None
) -> Dict[str, Any]:
    """
    Stage lower-quality duplicates into quarantine directory.
    If target_file_ids is provided, only quarantine specified file IDs.
    """
    groups = db.get_duplicate_groups_summary()
    quarantine_plan: List[Dict[str, Any]] = []
    total_space_saved = 0
    reserved_targets: Set[str] = set()

    for group in groups:
        gid = group["group_id"]
        master = group["master_file"]
        duplicates = group["all_files"][1:]  # Rank 2 and below

        # Safety: never quarantine the remaining copies if the file we'd keep is gone
        if not os.path.exists(_lp(master["filepath"])):
            logger.warning(f"Skipping group {gid}: master file missing ({master['filepath']})")
            continue

        for dup in duplicates:
            if dup["is_quarantined"]:
                continue  # Already quarantined

            if target_file_ids is not None and dup["id"] not in target_file_ids:
                continue  # Skip files not selected by user

            orig_path = dup["filepath"]
            if not os.path.exists(_lp(orig_path)):
                continue

            target_path = get_quarantine_target_path(orig_path, base_scan_dir, quarantine_dir, reserved_targets)
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
    moved_size = 0
    errors: List[str] = []
    if not dry_run and quarantine_plan:
        os.makedirs(quarantine_dir, exist_ok=True)
        for item in quarantine_plan:
            orig = item["original_path"]
            target = item["quarantine_path"]
            
            try:
                os.makedirs(_lp(os.path.dirname(target)), exist_ok=True)
                if os.path.exists(_lp(target)):
                    raise FileExistsError(f"destination already exists: {target}")
                shutil.move(_lp(orig), _lp(target))
                try:
                    db.record_quarantine(item["file_id"], orig, target, item["group_id"])
                except Exception:
                    # Don't leave an untracked file in quarantine: put it back.
                    shutil.move(_lp(target), _lp(orig))
                    raise
                moved_count += 1
                moved_size += item["filesize"]
            except Exception as e:
                err_msg = f"Failed moving {os.path.basename(orig)}: {e}"
                logger.error(err_msg)
                errors.append(err_msg)

    return {
        "dry_run": dry_run,
        "plan": quarantine_plan,
        "total_files": len(quarantine_plan),
        "moved_files": moved_count if not dry_run else 0,
        "moved_size": moved_size,
        "total_space_saved": total_space_saved,
        "errors": errors
    }


def restore_quarantined_files(
    db: Database,
    dry_run: bool = False,
    target_file_ids: Optional[List[int]] = None
) -> Dict[str, Any]:
    """
    Restore quarantined files back to their original file locations.
    If target_file_ids is provided, only restore specified file IDs.
    """
    history = db.get_quarantine_history()
    restored_count = 0
    errors: List[str] = []
    plan = []

    for item in history:
        file_id = item["file_id"]
        q_path = item["quarantine_path"]
        orig_path = item["original_path"]

        if target_file_ids is not None and file_id not in target_file_ids:
            continue

        plan.append({
            "file_id": file_id,
            "original_path": orig_path,
            "quarantine_path": q_path,
            "title": item.get("title") or os.path.basename(orig_path)
        })

    if not dry_run and plan:
        for item in plan:
            file_id = item["file_id"]
            q_path = item["quarantine_path"]
            orig_path = item["original_path"]

            name = os.path.basename(q_path)
            if not os.path.exists(_lp(q_path)):
                errors.append(f"Failed restoring {name}: quarantined file is missing ({q_path})")
                continue
            if os.path.exists(_lp(orig_path)):
                # Never overwrite: on macOS/Linux shutil.move would silently replace it.
                errors.append(f"Failed restoring {name}: a file already exists at {orig_path}")
                continue
            try:
                os.makedirs(_lp(os.path.dirname(orig_path)), exist_ok=True)
                shutil.move(_lp(q_path), _lp(orig_path))
                try:
                    db.record_restore(file_id, orig_path)
                except Exception:
                    shutil.move(_lp(orig_path), _lp(q_path))  # keep DB and disk consistent
                    raise
                restored_count += 1
            except Exception as e:
                err_msg = f"Failed restoring {name}: {e}"
                logger.error(err_msg)
                errors.append(err_msg)

    return {
        "dry_run": dry_run,
        "plan": plan,
        "total_files": len(plan),
        "restored_files": restored_count if not dry_run else 0,
        "errors": errors
    }

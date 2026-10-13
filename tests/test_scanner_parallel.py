"""Parallel scanning, batched DB writes and long-path handling."""
import os

import pytest

from music_dup import paths, scanner
from music_dup.db import Database
from music_dup.duplicate_finder import find_and_rank_duplicates
from music_dup.scanner import scan_directory


@pytest.mark.parametrize("workers", [1, 8])
def test_parallel_scan_matches_sequential(library, no_fpcalc, workers):
    names = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot",
             "golf", "hotel", "india", "juliet", "kilo", "lima"]
    for i, name in enumerate(names):
        library.song(f"album{i % 3}/{name}.wav", freq=300 + 40 * i, duration=1.0)
    library.song("copies/foxtrot.wav", freq=300 + 40 * 5, duration=1.0)
    db = Database(library.db_path)
    stats = scan_directory(library.music, db, max_workers=workers)
    assert stats["new_scanned_count"] == 13 and stats["failed_count"] == 0
    assert db.get_stats()["total_files"] == 13
    (group,) = find_and_rank_duplicates(db)
    assert {os.path.basename(f["filepath"]) for f in group["all_files"]} == {"foxtrot.wav"}


def test_batches_are_flushed(library, no_fpcalc, monkeypatch):
    monkeypatch.setattr(scanner, "DB_BATCH_SIZE", 2)
    for i in range(5):  # 2 + 2 + remainder of 1
        library.song(f"t{i}.wav", freq=200 + 50 * i, duration=0.5)
    db = Database(library.db_path)
    scan_directory(library.music, db, max_workers=3)
    assert db.get_stats()["total_files"] == 5
    assert scan_directory(library.music, db)["cached_count"] == 5


def test_progress_reaches_total(library, no_fpcalc):
    for i in range(4):
        library.song(f"t{i}.wav", freq=200 + 50 * i, duration=0.5)
    db = Database(library.db_path)
    scan_directory(library.music, db)  # cache two of them...
    os.remove(os.path.join(library.music, "t0.wav"))
    library.song("new.wav", freq=900, duration=0.5)

    calls = []
    scan_directory(library.music, db, progress_callback=lambda c, t, f, cached: calls.append((c, t)))
    assert [c for c, _ in calls] == list(range(1, 5))
    assert all(t == 4 for _, t in calls)


class TestLongPaths:
    def test_short_paths_unchanged(self, tmp_path):
        p = str(tmp_path / "a.mp3")
        assert paths.normalize_long_path(p) == os.path.abspath(p)

    def test_windows_prefix_for_long_paths(self, monkeypatch):
        monkeypatch.setattr(paths.os, "name", "nt")
        monkeypatch.setattr(paths.os.path, "abspath", lambda p: p)
        long_path = "C:\\Music\\" + "x" * 250 + ".mp3"
        assert paths.normalize_long_path(long_path) == "\\\\?\\" + long_path
        assert paths.normalize_long_path("\\\\?\\" + long_path) == "\\\\?\\" + long_path
        assert paths.normalize_long_path("C:\\short.mp3") == "C:\\short.mp3"

    @pytest.mark.skipif(os.name != "nt", reason="needs Windows long-path behaviour")
    def test_scan_and_quarantine_deep_folder(self, library, no_fpcalc):
        from music_dup.quarantine import quarantine_duplicates, restore_quarantined_files
        deep = os.path.join(*(["very_long_folder_name_" + "x" * 30] * 5))
        a = library.song(os.path.join(deep, "a", "song.wav"), duration=0.5)
        b = library.song(os.path.join(deep, "b", "song.wav"), duration=0.5)
        assert len(a) > 260
        db = Database(library.db_path)
        scan_directory(library.music, db)
        assert scan_directory(library.music, db)["removed_count"] == 0
        find_and_rank_duplicates(db)
        assert quarantine_duplicates(db, library.music, library.quarantine)["moved_files"] == 1
        assert restore_quarantined_files(db)["restored_files"] == 1

"""Database, scanning, quarantine and restore behaviour across repeated runs."""
import os
import sqlite3

import pytest

from music_dup import db as db_module
from music_dup.db import Database
from music_dup.duplicate_finder import find_and_rank_duplicates
from music_dup.quarantine import (
    get_quarantine_target_path,
    quarantine_duplicates,
    restore_quarantined_files,
)
from music_dup.scanner import find_audio_files, scan_directory


def scan_and_group(lib, db):
    scan_directory(lib.music, db)
    return find_and_rank_duplicates(db)


class TestDatabase:
    def test_connections_are_closed(self, library, monkeypatch, no_fpcalc):
        # Regression: `with sqlite3.connect()` commits but never closes, leaking
        # handles and keeping the DB locked on Windows.
        opened = []
        real_connect = sqlite3.connect

        def tracking_connect(*a, **kw):
            conn = real_connect(*a, **kw)
            opened.append(conn)
            return conn

        monkeypatch.setattr(db_module.sqlite3, "connect", tracking_connect)
        library.song("a/x.wav")
        library.song("b/x.wav")
        db = Database(library.db_path)
        scan_and_group(library, db)
        db.get_stats()
        assert opened
        for conn in opened:
            with pytest.raises(sqlite3.ProgrammingError):
                conn.execute("SELECT 1")

    def test_reset(self, library, no_fpcalc):
        library.song("a.wav")
        db = Database(library.db_path)
        scan_directory(library.music, db)
        db.reset_db()
        assert db.get_stats()["total_files"] == 0


class TestScanner:
    def test_finds_supported_extensions_case_insensitively(self, library):
        for name in ["a.MP3", "b.flac", "c.Wav", "notes.txt", "cover.jpg"]:
            path = os.path.join(library.music, "sub", name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            open(path, "wb").close()
        found = sorted(os.path.basename(p) for p in find_audio_files(library.music))
        assert found == ["a.MP3", "b.flac", "c.Wav"]

    def test_modified_file_is_rescanned(self, library, no_fpcalc):
        path = library.song("a.wav")
        db = Database(library.db_path)
        scan_directory(library.music, db)
        library.song("a.wav", freq=660)
        st = os.stat(path)
        os.utime(path, (st.st_atime, st.st_mtime + 10))
        assert scan_directory(library.music, db)["new_scanned_count"] == 1

    def test_corrupt_file_does_not_abort_scan(self, library, no_fpcalc):
        library.song("good.wav")
        with open(os.path.join(library.music, "bad.mp3"), "wb") as f:
            f.write(b"not really audio")
        db = Database(library.db_path)
        stats = scan_directory(library.music, db)
        assert stats["total_files"] == 2
        assert stats["failed_count"] == 0  # unreadable tags fall back gracefully

    def test_deleted_files_are_pruned(self, library, no_fpcalc):
        # Regression: deleted files stayed in the DB forever and kept showing up
        # as duplicates and in the reclaimable-space total.
        library.song("a/song.wav")
        gone = library.song("b/song.wav")
        db = Database(library.db_path)
        assert len(scan_and_group(library, db)) == 1

        os.remove(gone)
        stats = scan_directory(library.music, db)
        assert stats["removed_count"] == 1
        assert find_and_rank_duplicates(db) == []
        assert db.get_stats()["total_files"] == 1

    def test_pruning_leaves_other_libraries_alone(self, library, tmp_path, no_fpcalc):
        other_dir = tmp_path / "other_library"
        library.song("a.wav")
        from helpers import create_sine_wave_wav
        create_sine_wave_wav(str(other_dir / "b.wav"))
        db = Database(library.db_path)
        scan_directory(str(other_dir), db)
        scan_directory(library.music, db)
        assert db.get_stats()["total_files"] == 2

    def test_sibling_folder_with_shared_prefix_not_pruned(self, library, tmp_path, no_fpcalc):
        # "/x/music" must not prune "/x/music2"
        from helpers import create_sine_wave_wav
        sibling = create_sine_wave_wav(str(tmp_path / "music2" / "s.wav"))
        db = Database(library.db_path)
        scan_directory(str(tmp_path / "music2"), db)
        os.makedirs(library.music, exist_ok=True)
        scan_directory(library.music, db)
        assert db.get_stats()["total_files"] == 1
        assert os.path.exists(sibling)


class TestQuarantineLifecycle:
    def test_rescan_after_quarantine_does_not_requarantine(self, library, no_fpcalc):
        # Regression: re-running analysis put quarantined files back into duplicate
        # groups, and the next quarantine moved them again inside the quarantine
        # folder, so restore could no longer find them.
        library.quarantine = os.path.join(library.music, "_quarantine")  # inside the library
        keep = library.song("a/song.wav")
        dup = library.song("b/song.wav")
        db = Database(library.db_path)
        scan_and_group(library, db)
        assert quarantine_duplicates(db, library.music, library.quarantine)["moved_files"] == 1

        groups = scan_and_group(library, db)
        assert groups == []
        assert quarantine_duplicates(db, library.music, library.quarantine)["total_files"] == 0

        res = restore_quarantined_files(db)
        assert res["restored_files"] == 1 and not res["errors"]
        assert os.path.exists(keep) and os.path.exists(dup)

    def test_restore_then_rescan_groups_again(self, library, no_fpcalc):
        library.song("a/song.wav")
        library.song("b/song.wav")
        db = Database(library.db_path)
        scan_and_group(library, db)
        quarantine_duplicates(db, library.music, library.quarantine)
        restore_quarantined_files(db)
        assert len(scan_and_group(library, db)) == 1

    def test_restore_never_overwrites(self, library, no_fpcalc):
        library.song("a/song.wav")
        dup = library.song("b/song.wav")
        db = Database(library.db_path)
        scan_and_group(library, db)
        quarantine_duplicates(db, library.music, library.quarantine)

        with open(dup, "wb") as f:
            f.write(b"new file the user put here")
        res = restore_quarantined_files(db)
        assert res["restored_files"] == 0 and len(res["errors"]) == 1
        with open(dup, "rb") as f:
            assert f.read() == b"new file the user put here"
        assert len(db.get_quarantine_history()) == 1  # still recoverable

    def test_restore_reports_missing_quarantined_file(self, library, no_fpcalc):
        library.song("a/song.wav")
        library.song("b/song.wav")
        db = Database(library.db_path)
        scan_and_group(library, db)
        res = quarantine_duplicates(db, library.music, library.quarantine)
        os.remove(res["plan"][0]["quarantine_path"])
        res = restore_quarantined_files(db)
        assert res["restored_files"] == 0
        assert "missing" in res["errors"][0]

    def test_skips_group_when_master_missing(self, library, no_fpcalc):
        library.song("a/song.wav")
        library.song("b/song.wav")
        db = Database(library.db_path)
        (group,) = scan_and_group(library, db)
        os.remove(group["master_file"]["filepath"])
        res = quarantine_duplicates(db, library.music, library.quarantine)
        assert res["total_files"] == 0
        assert os.path.exists(group["duplicates"][0]["filepath"])

    def test_dry_run_moves_nothing(self, library, no_fpcalc):
        library.song("a/song.wav")
        dup = library.song("b/song.wav")
        db = Database(library.db_path)
        scan_and_group(library, db)
        res = quarantine_duplicates(db, library.music, library.quarantine, dry_run=True)
        assert res["total_files"] == 1 and res["moved_files"] == 0
        assert os.path.exists(dup) and not os.path.exists(library.quarantine)

    def test_preserves_folder_structure(self, library, no_fpcalc):
        library.song("Artist/Album/song.wav")
        library.song("Other/Album/song.wav")
        db = Database(library.db_path)
        scan_and_group(library, db)
        res = quarantine_duplicates(db, library.music, library.quarantine)
        rel = os.path.relpath(res["plan"][0]["quarantine_path"], library.quarantine)
        assert rel.endswith(os.path.join("Album", "song.wav"))
        assert rel.count(os.sep) == 2

    def test_move_failure_is_reported(self, library, monkeypatch, no_fpcalc):
        library.song("a/song.wav")
        library.song("b/song.wav")
        db = Database(library.db_path)
        scan_and_group(library, db)

        def boom(*a, **kw):
            raise PermissionError("file is in use")

        monkeypatch.setattr("music_dup.quarantine.shutil.move", boom)
        res = quarantine_duplicates(db, library.music, library.quarantine)
        assert res["moved_files"] == 0 and res["moved_size"] == 0
        assert "in use" in res["errors"][0]
        assert db.get_quarantine_history() == []


class TestTargetPaths:
    def test_collisions_within_one_batch_get_unique_names(self, tmp_path):
        # Regression: two files outside the scan folder with the same name mapped
        # to the same destination, and the second move overwrote the first.
        reserved = set()
        q = str(tmp_path / "q")
        base = str(tmp_path / "lib")
        a = get_quarantine_target_path(str(tmp_path / "x" / "song.mp3"), base, q, reserved)
        b = get_quarantine_target_path(str(tmp_path / "y" / "song.mp3"), base, q, reserved)
        assert a != b
        assert os.path.basename(b) == "song_dup1.mp3"

    def test_existing_file_in_quarantine(self, tmp_path):
        q = tmp_path / "q"
        q.mkdir()
        (q / "song.mp3").write_bytes(b"x")
        target = get_quarantine_target_path(str(tmp_path / "lib" / "song.mp3"), str(tmp_path / "lib"), str(q))
        assert os.path.basename(target) == "song_dup1.mp3"

    def test_end_to_end_same_name_outside_base(self, tmp_path, no_fpcalc):
        from helpers import create_sine_wave_wav
        db = Database(str(tmp_path / "t.db"))
        for d in ["one", "two", "three"]:
            create_sine_wave_wav(str(tmp_path / "lib" / d / "song.wav"))
            scan_directory(str(tmp_path / "lib" / d), db)
        find_and_rank_duplicates(db)
        q = str(tmp_path / "q")
        # base dir that contains none of the files -> all use basenames
        res = quarantine_duplicates(db, str(tmp_path / "elsewhere"), q)
        assert res["moved_files"] == 2 and not res["errors"]
        assert len(os.listdir(q)) == 2


def test_db_failure_after_move_puts_file_back(library, monkeypatch, no_fpcalc):
    library.song("a/song.wav")
    dup = library.song("b/song.wav")
    db = Database(library.db_path)
    scan_and_group(library, db)

    def fail(*a, **kw):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(db, "record_quarantine", fail)
    res = quarantine_duplicates(db, library.music, library.quarantine)
    assert res["moved_files"] == 0 and "locked" in res["errors"][0]
    assert os.path.exists(dup)

"""Title normalization, metadata matching and duplicate ranking."""
import pytest

from music_dup.db import Database
from music_dup.duplicate_finder import (
    find_and_rank_duplicates,
    is_metadata_duplicate,
    normalize_filename,
    normalize_string,
)
from music_dup.scanner import scan_directory


def rec(title=None, artist=None, duration=200.0, filepath="/music/x.mp3"):
    return {"title": title, "artist": artist, "duration": duration, "filepath": filepath}


class TestNormalize:
    def test_titles_with_periods_are_not_treated_as_paths(self):
        # Regression: "Mr. Brightside" used to normalize to "mr"
        assert normalize_string("Mr. Brightside") == "mr brightside"
        assert normalize_string("Mr. Jones") == "mr jones"

    def test_leading_numbers_kept_in_tags(self):
        assert normalize_string("99 Problems") == "99 problems"
        assert normalize_string("1979") == "1979"

    def test_punctuation_case_and_whitespace(self):
        assert normalize_string("  Don't   Stop Me Now!  ") == "dont stop me now"

    @pytest.mark.parametrize("path,expected", [
        ("/music/Queen/01 - Bohemian Rhapsody.mp3", "bohemian rhapsody"),
        ("C:\\Music\\02. Under Pressure.flac", "under pressure"),
        ("/music/03_Killer_Queen.m4a", "killer queen"),
        ("/music/Mr. Brightside.mp3", "mr brightside"),
    ])
    def test_filenames(self, path, expected):
        assert normalize_filename(path) == expected

    def test_empty(self):
        assert normalize_string("") == ""
        assert normalize_filename("") == ""


class TestMetadataDuplicate:
    def test_same_title_and_artist(self):
        assert is_metadata_duplicate(rec("Yellow", "Coldplay"), rec("yellow", "COLDPLAY"), 3.5)

    def test_different_titles_sharing_a_prefix_with_a_period(self):
        a = rec("Mr. Brightside", "The Killers")
        b = rec("Mr. Jones", "The Killers")
        assert not is_metadata_duplicate(a, b, 3.5)

    def test_duration_outside_tolerance(self):
        assert not is_metadata_duplicate(rec("Yellow", "Coldplay", 266), rec("Yellow", "Coldplay", 300), 3.5)

    def test_different_artists(self):
        assert not is_metadata_duplicate(rec("Hurt", "Nine Inch Nails"), rec("Hurt", "Johnny Cash"), 3.5)

    def test_falls_back_to_filename_when_untagged(self):
        a = rec(filepath="/a/01 - Clocks.mp3")
        b = rec(filepath="/b/Clocks.flac")
        assert is_metadata_duplicate(a, b, 3.5)


class TestRanking:
    def test_higher_quality_file_is_master(self, library, no_fpcalc):
        # Two identical CD copies plus a 96 kHz copy: the 96 kHz file should be kept
        library.song("cd/track.wav")
        library.song("cd_copy/track.wav")
        hi = library.song("hires/track.wav", sample_rate=96000)
        db = Database(library.db_path)
        scan_directory(library.music, db)

        groups = find_and_rank_duplicates(db)
        # The 96 kHz file differs byte-wise, so only the two identical copies group by
        # fingerprint; the hi-res file joins via filename metadata match.
        assert len(groups) == 1
        assert groups[0]["master_file"]["filepath"] == hi
        assert [f["rank"] for f in groups[0]["all_files"]] == [1, 2, 3]

    def test_singletons_not_reported(self, library, no_fpcalc):
        library.song("a.wav", freq=440)
        library.song("b.wav", freq=550)
        db = Database(library.db_path)
        scan_directory(library.music, db)
        assert find_and_rank_duplicates(db) == []

    def test_wasted_size_excludes_master(self, library, no_fpcalc):
        library.song("x/song.wav")
        library.song("y/song.wav")
        db = Database(library.db_path)
        scan_directory(library.music, db)
        (group,) = find_and_rank_duplicates(db)
        assert group["wasted_size"] == group["duplicates"][0]["filesize"]


class TestDurationWindow:
    """The matcher sorts by duration and stops early; make sure it still finds everything."""

    def _db_with(self, library, durations_and_names):
        from helpers import create_sine_wave_wav
        import os
        for i, (dur, name) in enumerate(durations_and_names):
            create_sine_wave_wav(os.path.join(library.music, f"d{i}", name), duration=dur, sample_rate=8000, num_channels=1)
        db = Database(library.db_path)
        scan_directory(library.music, db)
        return db

    def test_zero_tolerance_requires_equal_length(self, library, no_fpcalc):
        # Regression (merge): tolerance 0 used to disable the length check entirely
        db = self._db_with(library, [(2.0, "Song.wav"), (3.0, "Song.wav")])
        assert find_and_rank_duplicates(db, duration_tolerance=0.0) == []
        assert len(find_and_rank_duplicates(db, duration_tolerance=1.5)) == 1

    def test_matches_beyond_the_first_neighbour(self, library, no_fpcalc):
        # A, B, C sorted by length; A and C are within tolerance, B is unrelated
        db = self._db_with(library, [(2.0, "Alpha.wav"), (2.5, "Zulu.wav"), (3.0, "Alpha.wav")])
        groups = find_and_rank_duplicates(db, duration_tolerance=1.5)
        assert len(groups) == 1
        assert {f["filepath"].split("/")[-1] for f in groups[0]["all_files"]} == {"Alpha.wav"}

    def test_ranking_ties_are_deterministic(self, library, no_fpcalc):
        library.song("a/song.wav")
        library.song("b/song.wav")
        db = Database(library.db_path)
        scan_directory(library.music, db)
        first = find_and_rank_duplicates(db)[0]["master_file"]["id"]
        for _ in range(3):
            assert find_and_rank_duplicates(db)[0]["master_file"]["id"] == first
        assert first == min(f["id"] for f in find_and_rank_duplicates(db)[0]["all_files"])

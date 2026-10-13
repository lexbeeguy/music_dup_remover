"""End-to-end tests carried over from the original project."""
import os

from helpers import create_sine_wave_wav
from music_dup.metadata import extract_audio_metadata, AudioMetadata
from music_dup.fingerprint import compute_fingerprint, calculate_fingerprint_similarity
from music_dup.db import Database
from music_dup.scanner import scan_directory
from music_dup.duplicate_finder import find_and_rank_duplicates
from music_dup.quarantine import quarantine_duplicates, restore_quarantined_files


def test_metadata_extraction(tmp_path):
    wav_file = str(tmp_path / "test_song.wav")
    create_sine_wave_wav(wav_file, duration=2.0, sample_rate=44100)

    meta = extract_audio_metadata(wav_file)
    assert meta.format_ext == ".wav"
    assert meta.sample_rate == 44100
    assert meta.channels == 2
    assert meta.is_lossless is True
    assert meta.quality_score > 100000.0  # Lossless bonus


def test_quality_score_ranking():
    # Lossless FLAC vs Lossy MP3
    high_qual = AudioMetadata(
        filepath="song.flac", filesize=1000000, format_ext=".flac", duration=180.0,
        bitrate=1411, sample_rate=96000, channels=2, bits_per_sample=24, is_lossless=True
    )
    high_qual.calculate_quality_score()

    mid_qual = AudioMetadata(
        filepath="song_320k.mp3", filesize=500000, format_ext=".mp3", duration=180.0,
        bitrate=320, sample_rate=44100, channels=2, bits_per_sample=0, is_lossless=False
    )
    mid_qual.calculate_quality_score()

    low_qual = AudioMetadata(
        filepath="song_128k.mp3", filesize=200000, format_ext=".mp3", duration=180.0,
        bitrate=128, sample_rate=44100, channels=2, bits_per_sample=0, is_lossless=False
    )
    low_qual.calculate_quality_score()

    assert high_qual.quality_score > mid_qual.quality_score > low_qual.quality_score


def test_database_and_scanner_caching(tmp_path):
    music_dir = str(tmp_path / "music")
    db_path = str(tmp_path / "test.db")
    
    wav1 = os.path.join(music_dir, "track1.wav")
    create_sine_wave_wav(wav1, duration=2.5, freq=440.0)

    db = Database(db_path=db_path)
    
    # First scan
    res1 = scan_directory(music_dir, db)
    assert res1["total_files"] == 1
    assert res1["new_scanned_count"] == 1
    assert res1["cached_count"] == 0

    # Second scan (incremental cache hit)
    res2 = scan_directory(music_dir, db)
    assert res2["total_files"] == 1
    assert res2["new_scanned_count"] == 0
    assert res2["cached_count"] == 1


def test_duplicate_detection_and_quarantine(tmp_path):
    music_dir = str(tmp_path / "library")
    db_path = str(tmp_path / "dup_test.db")
    quarantine_dir = str(tmp_path / "quarantine")

    # Create two duplicate wav tracks (same audio, slightly different file sizes/paths)
    track_orig = os.path.join(music_dir, "album_a", "track_master.wav")
    track_dup = os.path.join(music_dir, "album_b", "track_copy.wav")
    
    create_sine_wave_wav(track_orig, duration=3.0, freq=440.0)
    create_sine_wave_wav(track_dup, duration=3.0, freq=440.0)

    db = Database(db_path=db_path)
    
    # 1. Scan
    scan_directory(music_dir, db)
    
    # 2. Find duplicates
    groups = find_and_rank_duplicates(db, similarity_threshold=0.8, duration_tolerance=2.0)
    assert len(groups) == 1
    assert len(groups[0]["all_files"]) == 2

    # 3. Dry-run Quarantine
    dry_res = quarantine_duplicates(db, base_scan_dir=music_dir, quarantine_dir=quarantine_dir, dry_run=True)
    assert dry_res["dry_run"] is True
    assert dry_res["total_files"] == 1
    assert os.path.exists(track_dup)  # Not moved in dry-run

    # 4. Live Quarantine
    q_res = quarantine_duplicates(db, base_scan_dir=music_dir, quarantine_dir=quarantine_dir, dry_run=False)
    assert q_res["dry_run"] is False
    assert q_res["moved_files"] == 1
    assert os.path.exists(track_orig)  # Master preserved
    assert not os.path.exists(track_dup)  # Lower quality duplicate moved
    
    # 5. Restore
    restore_res = restore_quarantined_files(db, dry_run=False)
    assert restore_res["restored_files"] == 1
    assert os.path.exists(track_dup)  # Restored to original path


def test_cross_format_duplicate_detection(tmp_path):
    music_dir = str(tmp_path / "cross_format_library")
    db_path = str(tmp_path / "cross_format.db")

    # Create FLAC/WAV master and simulated MP3/M4A duplicate records
    wav_file = os.path.join(music_dir, "song.wav")
    mp3_file = os.path.join(music_dir, "song.mp3")
    m4a_file = os.path.join(music_dir, "song.m4a")

    create_sine_wave_wav(wav_file, duration=3.0, freq=440.0)
    create_sine_wave_wav(mp3_file, duration=3.0, freq=440.0)
    create_sine_wave_wav(m4a_file, duration=3.0, freq=440.0)

    db = Database(db_path=db_path)
    scan_directory(music_dir, db)

    groups = find_and_rank_duplicates(db, similarity_threshold=0.70)
    assert len(groups) == 1
    assert len(groups[0]["all_files"]) == 3
    
    # Check that highest quality version (WAV) is Rank 1
    master = groups[0]["master_file"]
    assert master["filepath"].endswith(".wav")


def test_granular_quarantine_and_restore(tmp_path):
    music_dir = str(tmp_path / "granular_library")
    db_path = str(tmp_path / "granular.db")
    quarantine_dir = str(tmp_path / "quarantine")

    track1 = os.path.join(music_dir, "master.wav")
    track2 = os.path.join(music_dir, "dup1.wav")
    track3 = os.path.join(music_dir, "dup2.wav")

    create_sine_wave_wav(track1, duration=3.0, freq=440.0)
    create_sine_wave_wav(track2, duration=3.0, freq=440.0)
    create_sine_wave_wav(track3, duration=3.0, freq=440.0)

    db = Database(db_path=db_path)
    scan_directory(music_dir, db)
    groups = find_and_rank_duplicates(db, similarity_threshold=0.70)
    
    assert len(groups) == 1
    duplicates = groups[0]["duplicates"]
    assert len(duplicates) == 2

    # Target ONLY the first duplicate file ID
    target_id = duplicates[0]["id"]
    q_res = quarantine_duplicates(
        db, base_scan_dir=music_dir, quarantine_dir=quarantine_dir, dry_run=False, target_file_ids=[target_id]
    )
    assert q_res["moved_files"] == 1
    assert not os.path.exists(duplicates[0]["filepath"])
    assert os.path.exists(duplicates[1]["filepath"])  # Untargeted duplicate remains

    # Target restore of that specific file ID
    r_res = restore_quarantined_files(db, dry_run=False, target_file_ids=[target_id])
    assert r_res["restored_files"] == 1
    assert os.path.exists(duplicates[0]["filepath"])



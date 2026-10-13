"""Fingerprint parsing, similarity and fpcalc discovery."""
import os
import random
import sys

import pytest

from helpers import create_melody_wav
from music_dup import fingerprint
from music_dup.fingerprint import (
    calculate_fingerprint_similarity,
    compute_fingerprint,
    find_fpcalc,
    generate_fallback_fingerprint,
    match_fingerprints,
    parse_fingerprint_to_ints,
    parse_raw_fpcalc_output,
    verify_fpcalc,
)


def raw(ints):
    return ",".join(str(i) for i in ints)


class TestParsing:
    def test_parse_raw_output(self):
        out = "DURATION=215\nFINGERPRINT=1,-2,3\n"
        assert parse_raw_fpcalc_output(out) == (215.0, "1,-2,3")

    def test_parse_raw_output_garbage(self):
        assert parse_raw_fpcalc_output("nonsense\nDURATION=abc") == (0.0, "")

    def test_parse_ints(self):
        assert parse_fingerprint_to_ints("1,-2,3") == [1, -2, 3]
        assert parse_fingerprint_to_ints("42") == [42]
        assert parse_fingerprint_to_ints("fallback:10:abc") == []
        assert parse_fingerprint_to_ints("error:x.mp3") == []
        assert parse_fingerprint_to_ints("") == []


class TestSimilarity:
    def test_identical(self):
        fp = raw(random.Random(1).getrandbits(31) for _ in range(50))
        assert calculate_fingerprint_similarity(fp, fp) == 1.0

    def test_unrelated(self):
        rng = random.Random(2)
        a = raw(rng.getrandbits(31) for _ in range(80))
        b = raw(rng.getrandbits(31) for _ in range(80))
        assert calculate_fingerprint_similarity(a, b) < 0.1

    def test_offset_and_bit_noise_still_match(self):
        rng = random.Random(3)
        base = [rng.getrandbits(31) for _ in range(120)]
        shifted = [v ^ (1 << rng.randrange(31)) for v in base[10:]]  # trimmed + 1-bit errors
        assert match_fingerprints(base, shifted) > 0.9

    def test_error_fingerprints_never_match(self):
        # Regression: two unreadable files with the same name in different folders
        # both got "error:<basename>" and were reported as 100% duplicates.
        assert calculate_fingerprint_similarity("error:song.mp3", "error:song.mp3") == 0.0

    def test_fallback_matches_only_exact(self):
        assert calculate_fingerprint_similarity("fallback:10:aa", "fallback:10:aa") == 1.0
        assert calculate_fingerprint_similarity("fallback:10:aa", "fallback:10:bb") == 0.0
        assert calculate_fingerprint_similarity("fallback:10:aa", "1,2,3") == 0.0

    def test_empty(self):
        assert calculate_fingerprint_similarity("", "1,2") == 0.0
        assert match_fingerprints([], [1]) == 0.0

    def test_matches_pyacoustid_reference(self):
        acoustid = pytest.importorskip("acoustid")
        ref = getattr(acoustid, "_match_fingerprints", None)
        if ref is None:
            pytest.skip("installed pyacoustid has no reference matcher")
        rng = random.Random(4)
        for _ in range(50):
            a = [rng.getrandbits(32) - 2**31 for _ in range(rng.randint(1, 60))]
            b = [v ^ (1 << rng.randrange(32)) if rng.random() < 0.6 else rng.getrandbits(31) for v in a]
            b = b[rng.randrange(len(b)):] or [0]
            assert match_fingerprints(a, b) == pytest.approx(min(1.0, ref(a, b)))


class TestFallback:
    def test_same_content_same_fingerprint(self, tmp_path):
        a, b = tmp_path / "a.bin", tmp_path / "b.bin"
        a.write_bytes(os.urandom(300_000))
        b.write_bytes(a.read_bytes())
        assert generate_fallback_fingerprint(str(a))[1] == generate_fallback_fingerprint(str(b))[1]

    def test_unreadable_file(self, tmp_path):
        _, fp, method = generate_fallback_fingerprint(str(tmp_path / "missing.mp3"))
        assert method == "error" and fp.startswith("error:")

    def test_compute_uses_fallback_without_fpcalc(self, tmp_path, no_fpcalc):
        f = tmp_path / "a.wav"
        f.write_bytes(b"x" * 1000)
        assert compute_fingerprint(str(f))[2] == "fallback"


class TestFindFpcalc:
    def _make_exe(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("#!/bin/sh\necho fpcalc version test\n")
        path.chmod(0o755)
        return str(path)

    def test_env_var_takes_priority(self, tmp_path, monkeypatch):
        name = "fpcalc.exe" if sys.platform == "win32" else "fpcalc"
        exe = self._make_exe(tmp_path / name)
        monkeypatch.setenv("FPCALC", exe)
        assert find_fpcalc() == exe

    @pytest.mark.skipif(sys.platform == "win32", reason="checks non-Windows behaviour")
    def test_windows_exe_ignored_elsewhere(self, tmp_path, monkeypatch):
        # Regression: the bundled fpcalc.exe was picked on macOS/Linux, hiding a
        # working fpcalc on PATH.
        exe = tmp_path / "fpcalc.exe"
        exe.write_text("MZ")
        monkeypatch.setenv("FPCALC", str(exe))
        found = find_fpcalc()
        assert found is None or not found.lower().endswith(".exe")

    def test_verify_reports_missing(self, monkeypatch):
        monkeypatch.setattr(fingerprint, "find_fpcalc", lambda: None)
        status = verify_fpcalc()
        assert status["available"] is False and status["error"]


@pytest.mark.skipif(not verify_fpcalc()["available"], reason="fpcalc not installed")
class TestChromaprintIntegration:
    """Runs only where fpcalc is available (CI installs it)."""

    def test_same_song_different_sample_rate(self, tmp_path):
        a = create_melody_wav(str(tmp_path / "a_44k.wav"), seed=1, sample_rate=44100)
        b = create_melody_wav(str(tmp_path / "a_22k.wav"), seed=1, sample_rate=22050)
        fa, fb = compute_fingerprint(a), compute_fingerprint(b)
        assert fa[2] == fb[2] == "chromaprint_raw"
        assert calculate_fingerprint_similarity(fa[1], fb[1]) > 0.85

    def test_different_songs(self, tmp_path):
        a = create_melody_wav(str(tmp_path / "a.wav"), seed=1)
        b = create_melody_wav(str(tmp_path / "b.wav"), seed=2)
        assert calculate_fingerprint_similarity(compute_fingerprint(a)[1], compute_fingerprint(b)[1]) < 0.5

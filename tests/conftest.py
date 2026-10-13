import os

import pytest

from helpers import create_sine_wave_wav
from music_dup import fingerprint


@pytest.fixture(autouse=True)
def reset_fpcalc_cache():
    """fpcalc detection is cached per process; reset it so tests don't leak state."""
    fingerprint._FPCALC_STATUS_CACHE = None
    fingerprint._FPCALC_VERIFIED_PATH = None
    yield
    fingerprint._FPCALC_STATUS_CACHE = None
    fingerprint._FPCALC_VERIFIED_PATH = None


@pytest.fixture
def no_fpcalc(monkeypatch):
    """Force the fallback (exact-copy) fingerprint path, regardless of the host."""
    monkeypatch.setattr(fingerprint, "find_fpcalc", lambda: None)


@pytest.fixture
def library(tmp_path):
    """Paths for a throwaway music library, database and quarantine folder."""
    class Lib:
        root = tmp_path
        music = str(tmp_path / "music")
        db_path = str(tmp_path / "test.db")
        quarantine = str(tmp_path / "quarantine")

        def song(self, relpath: str, freq: float = 440.0, duration: float = 3.0, **kw) -> str:
            return create_sine_wave_wav(os.path.join(self.music, relpath), duration=duration, freq=freq, **kw)

    os.makedirs(Lib.music, exist_ok=True)
    return Lib()

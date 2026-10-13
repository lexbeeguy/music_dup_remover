"""Command-line interface smoke tests."""
import os

import pytest
from click.testing import CliRunner

from music_dup import __version__, ui
from music_dup.cli import cli


@pytest.fixture
def run(library, no_fpcalc, monkeypatch):
    # Wide console so long paths aren't wrapped mid-word in assertions
    monkeypatch.setattr(ui.console, "width", 400, raising=False)
    monkeypatch.setattr(ui.console, "_width", 400, raising=False)
    runner = CliRunner()

    def _run(*args):
        result = runner.invoke(cli, list(args) + (["--db", library.db_path] if args[0] != "--version" else []))
        assert result.exit_code == 0, result.output + repr(result.exception)
        return result

    return _run


def test_version(run):
    assert __version__ in run("--version").output


def test_full_workflow(run, library):
    library.song("a/song.wav")
    dup = library.song("b/song.wav")

    out = run("scan", library.music).output
    assert "Found 1" in out

    out = run("quarantine", library.music, "--quarantine-dir", library.quarantine, "--dry-run").output
    assert "DRY RUN" in out and os.path.exists(dup)

    run("quarantine", library.music, "--quarantine-dir", library.quarantine)
    assert not os.path.exists(dup)

    assert "Quarantined" in run("stats").output

    run("restore")
    assert os.path.exists(dup)

    run("reset", "--yes")


def test_brackets_in_filenames_are_shown(run, library):
    # Regression: rich treated "[live]" as a style tag and silently dropped it.
    library.song("a/Song [live].wav")
    library.song("b/Song [live].wav")
    out = run("scan", library.music).output
    assert "Song [live].wav" in out


def test_rejects_out_of_range_similarity(library, no_fpcalc):
    result = CliRunner().invoke(cli, ["scan", library.music, "--similarity", "1.5", "--db", library.db_path])
    assert result.exit_code != 0
    assert "1.5" in result.output


def test_format_bytes():
    assert ui.format_bytes(0) == "0.00 B"
    assert ui.format_bytes(1536) == "1.50 KB"
    assert ui.format_bytes(5 * 1024 ** 3) == "5.00 GB"

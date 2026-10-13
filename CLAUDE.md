# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What this is

`music-dup` finds duplicate songs by acoustic fingerprint (Chromaprint via `fpcalc`), ranks each group by audio quality, and moves lower-quality copies to a quarantine folder that can be restored. It ships as a CLI (`music-dup`) and a CustomTkinter desktop app (`music-dup gui` / `music-dup-gui`, plus a standalone Windows `.exe`). Windows is the primary platform; the code also runs on macOS and Linux.

## Commands

```bash
python -m pip install -e ".[dev]"     # install with test deps
python -m pytest                      # run all tests
python -m pytest tests/test_library_lifecycle.py -k restore   # a subset

music-dup scan <folder>               # scan + list duplicate groups
music-dup quarantine <folder> --dry-run
music-dup restore
music-dup gui

pyinstaller music-dup.spec            # Windows only -> dist\music-dup-gui.exe
```

## Layout

| File | Role |
|---|---|
| `music_dup/cli.py` | Click commands; thin wrappers over the modules below |
| `music_dup/scanner.py` | Walks folders, uses the DB cache (path + size + mtime), prunes deleted files |
| `music_dup/metadata.py` | mutagen tag/audio-property extraction; `AudioMetadata.calculate_quality_score()` |
| `music_dup/fingerprint.py` | `fpcalc` discovery/verification, raw fingerprints, `match_fingerprints()` |
| `music_dup/duplicate_finder.py` | Pairwise matching (fingerprint OR title/artist/duration), union-find grouping, ranking |
| `music_dup/quarantine.py` | Moves files to/from quarantine and records each move |
| `music_dup/db.py` | SQLite: `files`, `duplicate_groups`, `quarantine_history` |
| `music_dup/ui.py` | rich terminal output |
| `music_dup/gui/app.py`, `gui/player.py` | Desktop app; preview via pygame, or Windows Media Player COM for M4A/AAC/WMA |
| `bin/…/fpcalc.exe` | Bundled Windows fpcalc |

## Invariants: don't break these

These protect users' music files. Each has a regression test.

- **Never delete audio files.** Quarantine moves; restore moves back. Nothing calls `os.remove` on user files.
- **Never overwrite.** Quarantine destinations are reserved per batch (`get_quarantine_target_path(..., reserved)`) and checked for existence; restore refuses if the original path is occupied.
- **Disk and DB stay consistent.** If `record_quarantine` / `record_restore` fails after a move, the move is undone.
- **Quarantined files are excluded from matching.** `Database.get_all_scanned_files()` filters out IDs in `quarantine_history`; otherwise a rescan would quarantine them twice. While quarantined, `files.filepath` holds the quarantine path.
- **The rank-1 file is never moved**, and a group is skipped if that file is missing.
- **Pruning is scoped.** `prune_missing_files(dir)` only removes records under the scanned folder (normalized prefix + separator) and never quarantined ones.

## Conventions and gotchas

- **DB access:** always use `with self._connect() as conn:` (commits, rolls back on error, always closes). Plain `with sqlite3.connect()` never closes, which leaks handles and locks the file on Windows.
- **Terminal output:** wrap any user-controlled text (paths, tags, error messages) in `rich.markup.escape()`; otherwise names like `Song [live].mp3` lose text or crash.
- **Normalization:** `normalize_string()` is for tags (keeps leading numbers like "99 Problems"); `normalize_filename()` is for paths (strips extension and track numbers). Don't treat strings containing `.` as paths.
- **Fingerprints:** strings are `"<int>,<int>,…"` (Chromaprint raw), `"fallback:<size>:<hash>"` (no fpcalc; matches exact copies only), or `"error:<name>"` (never matches).
- **fpcalc lookup order:** `FPCALC` env var, PyInstaller bundle, `bin/`, `acoustid.FPCALC_COMMAND`, PATH, venv. `.exe` builds are ignored off Windows. The result is cached in module globals, which tests reset via an autouse fixture.
- **Thresholds:** defaults live in `duplicate_finder.DEFAULT_SIMILARITY_THRESHOLD` (0.85) and `DEFAULT_DURATION_TOLERANCE` (3.5 s); the CLI and GUI use these.
- **Windows file locks:** stop the preview player (it unloads the file) before moving files; the GUI already does this.
- **Version** is in two places: `pyproject.toml` and `music_dup/__init__.py`. The GUI and `--version` read `__version__`.

## Tests

- Tests generate synthetic WAVs (`tests/helpers.py`); never commit audio files.
- Use the `library` fixture for a temp music folder/DB/quarantine and `no_fpcalc` to force fallback fingerprinting so results don't depend on the host.
- `TestChromaprintIntegration` runs only where `fpcalc` is available. CI installs it on Linux (`libchromaprint-tools`) and uses the bundled exe on Windows.
- Every bug fix gets a regression test that fails without the fix.
- The GUI has no automated tests; after changing `gui/`, launch it and check by hand.

## CI and releases

- `.github/workflows/tests.yml`: pytest on Linux (Python 3.9–3.13) and Windows on every push and PR.
- `.github/workflows/release.yml`: pushing a tag `vX.Y.Z` builds `music-dup-gui.exe` on Windows and attaches it to a GitHub Release. It can also be run manually from the Actions tab, which produces the exe as a workflow artifact only.
- To release: bump both version strings, add a `CHANGELOG.md` entry, commit, then `git tag vX.Y.Z && git push origin vX.Y.Z`.

## History

Versions up to 2.0 were built with Antigravity; 2.1 onward with Claude. See `CHANGELOG.md`.

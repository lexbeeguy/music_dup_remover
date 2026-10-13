# music-dup

Find duplicate songs in your music library by **how they sound**, keep the best-quality copy, and move the rest into a quarantine folder you can restore from at any time.

It catches duplicates that file-hash tools miss: the same track as FLAC and MP3, a 320 kbps and a 128 kbps rip, or a copy with different tags or filename.

See [CHANGELOG.md](CHANGELOG.md) for what changed in each version.

## Download (Windows)

Get **`music-dup-gui.exe`** from the [latest release](https://github.com/lexbeeguy/music_dup_remover/releases/latest). It's a single file with everything included, Chromaprint too, so there's nothing to install: download it and double-click.

Windows SmartScreen may say the app is unrecognized, because it isn't code-signed. Click **More info → Run anyway**.

The download is the desktop app. For the command-line tool, or to run on macOS or Linux, install from source as described below.

## How it works

1. **Scan.** Walks your music folder, reads tags and audio properties with [mutagen](https://mutagen.readthedocs.io/), and computes a [Chromaprint](https://acoustid.org/chromaprint) acoustic fingerprint for each file with `fpcalc`. Results are cached in a SQLite database, so rescans only process new or changed files. Files that have been deleted since the last scan are dropped from the cache.
2. **Match.** Two tracks are duplicates when their fingerprints line up (default similarity ≥ 0.85), or when their normalized title and artist match and their durations agree within a tolerance (default 3.5 s). Matches are chained into groups.
3. **Rank.** Within each group, files are ranked by a quality score: lossless beats lossy, then higher bitrate, sample rate and bit depth, then more complete tags. Rank 1 is kept.
4. **Quarantine.** Lower-ranked copies are *moved* (never deleted) to a quarantine folder that mirrors your folder structure. Every move is logged, so `restore` puts files back exactly where they were.

## Supported formats

MP3, M4A/AAC/ALAC, FLAC, WAV, OGG, Opus, AIFF and WMA.

## Install from source

Requires Python 3.9 or newer.

```bash
git clone https://github.com/lexbeeguy/music_dup_remover
cd music_dup_remover
python -m pip install -e .
```

### fpcalc (Chromaprint)

Acoustic matching needs the `fpcalc` command-line tool.

| Platform | How to get it |
|---|---|
| Windows | Bundled in `bin/`, nothing to install. (Needs the Microsoft Visual C++ Redistributable, which most PCs already have.) |
| macOS | `brew install chromaprint` |
| Debian / Ubuntu | `sudo apt install libchromaprint-tools` |
| Other | Download from [acoustid.org/chromaprint](https://acoustid.org/chromaprint) |

To use a specific binary, set the `FPCALC` environment variable to its path.

Without `fpcalc`, music-dup still runs: it falls back to matching byte-identical copies and title/artist/duration metadata. The banner at the top of each command tells you which mode is active.

## Usage

### Command line

```bash
# 1. Scan a folder and list duplicate groups
music-dup scan ~/Music

# 2. Preview what would be moved
music-dup quarantine ~/Music --quarantine-dir ~/MusicQuarantine --dry-run

# 3. Move lower-quality copies to quarantine
music-dup quarantine ~/Music --quarantine-dir ~/MusicQuarantine

# Put everything back
music-dup restore

# Other commands
music-dup duplicates   # re-run matching on the cached scan (e.g. with a new threshold)
music-dup stats        # library size, duplicate groups, reclaimable space
music-dup reset        # clear the cache database
music-dup --version
```

Common options:

| Option | Commands | Default | Meaning |
|---|---|---|---|
| `--db PATH` | all | `music_dup.db` | Cache database location |
| `--similarity 0–1` | `scan`, `duplicates` | `0.85` | Minimum fingerprint similarity to count as a duplicate. Lower finds more matches but risks false positives. |
| `--tolerance SECONDS` | `scan`, `duplicates` | `3.5` | Maximum length difference between duplicates |
| `--quarantine-dir PATH` | `quarantine` | `quarantine` | Where duplicates are moved |
| `--dry-run` | `quarantine`, `restore` | off | Show the plan without moving anything |

`--db` and `--quarantine-dir` are relative to the folder you run the command from. Use the same `--db` for `scan`, `quarantine` and `restore`.

### Desktop app

```bash
music-dup gui          # or: music-dup-gui
```

The app has three tabs:

- **Scanner & Duplicates:** pick a folder, adjust the similarity and tolerance, and scan. Each group shows the copy that will be kept and checkboxes for the others. Click **Preview** to listen before deciding.
- **Quarantine Manager:** see and restore quarantined files individually or all at once.
- **Statistics:** library totals and a button to clear the cache.

## Safety

- Nothing is ever deleted. Duplicates are moved, and every move is recorded so it can be undone.
- The best-ranked copy in each group is never moved, and a group is skipped entirely if that copy is missing from disk.
- Restore never overwrites a file that has since appeared at the original location; it reports the conflict instead.
- If a move fails (for example, the file is open in another program), it is reported and the file stays where it was.
- Always run `quarantine --dry-run` first on a library you care about, and keep a backup.

Once you're happy with the results, you can delete the quarantine folder yourself to reclaim the space.

## Development

```bash
python -m pip install -e ".[dev]"
python -m pytest
```

Tests generate their own synthetic audio, so no music files are needed. Tests that exercise real Chromaprint matching run only when `fpcalc` is available; CI installs it on Linux and uses the bundled binary on Windows.

### Project layout

```
music_dup/
  cli.py               Click commands
  scanner.py           Folder walking, caching, stale-entry pruning
  metadata.py          Tag/audio-property extraction and quality scoring
  fingerprint.py       fpcalc discovery, fingerprinting, similarity matching
  duplicate_finder.py  Grouping and ranking
  quarantine.py        Moving files to and from quarantine
  db.py                SQLite cache and quarantine log
  ui.py                Terminal output (rich)
  gui/                 CustomTkinter desktop app and audio preview player
tests/
bin/                   Bundled fpcalc for Windows
```

### Building the Windows executable

Locally, on Windows:

```bash
python -m pip install . pyinstaller
pyinstaller music-dup.spec
```

The standalone app is written to `dist\music-dup-gui.exe` with `fpcalc.exe` bundled.

### Publishing a release

Pushing a version tag builds the executable on GitHub and publishes it as a release:

```bash
git tag v2.1.0
git push origin v2.1.0
```

The [release workflow](.github/workflows/release.yml) builds `music-dup-gui.exe` on Windows and attaches it to a new GitHub Release for that tag. To build without publishing, run the **release** workflow manually from the Actions tab; the `.exe` is then available under that run's artifacts.

Bump the version in `pyproject.toml` and `music_dup/__init__.py`, and add a `CHANGELOG.md` entry, before tagging a new version.

## License

[MIT](LICENSE)

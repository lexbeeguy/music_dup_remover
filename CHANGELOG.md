# Changelog

## 2.2.0

Merges the performance work from the unreleased local "Version 2.1" commit (`49cf438`) with the 2.1.0 release.

### Added
- **Parallel scanning:** new and changed files are fingerprinted concurrently (up to 32 workers by default; `scan_directory(..., max_workers=N)` to override). Results are written to the database in batches of 200.
- **Faster matching:** files are sorted by length and each is compared only with others of similar length, instead of with every file in the library.
- **Long Windows paths:** files in folders deeper than the classic 260-character limit can be scanned, quarantined and restored.
- **Desktop app paging:** duplicate groups are shown 50 per page with Previous/Next buttons, so large libraries stay responsive.
- A database index on track duration.
- Ties in quality ranking are broken by file ID, so the same copy is always kept.

### Fixed (in the merged code)
- With a length tolerance of 0, the faster matcher skipped the length check entirely instead of requiring equal lengths.
- On Windows, files with very long paths were treated as deleted by stale-entry cleanup and re-fingerprinted on every scan, because the cache check and cleanup didn't use the long-path form.
- Scan progress didn't reach 100% when some files failed the cache check.
- A new scan in the desktop app now starts on page 1.

### Changed
- Scanning uses a thread pool everywhere, rather than separate processes outside the `.exe`. The heavy work already runs in separate `fpcalc` processes, so threads keep all cores busy. This also avoids slow process start-up on Windows and behaves the same as the packaged app.

## 2.1.0

A reliability release on top of 2.0: bug fixes, a much larger test suite, CI and documentation. Developed with Claude (earlier versions were built with Antigravity).

### Fixed

**Data safety**
- Rescanning after a quarantine put the quarantined files back into duplicate groups, and the next quarantine moved them again inside the quarantine folder. The quarantine log then pointed at a path that no longer existed, so `restore` couldn't find them. Quarantined files are now left out of duplicate matching until they're restored.
- `restore` could silently overwrite a file that had since appeared at the original location (macOS/Linux). It now refuses and reports the conflict.
- Two duplicates from outside the scanned folder with the same filename were given the same quarantine path, so the second move overwrote the first. Destinations are now reserved across the whole batch.
- If the database update failed after a file was moved, the file was left in quarantine without a record. The move is now undone.
- A group is skipped if the copy that would be kept no longer exists, so the remaining copies aren't all quarantined.
- `restore` now reports quarantined files that are missing instead of skipping them silently.

**Matching accuracy**
- Any title containing a period was treated as a file path, so "Mr. Brightside" and "Mr. Jones" both became "mr" and could be grouped as duplicates. Tags and filenames are now normalized separately.
- Leading numbers were stripped from title tags ("99 Problems" became "problems"). They're now only stripped from filenames, where they're track numbers.
- Two unreadable files with the same name in different folders were reported as 100% matches. Error placeholders now never match.
- Deleted files stayed in the cache, kept appearing in duplicate groups and inflated the reclaimable-space total. Each scan now removes entries for files under the scanned folder that no longer exist.

**Platform and reliability**
- The bundled Windows `fpcalc.exe` was picked first on macOS and Linux, where it can't run, hiding a working `fpcalc` on the PATH. The `.exe` is now ignored off Windows, and the `FPCALC` environment variable takes priority.
- Database connections were never closed (`with sqlite3.connect()` only commits), leaking file handles and keeping the database locked on Windows.
- The audio preview kept the file open after stopping, which blocked quarantining that file on Windows. The player now releases the file.
- `fpcalc` could hang forever on a corrupt file; it now times out after 120 s.
- Fingerprint comparison relied on a private pyacoustid function (`acoustid._match_fingerprints`). The same algorithm is now implemented in the project and tested against pyacoustid's.
- `pip install .` failed because `pyproject.toml` referenced a README that didn't exist.

**Interface**
- Bracketed text in filenames and tags (such as `Song [live].mp3`) was swallowed by the terminal formatter, and a name like `[/live]` crashed the CLI. All user text is now escaped.
- `quarantine` and `restore` now list files that couldn't be moved, and the space-freed total counts only files that actually moved.
- The desktop window ignored its intended 1100×780 size (malformed geometry string).
- A scan error in the desktop app left the **Start Scan** button disabled for good. Errors are now shown and the button re-enabled.
- `--similarity` is validated to 0–1 and `--tolerance` to ≥ 0.
- Added `music-dup --version`. The banner now shows the detected `fpcalc` version instead of a hard-coded one.
- The library default similarity threshold (0.70) didn't match the CLI and GUI (0.85). All now use 0.85.

### Added
- `README.md` and an MIT `LICENSE`.
- A test suite of 65 tests, up from 6. It covers title normalization, fingerprint matching, fpcalc discovery, cache pruning, the quarantine/restore lifecycle and the CLI, with a regression test for each fix above.
- GitHub Actions CI running on Linux (Python 3.9–3.13) and Windows, with real Chromaprint fingerprinting.
- A `dev` extra: `pip install -e ".[dev]"`.
- A release workflow that builds `music-dup-gui.exe` on GitHub and attaches it to a GitHub Release when a version tag is pushed.

## 2.0.0

- CustomTkinter desktop app with audio preview, per-file quarantine and restore selection, and a standalone Windows executable.
- Windows Media Player playback for M4A/AAC previews.
- No console window flashing during fingerprinting on Windows.
- Audio preview stops before quarantine/restore so files aren't locked; move errors are reported.

## 1.0.0

- Initial command-line tool: acoustic fingerprint scanning, quality ranking, and quarantine/restore.

# Changelog

## 1.5.0 - 2026-05-15

- Added a thread title line above each progress bar.
- Changed progress rows to `status: [bar] downloaded/total | status text`.
- Reduced console flicker by redrawing dashboard lines in place instead of clearing the full screen on every update.
- Throttled dashboard refreshes during fast download loops.

## 1.4.0 - 2026-05-15

- Removed the visible commands line from the console dashboard.
- Removed `list` and `ls` handling.
- Changed the input prompt to `Paste URL>`.

## 1.3.0 - 2026-05-15

- Stopped writing `.downloaded.json` and `.thread_info.json` inside thread download folders.
- Avoided AppData state files; no persistent JSON is written by the script.
- Added disk-based detection by original filename for existing downloads.
- Added cleanup for legacy metadata files in thread folders when those folders are opened again.

## 1.2.0 - 2026-05-15

- Replaced per-file download log spam with a compact progress dashboard.
- Added one progress bar per watched thread.
- Added downloaded/total counters for each watched thread.
- Kept URL entry available while the progress dashboard updates.

## 1.1.0 - 2026-05-15

- Added colored console output for the header, prompt, status messages, warnings, and errors.
- Added `--no-color` to force plain console output.
- Added colored prompt text.

## 1.0.0 - 2026-05-15

- Created the single-file `4chan_downloader.py` script.
- Added an interactive prompt for thread URLs.
- Added support for watching multiple threads at the same time.
- Added an independent 5-minute check cycle per thread.
- Added automatic saving to the current user's Downloads folder.
- Added fallback to the script folder when the default Downloads folder does not exist.
- Added original filename handling through the 4chan API.
- Added per-thread control files to prevent repeated downloads.
- Added initial documentation.

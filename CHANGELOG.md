# Changelog

## 1.2.0 - 2026-05-15

- Replaced per-file download log spam with a compact progress dashboard.
- Added one progress bar per watched thread.
- Added downloaded/total counters for each watched thread.
- Kept URL entry available while the progress dashboard updates.

## 1.1.0 - 2026-05-15

- Added colored console output for the header, prompt, status messages, warnings, and errors.
- Added `--no-color` to force plain console output.
- Changed the prompt text to `URL/command>`.

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

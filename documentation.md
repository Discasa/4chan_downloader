# Technical Documentation

## Overview

`4chan_downloader.py` is a single-file script that uses only the Python standard
library. It receives thread URLs from the console, starts one watcher per thread,
and downloads new files found through the 4chan JSON API.

The script reads thread data from:

```text
https://a.4cdn.org/{board}/thread/{thread_id}.json
```

It downloads media from:

```text
https://i.4cdn.org/{board}/{tim}{ext}
```

## Execution Flow

1. The user runs `python .\4chan_downloader.py`.
2. The script detects the current user's Downloads folder.
3. If the detected Downloads folder does not exist, the script uses its own
   folder as the output base.
4. The prompt accepts URLs or commands.
5. Each valid URL creates a `ThreadWatcher` in a separate Python thread.
6. The first check runs immediately.
7. Later checks run every 300 seconds for each watcher.
8. The `exit` command signals all watchers to stop.

## Console Dashboard

The script uses a compact dashboard instead of printing one line per downloaded
file. Each watched thread gets one line with:

- Thread key, such as `gif/30633210`.
- Progress bar.
- Downloaded and total media count.
- Current status.

On Windows, the script attempts to enable virtual terminal processing before
redrawing the dashboard. If the terminal does not support ANSI control sequences,
the script falls back to plain prompt output and the `list` command can be used
to print a progress snapshot.

Color output is disabled when:

- The `NO_COLOR` environment variable is set.
- The user runs the script with `--no-color`.

## Folder Names

The destination folder is created inside the configured downloads root. Folder
names use this priority:

1. Slug from the URL.
2. Thread subject returned by the API.
3. Opening post text with HTML removed.
4. Fallback `{board}-{thread_id}`.

Invalid Windows characters are replaced, and reserved names such as `CON`, `NUL`,
and `LPT1` are avoided.

## File Names

The script uses `filename` and `ext` from the thread API, preserving original
filenames when possible. When a filename collision happens, the `tim` identifier
is used to generate a unique filename.

Incomplete downloads temporarily use the `.part` extension and are moved to the
final name only after the file has been fully written.

## Local State

Each thread folder receives:

```text
.downloaded.json
.thread_info.json
```

`.downloaded.json` maps the `{tim}{ext}` key to the saved filename. This avoids
downloading a media item again after it has already been processed.

`.thread_info.json` stores the board, thread ID, and normalized thread URL.

## Error Handling

- HTTP 404 stops that thread watcher.
- HTTP 429 applies progressive waiting before retrying.
- Temporary network failures are logged and retried on the next cycle.
- Invalid URLs are ignored without stopping the program.

## Local Validation

Run:

```powershell
python -m py_compile 4chan_downloader.py
python .\4chan_downloader.py --help
```

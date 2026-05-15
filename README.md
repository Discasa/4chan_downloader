# 4chan_downloader

Interactive Python script for watching one or more 4chan threads and saving new
files automatically while the console stays open.

The project was inspired by the workflow of
[Exceen/4chan-downloader](https://github.com/Exceen/4chan-downloader), but this
version is consolidated into a single dependency-free script for direct Windows
use.

## Features

- Prompts for thread URLs in the console.
- Allows new threads to be added while the script keeps running.
- Watches as many threads as the user adds, each with its own cycle.
- Checks a thread immediately when the URL is added.
- Checks each thread again every 5 minutes by default.
- Saves files to the current Windows user's Downloads folder by default.
- Falls back to the script folder if the default Downloads folder does not exist.
- Creates one folder per thread.
- Preserves the original filenames returned by the 4chan API.
- Detects existing files by name so reopened threads only download new files.
- Shows a compact progress dashboard with one progress bar per thread.
- Displays the downloaded and total file counts for each watched thread.

## Requirements

- Python 3.10 or newer.
- Windows, Linux, or macOS. On Windows, the current user's Downloads folder is
  detected automatically.

No packages need to be installed. `requirements.txt` is included for tooling and
contains no external dependencies.

## Quick Start

Open a terminal in the project folder and run:

```powershell
python .\4chan_downloader.py
```

Paste a thread URL:

```text
https://boards.4chan.org/wg/thread/123456789/example-thread
```

While the script is open, paste more URLs to watch more threads.

The console keeps a compact dashboard instead of printing one line for every
downloaded file. Each thread appears with its board/thread ID, readable thread
name, progress bar, and `downloaded/total` counter:

```text
Threads
gif/30633210  Example thread name
  status: [########################]   184/184 | waiting 300s for next check
```

Press Ctrl+C to stop the script.

## Output Folder

By default, files are saved under:

```text
%USERPROFILE%\Downloads
```

If the detected Downloads folder does not exist, the script saves files in the
same folder as `4chan_downloader.py`.

Each thread gets its own folder inside Downloads. The folder name comes from the
URL slug when available. If the URL has no slug, the script tries to use the
thread subject or opening post text. If names collide, the board and thread ID
are added to keep the folders separate.

## Configuration

Configuration is done inside `4chan_downloader.py`, near the top of the file, in
the `CONFIGURATION` section.

Common settings:

```python
DOWNLOADS_DIR = ""
CHECK_INTERVAL_SECONDS = 300.0
DOWNLOAD_THROTTLE_SECONDS = 0.5
ENABLE_COLORS = True
ENABLE_DASHBOARD = True
PROGRESS_BAR_WIDTH = 24
```

Examples:

```python
DOWNLOADS_DIR = "D:\\4chan"
CHECK_INTERVAL_SECONDS = 600.0
ENABLE_COLORS = False
```

## State Tracking

Thread download folders are kept clean. The script does not create JSON files
inside those folders, and it does not keep state in AppData.

When a thread is opened again on another day, the script computes the expected
original filename for each media item. If that filename already exists in the
thread folder, the item is counted as already downloaded and skipped. Only
missing filenames are downloaded.

Older `.downloaded.json` and `.thread_info.json` files created by previous
versions are removed from a thread folder when that thread is opened again.

## Notice

Use this script responsibly and follow the site's rules, copyright restrictions,
and applicable laws. The project only automates downloads from URLs provided by
the user.

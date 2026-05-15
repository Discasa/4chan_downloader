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
- Tracks processed files to avoid repeated downloads.

## Requirements

- Python 3.10 or newer.
- Windows, Linux, or macOS. On Windows, the current user's Downloads folder is
  detected automatically.

No packages need to be installed.

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

Available commands:

```text
list
exit
```

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

## Options

Show help:

```powershell
python .\4chan_downloader.py --help
```

Main options:

```text
--refresh-time  Interval between checks, in seconds. Default: 300.
--throttle      Pause between downloads from the same thread. Default: 0.5.
--downloads-dir Alternate base folder for saved files.
```

Example with a custom output folder:

```powershell
python .\4chan_downloader.py --downloads-dir "D:\4chan"
```

## Control Files

Inside each thread folder, the script creates:

```text
.downloaded.json
.thread_info.json
```

These files store which media items have already been processed and basic thread
metadata. They live next to the downloaded files, not inside this repository.

## Notice

Use this script responsibly and follow the site's rules, copyright restrictions,
and applicable laws. The project only automates downloads from URLs provided by
the user.

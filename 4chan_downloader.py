#!/usr/bin/env python3
import argparse
import html
import json
import os
import re
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)
THREAD_API_TEMPLATE = "https://a.4cdn.org/{board}/thread/{thread_id}.json"
MEDIA_URL_TEMPLATE = "https://i.4cdn.org/{board}/{tim}{ext}"
INVALID_WINDOWS_CHARS = r'<>:"/\|?*'
RESERVED_WINDOWS_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}

print_lock = threading.Lock()


@dataclass(frozen=True)
class ThreadRef:
    board: str
    thread_id: str
    slug: str | None
    source_url: str

    @property
    def key(self) -> str:
        return f"{self.board}/{self.thread_id}"


class RateLimited(Exception):
    pass


def log(message: str) -> None:
    with print_lock:
        stamp = datetime.now().strftime("%H:%M:%S")
        print(f"\n[{stamp}] {message}", flush=True)


def get_windows_downloads_folder() -> Path:
    if os.name == "nt":
        try:
            import winreg

            guid = "{374DE290-123F-4565-9164-39C4925E467B}"
            key_path = r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                for value_name in (guid, "Downloads"):
                    try:
                        value, _ = winreg.QueryValueEx(key, value_name)
                        return Path(os.path.expandvars(value))
                    except FileNotFoundError:
                        pass
        except Exception:
            pass

        # Fallback for normal Windows profiles.
        user_profile = os.environ.get("USERPROFILE")
        if user_profile:
            return Path(user_profile) / "Downloads"

    return Path.home() / "Downloads"


def get_default_output_folder() -> Path:
    downloads_folder = get_windows_downloads_folder()
    if downloads_folder.is_dir():
        return downloads_folder
    return Path(__file__).resolve().parent


def strip_html(value: str) -> str:
    value = re.sub(r"<br\s*/?>", " ", value, flags=re.IGNORECASE)
    value = re.sub(r"<[^>]+>", " ", value)
    value = html.unescape(value)
    return re.sub(r"\s+", " ", value).strip()


def sanitize_windows_name(value: str, fallback: str, max_length: int = 140) -> str:
    value = urllib.parse.unquote(value or "")
    value = html.unescape(value)
    value = re.sub(r"[\x00-\x1f]+", " ", value)
    translation = str.maketrans({char: "_" for char in INVALID_WINDOWS_CHARS})
    value = value.translate(translation)
    value = re.sub(r"\s+", " ", value).strip(" .")
    value = re.sub(r"_+", "_", value)

    if not value:
        value = fallback

    if value.upper() in RESERVED_WINDOWS_NAMES:
        value = f"{value}_"

    if len(value) > max_length:
        value = value[:max_length].rstrip(" .")

    return value or fallback


def sanitize_file_name(stem: str, ext: str, fallback: str) -> str:
    safe_ext = re.sub(r"[^A-Za-z0-9.]", "", ext or "")
    if safe_ext and not safe_ext.startswith("."):
        safe_ext = f".{safe_ext}"

    safe_stem = sanitize_windows_name(stem, fallback=fallback, max_length=180 - len(safe_ext))
    return f"{safe_stem}{safe_ext}"


def parse_thread_url(raw_url: str) -> ThreadRef:
    url = raw_url.strip()
    if not url:
        raise ValueError("Empty URL.")

    if not re.match(r"^https?://", url, flags=re.IGNORECASE):
        url = "https://" + url

    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc.lower()
    if not host:
        raise ValueError("URL has no domain.")

    path_parts = [urllib.parse.unquote(part) for part in parsed.path.split("/") if part]
    try:
        thread_index = path_parts.index("thread")
    except ValueError as exc:
        raise ValueError("URL does not look like a 4chan thread URL.") from exc

    if thread_index < 1 or thread_index + 1 >= len(path_parts):
        raise ValueError("Incomplete thread URL.")

    board = path_parts[thread_index - 1].lower()
    thread_id = path_parts[thread_index + 1].split("#", 1)[0]
    slug_parts = path_parts[thread_index + 2 :]
    slug = "-".join(slug_parts).split("#", 1)[0] if slug_parts else None
    slug = slug or None

    if not re.match(r"^[a-z0-9]+$", board):
        raise ValueError("Invalid board in URL.")
    if not re.match(r"^\d+$", thread_id):
        raise ValueError("Invalid thread ID in URL.")
    if "4chan.org" not in host and "4channel.org" not in host:
        raise ValueError("Use a boards.4chan.org or boards.4channel.org URL.")

    normalized = f"https://boards.4chan.org/{board}/thread/{thread_id}"
    if slug:
        normalized += "/" + urllib.parse.quote(slug)

    return ThreadRef(board=board, thread_id=thread_id, slug=slug, source_url=normalized)


def request_json(url: str) -> dict:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json,text/plain,*/*",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def request_bytes(url: str, referer: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "*/*",
            "Referer": referer,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            raise RateLimited() from exc
        raise


def load_json_file(path: Path, default):
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as file:
            return json.load(file)
    except (OSError, json.JSONDecodeError):
        return default


def save_json_file(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    with temp_path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2, sort_keys=True)
    temp_path.replace(path)


def thread_title_from_posts(ref: ThreadRef, posts: list[dict]) -> str:
    if ref.slug:
        return sanitize_windows_name(ref.slug.replace("-", " "), fallback=f"{ref.board}-{ref.thread_id}")

    if posts:
        opening_post = posts[0]
        subject = opening_post.get("sub")
        comment = opening_post.get("com")
        if subject:
            return sanitize_windows_name(str(subject), fallback=f"{ref.board}-{ref.thread_id}")
        if comment:
            clean_comment = strip_html(str(comment))
            return sanitize_windows_name(clean_comment, fallback=f"{ref.board}-{ref.thread_id}")

    return sanitize_windows_name(f"{ref.board}-{ref.thread_id}", fallback=f"{ref.board}-{ref.thread_id}")


def choose_existing_or_unique_path(
    directory: Path,
    file_name: str,
    post_key: str,
    expected_size: int | None,
) -> Path:
    candidate = directory / file_name
    if not candidate.exists():
        return candidate

    if expected_size is not None:
        try:
            if candidate.stat().st_size == expected_size:
                return candidate
        except OSError:
            pass

    stem = candidate.stem
    suffix = candidate.suffix
    unique = directory / f"{stem} ({post_key}){suffix}"
    counter = 2
    while unique.exists():
        unique = directory / f"{stem} ({post_key}-{counter}){suffix}"
        counter += 1
    return unique


class ThreadWatcher:
    def __init__(
        self,
        ref: ThreadRef,
        downloads_root: Path,
        refresh_time: float,
        throttle: float,
        manager: "WatchManager",
    ) -> None:
        self.ref = ref
        self.downloads_root = downloads_root
        self.refresh_time = refresh_time
        self.throttle = throttle
        self.manager = manager
        self.stop_event = threading.Event()
        self.worker = threading.Thread(target=self.run, name=f"watch-{ref.board}-{ref.thread_id}", daemon=True)
        self.directory: Path | None = None

    def start(self) -> None:
        self.worker.start()

    def stop(self) -> None:
        self.stop_event.set()

    def join(self, timeout: float | None = None) -> None:
        self.worker.join(timeout)

    def run(self) -> None:
        backoff = 0.0
        while not self.stop_event.is_set():
            try:
                new_count = self.poll_once()
                backoff = 0.0
                if new_count:
                    log(f"{self.ref.key}: {new_count} new file(s).")
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    log(f"{self.ref.key}: thread unavailable or archived. Watcher stopped.")
                    break
                if exc.code == 429:
                    backoff = min(backoff + 30.0, 300.0)
                    log(f"{self.ref.key}: rate limited. Trying again in {int(backoff)}s.")
                else:
                    log(f"{self.ref.key}: HTTP {exc.code}. Trying again on the next cycle.")
            except RateLimited:
                backoff = min(backoff + 30.0, 300.0)
                log(f"{self.ref.key}: rate limited while downloading. Trying again in {int(backoff)}s.")
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                log(f"{self.ref.key}: temporary failure ({exc}).")
            except Exception as exc:
                log(f"{self.ref.key}: unexpected error ({exc}).")

            wait_time = backoff or self.refresh_time
            self.stop_event.wait(wait_time)

        self.manager.mark_stopped(self.ref.key)

    def poll_once(self) -> int:
        api_url = THREAD_API_TEMPLATE.format(board=self.ref.board, thread_id=self.ref.thread_id)
        payload = request_json(api_url)
        posts = payload.get("posts", [])

        if self.directory is None:
            folder_name = thread_title_from_posts(self.ref, posts)
            self.directory = self.manager.allocate_directory(self.ref, folder_name)
            self.directory.mkdir(parents=True, exist_ok=True)
            save_json_file(
                self.directory / ".thread_info.json",
                {
                    "board": self.ref.board,
                    "thread_id": self.ref.thread_id,
                    "source_url": self.ref.source_url,
                },
            )
            log(f"{self.ref.key}: saving to {self.directory}")

        downloaded_path = self.directory / ".downloaded.json"
        downloaded = load_json_file(downloaded_path, {})
        if not isinstance(downloaded, dict):
            downloaded = {}

        referer = f"https://boards.4chan.org/{self.ref.board}/thread/{self.ref.thread_id}"
        new_count = 0

        for post in posts:
            if self.stop_event.is_set():
                break
            if "tim" not in post or "ext" not in post:
                continue

            tim = str(post["tim"])
            ext = str(post["ext"])
            post_key = f"{tim}{ext}"
            if post_key in downloaded:
                continue

            original_stem = str(post.get("filename") or tim)
            output_name = sanitize_file_name(original_stem, ext, fallback=tim)
            expected_size = post.get("fsize")
            if not isinstance(expected_size, int):
                expected_size = None

            output_path = choose_existing_or_unique_path(self.directory, output_name, post_key, expected_size)
            if output_path.exists():
                downloaded[post_key] = output_path.name
                save_json_file(downloaded_path, downloaded)
                continue

            media_url = MEDIA_URL_TEMPLATE.format(board=self.ref.board, tim=tim, ext=ext)
            data = request_bytes(media_url, referer=referer)
            temp_path = output_path.with_suffix(output_path.suffix + ".part")
            try:
                with temp_path.open("wb") as file:
                    file.write(data)
                temp_path.replace(output_path)
            finally:
                if temp_path.exists():
                    try:
                        temp_path.unlink()
                    except OSError:
                        pass

            downloaded[post_key] = output_path.name
            save_json_file(downloaded_path, downloaded)
            new_count += 1
            log(f"{self.ref.key}: downloaded {output_path.name}")
            self.stop_event.wait(self.throttle)

        return new_count


class WatchManager:
    def __init__(self, downloads_root: Path, refresh_time: float, throttle: float) -> None:
        self.downloads_root = downloads_root
        self.refresh_time = refresh_time
        self.throttle = throttle
        self.watchers: dict[str, ThreadWatcher] = {}
        self.directories: dict[str, str] = {}
        self.lock = threading.Lock()

    def add(self, raw_url: str) -> None:
        ref = parse_thread_url(raw_url)
        with self.lock:
            existing = self.watchers.get(ref.key)
            if existing and existing.worker.is_alive():
                log(f"{ref.key}: already being watched.")
                return

            watcher = ThreadWatcher(ref, self.downloads_root, self.refresh_time, self.throttle, self)
            self.watchers[ref.key] = watcher
            watcher.start()
            log(f"{ref.key}: watcher started.")

    def allocate_directory(self, ref: ThreadRef, folder_name: str) -> Path:
        base_name = sanitize_windows_name(folder_name, fallback=f"{ref.board}-{ref.thread_id}")
        with self.lock:
            candidate = self.downloads_root / base_name
            assigned_key = self.directories.get(str(candidate).lower())
            if assigned_key in (None, ref.key):
                self.directories[str(candidate).lower()] = ref.key
                return candidate

            suffix = f"{ref.board}-{ref.thread_id}"
            candidate = self.downloads_root / sanitize_windows_name(f"{base_name} {suffix}", fallback=suffix)
            counter = 2
            while str(candidate).lower() in self.directories:
                candidate = self.downloads_root / sanitize_windows_name(
                    f"{base_name} {suffix}-{counter}",
                    fallback=f"{suffix}-{counter}",
                )
                counter += 1

            self.directories[str(candidate).lower()] = ref.key
            return candidate

    def mark_stopped(self, key: str) -> None:
        with self.lock:
            watcher = self.watchers.get(key)
            if watcher and not watcher.worker.is_alive():
                return
        log(f"{key}: watcher stopped.")

    def list_threads(self) -> None:
        with self.lock:
            if not self.watchers:
                log("No threads are being watched.")
                return
            for key, watcher in self.watchers.items():
                status = "running" if watcher.worker.is_alive() else "stopped"
                directory = watcher.directory or "(waiting for first check)"
                log(f"{key}: {status} - {directory}")

    def stop_all(self) -> None:
        with self.lock:
            watchers = list(self.watchers.values())
        for watcher in watchers:
            watcher.stop()
        for watcher in watchers:
            watcher.join(timeout=5)


def extract_urls_or_command(line: str) -> list[str]:
    matches = re.findall(r"https?://\S+", line, flags=re.IGNORECASE)
    if matches:
        return matches
    return [line.strip()] if line.strip() else []


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Watch one or more 4chan threads and download files to the Downloads folder."
    )
    parser.add_argument(
        "--refresh-time",
        type=float,
        default=300.0,
        help="Interval in seconds between checks for each thread.",
    )
    parser.add_argument(
        "--throttle",
        type=float,
        default=0.5,
        help="Pause in seconds between downloads from the same thread.",
    )
    parser.add_argument(
        "--downloads-dir",
        type=Path,
        default=None,
        help=(
            "Optional base folder. Default: current user's Downloads folder, "
            "or the script folder if Downloads does not exist."
        ),
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    downloads_root = args.downloads_dir or get_default_output_folder()
    downloads_root.mkdir(parents=True, exist_ok=True)

    manager = WatchManager(
        downloads_root=downloads_root,
        refresh_time=max(args.refresh_time, 1.0),
        throttle=max(args.throttle, 0.0),
    )

    print("Interactive 4chan downloader")
    print(f"Base folder: {downloads_root}")
    print("Paste a thread URL and press Enter.")
    print("While the script is open, paste new URLs to watch more threads.")
    print("Each thread is checked immediately when added, then checked again every 5 minutes.")
    print("Commands: list, exit")

    try:
        while True:
            line = input("URL/comando> ").strip()
            if not line:
                continue

            command = line.lower()
            if command in {"exit", "quit", "q"}:
                break
            if command in {"list", "ls"}:
                manager.list_threads()
                continue

            for url in extract_urls_or_command(line):
                try:
                    manager.add(url)
                except ValueError as exc:
                    log(f"URL ignored: {exc}")
    except KeyboardInterrupt:
        print()
    finally:
        log("Stopping watchers...")
        manager.stop_all()

    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
import argparse
import html
import json
import os
import re
import shutil
import sys
import threading
import time
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
LEGACY_METADATA_FILES = (".downloaded.json", ".thread_info.json")
RESERVED_WINDOWS_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}

ANSI_ENABLED = False
COLOR_ENABLED = False
COLOR_CODES = {
    "reset": "\033[0m",
    "bold": "\033[1m",
    "dim": "\033[2m",
    "red": "\033[31m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "blue": "\033[34m",
    "magenta": "\033[35m",
    "cyan": "\033[36m",
    "gray": "\033[90m",
}


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


def enable_ansi_console() -> bool:
    if not sys.stdout.isatty():
        return False
    if os.name != "nt":
        return True

    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_uint()
        if not handle or handle == -1:
            return False
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        return bool(kernel32.SetConsoleMode(handle, mode.value | 0x0004))
    except Exception:
        return False


def configure_colors(disabled: bool) -> None:
    global ANSI_ENABLED, COLOR_ENABLED
    ANSI_ENABLED = enable_ansi_console()
    COLOR_ENABLED = ANSI_ENABLED and not disabled and not os.environ.get("NO_COLOR")


def colorize(text: str, *styles: str) -> str:
    if not COLOR_ENABLED:
        return text
    prefix = "".join(COLOR_CODES[style] for style in styles if style in COLOR_CODES)
    if not prefix:
        return text
    return f"{prefix}{text}{COLOR_CODES['reset']}"


def progress_bar(done: int, total: int, width: int = 24) -> str:
    if total <= 0:
        filled = 0
    else:
        filled = int(width * min(done, total) / total)
    return "[" + ("#" * filled).ljust(width, "-") + "]"


def truncate_text(text: str, max_length: int) -> str:
    if max_length <= 0:
        return ""
    if len(text) <= max_length:
        return text
    if max_length <= 3:
        return text[:max_length]
    return text[: max_length - 3] + "..."


@dataclass
class ThreadProgress:
    key: str
    status: str = "queued"
    downloaded: int = 0
    total: int = 0
    new_files: int = 0
    directory: str = ""
    message: str = ""
    updated_at: str = ""


class ConsoleUI:
    def __init__(self, downloads_root: Path, refresh_time: float) -> None:
        self.downloads_root = downloads_root
        self.refresh_time = refresh_time
        self.statuses: dict[str, ThreadProgress] = {}
        self.order: list[str] = []
        self.input_buffer = ""
        self.notice = ""
        self.notice_status = "muted"
        self.lock = threading.Lock()
        self.dashboard_enabled = ANSI_ENABLED and sys.stdout.isatty() and os.name == "nt"

    def set_input(self, value: str) -> None:
        with self.lock:
            self.input_buffer = value

    def update_thread(self, key: str, **changes) -> None:
        with self.lock:
            status = self.statuses.get(key)
            if status is None:
                status = ThreadProgress(key=key)
                self.statuses[key] = status
                self.order.append(key)
            for name, value in changes.items():
                setattr(status, name, value)
            status.updated_at = datetime.now().strftime("%H:%M:%S")
            if self.dashboard_enabled:
                self.render_locked()

    def set_notice(self, message: str, status: str = "muted") -> None:
        with self.lock:
            self.notice = message
            self.notice_status = status
            if self.dashboard_enabled:
                self.render_locked()

    def print_header(self) -> None:
        if self.dashboard_enabled:
            with self.lock:
                self.render_locked()
            return

        print(colorize("Interactive 4chan downloader", "bold", "green"))
        print(f"{colorize('Base folder:', 'cyan')} {self.downloads_root}")
        print(f"{colorize('Check interval:', 'cyan')} {int(self.refresh_time)} seconds")
        print("Paste a thread URL and press Enter.")

    def render(self) -> None:
        if not self.dashboard_enabled:
            self.print_snapshot()
            return
        with self.lock:
            self.render_locked()

    def print_snapshot(self) -> None:
        with self.lock:
            width = shutil.get_terminal_size((100, 30)).columns
            if not self.order:
                print("No threads are being watched.")
                return
            for key in self.order:
                print(self.format_thread_line(self.statuses[key], width))

    def render_locked(self) -> None:
        width = shutil.get_terminal_size((100, 30)).columns
        lines = [
            colorize("Interactive 4chan downloader", "bold", "green"),
            f"{colorize('Base folder:', 'cyan')} {self.downloads_root}",
            f"{colorize('Check interval:', 'cyan')} {int(self.refresh_time)} seconds",
        ]
        if self.notice:
            notice_color = {
                "error": "red",
                "warning": "yellow",
                "success": "green",
            }.get(self.notice_status, "gray")
            lines.append(colorize(self.notice, notice_color))
        lines.extend(["", colorize("Threads", "bold", "cyan")])

        if not self.order:
            lines.append(colorize("No threads are being watched.", "gray"))
        else:
            for key in self.order:
                progress = self.statuses[key]
                lines.append(self.format_thread_line(progress, width))

        lines.extend(["", colorize("Paste URL> ", "bold", "cyan") + self.input_buffer])
        sys.stdout.write("\033[2J\033[H" + "\n".join(lines))
        sys.stdout.flush()

    def format_thread_line(self, progress: ThreadProgress, width: int) -> str:
        bar = progress_bar(progress.downloaded, progress.total)
        count = f"{progress.downloaded}/{progress.total}" if progress.total else "0/0"
        status_color = {
            "downloading": "green",
            "checking": "cyan",
            "waiting": "yellow",
            "queued": "yellow",
            "stopped": "gray",
            "error": "red",
        }.get(progress.status, "cyan")
        prefix = f"{progress.key:<16} {bar} {count:>9} "
        detail = progress.message or progress.status
        visible_budget = max(width - len(prefix), 20)
        line = prefix + truncate_text(detail, visible_budget)
        return colorize(line, status_color)

    def message(self, key: str, text: str, status: str = "checking") -> None:
        self.update_thread(key, status=status, message=text)


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


def remove_legacy_metadata_files(directory: Path) -> None:
    for file_name in LEGACY_METADATA_FILES:
        path = directory / file_name
        try:
            if path.is_file():
                path.unlink()
        except OSError:
            pass


def collect_media_items(posts: list[dict]) -> list[dict]:
    seen = set()
    media_items = []
    for post in posts:
        if "tim" not in post or "ext" not in post:
            continue
        key = f"{post['tim']}{post['ext']}"
        if key in seen:
            continue
        seen.add(key)
        media_items.append(post)
    return media_items


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
                self.manager.ui.message(self.ref.key, "checking thread", "checking")
                self.poll_once()
                backoff = 0.0
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    self.manager.ui.message(self.ref.key, "thread unavailable or archived", "stopped")
                    break
                if exc.code == 429:
                    backoff = min(backoff + 30.0, 300.0)
                    self.manager.ui.message(
                        self.ref.key,
                        f"rate limited, retrying in {int(backoff)}s",
                        "waiting",
                    )
                else:
                    self.manager.ui.message(
                        self.ref.key,
                        f"HTTP {exc.code}, retrying on next cycle",
                        "waiting",
                    )
            except RateLimited:
                backoff = min(backoff + 30.0, 300.0)
                self.manager.ui.message(
                    self.ref.key,
                    f"rate limited while downloading, retrying in {int(backoff)}s",
                    "waiting",
                )
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                self.manager.ui.message(self.ref.key, f"temporary failure: {exc}", "waiting")
            except Exception as exc:
                self.manager.ui.message(self.ref.key, f"unexpected error: {exc}", "error")

            wait_time = backoff or self.refresh_time
            if not self.stop_event.is_set() and backoff == 0.0:
                self.manager.ui.message(self.ref.key, f"waiting {int(wait_time)}s for next check", "waiting")
            self.stop_event.wait(wait_time)

        self.manager.mark_stopped(self.ref.key)

    def poll_once(self) -> int:
        api_url = THREAD_API_TEMPLATE.format(board=self.ref.board, thread_id=self.ref.thread_id)
        payload = request_json(api_url)
        posts = payload.get("posts", [])
        media_items = collect_media_items(posts)
        total = len(media_items)

        if self.directory is None:
            folder_name = thread_title_from_posts(self.ref, posts)
            self.directory = self.manager.allocate_directory(self.ref, folder_name)
            self.directory.mkdir(parents=True, exist_ok=True)
            remove_legacy_metadata_files(self.directory)

        referer = f"https://boards.4chan.org/{self.ref.board}/thread/{self.ref.thread_id}"
        new_count = 0
        completed_count = 0
        self.manager.ui.update_thread(
            self.ref.key,
            status="downloading",
            downloaded=completed_count,
            total=total,
            new_files=0,
            directory=str(self.directory),
            message="checking files",
        )

        for post in media_items:
            if self.stop_event.is_set():
                break

            tim = str(post["tim"])
            ext = str(post["ext"])
            post_key = f"{tim}{ext}"

            original_stem = str(post.get("filename") or tim)
            output_name = sanitize_file_name(original_stem, ext, fallback=tim)
            output_path = self.directory / output_name
            if output_path.exists():
                completed_count += 1
                self.manager.ui.update_thread(
                    self.ref.key,
                    status="downloading",
                    downloaded=completed_count,
                    total=total,
                    new_files=new_count,
                    directory=str(self.directory),
                    message="checking files",
                )
                continue

            self.manager.ui.update_thread(
                self.ref.key,
                status="downloading",
                downloaded=completed_count,
                total=total,
                new_files=new_count,
                directory=str(self.directory),
                message="downloading",
            )
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

            new_count += 1
            completed_count += 1
            self.manager.ui.update_thread(
                self.ref.key,
                status="downloading",
                downloaded=completed_count,
                total=total,
                new_files=new_count,
                directory=str(self.directory),
                message="downloading",
            )
            self.stop_event.wait(self.throttle)

        self.manager.ui.update_thread(
            self.ref.key,
            status="waiting",
            downloaded=completed_count,
            total=total,
            new_files=new_count,
            directory=str(self.directory),
            message="check complete",
        )
        return new_count


class WatchManager:
    def __init__(self, downloads_root: Path, refresh_time: float, throttle: float, ui: ConsoleUI) -> None:
        self.downloads_root = downloads_root
        self.refresh_time = refresh_time
        self.throttle = throttle
        self.ui = ui
        self.watchers: dict[str, ThreadWatcher] = {}
        self.directories: dict[str, str] = {}
        self.lock = threading.Lock()

    def add(self, raw_url: str) -> None:
        ref = parse_thread_url(raw_url)
        with self.lock:
            existing = self.watchers.get(ref.key)
            if existing and existing.worker.is_alive():
                self.ui.message(ref.key, "already being watched", "waiting")
                self.ui.set_notice(f"{ref.key} is already being watched.", "warning")
                return

            watcher = ThreadWatcher(ref, self.downloads_root, self.refresh_time, self.throttle, self)
            self.watchers[ref.key] = watcher
            self.ui.update_thread(ref.key, status="queued", message="queued")
            watcher.start()
            self.ui.set_notice(f"Watching {ref.key}.", "success")

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
        self.ui.message(key, "watcher stopped", "stopped")

    def stop_all(self) -> None:
        with self.lock:
            watchers = list(self.watchers.values())
        for watcher in watchers:
            watcher.stop()
        for watcher in watchers:
            watcher.join(timeout=5)


def extract_urls_from_input(line: str) -> list[str]:
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
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable colored console output.",
    )
    return parser


def process_input_line(line: str, manager: WatchManager) -> bool:
    if not line:
        return True

    lowered = line.lower()
    if lowered in {"exit", "quit", "q"}:
        return False
    for url in extract_urls_from_input(line):
        try:
            manager.add(url)
        except ValueError as exc:
            manager.ui.set_notice(f"URL ignored: {exc}", "warning")
    return True


def run_dashboard_input_loop(manager: WatchManager, ui: ConsoleUI) -> None:
    if os.name != "nt":
        run_prompt_input_loop(manager)
        return

    import msvcrt

    buffer: list[str] = []
    ui.render()
    while True:
        while msvcrt.kbhit():
            char = msvcrt.getwch()
            if char in {"\x00", "\xe0"}:
                msvcrt.getwch()
                continue
            if char == "\x03":
                raise KeyboardInterrupt
            if char in {"\r", "\n"}:
                line = "".join(buffer).strip()
                buffer.clear()
                ui.set_input("")
                ui.render()
                if not process_input_line(line, manager):
                    return
                continue
            if char == "\b":
                if buffer:
                    buffer.pop()
                    ui.set_input("".join(buffer))
                    ui.render()
                continue
            if char >= " ":
                buffer.append(char)
                ui.set_input("".join(buffer))
                ui.render()
        time.sleep(0.05)


def run_prompt_input_loop(manager: WatchManager) -> None:
    while True:
        line = input(colorize("Paste URL> ", "bold", "cyan")).strip()
        if not process_input_line(line, manager):
            return


def main() -> int:
    args = build_parser().parse_args()
    configure_colors(args.no_color)
    downloads_root = args.downloads_dir or get_default_output_folder()
    downloads_root.mkdir(parents=True, exist_ok=True)

    ui = ConsoleUI(downloads_root=downloads_root, refresh_time=max(args.refresh_time, 1.0))
    manager = WatchManager(
        downloads_root=downloads_root,
        refresh_time=max(args.refresh_time, 1.0),
        throttle=max(args.throttle, 0.0),
        ui=ui,
    )

    ui.print_header()

    try:
        if ui.dashboard_enabled:
            run_dashboard_input_loop(manager, ui)
        else:
            run_prompt_input_loop(manager)
    except KeyboardInterrupt:
        print()
    finally:
        ui.update_thread("system", status="stopped", message="stopping watchers")
        manager.stop_all()

    return 0


if __name__ == "__main__":
    sys.exit(main())

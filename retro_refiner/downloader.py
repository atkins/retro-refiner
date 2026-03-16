"""Download operations: file downloading with aria2c, curl, or urllib.

Standalone implementations extracted from the monolith. Uses plain print
for progress output instead of Console/Style dependencies.
"""
import atexit
import json
import os
import shutil
import subprocess
import sys
import threading
import time as _time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Platform detection
# ---------------------------------------------------------------------------

WINDOWS = sys.platform == 'win32'

if WINDOWS:
    try:
        import msvcrt  # pylint: disable=import-error
        HAS_MSVCRT = True
    except ImportError:
        HAS_MSVCRT = False
    HAS_TERMIOS = False
else:
    HAS_MSVCRT = False
    try:
        import termios  # pylint: disable=import-error
        import tty  # pylint: disable=import-error
        HAS_TERMIOS = True
    except ImportError:
        HAS_TERMIOS = False

# Subprocess kwargs to hide console windows on Windows
_SUBPROCESS_NO_WINDOW = (
    {"creationflags": subprocess.CREATE_NO_WINDOW} if WINDOWS else {}
)

# Unicode symbols with ASCII fallbacks
if WINDOWS:
    SYM_CHECK = '[OK]'
    SYM_CROSS = '[X]'
    SYM_ARROW = 'v'
    SYM_ARROW_RIGHT = '->'
    SYM_CIRCLE = 'o'
    SYM_BLOCK_FULL = '#'
    SYM_BLOCK_LIGHT = '-'
    SYM_HLINE = '-'
else:
    SYM_CHECK = '\u2713'
    SYM_CROSS = '\u2717'
    SYM_ARROW = '\u2193'
    SYM_ARROW_RIGHT = '\u2192'
    SYM_CIRCLE = '\u25CB'
    SYM_BLOCK_FULL = '\u2588'
    SYM_BLOCK_LIGHT = '\u2591'
    SYM_HLINE = '\u2500'


# ---------------------------------------------------------------------------
# Process management for aria2c subprocesses
# ---------------------------------------------------------------------------

_aria2c_processes: set = set()
_aria2c_lock = threading.Lock()


def _register_aria2c_process(proc: subprocess.Popen) -> None:
    """Register an aria2c process for cleanup tracking."""
    with _aria2c_lock:
        _aria2c_processes.add(proc)


def _unregister_aria2c_process(proc: subprocess.Popen) -> None:
    """Unregister an aria2c process from cleanup tracking."""
    with _aria2c_lock:
        _aria2c_processes.discard(proc)


def _terminate_process(proc: subprocess.Popen) -> None:
    """Terminate a subprocess gracefully, then forcefully if needed."""
    if proc.poll() is not None:
        return
    try:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)
    except Exception:  # pylint: disable=broad-except
        pass


def _cleanup_aria2c_processes() -> None:
    """Kill any orphaned aria2c processes on exit."""
    with _aria2c_lock:
        for proc in list(_aria2c_processes):
            _terminate_process(proc)
        _aria2c_processes.clear()


atexit.register(_cleanup_aria2c_processes)


# ---------------------------------------------------------------------------
# Download tool detection
# ---------------------------------------------------------------------------

_download_tool: Optional[str] = None


def get_download_tool() -> Optional[str]:
    """Detect best available download tool.

    Returns 'aria2c', 'curl', or None based on availability.
    Prefers aria2c > curl > urllib (urllib always available).
    """
    global _download_tool  # pylint: disable=global-statement
    if _download_tool is not None:
        return _download_tool if _download_tool != '' else None

    try:
        result = subprocess.run(
            ['aria2c', '--version'], capture_output=True,
            timeout=5, check=False, **_SUBPROCESS_NO_WINDOW
        )
        if result.returncode == 0:
            _download_tool = 'aria2c'
            return 'aria2c'
    except Exception:  # pylint: disable=broad-except
        pass

    try:
        result = subprocess.run(
            ['curl', '--version'], capture_output=True,
            timeout=5, check=False, **_SUBPROCESS_NO_WINDOW
        )
        if result.returncode == 0:
            _download_tool = 'curl'
            return 'curl'
    except Exception:  # pylint: disable=broad-except
        pass

    _download_tool = ''
    return None


# ---------------------------------------------------------------------------
# Auto-tuning constants and calculation
# ---------------------------------------------------------------------------

AUTOTUNE_SMALL_THRESHOLD = 10 * 1024 * 1024    # 10 MB
AUTOTUNE_LARGE_THRESHOLD = 100 * 1024 * 1024   # 100 MB

AUTOTUNE_SMALL = (8, 1)    # Small files (<10MB): many files, minimal overhead
AUTOTUNE_MEDIUM = (8, 2)   # Medium files (10-100MB): balanced
AUTOTUNE_LARGE = (4, 1)    # Large files (>100MB): conservative start


def calculate_autotune_settings(file_sizes: List[int]) -> Tuple[int, int]:
    """Calculate starting parallel/connections settings based on file sizes.

    Uses median file size to determine initial settings. The DownloadUI
    adaptively ramps parallel up during stable periods and backs off on errors.

    Returns (parallel, connections) tuple.
    """
    if not file_sizes:
        return AUTOTUNE_MEDIUM

    valid_sizes = [s for s in file_sizes if s > 0]
    if not valid_sizes:
        return AUTOTUNE_MEDIUM

    valid_sizes.sort()
    median_size = valid_sizes[len(valid_sizes) // 2]

    if median_size < AUTOTUNE_SMALL_THRESHOLD:
        return AUTOTUNE_SMALL
    if median_size > AUTOTUNE_LARGE_THRESHOLD:
        return AUTOTUNE_LARGE
    return AUTOTUNE_MEDIUM


# ---------------------------------------------------------------------------
# Single-file and batch download functions
# ---------------------------------------------------------------------------

def download_with_external_tool(url: str, dest_path: Path,
                                connections: int = 4,
                                auth_header: Optional[str] = None) -> bool:
    """Download a file using aria2c or curl. Returns True on success."""
    tool = get_download_tool()
    if not tool:
        return False

    try:
        if tool == 'aria2c':
            cmd = [
                'aria2c', '-x', str(connections), '-s', str(connections),
                '-q', '--connect-timeout=30', '--timeout=300',
                '-d', str(dest_path.parent), '-o', dest_path.name
            ]
            if auth_header:
                cmd.append(f'--header=Authorization: {auth_header}')
            cmd.append(url)
            result = subprocess.run(
                cmd, capture_output=True, timeout=310, check=False,
                **_SUBPROCESS_NO_WINDOW
            )
        else:
            cmd = [
                'curl', '-sSL', '-o', str(dest_path),
                '--connect-timeout', '30', '--max-time', '300'
            ]
            if auth_header:
                cmd.extend(['-H', f'Authorization: {auth_header}'])
            cmd.append(url)
            result = subprocess.run(
                cmd, capture_output=True, timeout=310, check=False,
                **_SUBPROCESS_NO_WINDOW
            )
        return (result.returncode == 0
                and dest_path.exists()
                and dest_path.stat().st_size > 0)
    except Exception:  # pylint: disable=broad-except
        return False


def download_batch_with_curl(
        downloads: List[Tuple[str, Path]], parallel: int = 4,
        timeout_per_file: int = 60, auth_header: Optional[str] = None,
        resume: bool = False) -> List[Path]:
    """Download multiple files with a single curl call.

    Returns list of successfully downloaded paths.
    """
    if not downloads:
        return []

    cmd = [
        'curl', '-sSL', '--connect-timeout', '30',
        '--parallel', '--parallel-max', str(parallel)
    ]
    if resume:
        cmd.extend(['-C', '-'])
    if auth_header:
        cmd.extend(['-H', f'Authorization: {auth_header}'])

    for url, dest_path in downloads:
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        cmd.extend(['-o', str(dest_path), url])

    try:
        total_timeout = max(
            60, (len(downloads) // parallel + 1) * timeout_per_file
        )
        subprocess.run(
            cmd, capture_output=True, timeout=total_timeout, check=False,
            **_SUBPROCESS_NO_WINDOW
        )
    except subprocess.TimeoutExpired:
        pass
    except Exception:  # pylint: disable=broad-except
        return []

    successful = []
    for _url, dest_path in downloads:
        if dest_path.exists() and dest_path.stat().st_size > 0:
            successful.append(dest_path)
    return successful


def download_batch_with_aria2c(
        downloads: List[Tuple[str, Path]], parallel: int = 4,
        connections: int = 4, timeout_per_file: int = 60,
        auth_header: Optional[str] = None) -> List[Path]:
    """Download multiple files with aria2c.

    Returns list of successfully downloaded paths.
    """
    if not downloads:
        return []

    import tempfile  # pylint: disable=import-outside-toplevel
    with tempfile.NamedTemporaryFile(
            mode='w', suffix='.txt', delete=False, encoding='utf-8') as tmp:
        input_file = tmp.name
        for url, dest_path in downloads:
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write(f"{url}\n")
            tmp.write(f"  dir={dest_path.parent}\n")
            tmp.write(f"  out={dest_path.name}\n")

    proc = None
    try:
        cmd = [
            'aria2c', '-q', '--console-log-level=error',
            '-j', str(parallel),
            '-x', str(connections),
            '-s', str(connections),
            '--connect-timeout=30',
            '--timeout=60',
            '--max-tries=3',
            '--retry-wait=5',
            '--file-allocation=none',
        ]
        if auth_header:
            cmd.append(f'--header=Authorization: {auth_header}')
        cmd.extend(['-i', input_file])
        total_timeout = max(
            60, (len(downloads) // parallel + 1) * timeout_per_file
        )

        proc = subprocess.Popen(  # pylint: disable=consider-using-with
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            **_SUBPROCESS_NO_WINDOW
        )
        _register_aria2c_process(proc)
        try:
            proc.wait(timeout=total_timeout)
        except subprocess.TimeoutExpired:
            pass
    except Exception:  # pylint: disable=broad-except
        pass
    finally:
        if proc is not None:
            _terminate_process(proc)
            _unregister_aria2c_process(proc)
        try:
            os.unlink(input_file)
        except Exception:  # pylint: disable=broad-except
            pass

    successful = []
    for _url, dest_path in downloads:
        if dest_path.exists() and dest_path.stat().st_size > 0:
            successful.append(dest_path)
    return successful


# ---------------------------------------------------------------------------
# Aria2c JSON-RPC client
# ---------------------------------------------------------------------------

class Aria2cRPC:
    """Simple aria2c JSON-RPC client for download status polling."""

    def __init__(self, port: int = 6800, secret: str = 'retro'):
        self.url = f'http://localhost:{port}/jsonrpc'
        self.secret = f'token:{secret}'

    def _call(self, method: str, params: list = None) -> Optional[dict]:
        """Make an RPC call. Returns None on error."""
        payload = {
            'jsonrpc': '2.0',
            'id': '1',
            'method': method,
            'params': [self.secret] + (params or [])
        }
        try:
            data = json.dumps(payload).encode('utf-8')
            req = urllib.request.Request(
                self.url, data=data,
                headers={'Content-Type': 'application/json'}
            )
            with urllib.request.urlopen(req, timeout=1) as resp:
                result = json.loads(resp.read().decode('utf-8'))
                return result.get('result')
        except Exception:  # pylint: disable=broad-except
            return None

    def get_active(self) -> List[dict]:
        """Get active downloads with progress info."""
        result = self._call('aria2.tellActive')
        return result if result else []

    def get_stopped(self, offset: int = 0, limit: int = 100) -> List[dict]:
        """Get completed/failed downloads."""
        result = self._call('aria2.tellStopped', [offset, limit])
        return result if result else []

    def get_global_stat(self) -> Optional[dict]:
        """Get global download stats (speed, active count)."""
        return self._call('aria2.getGlobalStat')

    def change_global_option(self, options: dict) -> bool:
        """Change aria2c global options at runtime."""
        result = self._call('aria2.changeGlobalOption', [options])
        return result == 'OK'

    def shutdown(self):
        """Gracefully shutdown aria2c."""
        self._call('aria2.shutdown')


# ---------------------------------------------------------------------------
# DownloadUI - Interactive download manager
# ---------------------------------------------------------------------------

class DownloadUI:
    """Interactive download UI with simple and detailed modes.

    Default mode: Single-line progress bar with connection stats.
    Detailed mode (press 'i'): Fullscreen curses display with per-file progress.
    """

    STATUS_QUEUED = 'queued'
    STATUS_DOWNLOADING = 'downloading'
    STATUS_DONE = 'done'
    STATUS_FAILED = 'failed'

    # aria2c error codes that indicate server throttling/overload
    THROTTLE_ERROR_CODES = {'2', '5', '6', '19', '20'}

    def __init__(self, system_name: str,
                 files: List[Tuple[str, Path]],
                 parallel: int = 4, connections: int = 4,
                 auth_header: Optional[str] = None,
                 max_retries: int = 3, stall_timeout: int = 60,
                 on_file_complete: Optional[Callable] = None,
                 crc_indexer: Optional[object] = None,
                 resume: bool = False,
                 on_message: Optional[Callable] = None):
        self.system_name = system_name
        self.parallel = parallel
        self.connections = connections
        self.auth_header = auth_header
        self.max_retries = max_retries
        self.stall_timeout = stall_timeout
        self.on_file_complete = on_file_complete
        self.crc_indexer = crc_indexer
        self._resume_enabled = resume
        self.on_message = on_message  # callback(level, msg) for warnings etc.
        self.rpc: Optional[Aria2cRPC] = None
        self.rpc_available = False
        self.download_thread: Optional[threading.Thread] = None
        self.subprocess: Optional[subprocess.Popen] = None
        self.lock = threading.Lock()
        self.download_tool = 'unknown'
        self.detailed_mode = False
        self._shutdown_flag = False
        self._old_term_settings = None
        self._notified_done: set = set()
        self._resume_supported = False
        self._resume_files: set = set()

        # File tracking
        self.files: List[dict] = []
        for url, path in files:
            self.files.append({
                'url': url,
                'path': path,
                'status': self.STATUS_QUEUED,
                'size': 0,
                'completed': 0,
                'speed': 0,
                'retries': 0,
                'error_code': None,
                'error_message': '',
            })

        # Stats
        self.start_time = 0.0
        self.total_speed = 0
        self.completed_count = 0
        self.failed_count = 0
        self.active_count = 0
        self.last_progress_time = 0.0
        self.last_completed_count = 0

        # Adaptive ramping
        self._min_parallel = 1
        self._last_failed_count = 0
        self._stable_since = 0.0
        self._ramp_interval = 60

    @property
    def shutdown_requested(self) -> bool:
        """Check both local and network-level shutdown flags."""
        if self._shutdown_flag:
            return True
        try:
            from retro_refiner.network import _shutdown_event  # pylint: disable=import-outside-toplevel
            return _shutdown_event.is_set()
        except ImportError:
            return False

    def _is_tty(self) -> bool:
        """Check if running in a terminal."""
        return sys.stdout.isatty()

    def _emit(self, level: str, msg: str) -> None:
        """Emit a message via callback or print."""
        if self.on_message:
            self.on_message(level, msg)
        elif level == 'warning':
            print(f"  [!] {msg}", flush=True)
        elif level == 'error':
            print(f"  [X] {msg}", file=sys.stderr, flush=True)
        else:
            print(f"  {msg}", flush=True)

    def _check_resume_support(self) -> bool:
        """Check if the server supports byte-range requests via HEAD."""
        test_url = None
        for f_item in self.files:
            if f_item['url'] in self._resume_files:
                test_url = f_item['url']
                break
        if not test_url:
            return False
        try:
            headers = {'User-Agent': 'Mozilla/5.0'}
            if self.auth_header:
                headers['Authorization'] = self.auth_header
            req = urllib.request.Request(
                test_url, method='HEAD', headers=headers
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                accept_ranges = resp.headers.get('Accept-Ranges', '')
                return accept_ranges.lower() == 'bytes'
        except Exception:  # pylint: disable=broad-except
            return False

    def _identify_resume_candidates(self) -> None:
        """Identify partial files that could be resumed."""
        if not self._resume_enabled:
            for f_item in self.files:
                if f_item['path'].exists() and f_item['path'].stat().st_size > 0:
                    try:
                        f_item['path'].unlink()
                    except OSError:
                        pass
            return
        for f_item in self.files:
            if f_item['path'].exists() and f_item['path'].stat().st_size > 0:
                self._resume_files.add(f_item['url'])
        if self._resume_files:
            self._resume_supported = self._check_resume_support()
            if not self._resume_supported:
                for f_item in self.files:
                    if f_item['url'] in self._resume_files:
                        try:
                            f_item['path'].unlink()
                        except OSError:
                            pass
                self._resume_files.clear()

    def _check_adaptive_ramp(self) -> None:
        """Adjust parallel downloads: ramp up if stable, back off on errors."""
        now = _time.time()
        current_failed = self.failed_count

        if current_failed > self._last_failed_count:
            self._last_failed_count = current_failed
            self._stable_since = now
            new_parallel = max(self._min_parallel, self.parallel - 1)
            if new_parallel < self.parallel:
                self.parallel = new_parallel
                self._apply_parallel_change()
        elif now - self._stable_since >= self._ramp_interval:
            self._stable_since = now
            new_parallel = self.parallel + 1
            if new_parallel != self.parallel:
                self.parallel = new_parallel
                self._apply_parallel_change()

    def _apply_parallel_change(self) -> None:
        """Apply the current parallel setting to a running aria2c via RPC."""
        if self.rpc_available and self.rpc:
            self.rpc.change_global_option({
                'max-concurrent-downloads': str(self.parallel)
            })

    def _delete_failed_resume_files(self) -> None:
        """Delete partial files that failed to resume."""
        for f_item in self.files:
            if (f_item['status'] == self.STATUS_FAILED
                    and f_item['url'] in self._resume_files):
                try:
                    if f_item['path'].exists():
                        f_item['path'].unlink()
                except OSError:
                    pass
                self._resume_files.discard(f_item['url'])

    @staticmethod
    def _format_time(seconds: float) -> str:
        """Format seconds as MM:SS or HH:MM:SS."""
        if seconds < 0 or seconds > 86400:
            return '--:--'
        seconds = int(seconds)
        if seconds < 3600:
            mins, secs = divmod(seconds, 60)
            return f"{mins}:{secs:02d}"
        hours, remainder = divmod(seconds, 3600)
        mins, secs = divmod(remainder, 60)
        return f"{hours}:{mins:02d}:{secs:02d}"

    @staticmethod
    def _format_size(bytes_val: int) -> str:
        """Format bytes as human-readable size."""
        if bytes_val < 1024:
            return f"{bytes_val} B"
        if bytes_val < 1024 * 1024:
            return f"{bytes_val / 1024:.1f} KB"
        if bytes_val < 1024 * 1024 * 1024:
            return f"{bytes_val / (1024 * 1024):.1f} MB"
        return f"{bytes_val / (1024 * 1024 * 1024):.1f} GB"

    @staticmethod
    def _truncate(text: str, max_len: int) -> str:
        """Truncate text with ellipsis if too long."""
        if len(text) <= max_len:
            return text
        return text[:max_len - 3] + '...'

    def _get_counts(self) -> tuple:
        """Get current status counts."""
        active = sum(
            1 for f_item in self.files
            if f_item['status'] == self.STATUS_DOWNLOADING
        )
        queued = sum(
            1 for f_item in self.files
            if f_item['status'] == self.STATUS_QUEUED
        )
        return self.completed_count, self.failed_count, active, queued

    def _render_simple(self) -> None:
        """Render simple single-line progress bar with connection stats."""
        total = len(self.files)
        done, failed, active, queued = self._get_counts()
        elapsed = _time.time() - self.start_time if self.start_time else 0

        bar_width = 20
        pct_int = int(done * 100 / total) if total > 0 else 0
        if total > 0:
            pct = done / total
            filled = int(bar_width * pct)
            bar = (SYM_BLOCK_FULL * filled
                   + SYM_BLOCK_LIGHT * (bar_width - filled))
        else:
            bar = SYM_BLOCK_LIGHT * bar_width

        if done > 0 and elapsed > 0:
            rate = done / elapsed
            remaining = (total - done) / rate if rate > 0 else 0
            eta_str = self._format_time(remaining)
        else:
            eta_str = '--:--'
        elapsed_str = self._format_time(elapsed)

        speed_str = (
            self._format_size(self.total_speed) + '/s'
            if self.total_speed else '-- B/s'
        )

        line = f"  {self.system_name.upper()} |{bar}| {done}/{total} ({pct_int}%)"
        line += f"  {self.download_tool}"
        line += f" {self.parallel}p {self.connections}x"
        line += f" {SYM_ARROW}{active} {SYM_CIRCLE}{queued}"
        if failed:
            line += f" {SYM_CROSS}{failed}"
        if self.crc_indexer:
            verified = self.crc_indexer.verified_count
            line += f" CRC-OK:{verified}"
        line += f"  {speed_str}"
        line += f"  [{elapsed_str}<{eta_str}]"
        if self._is_tty():
            line += "  [i]"

        sys.stdout.write(f"\r\033[K{line}")
        sys.stdout.flush()

    def _render_detailed(self, stdscr) -> None:
        """Render fullscreen curses detailed view."""
        import curses  # pylint: disable=import-outside-toplevel

        stdscr.clear()
        height, width = stdscr.getmaxyx()

        if height < 10 or width < 60:
            stdscr.addstr(0, 0, "Terminal too small. Press 'i' to return.")
            stdscr.refresh()
            return

        total = len(self.files)
        done, failed, active, queued = self._get_counts()
        elapsed = _time.time() - self.start_time if self.start_time else 0

        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(1, curses.COLOR_GREEN, -1)
        curses.init_pair(2, curses.COLOR_CYAN, -1)
        curses.init_pair(3, curses.COLOR_RED, -1)
        curses.init_pair(4, curses.COLOR_CYAN, -1)

        header = f" Downloading ROMs for {self.system_name.upper()}"
        toggle_hint = "[i] simple view  [q] cancel "
        stdscr.addstr(0, 0, header[:width - 1], curses.A_BOLD)
        if len(toggle_hint) < width:
            stdscr.addstr(
                0, width - len(toggle_hint) - 1, toggle_hint, curses.A_DIM
            )

        stdscr.addstr(1, 0, SYM_HLINE * (width - 1))

        bar_width = min(30, width - 60)
        if total > 0:
            pct = done / total
            filled = int(bar_width * pct)
            bar = (SYM_BLOCK_FULL * filled
                   + SYM_BLOCK_LIGHT * (bar_width - filled))
        else:
            bar = SYM_BLOCK_LIGHT * bar_width

        speed_str = (
            self._format_size(self.total_speed) + '/s'
            if self.total_speed else '-- B/s'
        )
        if done > 0 and elapsed > 0:
            rate = done / elapsed
            remaining = (total - done) / rate if rate > 0 else 0
            eta_str = self._format_time(remaining)
        else:
            eta_str = '--:--'
        elapsed_str = self._format_time(elapsed)

        progress_line = (
            f" |{bar}| {done}/{total}  {speed_str}"
            f"  [{elapsed_str}<{eta_str}]"
        )
        stdscr.addstr(2, 0, progress_line[:width - 1])

        stats_line = (
            f" {self.download_tool} | {self.parallel} parallel"
            f" | {self.connections} conn/file"
            f" | Active: {active} | Queued: {queued}"
        )
        if failed:
            stats_line += f" | Failed: {failed}"
        if self.crc_indexer:
            verified = self.crc_indexer.verified_count
            stats_line += f" | CRC-OK: {verified}"
        stdscr.addstr(3, 0, stats_line[:width - 1])

        stdscr.addstr(4, 0, SYM_HLINE * (width - 1))

        list_start = 5
        list_height = height - list_start - 2

        def sort_key(f_item):
            status_order = {
                self.STATUS_DOWNLOADING: 0,
                self.STATUS_QUEUED: 1,
                self.STATUS_DONE: 2,
                self.STATUS_FAILED: 3
            }
            return (
                status_order.get(f_item['status'], 4),
                f_item['path'].name
            )

        sorted_files = sorted(self.files, key=sort_key)

        for i, f_item in enumerate(sorted_files[:list_height]):
            row = list_start + i
            if row >= height - 2:
                break

            status = f_item['status']
            filename = self._truncate(f_item['path'].name, width - 30)

            if status == self.STATUS_DONE:
                icon = SYM_CHECK
                color = curses.color_pair(1)
                suffix = 'done'
            elif status == self.STATUS_DOWNLOADING:
                icon = SYM_ARROW
                color = curses.color_pair(2)
                if f_item['size'] > 0:
                    pct_val = int(
                        100 * f_item['completed'] / f_item['size']
                    )
                    speed = (
                        self._format_size(f_item['speed']) + '/s'
                        if f_item['speed'] else ''
                    )
                    suffix = f"{pct_val}% {speed}"
                else:
                    suffix = '...'
            elif status == self.STATUS_FAILED:
                icon = SYM_CROSS
                color = curses.color_pair(3)
                err = f_item.get('error_code')
                suffix = f'err {err}' if err else 'failed'
            else:
                icon = SYM_CIRCLE
                color = curses.A_DIM
                suffix = 'queued'

            line = f" {icon} {filename:<{width - 25}} {suffix:>15}"
            try:
                stdscr.addstr(row, 0, line[:width - 1], color)
            except curses.error:
                pass

        if len(sorted_files) > list_height:
            remaining_msg = (
                f" ... and {len(sorted_files) - list_height} more files"
            )
            try:
                stdscr.addstr(
                    height - 3, 0, remaining_msg[:width - 1], curses.A_DIM
                )
            except curses.error:
                pass

        footer = " [i] simple view    [q] cancel downloads "
        try:
            stdscr.addstr(height - 1, 0, SYM_HLINE * (width - 1))
            stdscr.addstr(
                height - 1, (width - len(footer)) // 2, footer, curses.A_DIM
            )
        except curses.error:
            pass

        stdscr.refresh()

    def _check_new_completions(self) -> None:
        """Notify on_file_complete callback for newly completed files."""
        if not self.on_file_complete:
            return
        for f_item in self.files:
            if (f_item['status'] == self.STATUS_DONE
                    and f_item['path'] not in self._notified_done):
                self._notified_done.add(f_item['path'])
                try:
                    self.on_file_complete(f_item['path'])
                except Exception:  # pylint: disable=broad-except
                    pass

    def _update_from_rpc(self) -> None:
        """Poll aria2c RPC for download status updates."""
        if not self.rpc or not self.rpc_available:
            self._update_status_from_files_incremental()
            return

        try:
            stats = self.rpc.get_global_stat()
            if stats:
                self.total_speed = int(stats.get('downloadSpeed', 0))

            active_filenames: set = set()

            active_list = self.rpc.get_active()
            for dl_info in active_list:
                try:
                    dl_files = dl_info.get('files', [])
                    if not dl_files:
                        continue
                    path = Path(dl_files[0].get('path', ''))
                    active_filenames.add(path.name)

                    for f_item in self.files:
                        if f_item['path'].name == path.name:
                            f_item['status'] = self.STATUS_DOWNLOADING
                            f_item['size'] = int(
                                dl_info.get('totalLength', 0)
                            )
                            f_item['completed'] = int(
                                dl_info.get('completedLength', 0)
                            )
                            f_item['speed'] = int(
                                dl_info.get('downloadSpeed', 0)
                            )
                            break
                except (KeyError, ValueError):
                    continue

            stopped_list = self.rpc.get_stopped(limit=500)
            for dl_info in stopped_list:
                try:
                    dl_files = dl_info.get('files', [])
                    if not dl_files:
                        continue
                    path = Path(dl_files[0].get('path', ''))
                    status = dl_info.get('status', '')

                    for f_item in self.files:
                        if f_item['path'].name == path.name:
                            if status == 'complete':
                                f_item['status'] = self.STATUS_DONE
                                f_item['size'] = int(
                                    dl_info.get('totalLength', 0)
                                )
                                f_item['completed'] = f_item['size']
                            elif status == 'error':
                                f_item['status'] = self.STATUS_FAILED
                                f_item['error_code'] = dl_info.get(
                                    'errorCode'
                                )
                                f_item['error_message'] = dl_info.get(
                                    'errorMessage', ''
                                )
                            break
                except (KeyError, ValueError):
                    continue

            for f_item in self.files:
                if (f_item['status'] == self.STATUS_DOWNLOADING
                        and f_item['path'].name not in active_filenames):
                    if (f_item['path'].exists()
                            and f_item['path'].stat().st_size > 0):
                        f_item['status'] = self.STATUS_DONE
                        f_item['completed'] = f_item['path'].stat().st_size
                        f_item['size'] = f_item['completed']
                        f_item['speed'] = 0

            with self.lock:
                self.completed_count = sum(
                    1 for f_item in self.files
                    if f_item['status'] == self.STATUS_DONE
                )
                self.failed_count = sum(
                    1 for f_item in self.files
                    if f_item['status'] == self.STATUS_FAILED
                )
                self.active_count = len(active_filenames)

        except Exception:  # pylint: disable=broad-except
            self.rpc_available = False

        self._check_new_completions()

    def _update_status_from_files_incremental(self) -> None:
        """Update status by checking files on disk (non-final states only)."""
        for f_item in self.files:
            if f_item['status'] in (self.STATUS_QUEUED, self.STATUS_DOWNLOADING):
                if (f_item['path'].exists()
                        and f_item['path'].stat().st_size > 0):
                    f_item['status'] = self.STATUS_DONE
                    f_item['completed'] = f_item['path'].stat().st_size
                    f_item['size'] = f_item['completed']
                    f_item['speed'] = 0

        self.completed_count = sum(
            1 for f_item in self.files
            if f_item['status'] == self.STATUS_DONE
        )
        self.failed_count = sum(
            1 for f_item in self.files
            if f_item['status'] == self.STATUS_FAILED
        )
        self._check_new_completions()

    def _download_worker(self) -> None:
        """Background thread that runs the actual downloads."""
        with self.lock:
            downloads = [
                (f_item['url'], f_item['path']) for f_item in self.files
                if f_item['status'] == self.STATUS_QUEUED
            ]

        if not downloads:
            return

        tool = get_download_tool()
        self.download_tool = tool

        if tool == 'aria2c':
            self._run_aria2c_with_rpc(downloads)
        elif tool == 'curl':
            self._run_curl_batch(downloads)
        else:
            self._run_python_downloads(downloads)

    def _run_aria2c_with_rpc(
            self, downloads: List[Tuple[str, Path]]) -> None:
        """Run aria2c with RPC enabled for status tracking."""
        import tempfile  # pylint: disable=import-outside-toplevel

        with tempfile.NamedTemporaryFile(
                mode='w', suffix='.txt', delete=False,
                encoding='utf-8') as tmp:
            input_file = tmp.name
            for url, dest_path in downloads:
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                tmp.write(f"{url}\n")
                tmp.write(f"  dir={dest_path.parent}\n")
                tmp.write(f"  out={dest_path.name}\n")

        rpc_port = 6800
        rpc_secret = 'retro'

        cmd = [
            'aria2c',
            '--enable-rpc',
            f'--rpc-listen-port={rpc_port}',
            f'--rpc-secret={rpc_secret}',
            '--rpc-listen-all=false',
            '-q', '--console-log-level=error',
            '-j', str(self.parallel),
            '-x', str(self.connections),
            '-s', str(self.connections),
            '--connect-timeout=30',
            '--timeout=60',
            '--max-tries=3',
            '--retry-wait=5',
            '--file-allocation=none',
        ]
        if self._resume_supported and self._resume_files:
            cmd.append('--continue=true')
        if self.auth_header:
            cmd.append(f'--header=Authorization: {self.auth_header}')
        cmd.extend(['-i', input_file])

        try:
            self.subprocess = subprocess.Popen(  # pylint: disable=consider-using-with
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                **_SUBPROCESS_NO_WINDOW
            )
            _register_aria2c_process(self.subprocess)

            self.rpc = Aria2cRPC(port=rpc_port, secret=rpc_secret)
            for _ in range(20):
                if self.rpc.get_global_stat() is not None:
                    self.rpc_available = True
                    break
                _time.sleep(0.1)

            while True:
                try:
                    if (self.subprocess is None
                            or self.subprocess.poll() is not None):
                        break
                    if self.shutdown_requested:
                        break
                    if self.rpc_available:
                        stat = self.rpc.get_global_stat()
                        if (stat
                                and int(stat.get('numActive', 1)) == 0
                                and int(stat.get('numWaiting', 1)) == 0):
                            break
                except Exception:  # pylint: disable=broad-except
                    break
                _time.sleep(0.1)

        except Exception:  # pylint: disable=broad-except
            pass
        finally:
            if self.rpc is not None:
                try:
                    self.rpc.shutdown()
                except Exception:  # pylint: disable=broad-except
                    pass
            proc = self.subprocess
            if proc is not None:
                try:
                    _terminate_process(proc)
                    _unregister_aria2c_process(proc)
                except Exception:  # pylint: disable=broad-except
                    pass
                self.subprocess = None
            try:
                os.unlink(input_file)
            except Exception:  # pylint: disable=broad-except
                pass
            self._update_status_from_files()

    def _run_curl_batch(self, downloads: List[Tuple[str, Path]]) -> None:
        """Run curl batch download (no per-file progress)."""
        resume = self._resume_supported and bool(self._resume_files)
        successful = download_batch_with_curl(
            downloads, parallel=self.parallel,
            auth_header=self.auth_header, resume=resume
        )
        attempted_paths = {path for _, path in downloads}

        with self.lock:
            for f_item in self.files:
                if f_item['path'] not in attempted_paths:
                    continue
                if f_item['path'] in successful:
                    f_item['status'] = self.STATUS_DONE
                elif (f_item['path'].exists()
                      and f_item['path'].stat().st_size > 0):
                    f_item['status'] = self.STATUS_DONE
                else:
                    f_item['status'] = self.STATUS_FAILED

            self.completed_count = sum(
                1 for f_item in self.files
                if f_item['status'] == self.STATUS_DONE
            )
            self.failed_count = sum(
                1 for f_item in self.files
                if f_item['status'] == self.STATUS_FAILED
            )

    def _run_python_downloads(
            self, downloads: List[Tuple[str, Path]]) -> None:
        """Fall back to Python urllib sequential downloads."""
        for url, dest_path in downloads:
            if self.shutdown_requested:
                break
            for f_item in self.files:
                if f_item['url'] == url:
                    f_item['status'] = self.STATUS_DOWNLOADING
                    break

            success = False
            try:
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                headers = {'User-Agent': 'Mozilla/5.0'}
                if self.auth_header:
                    headers['Authorization'] = self.auth_header

                resume_from = 0
                if (self._resume_supported
                        and url in self._resume_files
                        and dest_path.exists()):
                    resume_from = dest_path.stat().st_size
                    headers['Range'] = f'bytes={resume_from}-'

                req = urllib.request.Request(url, headers=headers)
                try:
                    with urllib.request.urlopen(req, timeout=60) as resp:
                        if resume_from > 0 and resp.status == 206:
                            with open(dest_path, 'ab') as out:
                                shutil.copyfileobj(resp, out)
                        else:
                            with open(dest_path, 'wb') as out:
                                shutil.copyfileobj(resp, out)
                except urllib.error.HTTPError:
                    if resume_from > 0:
                        headers.pop('Range', None)
                        req = urllib.request.Request(url, headers=headers)
                        with urllib.request.urlopen(req, timeout=60) as resp:
                            with open(dest_path, 'wb') as out:
                                shutil.copyfileobj(resp, out)
                    else:
                        raise

                success = (dest_path.exists()
                           and dest_path.stat().st_size > 0)
            except Exception:  # pylint: disable=broad-except
                pass

            with self.lock:
                for f_item in self.files:
                    if f_item['url'] == url:
                        f_item['status'] = (
                            self.STATUS_DONE if success
                            else self.STATUS_FAILED
                        )
                        break
                self.completed_count = sum(
                    1 for f_item in self.files
                    if f_item['status'] == self.STATUS_DONE
                )
                self.failed_count = sum(
                    1 for f_item in self.files
                    if f_item['status'] == self.STATUS_FAILED
                )

    def _update_status_from_files(self) -> None:
        """Update status by checking which files exist on disk."""
        with self.lock:
            for f_item in self.files:
                if f_item['status'] in (
                        self.STATUS_QUEUED, self.STATUS_DOWNLOADING):
                    if (f_item['path'].exists()
                            and f_item['path'].stat().st_size > 0):
                        f_item['status'] = self.STATUS_DONE
                    else:
                        f_item['status'] = self.STATUS_FAILED

            self.completed_count = sum(
                1 for f_item in self.files
                if f_item['status'] == self.STATUS_DONE
            )
            self.failed_count = sum(
                1 for f_item in self.files
                if f_item['status'] == self.STATUS_FAILED
            )
        self._check_new_completions()

    def _check_stall(self) -> bool:
        """Check if downloads appear stalled."""
        now = _time.time()
        with self.lock:
            current_completed = self.completed_count
            current_speed = self.total_speed
            current_active = self.active_count
            total_files = len(self.files)
            done_and_failed = self.completed_count + self.failed_count

            if current_completed > self.last_completed_count:
                self.last_completed_count = current_completed
                self.last_progress_time = now

            if current_speed > 0:
                self.last_progress_time = now

            if current_active > 0:
                self.last_progress_time = now

            if self.last_progress_time > 0:
                stall_duration = now - self.last_progress_time
                idle_timeout = (
                    30 if (current_active == 0
                           and done_and_failed < total_files)
                    else self.stall_timeout
                )
                if stall_duration > idle_timeout:
                    return True

            return False

    def _get_failed_downloads(self) -> List[Tuple[str, Path]]:
        """Get list of failed downloads that can be retried."""
        failed = []
        with self.lock:
            for f_item in self.files:
                if (f_item['status'] == self.STATUS_FAILED
                        and f_item['retries'] < self.max_retries):
                    failed.append((f_item['url'], f_item['path']))
        return failed

    def _has_throttle_errors(self) -> bool:
        """Check if any failed downloads have throttling-related errors."""
        with self.lock:
            for f_item in self.files:
                if (f_item['status'] == self.STATUS_FAILED
                        and f_item.get('error_code')
                        in self.THROTTLE_ERROR_CODES):
                    return True
        return False

    def _get_throttle_summary(self) -> str:
        """Get a summary of throttle-related error codes."""
        code_counts: Dict[str, int] = {}
        with self.lock:
            for f_item in self.files:
                if (f_item['status'] == self.STATUS_FAILED
                        and f_item.get('error_code')):
                    code = f_item['error_code']
                    code_counts[code] = code_counts.get(code, 0) + 1
        if not code_counts:
            return ''
        parts = []
        code_labels = {
            '2': 'timeout', '5': 'too slow', '6': 'network error',
            '19': 'HTTP 4xx', '20': 'HTTP 5xx',
        }
        for code, count in sorted(code_counts.items()):
            label = code_labels.get(code, f'err {code}')
            parts.append(f"{label}={count}")
        return ', '.join(parts)

    def _mark_for_retry(self, urls: List[str]) -> None:
        """Mark failed downloads for retry by resetting their status."""
        with self.lock:
            for f_item in self.files:
                if (f_item['url'] in urls
                        and f_item['status'] == self.STATUS_FAILED):
                    f_item['retries'] += 1
                    f_item['status'] = self.STATUS_QUEUED
                    f_item['completed'] = 0
                    f_item['speed'] = 0
                    f_item['error_code'] = None
                    f_item['error_message'] = ''
            self.completed_count = sum(
                1 for f_item in self.files
                if f_item['status'] == self.STATUS_DONE
            )
            self.failed_count = sum(
                1 for f_item in self.files
                if f_item['status'] == self.STATUS_FAILED
            )

    def _terminate_download(self) -> None:
        """Terminate the current download process."""
        if self.rpc is not None:
            try:
                self.rpc.shutdown()
            except Exception:  # pylint: disable=broad-except
                pass

        proc = self.subprocess
        if proc is not None:
            _terminate_process(proc)

    def _setup_keyboard(self) -> None:
        """Set up non-blocking keyboard input."""
        if not self._is_tty():
            return

        if WINDOWS:
            pass  # msvcrt is always non-blocking
        elif HAS_TERMIOS:
            try:
                self._old_term_settings = termios.tcgetattr(  # pylint: disable=possibly-used-before-assignment
                    sys.stdin.fileno()
                )
                tty.setcbreak(sys.stdin.fileno())  # pylint: disable=possibly-used-before-assignment
            except Exception:  # pylint: disable=broad-except
                self._old_term_settings = None

    def _restore_keyboard(self) -> None:
        """Restore normal keyboard input."""
        if WINDOWS:
            pass
        elif (HAS_TERMIOS
              and hasattr(self, '_old_term_settings')
              and self._old_term_settings):
            try:
                termios.tcsetattr(
                    sys.stdin.fileno(), termios.TCSADRAIN,
                    self._old_term_settings
                )
            except Exception:  # pylint: disable=broad-except
                pass

    def _check_keypress(self) -> Optional[str]:
        """Non-blocking check for keypress. Returns key or None."""
        if not self._is_tty():
            return None

        try:
            if WINDOWS and HAS_MSVCRT:
                if msvcrt.kbhit():  # pylint: disable=possibly-used-before-assignment
                    key = msvcrt.getch()
                    try:
                        return key.decode('utf-8', errors='ignore')
                    except Exception:  # pylint: disable=broad-except
                        return None
            elif HAS_TERMIOS:
                import select  # pylint: disable=import-outside-toplevel
                if select.select([sys.stdin], [], [], 0)[0]:
                    return sys.stdin.read(1)
        except Exception:  # pylint: disable=broad-except
            pass
        return None

    def _run_curses_detailed(self) -> None:
        """Run the detailed curses view until 'i' or 'q' is pressed."""
        try:
            import curses  # pylint: disable=import-outside-toplevel
        except ImportError:
            self._emit('info',
                       "[Detailed view not available on this platform]")
            self.detailed_mode = False
            return

        def curses_main(stdscr):
            curses.curs_set(0)
            stdscr.nodelay(True)
            stdscr.timeout(100)

            while self.detailed_mode:
                key = stdscr.getch()
                if key == ord('i'):
                    self.detailed_mode = False
                    break
                if key == ord('q'):
                    self._shutdown_flag = True
                    self.detailed_mode = False
                    break

                if self.download_thread and self.download_thread.is_alive():
                    self._update_from_rpc()
                else:
                    self._update_status_from_files()

                self._render_detailed(stdscr)

        try:
            curses.wrapper(curses_main)
        except Exception:  # pylint: disable=broad-except
            self.detailed_mode = False

    def run(self) -> Dict[str, Path]:
        """Run the download UI.

        Returns dict of url -> local_path for successful downloads.
        """
        if not self.files:
            return {}

        self.start_time = _time.time()
        self.download_tool = get_download_tool()
        self.last_progress_time = _time.time()
        self.last_completed_count = 0
        self._stable_since = _time.time()
        self._last_failed_count = 0

        self._identify_resume_candidates()

        self.download_thread = threading.Thread(
            target=self._download_worker, daemon=True
        )
        self.download_thread.start()

        self._setup_keyboard()

        try:
            while (self.download_thread.is_alive()
                   and not self.shutdown_requested):
                key = self._check_keypress()
                if key == 'i':
                    self._restore_keyboard()
                    sys.stdout.write('\r\033[K')
                    sys.stdout.flush()
                    self.detailed_mode = True
                    self._run_curses_detailed()
                    self._setup_keyboard()
                    if self.shutdown_requested:
                        break
                elif key == 'q':
                    self._shutdown_flag = True
                    break

                self._update_from_rpc()
                self._check_adaptive_ramp()
                self._render_simple()

                if self._check_stall():
                    sys.stdout.write('\r\033[K')
                    self._emit(
                        'warning',
                        "Stall detected - aborting and retrying"
                        " failed downloads..."
                    )
                    self._terminate_download()
                    break

                _time.sleep(0.15)
        finally:
            self._restore_keyboard()

        if self.shutdown_requested and self.subprocess:
            self._terminate_download()

        if self.download_thread.is_alive():
            self.download_thread.join(timeout=5)

        self._update_status_from_files()

        # Retry failed downloads
        retry_round = 1
        while not self.shutdown_requested:
            self._delete_failed_resume_files()

            failed_downloads = self._get_failed_downloads()
            if not failed_downloads:
                break

            if self._has_throttle_errors():
                new_parallel = max(1, self.parallel // 2)
                if new_parallel < self.parallel:
                    throttle_info = self._get_throttle_summary()
                    self.parallel = new_parallel
                    if not self.detailed_mode:
                        sys.stdout.write('\r\033[K')
                    msg = (
                        f"Throttling detected ({throttle_info})"
                        f" {SYM_ARROW_RIGHT} reducing to"
                        f" {self.parallel} parallel downloads"
                    )
                    self._emit('warning', msg)

            self.last_progress_time = _time.time()
            self.last_completed_count = self.completed_count
            retry_urls = [url for url, _ in failed_downloads]
            self._mark_for_retry(retry_urls)

            if not self.detailed_mode:
                sys.stdout.write('\r\033[K')
            self._emit(
                'info',
                f"Retry {retry_round}/{self.max_retries}:"
                f" {len(failed_downloads)} failed files..."
            )

            self.download_thread = threading.Thread(
                target=self._download_worker, daemon=True
            )
            self.download_thread.start()

            self._setup_keyboard()
            try:
                while (self.download_thread.is_alive()
                       and not self.shutdown_requested):
                    key = self._check_keypress()
                    if key == 'q':
                        self._shutdown_flag = True
                        break

                    self._update_from_rpc()
                    self._check_adaptive_ramp()
                    self._render_simple()

                    if self._check_stall():
                        sys.stdout.write('\r\033[K')
                        self._emit(
                            'warning',
                            "Retry stalled - moving to next retry round..."
                        )
                        self._terminate_download()
                        break

                    _time.sleep(0.15)
            finally:
                self._restore_keyboard()

            if self.shutdown_requested and self.subprocess:
                self._terminate_download()

            if self.download_thread.is_alive():
                self.download_thread.join(timeout=5)

            self._update_status_from_files()
            retry_round += 1

        if not self.detailed_mode:
            self._render_simple()
            print()  # Move to new line after progress bar

        # Print final summary
        done = self.completed_count
        failed = self.failed_count
        verified = (
            self.crc_indexer.verified_count if self.crc_indexer else 0
        )
        summary = (
            f"  {SYM_CHECK} Downloaded {done}/{len(self.files)} files"
        )
        if verified:
            summary += f", {verified} CRC-OK"
        if failed:
            summary += f" ({failed} failed)"
            print(summary)
            failed_files = [
                f_item for f_item in self.files
                if f_item['status'] == self.STATUS_FAILED
            ]
            show_files = (
                failed_files if len(failed_files) <= 10
                else failed_files[:5]
            )
            for f_item in show_files:
                filename = Path(f_item['url']).name
                err_info = ''
                if f_item.get('error_code'):
                    err_info = (
                        f" [error {f_item['error_code']}:"
                        f" {f_item['error_message']}]"
                    )
                print(f"    {SYM_CROSS} {filename}{err_info}")
            if len(failed_files) > 10:
                print(f"    ... and {len(failed_files) - 5} more")
        else:
            print(summary)

        results = {}
        for f_item in self.files:
            if f_item['status'] == self.STATUS_DONE:
                results[f_item['url']] = f_item['path']

        return results

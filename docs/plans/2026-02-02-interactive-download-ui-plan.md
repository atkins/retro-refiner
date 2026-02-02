# Interactive Download UI Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add toggleable detailed download view (press 'i') with per-file progress, queue status, and network stats.

**Architecture:** DownloadUI class wraps curses for display, runs downloads in background thread, polls aria2c JSON-RPC for real-time stats. Falls back to completion-only tracking for curl.

**Tech Stack:** Python curses (stdlib), aria2c RPC (JSON over HTTP), threading

---

## Task 1: Add aria2c RPC Client

**Files:**
- Modify: `retro-refiner.py` (add after line ~1213, after `download_batch_with_aria2c`)

**Step 1: Write the aria2c RPC helper class**

Add this class after `download_batch_with_aria2c`:

```python
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
                self.url,
                data=data,
                headers={'Content-Type': 'application/json'}
            )
            with urllib.request.urlopen(req, timeout=1) as resp:
                result = json.loads(resp.read().decode('utf-8'))
                return result.get('result')
        except Exception:
            return None

    def get_active(self) -> List[dict]:
        """Get active downloads with progress info."""
        result = self._call('aria2.tellActive')
        return result if result else []

    def get_waiting(self, offset: int = 0, limit: int = 100) -> List[dict]:
        """Get waiting/queued downloads."""
        result = self._call('aria2.tellWaiting', [offset, limit])
        return result if result else []

    def get_stopped(self, offset: int = 0, limit: int = 100) -> List[dict]:
        """Get completed/failed downloads."""
        result = self._call('aria2.tellStopped', [offset, limit])
        return result if result else []

    def get_global_stat(self) -> Optional[dict]:
        """Get global download stats (speed, active count)."""
        return self._call('aria2.getGlobalStat')

    def shutdown(self):
        """Gracefully shutdown aria2c."""
        self._call('aria2.shutdown')
```

**Step 2: Run to verify no syntax errors**

Run: `python3 -c "import retro-refiner" 2>&1 | head -5`
Expected: No output (clean import) or unrelated warnings

**Step 3: Commit**

```bash
git add retro-refiner.py
git commit -m "feat: add aria2c JSON-RPC client class"
```

---

## Task 2: Create DownloadUI Class Structure

**Files:**
- Modify: `retro-refiner.py` (add after `Aria2cRPC` class)

**Step 1: Add DownloadUI class skeleton**

```python
class DownloadUI:
    """Interactive download UI with simple/detailed view toggle."""

    # Status constants
    STATUS_QUEUED = 'queued'
    STATUS_DOWNLOADING = 'downloading'
    STATUS_DONE = 'done'
    STATUS_FAILED = 'failed'

    def __init__(self, system_name: str, files: List[Tuple[str, Path]],
                 parallel: int = 4, connections: int = 4):
        self.system_name = system_name
        self.parallel = parallel
        self.connections = connections
        self.detailed_mode = False
        self.scroll_offset = 0
        self.cancelled = False
        self.rpc: Optional[Aria2cRPC] = None
        self.rpc_available = False
        self.download_thread: Optional[threading.Thread] = None
        self.subprocess: Optional[subprocess.Popen] = None
        self.lock = threading.Lock()

        # File tracking: list of dicts with url, path, status, size, progress, speed
        self.files = []
        for url, path in files:
            self.files.append({
                'url': url,
                'path': path,
                'status': self.STATUS_QUEUED,
                'size': 0,
                'completed': 0,
                'speed': 0,
            })

        # Stats
        self.start_time = 0
        self.total_speed = 0
        self.completed_count = 0
        self.failed_count = 0

    def _is_tty(self) -> bool:
        """Check if running in a terminal."""
        return sys.stdout.isatty()
```

**Step 2: Verify syntax**

Run: `python3 -c "import retro-refiner"`
Expected: Clean import

**Step 3: Commit**

```bash
git add retro-refiner.py
git commit -m "feat: add DownloadUI class skeleton with file tracking"
```

---

## Task 3: Implement Simple View Rendering

**Files:**
- Modify: `retro-refiner.py` (add methods to `DownloadUI` class)

**Step 1: Add simple view render method**

```python
    def _render_simple(self, stdscr) -> None:
        """Render simple one-line progress bar."""
        height, width = stdscr.getmaxyx()
        stdscr.clear()

        total = len(self.files)
        done = self.completed_count
        failed = self.failed_count
        elapsed = _time.time() - self.start_time if self.start_time else 0

        # Progress bar
        bar_width = min(30, width - 50)
        if total > 0:
            pct = done / total
            filled = int(bar_width * pct)
            bar = '█' * filled + '░' * (bar_width - filled)
        else:
            bar = '░' * bar_width

        # Stats
        if done > 0 and elapsed > 0:
            rate = done / elapsed
            remaining = (total - done) / rate if rate > 0 else 0
            eta_str = self._format_time(remaining)
            elapsed_str = self._format_time(elapsed)
            speed_str = self._format_size(self.total_speed) + '/s' if self.total_speed else ''
        else:
            eta_str = '--:--'
            elapsed_str = self._format_time(elapsed)
            speed_str = ''

        # Build status line
        status = f"{self.system_name.upper()} Downloading: |{bar}| {done}/{total}"
        if failed:
            status += f" ({failed} failed)"
        if speed_str:
            status += f"  {speed_str}"
        status += f"  [{elapsed_str}<{eta_str}]"

        # Hint
        hint = "  Press [i] for details, [q] to cancel"

        # Center vertically
        y = height // 2
        try:
            stdscr.addstr(y, 2, status[:width-4])
            stdscr.addstr(y + 1, 2, hint[:width-4], curses.A_DIM)
        except curses.error:
            pass

        stdscr.refresh()

    def _format_time(self, seconds: float) -> str:
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

    def _format_size(self, bytes_val: int) -> str:
        """Format bytes as human-readable size."""
        if bytes_val < 1024:
            return f"{bytes_val} B"
        elif bytes_val < 1024 * 1024:
            return f"{bytes_val / 1024:.1f} KB"
        elif bytes_val < 1024 * 1024 * 1024:
            return f"{bytes_val / (1024 * 1024):.1f} MB"
        else:
            return f"{bytes_val / (1024 * 1024 * 1024):.1f} GB"
```

**Step 2: Verify syntax**

Run: `python3 -c "import retro-refiner"`
Expected: Clean import

**Step 3: Commit**

```bash
git add retro-refiner.py
git commit -m "feat: add simple view rendering to DownloadUI"
```

---

## Task 4: Implement Detailed View Rendering

**Files:**
- Modify: `retro-refiner.py` (add methods to `DownloadUI` class)

**Step 1: Add detailed view render method**

```python
    def _render_detailed(self, stdscr) -> None:
        """Render full-screen detailed view with file list."""
        height, width = stdscr.getmaxyx()
        stdscr.clear()

        # Check minimum size
        if height < 10 or width < 60:
            try:
                msg = "Terminal too small (need 60x10)"
                stdscr.addstr(height // 2, max(0, (width - len(msg)) // 2), msg)
            except curses.error:
                pass
            stdscr.refresh()
            return

        total = len(self.files)
        done = self.completed_count
        failed = self.failed_count
        elapsed = _time.time() - self.start_time if self.start_time else 0

        # Calculate ETA
        if done > 0 and elapsed > 0:
            rate = done / elapsed
            remaining = (total - done) / rate if rate > 0 else 0
            eta_str = self._format_time(remaining)
            elapsed_str = self._format_time(elapsed)
        else:
            eta_str = '--:--'
            elapsed_str = self._format_time(elapsed)

        speed_str = self._format_size(self.total_speed) + '/s' if self.total_speed else '0 B/s'

        # Header
        try:
            title = f"Downloading ROMs for {self.system_name.upper()}"
            hint = "[i] simple view"
            stdscr.addstr(0, 2, title[:width-20], curses.A_BOLD)
            stdscr.addstr(0, width - len(hint) - 2, hint, curses.A_DIM)

            # Separator
            stdscr.addstr(1, 0, '─' * width)

            # Stats line
            stats = f"Progress: {done}/{total} files    {speed_str}    ETA: {eta_str}    Elapsed: {elapsed_str}"
            if failed:
                stats += f"    Failed: {failed}"
                stdscr.addstr(2, 2, stats[:width-4])
                # Highlight failed count in red
                fail_pos = stats.find('Failed:')
                if fail_pos >= 0 and curses.has_colors():
                    stdscr.addstr(2, 2 + fail_pos, f"Failed: {failed}", curses.color_pair(1))
            else:
                stdscr.addstr(2, 2, stats[:width-4])

            # Another separator
            stdscr.addstr(3, 0, '─' * width)
        except curses.error:
            pass

        # File list area
        list_start = 4
        list_height = height - list_start - 2  # Leave room for footer

        # Auto-scroll to show active downloads
        active_indices = [i for i, f in enumerate(self.files) if f['status'] == self.STATUS_DOWNLOADING]
        if active_indices and not self._manual_scroll:
            first_active = active_indices[0]
            if first_active < self.scroll_offset:
                self.scroll_offset = first_active
            elif first_active >= self.scroll_offset + list_height:
                self.scroll_offset = first_active - list_height + 1

        # Clamp scroll
        max_scroll = max(0, len(self.files) - list_height)
        self.scroll_offset = max(0, min(self.scroll_offset, max_scroll))

        # Render visible files
        for i in range(list_height):
            file_idx = self.scroll_offset + i
            if file_idx >= len(self.files):
                break

            f = self.files[file_idx]
            y = list_start + i

            # Status icon and color
            if f['status'] == self.STATUS_DONE:
                icon = '✓'
                attr = curses.color_pair(2) if curses.has_colors() else curses.A_NORMAL
            elif f['status'] == self.STATUS_DOWNLOADING:
                icon = '↓'
                attr = curses.color_pair(3) if curses.has_colors() else curses.A_BOLD
            elif f['status'] == self.STATUS_FAILED:
                icon = '✗'
                attr = curses.color_pair(1) if curses.has_colors() else curses.A_NORMAL
            else:  # queued
                icon = '○'
                attr = curses.A_DIM

            # Filename (truncate if needed)
            filename = f['path'].name
            max_name_len = width - 30
            if len(filename) > max_name_len:
                filename = filename[:max_name_len - 3] + '...'

            # Size and progress
            size_str = self._format_size(f['size']) if f['size'] else ''
            if f['status'] == self.STATUS_DOWNLOADING:
                if f['size'] > 0 and f['completed'] > 0:
                    pct = int(100 * f['completed'] / f['size'])
                    progress_str = f"{pct}%"
                else:
                    progress_str = '...'
            elif f['status'] == self.STATUS_DONE:
                progress_str = 'done'
            elif f['status'] == self.STATUS_FAILED:
                progress_str = 'failed'
            else:
                progress_str = 'queued'

            # Build line
            line = f" {icon} {filename:<{max_name_len}}  {size_str:>10}  {progress_str:>8}"

            try:
                stdscr.addstr(y, 0, line[:width], attr)
            except curses.error:
                pass

        # Scroll indicator
        if len(self.files) > list_height:
            if self.scroll_offset > 0:
                try:
                    stdscr.addstr(list_start, width - 3, ' ↑ ', curses.A_DIM)
                except curses.error:
                    pass
            if self.scroll_offset < max_scroll:
                try:
                    stdscr.addstr(list_start + list_height - 1, width - 3, ' ↓ ', curses.A_DIM)
                except curses.error:
                    pass

        # Footer
        footer = "[i] simple view    [q] cancel    [↑↓] scroll"
        try:
            stdscr.addstr(height - 1, 2, footer[:width-4], curses.A_DIM)
        except curses.error:
            pass

        stdscr.refresh()
```

**Step 2: Add manual scroll tracking**

Add to `__init__`:
```python
        self._manual_scroll = False
```

**Step 3: Verify syntax**

Run: `python3 -c "import retro-refiner"`
Expected: Clean import

**Step 4: Commit**

```bash
git add retro-refiner.py
git commit -m "feat: add detailed view rendering with file list"
```

---

## Task 5: Implement Input Handling

**Files:**
- Modify: `retro-refiner.py` (add methods to `DownloadUI` class)

**Step 1: Add input handler**

```python
    def _handle_input(self, stdscr) -> None:
        """Handle keyboard input (non-blocking)."""
        try:
            key = stdscr.getch()
        except curses.error:
            return

        if key == -1:
            return

        if key in (ord('i'), ord('I')):
            self.detailed_mode = not self.detailed_mode
            self._manual_scroll = False
        elif key in (ord('q'), ord('Q')):
            self.cancelled = True
        elif key == curses.KEY_UP:
            self.scroll_offset = max(0, self.scroll_offset - 1)
            self._manual_scroll = True
        elif key == curses.KEY_DOWN:
            max_scroll = max(0, len(self.files) - 10)  # Approximate
            self.scroll_offset = min(max_scroll, self.scroll_offset + 1)
            self._manual_scroll = True
        elif key == curses.KEY_PPAGE:  # Page Up
            self.scroll_offset = max(0, self.scroll_offset - 10)
            self._manual_scroll = True
        elif key == curses.KEY_NPAGE:  # Page Down
            max_scroll = max(0, len(self.files) - 10)
            self.scroll_offset = min(max_scroll, self.scroll_offset + 10)
            self._manual_scroll = True
```

**Step 2: Verify syntax**

Run: `python3 -c "import retro-refiner"`
Expected: Clean import

**Step 3: Commit**

```bash
git add retro-refiner.py
git commit -m "feat: add keyboard input handling for view toggle and scroll"
```

---

## Task 6: Implement RPC Status Updates

**Files:**
- Modify: `retro-refiner.py` (add methods to `DownloadUI` class)

**Step 1: Add RPC polling method**

```python
    def _update_from_rpc(self) -> None:
        """Poll aria2c RPC for download status updates."""
        if not self.rpc or not self.rpc_available:
            return

        try:
            # Get global stats
            stats = self.rpc.get_global_stat()
            if stats:
                self.total_speed = int(stats.get('downloadSpeed', 0))

            # Get active downloads
            active = self.rpc.get_active()
            active_paths = set()

            for dl in active:
                try:
                    # Extract filename from aria2c response
                    files = dl.get('files', [])
                    if not files:
                        continue
                    path = Path(files[0].get('path', ''))
                    active_paths.add(path.name)

                    # Find matching file in our list
                    for f in self.files:
                        if f['path'].name == path.name:
                            f['status'] = self.STATUS_DOWNLOADING
                            f['size'] = int(dl.get('totalLength', 0))
                            f['completed'] = int(dl.get('completedLength', 0))
                            f['speed'] = int(dl.get('downloadSpeed', 0))
                            break
                except (KeyError, ValueError):
                    continue

            # Get stopped (completed/failed)
            stopped = self.rpc.get_stopped()
            for dl in stopped:
                try:
                    files = dl.get('files', [])
                    if not files:
                        continue
                    path = Path(files[0].get('path', ''))
                    status = dl.get('status', '')

                    for f in self.files:
                        if f['path'].name == path.name:
                            if status == 'complete':
                                f['status'] = self.STATUS_DONE
                                f['size'] = int(dl.get('totalLength', 0))
                                f['completed'] = f['size']
                            elif status == 'error':
                                f['status'] = self.STATUS_FAILED
                            break
                except (KeyError, ValueError):
                    continue

            # Update counts
            with self.lock:
                self.completed_count = sum(1 for f in self.files if f['status'] == self.STATUS_DONE)
                self.failed_count = sum(1 for f in self.files if f['status'] == self.STATUS_FAILED)

        except Exception:
            self.rpc_available = False
```

**Step 2: Verify syntax**

Run: `python3 -c "import retro-refiner"`
Expected: Clean import

**Step 3: Commit**

```bash
git add retro-refiner.py
git commit -m "feat: add aria2c RPC polling for real-time status"
```

---

## Task 7: Implement Download Worker Thread

**Files:**
- Modify: `retro-refiner.py` (add methods to `DownloadUI` class)

**Step 1: Add download worker method**

```python
    def _download_worker(self) -> None:
        """Background thread that runs the actual downloads."""
        downloads = [(f['url'], f['path']) for f in self.files]

        tool = get_download_tool()

        if tool == 'aria2c':
            self._run_aria2c_with_rpc(downloads)
        elif tool == 'curl':
            self._run_curl_batch(downloads)
        else:
            self._run_python_downloads(downloads)

    def _run_aria2c_with_rpc(self, downloads: List[Tuple[str, Path]]) -> None:
        """Run aria2c with RPC enabled for status tracking."""
        import tempfile

        # Create input file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            input_file = f.name
            for url, dest_path in downloads:
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                f.write(f"{url}\n")
                f.write(f"  dir={dest_path.parent}\n")
                f.write(f"  out={dest_path.name}\n")

        # Start aria2c with RPC
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
            '--timeout=300',
            '--file-allocation=none',
            '-i', input_file
        ]

        try:
            self.subprocess = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )

            # Wait for RPC to become available
            self.rpc = Aria2cRPC(port=rpc_port, secret=rpc_secret)
            for _ in range(20):  # Try for 2 seconds
                if self.cancelled:
                    break
                if self.rpc.get_global_stat() is not None:
                    self.rpc_available = True
                    break
                _time.sleep(0.1)

            # Wait for process to finish
            while self.subprocess.poll() is None:
                if self.cancelled:
                    self.subprocess.terminate()
                    try:
                        self.subprocess.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        self.subprocess.kill()
                    break
                _time.sleep(0.1)

        except Exception:
            pass
        finally:
            try:
                os.unlink(input_file)
            except Exception:
                pass

            # Final status update from file system
            self._update_status_from_files()

    def _run_curl_batch(self, downloads: List[Tuple[str, Path]]) -> None:
        """Run curl batch download (no per-file progress)."""
        successful = download_batch_with_curl(downloads, parallel=self.parallel)

        with self.lock:
            for f in self.files:
                if f['path'] in successful:
                    f['status'] = self.STATUS_DONE
                elif f['path'].exists() and f['path'].stat().st_size > 0:
                    f['status'] = self.STATUS_DONE
                elif not self.cancelled:
                    f['status'] = self.STATUS_FAILED

            self.completed_count = sum(1 for f in self.files if f['status'] == self.STATUS_DONE)
            self.failed_count = sum(1 for f in self.files if f['status'] == self.STATUS_FAILED)

    def _run_python_downloads(self, downloads: List[Tuple[str, Path]]) -> None:
        """Fall back to Python urllib sequential downloads."""
        for url, dest_path in downloads:
            if self.cancelled:
                break

            # Mark as downloading
            for f in self.files:
                if f['url'] == url:
                    f['status'] = self.STATUS_DOWNLOADING
                    break

            # Download
            success = False
            try:
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=60) as resp:
                    with open(dest_path, 'wb') as out:
                        shutil.copyfileobj(resp, out)
                success = dest_path.exists() and dest_path.stat().st_size > 0
            except Exception:
                pass

            # Update status
            with self.lock:
                for f in self.files:
                    if f['url'] == url:
                        f['status'] = self.STATUS_DONE if success else self.STATUS_FAILED
                        break
                self.completed_count = sum(1 for f in self.files if f['status'] == self.STATUS_DONE)
                self.failed_count = sum(1 for f in self.files if f['status'] == self.STATUS_FAILED)

    def _update_status_from_files(self) -> None:
        """Update status by checking which files exist on disk."""
        with self.lock:
            for f in self.files:
                if f['status'] in (self.STATUS_QUEUED, self.STATUS_DOWNLOADING):
                    if f['path'].exists() and f['path'].stat().st_size > 0:
                        f['status'] = self.STATUS_DONE
                    elif not self.cancelled:
                        f['status'] = self.STATUS_FAILED

            self.completed_count = sum(1 for f in self.files if f['status'] == self.STATUS_DONE)
            self.failed_count = sum(1 for f in self.files if f['status'] == self.STATUS_FAILED)
```

**Step 2: Verify syntax**

Run: `python3 -c "import retro-refiner"`
Expected: Clean import

**Step 3: Commit**

```bash
git add retro-refiner.py
git commit -m "feat: add download worker thread with aria2c/curl/urllib backends"
```

---

## Task 8: Implement Main UI Loop

**Files:**
- Modify: `retro-refiner.py` (add methods to `DownloadUI` class)

**Step 1: Add main run method and curses loop**

```python
    def run(self) -> Dict[str, Path]:
        """
        Run the download UI. Returns dict of url -> local_path for successful downloads.
        """
        if not self.files:
            return {}

        # Non-TTY: fall back to simple progress
        if not self._is_tty():
            return self._run_simple_fallback()

        try:
            import curses
            return curses.wrapper(self._curses_main)
        except Exception:
            # Curses failed, fall back
            return self._run_simple_fallback()

    def _curses_main(self, stdscr) -> Dict[str, Path]:
        """Main curses loop."""
        import curses

        # Setup curses
        curses.curs_set(0)  # Hide cursor
        stdscr.nodelay(True)  # Non-blocking input
        stdscr.keypad(True)  # Enable arrow keys

        # Setup colors if available
        if curses.has_colors():
            curses.start_color()
            curses.use_default_colors()
            curses.init_pair(1, curses.COLOR_RED, -1)     # Failed
            curses.init_pair(2, curses.COLOR_GREEN, -1)   # Done
            curses.init_pair(3, curses.COLOR_CYAN, -1)    # Downloading

        self.start_time = _time.time()

        # Start download thread
        self.download_thread = threading.Thread(target=self._download_worker, daemon=True)
        self.download_thread.start()

        last_rpc_poll = 0
        rpc_poll_interval = 0.5  # Poll every 500ms

        # Main loop
        while True:
            # Check if downloads are complete
            if not self.download_thread.is_alive():
                # Final render
                if self.detailed_mode:
                    self._render_detailed(stdscr)
                else:
                    self._render_simple(stdscr)
                _time.sleep(0.3)  # Brief pause to show final state
                break

            # Handle input
            self._handle_input(stdscr)

            if self.cancelled:
                break

            # Poll RPC for status (only in detailed mode to save CPU)
            now = _time.time()
            if self.detailed_mode and self.rpc_available and now - last_rpc_poll >= rpc_poll_interval:
                self._update_from_rpc()
                last_rpc_poll = now

            # Render
            if self.detailed_mode:
                self._render_detailed(stdscr)
            else:
                self._render_simple(stdscr)

            _time.sleep(0.05)  # ~20 fps

        # Build result dict
        results = {}
        for f in self.files:
            if f['status'] == self.STATUS_DONE:
                results[f['url']] = f['path']

        return results

    def _run_simple_fallback(self) -> Dict[str, Path]:
        """Non-TTY fallback: just run downloads with print-based progress."""
        print(f"{self.system_name.upper()}: Downloading {len(self.files)} files...")

        downloads = [(f['url'], f['path']) for f in self.files]
        tool = get_download_tool()

        if tool == 'aria2c':
            successful = download_batch_with_aria2c(downloads, self.parallel, self.connections)
        elif tool == 'curl':
            successful = download_batch_with_curl(downloads, self.parallel)
        else:
            # Python fallback
            successful = []
            for url, path in downloads:
                try:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                    with urllib.request.urlopen(req, timeout=60) as resp:
                        with open(path, 'wb') as out:
                            shutil.copyfileobj(resp, out)
                    if path.exists() and path.stat().st_size > 0:
                        successful.append(path)
                except Exception:
                    pass

        # Build result dict
        results = {}
        for url, path in downloads:
            if path in successful or (path.exists() and path.stat().st_size > 0):
                results[url] = path

        print(f"  Downloaded {len(results)}/{len(self.files)} files")
        return results
```

**Step 2: Add curses import at top of file**

At the top of the file with other imports, add:
```python
import curses
```

**Step 3: Verify syntax**

Run: `python3 -c "import retro-refiner"`
Expected: Clean import

**Step 4: Commit**

```bash
git add retro-refiner.py
git commit -m "feat: add main UI loop with curses wrapper and fallback"
```

---

## Task 9: Integrate DownloadUI into Main Download Flow

**Files:**
- Modify: `retro-refiner.py` (update download section in main, around line 4773)

**Step 1: Replace the download loop with DownloadUI**

Find this code block (around line 4770-4779):
```python
        print(f"\n{system.upper()}: Downloading {len(filtered_urls)} ROMs...")

        # Use batch downloading for connection reuse and parallelism
        with tqdm(total=len(filtered_urls), desc=f"  {system.upper()} Downloading", unit="file", leave=False) as pbar:
            cached_files = download_files_cached_batch(
                filtered_urls, cache_dir,
                parallel=args.parallel,
                connections=args.parallel,  # Also use for multi-connection per file (aria2c)
                progress_callback=lambda: pbar.update(1)
            )
```

Replace with:
```python
        print(f"\n{system.upper()}: Downloading {len(filtered_urls)} ROMs...")

        # Prepare download list with cache paths
        downloads_to_ui = []
        for url in filtered_urls:
            url_clean = url.split('?')[0].split('#')[0]
            filename = urllib.request.unquote(url_clean.split('/')[-1])
            filename = re.sub(r'[<>:"/\\|?*]', '_', filename) or 'unknown_file'

            url_path = url_clean.replace('://', '/').split('/', 1)[1] if '://' in url_clean else url_clean
            path_parts = [p for p in url_path.split('/') if p]
            subdir = path_parts[-2] if len(path_parts) >= 2 else 'misc'
            subdir = re.sub(r'[<>:"/\\|?*]', '_', subdir)

            cache_subdir = cache_dir / subdir
            cache_subdir.mkdir(parents=True, exist_ok=True)
            cached_path = cache_subdir / filename

            # Skip already cached
            if not cached_path.exists():
                downloads_to_ui.append((url, cached_path))

        # Run interactive download UI
        if downloads_to_ui:
            ui = DownloadUI(
                system_name=system,
                files=downloads_to_ui,
                parallel=args.parallel,
                connections=args.parallel
            )
            cached_files = ui.run()
        else:
            cached_files = {}

        # Also include already-cached files in results
        for url in filtered_urls:
            if url not in cached_files:
                url_clean = url.split('?')[0].split('#')[0]
                filename = urllib.request.unquote(url_clean.split('/')[-1])
                filename = re.sub(r'[<>:"/\\|?*]', '_', filename) or 'unknown_file'

                url_path = url_clean.replace('://', '/').split('/', 1)[1] if '://' in url_clean else url_clean
                path_parts = [p for p in url_path.split('/') if p]
                subdir = path_parts[-2] if len(path_parts) >= 2 else 'misc'
                subdir = re.sub(r'[<>:"/\\|?*]', '_', subdir)

                cached_path = cache_dir / subdir / filename
                if cached_path.exists():
                    cached_files[url] = cached_path
```

**Step 2: Verify syntax**

Run: `python3 -c "import retro-refiner"`
Expected: Clean import

**Step 3: Commit**

```bash
git add retro-refiner.py
git commit -m "feat: integrate DownloadUI into main download flow"
```

---

## Task 10: Test End-to-End

**Step 1: Create a test with a small download**

Run a dry-run to verify the UI initializes:
```bash
python3 retro-refiner.py --help
```
Expected: Help text displays without errors

**Step 2: Test with a real (small) network source**

If you have a test URL with a few ROMs:
```bash
python3 retro-refiner.py -s https://example.com/roms/nes/ --commit
```
- Press 'i' to toggle detailed view
- Press 'i' again to return to simple view
- Let it complete or press 'q' to cancel

**Step 3: Verify non-TTY fallback**

```bash
python3 retro-refiner.py -s https://example.com/roms/nes/ --commit 2>&1 | cat
```
Expected: Falls back to print-based progress (no curses)

**Step 4: Final commit if any fixes needed**

```bash
git add -A
git commit -m "fix: address issues found during testing"
```

---

## Summary

This plan implements the interactive download UI in 10 tasks:

1. **Aria2c RPC Client** - JSON-RPC wrapper for real-time stats
2. **DownloadUI Structure** - Class skeleton with file tracking
3. **Simple View** - One-line progress bar rendering
4. **Detailed View** - Full-screen file list with scroll
5. **Input Handling** - Keyboard handling for toggle/scroll/cancel
6. **RPC Updates** - Poll aria2c for per-file progress
7. **Download Worker** - Background thread with aria2c/curl/urllib
8. **Main Loop** - Curses wrapper with render loop
9. **Integration** - Wire into main download flow
10. **Testing** - End-to-end verification

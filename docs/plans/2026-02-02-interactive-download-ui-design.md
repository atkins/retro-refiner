# Interactive Download UI Design

## Overview

Add an interactive download UI with two display modes. Users press "i" to toggle between a simple progress bar and a detailed full-screen view showing per-file progress, queue status, and network stats.

## Requirements

- **Default mode:** Simple progress bar (current behavior)
- **Detailed mode:** Full-screen curses display with per-file progress
- **Toggle:** Press "i" to switch between modes
- **Real-time stats:** Use aria2c JSON-RPC for per-file progress when available
- **Graceful degradation:** Show completion-only status when using curl/fallback
- **Cross-platform:** Use curses library for terminal control

## Architecture

### Components

1. **DownloadUI class** - Manages curses screen, handles keyboard input, renders both views
2. **aria2c RPC client** - Polls aria2c for real-time download stats
3. **Download state tracker** - Maintains file list with status updates

### Data Flow

- Main download loop runs in primary thread
- Curses UI runs refresh loop, checking for 'i' keypress
- When aria2c is active, RPC polling happens every 500ms
- When curl/fallback is used, only file-completion events update state

## UI Layout

### Header (3 lines)
```
Downloading ROMs for NES                                    [i] toggle view
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Progress: 24/150 files    12.4 MB/s    ETA: 2:34    Elapsed: 1:15
```

### File List (scrollable)
```
 ✓ Legend of Zelda, The (USA).zip                           2.1 MB    done
 ✓ Zelda II - The Adventure of Link (USA).zip               1.8 MB    done
 ↓ Metroid (USA).zip                                        1.2 MB    45%
 ↓ Super Mario Bros (USA).zip                               892 KB    23%
 ○ Kid Icarus (USA).zip                                     1.1 MB    queued
 ○ Castlevania (USA).zip                                    1.3 MB    queued
 ✗ Contra (USA).zip                                         failed
```

### Status Icons
- `✓` completed (green)
- `↓` downloading (cyan)
- `○` queued (dim)
- `✗` failed (red)

### Footer (1 line)
```
[i] simple view    [q] cancel    [↑↓] scroll
```

## aria2c RPC Integration

### Command-line flags
```
--enable-rpc --rpc-listen-port=6800 --rpc-secret=retro
```

### RPC Methods
- `aria2.tellActive(secret)` - Active downloads with speed/progress
- `aria2.tellWaiting(secret, 0, 100)` - Queued downloads
- `aria2.tellStopped(secret, 0, 100)` - Completed/failed downloads
- `aria2.getGlobalStat(secret)` - Overall bandwidth

### Data per Download
- `gid` - download ID
- `files[0].path` - local filename
- `totalLength` - file size in bytes
- `completedLength` - bytes downloaded
- `downloadSpeed` - current speed
- `status` - active/waiting/complete/error

### Polling Strategy
- Poll every 500ms while detailed view is active
- Stop polling in simple view to save CPU
- HTTP POST to `http://localhost:6800/jsonrpc`

## Integration Pattern

```python
class DownloadUI:
    def __init__(self, files_to_download, system_name):
        self.files = [{'url': url, 'path': path, 'status': 'queued', ...}
                      for url, path in files_to_download]
        self.detailed_mode = False
        self.rpc_port = None

    def run(self):
        curses.wrapper(self._main_loop)

    def _main_loop(self, stdscr):
        curses.curs_set(0)  # Hide cursor
        stdscr.nodelay(True)  # Non-blocking input

        download_thread = threading.Thread(target=self._download_worker)
        download_thread.start()

        while download_thread.is_alive() or not self._all_complete():
            self._handle_input(stdscr)
            self._update_from_rpc()
            self._render(stdscr)
            time.sleep(0.05)  # 20fps
```

## Error Handling

### Terminal Too Small
If terminal < 80x24, show "Terminal too small for detailed view" and stay in simple mode.

### RPC Connection Failure
Fall back to completion-only tracking. Show "RPC unavailable" briefly in header.

### User Cancellation (q key)
- Set shutdown flag
- Kill aria2c/curl subprocess
- Clean up partial downloads
- Exit curses cleanly

### Download Errors
Mark file as failed (✗), continue with remaining. Show error count in header.

### Curses Cleanup
Use `curses.wrapper()` for automatic cleanup. Add signal handlers for SIGINT/SIGTERM.

### Non-TTY Environments
If `sys.stdout.isatty()` is False, skip curses and use existing print-based progress.

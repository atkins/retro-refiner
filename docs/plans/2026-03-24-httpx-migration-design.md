# httpx Migration Design

## Goal

Replace aria2c, curl, and urllib with httpx for all HTTP operations. One download library, no external tools, no fallback chain.

## Motivation

- **Speed**: httpx with connection pooling + ThreadPoolExecutor parallelism
- **Reliability**: Native redirect handling (fixes myrient %5B/%5D encoding issues)
- **Simplicity**: One code path instead of aria2c → curl → urllib fallback chain (~400 lines removed)
- **Self-contained**: No external tool dependencies (aria2c/curl must be installed separately)

## Architecture

### Download Pipeline

```
_download_batch(downloads, parallel, system)
    └── ThreadPoolExecutor(max_workers=parallel)
        └── _download_one(url, dest_path, client)
            └── httpx.Client.get(url, follow_redirects=True)
                └── stream response → write chunks to .rrdownload
                └── rename to final path on completion
```

- Single `httpx.Client` with connection pooling, shared across all workers
- `follow_redirects=True` handles myrient redirects natively
- Streaming response writes chunks to `.rrdownload` temp file
- Rename to final path on completion (existing crash-safety pattern)
- Progress: file-polling every 1s (count completed files)
- Retry: 3 attempts per file on transient errors (5xx, timeouts, connection errors)

### Network Fetching (scanning/DATs)

Replace `fetch_url` and `fetch_urls_parallel` in network.py:
- `fetch_url(url)` → `httpx.get(url, follow_redirects=True, timeout=30)`
- `fetch_urls_parallel(urls, max_workers)` → ThreadPoolExecutor + shared httpx.Client

### Files Changed

| File | Changes |
|------|---------|
| `retro_refiner/network.py` | Replace `fetch_url`, `fetch_urls_parallel` with httpx |
| `retro_refiner/ui/api.py` | Replace `_download_batch` + `_download_with_aria2c` with single `_download_files` |
| `retro_refiner/downloader.py` | Gut aria2c/curl/urllib functions, replace with httpx downloader |
| `retro_refiner/scanner.py` | No direct changes (uses network.py functions) |
| `retro_refiner/dat.py` | No direct changes (uses network.py `fetch_url`) |

### What Gets Deleted

- `get_download_tool()` — no more tool detection
- `download_batch_with_curl()` — removed
- `download_batch_with_aria2c()` — removed
- `_download_with_aria2c()` in api.py — replaced by `_download_files()`
- Redirect pre-resolution HEAD request — httpx handles it
- curl chunking for Windows cmd length limits — gone
- Error page detection (curl saving HTML as ROMs) — httpx checks status codes
- `Aria2cRPC` class — removed
- `DownloadUI` class — simplified or removed

### What Stays

- `.rrdownload` temp file pattern — crash safety
- File-polling progress (count completed files per second)
- Step indicators `[1/3] [2/3] [3/3]` with ETA/speed
- `validate_destination` / `clean_destination` — unchanged
- Scan caching — unchanged
- `_SUBPROCESS_NO_WINDOW` pattern — no longer needed for downloads

### Error Handling

| Error | Action |
|-------|--------|
| `httpx.HTTPStatusError` (4xx/5xx) | Count as failed, don't retry 404s |
| `httpx.TimeoutException` | Retry up to 3 times |
| `httpx.ConnectError` | Retry up to 3 times |
| All retries exhausted | Log failure, continue with next file |

### Dependencies

- **Add**: `httpx`
- **Remove**: aria2c, curl as optional dependencies
- **Keep**: `urllib.parse` for URL string utilities (unquote, urlparse)

### Testing

- Update `tests/test_network.py` for httpx-based `fetch_url`
- Add download tests with `httpx.MockTransport` for unit testing without network
- Existing scanner/filter/transfer tests unaffected

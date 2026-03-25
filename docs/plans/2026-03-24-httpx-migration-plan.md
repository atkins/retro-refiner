# httpx Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace aria2c, curl, and urllib HTTP operations with httpx throughout the codebase.

**Architecture:** httpx.Client with connection pooling for all HTTP operations. ThreadPoolExecutor for parallel downloads. Streaming responses to `.rrdownload` temp files with atomic rename. 3 retries for transient errors.

**Tech Stack:** httpx, concurrent.futures.ThreadPoolExecutor

---

### Task 1: Install httpx and add to dependencies

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Install httpx**

```bash
pip install httpx
```

- [ ] **Step 2: Verify import works**

```bash
python -c "import httpx; print(httpx.__version__)"
```

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "chore: add httpx dependency"
```

---

### Task 2: Replace `fetch_url` and `fetch_urls_parallel` in network.py

**Files:**
- Modify: `retro_refiner/network.py:622-707`
- Test: `tests/test_network.py`

- [ ] **Step 1: Replace `fetch_url` with httpx**

Replace the `fetch_url` function (lines 622-671) with:

```python
def fetch_url(url: str, timeout: int = 30, max_redirects: int = 5,
              auth_header: Optional[str] = None) -> Tuple[bytes, str]:
    """Fetch content from a URL, following redirects.

    Returns (content, final_url) tuple.
    """
    import httpx  # pylint: disable=import-outside-toplevel
    headers = {
        'User-Agent': 'Mozilla/5.0 (compatible; Retro-Refiner/1.0)',
        'Accept': 'text/html,application/xhtml+xml,*/*',
        'Accept-Language': 'en-US,en;q=0.9',
    }
    if auth_header:
        headers['Authorization'] = auth_header

    with httpx.Client(
        follow_redirects=True,
        max_redirects=max_redirects,
        timeout=timeout,
        headers=headers,
    ) as client:
        response = client.get(url)
        final_url = str(response.url)

        if 'archive.org/account/' in final_url:
            raise Exception(  # pylint: disable=broad-exception-raised
                "Archive.org requires authentication.\n"
                "Get credentials at: https://archive.org/account/s3.php\n"
                "Then set: export IA_ACCESS_KEY=your_key\n"
                "         export IA_SECRET_KEY=your_secret"
            )

        response.raise_for_status()
        return response.content, final_url
```

- [ ] **Step 2: Replace `fetch_urls_parallel` with httpx**

Replace the `fetch_urls_parallel` function (lines 674-707) with:

```python
def fetch_urls_parallel(urls: List[str], max_workers: int = 16,
                        auth_header: Optional[str] = None,
                        progress_callback=None) -> Dict[str, Tuple[bytes, str]]:
    """Fetch multiple URLs in parallel using httpx + ThreadPoolExecutor.

    Returns dict of {url: (content, final_url)} for successful fetches.
    """
    import httpx  # pylint: disable=import-outside-toplevel
    results: Dict[str, Tuple[bytes, str]] = {}

    if not urls:
        return results

    headers = {
        'User-Agent': 'Mozilla/5.0 (compatible; Retro-Refiner/1.0)',
        'Accept': 'text/html,application/xhtml+xml,*/*',
    }
    if auth_header:
        headers['Authorization'] = auth_header

    client = httpx.Client(
        follow_redirects=True,
        timeout=30,
        headers=headers,
    )

    def _fetch_one(target_url):
        try:
            check_shutdown()
            response = client.get(target_url)
            response.raise_for_status()
            return target_url, (response.content, str(response.url)), None
        except Exception as exc:  # pylint: disable=broad-except
            return target_url, None, str(exc)

    actual_workers = min(max_workers, len(urls))

    try:
        with ThreadPoolExecutor(max_workers=actual_workers) as executor:
            futures = {executor.submit(_fetch_one, u): u for u in urls}
            completed = 0
            for future in as_completed(futures):
                completed += 1
                if progress_callback:
                    progress_callback(completed, len(urls))
                target_url, result, _error = future.result()
                if result:
                    results[target_url] = result
    finally:
        client.close()

    return results
```

- [ ] **Step 3: Remove old urllib imports no longer needed for fetching**

Remove `import urllib.request` and `import urllib.error` from the top of network.py if they are ONLY used by the old fetch functions. Keep `urllib.request.unquote` if used elsewhere (check with grep).

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_network.py -v --tb=short
```

Expected: All tests pass (scan cache, URL parsing, HTML parsing tests are unaffected since they don't do real HTTP).

Note: Tests that mock `fetch_url` behavior will need updating if they patch `urllib.request.urlopen`. Update them to work with the new httpx-based implementation.

- [ ] **Step 5: Commit**

```bash
git add retro_refiner/network.py tests/test_network.py
git commit -m "refactor: replace urllib with httpx in fetch_url and fetch_urls_parallel"
```

---

### Task 3: Replace download pipeline in api.py

**Files:**
- Modify: `retro_refiner/ui/api.py:1632-1870`

- [ ] **Step 1: Replace `_download_batch` and `_download_with_aria2c` with `_download_files`**

Delete both `_download_batch` (lines 1632-1707) and `_download_with_aria2c` (lines 1709-1870). Replace with:

```python
def _download_batch(self, downloads, parallel, system):
    """Download files using httpx with ThreadPoolExecutor."""
    import httpx  # pylint: disable=import-outside-toplevel

    total = len(downloads)
    fail_count = 0
    display = _display_name(system)

    client = httpx.Client(
        follow_redirects=True,
        timeout=60,
        headers={'User-Agent': 'Mozilla/5.0 (compatible; Retro-Refiner/1.0)'},
    )

    done_set = set()

    def _download_one(idx_url_path):
        idx, (url, dest_path) = idx_url_path
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        for attempt in range(3):
            try:
                with client.stream('GET', url) as response:
                    response.raise_for_status()
                    with open(dest_path, 'wb') as f:
                        for chunk in response.iter_bytes(8192):
                            f.write(chunk)
                done_set.add(idx)
                return idx, None
            except (httpx.TimeoutException, httpx.ConnectError,
                    httpx.HTTPStatusError) as exc:
                if (isinstance(exc, httpx.HTTPStatusError)
                        and exc.response.status_code < 500):
                    return idx, str(exc)  # don't retry 4xx
                if attempt == 2:
                    return idx, str(exc)
        return idx, 'max retries'

    dl_t0 = time.monotonic()

    try:
        with ThreadPoolExecutor(max_workers=parallel) as executor:
            futures = {
                executor.submit(_download_one, (i, d)): i
                for i, d in enumerate(downloads)
            }

            # Progress polling in main thread
            while not all(f.done() for f in futures):
                if not self._running:
                    executor.shutdown(wait=False, cancel_futures=True)
                    break
                completed = len(done_set)
                elapsed = time.monotonic() - dl_t0
                eta = self._eta_str(elapsed, completed, total)
                rate = completed / max(elapsed, 0.1)
                elapsed_s = self._elapsed_str(elapsed)
                msg = (f'{self._step_prefix(3)}'
                       f'{display}: {completed}/{total} '
                       f'\u2502 {rate:.1f} files/s '
                       f'\u2502 {elapsed_s}'
                       f'{eta}')
                self._push_event('progress', {
                    'phase': 'download',
                    'message': msg,
                    'current': completed,
                    'total': total,
                })
                time.sleep(1.0)

            # Collect errors
            for future in futures:
                _idx, error = future.result()
                if error:
                    fail_count += 1
    finally:
        client.close()

    if fail_count:
        self._push_event('log', {
            'text': f'  {display}: {fail_count} download(s) '
                    f'failed\n',
            'className': 'log-warning',
        })
    self._push_event('log', {
        'text': f'  {display}: downloaded {total - fail_count}'
                f'/{total} files\n',
    })
```

- [ ] **Step 2: Remove old imports and dead code**

Remove from api.py:
- Any `from retro_refiner.downloader import` lines in `_download_batch` (get_download_tool, download_batch_with_curl)
- The `_download_with_aria2c` method entirely
- Any `import subprocess`, `import tempfile` that were only used by the old download methods

- [ ] **Step 3: Run existing tests**

```bash
python -m pytest tests/test_api.py -v --tb=short
```

Expected: All tests pass (api tests don't do real downloads).

- [ ] **Step 4: Commit**

```bash
git add retro_refiner/ui/api.py
git commit -m "refactor: replace aria2c/curl/urllib download chain with httpx"
```

---

### Task 4: Clean up downloader.py

**Files:**
- Modify: `retro_refiner/downloader.py`

- [ ] **Step 1: Identify what's still used**

Grep the codebase for functions imported from downloader.py:

```bash
grep -r "from retro_refiner.downloader import\|from retro_refiner import downloader" retro_refiner/ tests/
```

After Tasks 2-3, the only remaining consumers should be:
- `DownloadUI` class (used by CLI mode in `cli.py`)
- `calculate_autotune_settings` (if still referenced)

- [ ] **Step 2: Remove unused functions**

Delete these functions that are no longer called:
- `get_download_tool()`
- `download_batch_with_curl()`
- `download_batch_with_aria2c()`
- `download_with_external_tool()`
- `Aria2cRPC` class
- `_register_aria2c_process`, `_unregister_aria2c_process`, `_terminate_process`, `_cleanup_aria2c_processes`
- The `_download_tool` global and its caching logic

Keep:
- `DownloadUI` class if CLI mode still uses it (check `cli.py`)
- `calculate_autotune_settings` if referenced
- Any constants or helpers that other code imports

- [ ] **Step 3: If DownloadUI is still used by CLI, refactor it to use httpx**

Check `cli.py` for `DownloadUI` usage. If the CLI still uses it for interactive downloads, update `DownloadUI._run_python_downloads` to use httpx instead of urllib. If CLI mode now routes through `_download_batch` in api.py, DownloadUI may be dead code entirely.

- [ ] **Step 4: Run full test suite**

```bash
python -m pytest --ignore=tests/test_smoke.py -v --tb=short
```

Expected: All tests pass.

- [ ] **Step 5: Run pylint and ruff**

```bash
python -m pylint retro_refiner/
python -m ruff check retro_refiner/
```

Expected: 10.00/10 pylint, no ruff errors.

- [ ] **Step 6: Commit**

```bash
git add retro_refiner/downloader.py retro_refiner/cli.py
git commit -m "refactor: remove aria2c/curl/urllib from downloader.py, clean up dead code"
```

---

### Task 5: Update CLAUDE.md and dependencies

**Files:**
- Modify: `CLAUDE.md`
- Modify: `pyproject.toml` (if not already done)

- [ ] **Step 1: Update CLAUDE.md**

Update these sections:
- Dependencies: add `httpx`, remove `aria2c` and `curl` from optional
- `_download_with_aria2c()` description → `_download_batch()` with httpx
- Remove references to aria2c RPC, curl fallback, redirect pre-resolution
- Update download progress description

- [ ] **Step 2: Update pyproject.toml with project metadata if needed**

Add httpx to any `[project.dependencies]` section if one exists.

- [ ] **Step 3: Run full test suite one final time**

```bash
python -m pytest --ignore=tests/test_smoke.py
python -m pylint retro_refiner/
python -m ruff check retro_refiner/
```

Expected: All pass.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md pyproject.toml
git commit -m "docs: update CLAUDE.md for httpx migration"
```

---

### Task 6: Manual smoke test

- [ ] **Step 1: Test with myrient NES source (includes T-En redirects)**

Launch the GUI, add the NES source with T-En collection, run preview, then commit. Verify:
- All 1445 ROMs selected
- All download successfully (including T-En files with brackets/ampersands in URLs)
- Progress bar shows during download
- No stalls or hangs

- [ ] **Step 2: Test with archive.org source**

Verify archive.org `/serve/` endpoint still works for browsing zip contents.

- [ ] **Step 3: Push final tag**

```bash
git tag v2026.03.24.HHMM
git push origin v2026.03.24.HHMM
```

# tenacity Integration Design

## Goal

Replace 3 manual retry loops with tenacity decorators for cleaner retry logic with proper backoff.

## Retry Patterns Found

| Location | Function | Retries | Backoff | Skip Logic |
|----------|----------|---------|---------|------------|
| `dat.py:390-422` | `download_ten_dat()` | 3 | Exponential (2s, 4s) | 404 = no retry |
| `cli.py:309-336` | download loop | 3 | None | 4xx = no retry |
| `api.py:1651-1667` | `_download_one()` | 3 | None | 4xx = no retry |

## Approach

### Shared retry predicate

All 3 sites share the same "don't retry 4xx" logic. Extract a reusable predicate:

```python
def _is_retryable(exc):
    """Return True if the exception should trigger a retry."""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return isinstance(exc, (httpx.TimeoutException, httpx.ConnectError))
```

### dat.py — `download_ten_dat()`

Uses urllib, not httpx. The retry wraps the entire download. Use tenacity with exponential backoff:

```python
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=4),
    retry=retry_if_exception_type((urllib.error.URLError, OSError)),
    reraise=True,
)
def _fetch_dat(url, dest_path): ...
```

Call from `download_ten_dat()` with 404 handled at the call site (catch and return None).

### cli.py — download loop

Extract the inner download body to a retryable function:

```python
@retry(
    stop=stop_after_attempt(3),
    retry=retry_if_exception(_is_retryable),
    reraise=True,
)
def _download_file(client, url, tmp_path): ...
```

### api.py — `_download_one()`

Same pattern as cli.py but returns `(idx, error)` tuple. Apply retry inside the function:

```python
@retry(
    stop=stop_after_attempt(3),
    retry=retry_if_exception(_is_retryable),
    reraise=True,
)
def _stream_to_file(client, url, dest_path): ...
```

## What Changes

| File | Change |
|------|--------|
| `retro_refiner/network.py` | Add `_is_retryable()` predicate (shared) |
| `retro_refiner/dat.py` | Replace manual retry loop with tenacity decorator |
| `retro_refiner/cli.py` | Replace manual retry loop with tenacity decorator |
| `retro_refiner/ui/api.py` | Replace manual retry loop with tenacity decorator |

## Dependencies

- **Add**: `tenacity`

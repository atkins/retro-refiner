"""Network operations: URL handling, HTML scraping, source validation.

Standalone implementations extracted from the monolith. No Console/Style
dependencies — output goes through callbacks or plain stderr.
"""
import json
import os
import re
import socket
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Shutdown mechanism
# ---------------------------------------------------------------------------

_shutdown_event = threading.Event()


def request_shutdown():
    """Signal all network operations to stop."""
    _shutdown_event.set()


def check_shutdown():
    """Raise SystemExit if shutdown was requested."""
    if _shutdown_event.is_set():
        raise SystemExit("Shutdown requested")


def reset_shutdown():
    """Clear the shutdown flag (useful between runs / in tests)."""
    _shutdown_event.clear()


# ---------------------------------------------------------------------------
# Size / URL formatting helpers
# ---------------------------------------------------------------------------

def format_size(size_bytes: int) -> str:
    """Format a size in bytes to a human-readable string."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    if size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    if size_bytes < 1024 ** 4:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"
    return f"{size_bytes / (1024 ** 4):.2f} TB"


def parse_budget_size(size_str):
    """Parse a budget size string like '10GB', '500MB' into bytes.

    Returns integer bytes or None if parsing fails.  Unlike
    ``parse_size_string`` (which returns 0 on failure for HTTP size
    headers), this function returns None so callers can distinguish
    "no budget" from "zero".
    """
    if not size_str:
        return None
    size_str = str(size_str).strip().upper()
    multipliers = {
        'TB': 1024 ** 4, 'T': 1024 ** 4,
        'GB': 1024 ** 3, 'G': 1024 ** 3,
        'MB': 1024 ** 2, 'M': 1024 ** 2,
        'KB': 1024, 'K': 1024,
        'B': 1,
    }
    for suffix, mult in multipliers.items():
        if size_str.endswith(suffix):
            try:
                return int(float(size_str[:-len(suffix)].strip()) * mult)
            except ValueError:
                return None
    try:
        return int(float(size_str))
    except ValueError:
        return None


def format_url(url: str, max_length: int = 0) -> str:
    """Format a URL for display: decode percent-encoding for readability."""
    decoded = urllib.request.unquote(url)
    if 0 < max_length < len(decoded):
        return decoded[:max_length - 3] + "..."
    return decoded


# ---------------------------------------------------------------------------
# URL utilities
# ---------------------------------------------------------------------------

def is_url(source: str) -> bool:
    """Check if a source string is a URL."""
    return source.startswith('http://') or source.startswith('https://')


def parse_url(url: str) -> Tuple[str, str, str]:
    """Parse URL into (scheme, host, path) components."""
    if '://' in url:
        scheme, rest = url.split('://', 1)
    else:
        scheme = 'https'
        rest = url

    if '/' in rest:
        host, path = rest.split('/', 1)
        path = '/' + path
    else:
        host = rest
        path = '/'

    return scheme, host, path


def normalize_url(href: str, base_url: str) -> Optional[str]:
    """Normalize a URL reference relative to a base URL.

    Handles relative paths, absolute paths, and full URLs.
    Returns None if the URL should be skipped.
    """
    # Decode HTML entities
    href = href.replace('&amp;', '&')

    # Skip empty, anchors, javascript, mailto, data URIs
    if not href or href.startswith('#') or href.startswith('javascript:') or \
       href.startswith('mailto:') or href.startswith('data:'):
        return None

    # Skip parent directory links
    if href in ('.', '..', '../', './'):
        return None

    # Skip query-only links
    if href.startswith('?'):
        return None

    # Parse base URL
    base_scheme, base_host, base_path = parse_url(base_url)

    # Ensure base path ends with /
    if not base_path.endswith('/'):
        base_path = base_path.rsplit('/', 1)[0] + '/'

    # Handle different URL types
    if href.startswith('//'):
        return f"{base_scheme}:{href}"

    if href.startswith('http://') or href.startswith('https://'):
        _, href_host, _ = parse_url(href)
        if href_host.lower() != base_host.lower():
            return None
        return href

    if href.startswith('/'):
        return f"{base_scheme}://{base_host}{href}"

    # Relative path
    path_parts = [p for p in base_path.split('/') if p]
    href_parts = href.split('/')

    for part in href_parts:
        if part == '..':
            if path_parts:
                path_parts.pop()
        elif part in ('', '.'):
            continue
        else:
            path_parts.append(part)

    resolved_path = '/' + '/'.join(path_parts)
    return f"{base_scheme}://{base_host}{resolved_path}"


# ---------------------------------------------------------------------------
# ROM extension constants
# ---------------------------------------------------------------------------

ROM_EXTENSIONS = (
    '.zip', '.7z', '.rar', '.sfc', '.smc', '.nes', '.fds', '.gb', '.gbc',
    '.gba', '.n64', '.z64', '.v64', '.md', '.gen', '.smd', '.sms', '.gg',
    '.pce', '.col', '.a26', '.a52', '.a78', '.j64', '.jag', '.lnx',
    '.vb', '.ws', '.wsc', '.mx1', '.mx2', '.32x', '.sg', '.vec',
    '.int', '.st', '.gcm', '.gcz', '.rvz', '.wbfs', '.iso', '.cue',
    '.chd', '.nds', '.3ds', '.cia', '.nsp', '.xci', '.pbp', '.cso',
    '.ngp', '.ngc', '.neo', '.pco', '.min', '.ndd', '.fcf'
)


# ---------------------------------------------------------------------------
# HTML link extraction and parsing
# ---------------------------------------------------------------------------

def extract_links_from_html(html: str) -> List[str]:
    """Extract all potential file/directory links from HTML content."""
    links = []

    href_pattern = re.compile(
        r'href\s*=\s*["\']?([^"\'<>\s]+)["\']?',
        re.IGNORECASE
    )
    src_pattern = re.compile(
        r'src\s*=\s*["\']([^"\'<>]+)["\']',
        re.IGNORECASE
    )
    data_pattern = re.compile(
        r'data-(?:url|href|src|link|file)\s*=\s*["\']([^"\'<>]+)["\']',
        re.IGNORECASE
    )
    url_pattern = re.compile(
        r'(?:^|\s|>)(/[^\s<>"\']+\.[a-zA-Z0-9]{2,4})(?:\s|<|$)',
        re.MULTILINE
    )
    onclick_pattern = re.compile(
        r'on(?:click|mousedown)\s*=\s*["\'][^"\']*'
        r'(?:location\.href\s*=\s*|window\.open\s*\()["\']([^"\']+)["\']',
        re.IGNORECASE
    )
    text_file_pattern = re.compile(
        r'(?:^|\s)([A-Za-z0-9][\w\s\-\.\(\)\[\]]+\.(?:' +
        '|'.join(ext[1:] for ext in ROM_EXTENSIONS) +
        r'))(?:\s|$)',
        re.IGNORECASE | re.MULTILINE
    )

    for match in href_pattern.finditer(html):
        links.append(match.group(1))
    for match in src_pattern.finditer(html):
        link = match.group(1)
        if any(link.lower().endswith(ext) for ext in ROM_EXTENSIONS):
            links.append(link)
    for match in data_pattern.finditer(html):
        links.append(match.group(1))
    for match in onclick_pattern.finditer(html):
        links.append(match.group(1))
    for match in url_pattern.finditer(html):
        links.append(match.group(1))

    pre_sections = re.findall(
        r'<(?:pre|code|listing)[^>]*>(.*?)</(?:pre|code|listing)>',
        html, re.IGNORECASE | re.DOTALL
    )
    for section in pre_sections:
        for match in text_file_pattern.finditer(section):
            links.append(match.group(1))

    return links


def is_rom_file(filename: str) -> bool:
    """Check if a filename appears to be a ROM file."""
    clean_name = filename.split('?')[0].split('#')[0]
    lower_name = clean_name.lower()
    try:
        lower_name = urllib.request.unquote(lower_name)
    except Exception:  # pylint: disable=broad-except
        pass
    return any(lower_name.endswith(ext) for ext in ROM_EXTENSIONS)


def is_directory_link(href: str) -> bool:
    """Check if a link appears to be a directory."""
    clean = href.split('?')[0].split('#')[0]
    if clean.endswith('/'):
        return True
    last_part = clean.rstrip('/').split('/')[-1]
    if '.' not in last_part and last_part not in ('', '.', '..'):
        return not any(last_part.lower().endswith(ext) for ext in ROM_EXTENSIONS)
    return False


def parse_size_string(size_str: str) -> int:
    """Parse a human-readable size string into bytes.

    Handles formats like: 1.5M, 100K, 50G, 1.5 MB, 100 KB, 175.9 MiB, 1536000
    """
    if not size_str:
        return 0

    size_str = size_str.strip().upper()

    try:
        return int(size_str)
    except ValueError:
        pass

    match = re.match(r'^([\d.]+)\s*([KMGT])I?B?$', size_str)
    if not match:
        return 0

    try:
        value = float(match.group(1))
        unit = match.group(2) or ''
        multipliers = {
            '': 1,
            'K': 1024,
            'M': 1024 * 1024,
            'G': 1024 * 1024 * 1024,
            'T': 1024 * 1024 * 1024 * 1024,
        }
        return int(value * multipliers.get(unit, 1))
    except (ValueError, TypeError):
        return 0


def extract_file_sizes_from_html(html: str) -> Dict[str, int]:
    """Extract file sizes from HTML directory listings.

    Returns dict mapping filename -> size in bytes.
    """
    sizes: Dict[str, int] = {}

    # Pattern 1: Myrient/structured table format
    myrient_pattern = re.compile(
        r'<td[^>]*class="link"[^>]*>\s*<a\s+href="([^"]+)"[^>]*>([^<]+)</a>\s*</td>\s*'
        r'<td[^>]*class="size"[^>]*>\s*([\d.]+\s*[KMGT]i?B|[\d.]+|-)\s*</td>',
        re.IGNORECASE
    )

    myrient_matched = False
    for match in myrient_pattern.finditer(html):
        myrient_matched = True
        href = match.group(1)
        filename = match.group(2).strip()
        size_str = match.group(3).strip()

        if size_str != '-':
            size = parse_size_string(size_str)
            if size > 0:
                clean_href = urllib.request.unquote(href.split('?')[0].split('#')[0])
                sizes[clean_href] = size
                sizes[filename] = size

    if myrient_matched:
        return sizes

    # Pattern 2: Apache/nginx autoindex format
    autoindex_pattern = re.compile(
        r'<a\s+href=["\']?([^"\'<>\s]+)["\']?[^>]*>([^<]+)</a>\s*'
        r'(?:\d{1,2}[-/]\w{3}[-/]\d{2,4}\s+\d{1,2}:\d{2}'
        r'|\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})\s*'
        r'([\d.]+\s*[KMGT]i?B?|\d+|-)',
        re.IGNORECASE
    )

    for match in autoindex_pattern.finditer(html):
        href = match.group(1)
        size_str = match.group(3).strip()
        if size_str != '-':
            size = parse_size_string(size_str)
            if size > 0:
                filename = match.group(2).strip()
                clean_href = urllib.request.unquote(href.split('?')[0].split('#')[0])
                sizes[clean_href] = size
                sizes[filename] = size

    if sizes:
        return sizes

    # Pattern 3: Generic table format with size in separate cell
    table_row_pattern = re.compile(
        r'<tr[^>]*>.*?<a\s+href=["\']?([^"\'<>\s]+)["\']?[^>]*>([^<]+)</a>.*?'
        r'<td[^>]*>\s*([\d.]+\s*[KMGT]i?B?|\d+)\s*</td>.*?</tr>',
        re.IGNORECASE | re.DOTALL
    )

    for match in table_row_pattern.finditer(html):
        href = match.group(1)
        filename = match.group(2).strip()
        size_str = match.group(3).strip()
        size = parse_size_string(size_str)
        if size > 0:
            clean_href = urllib.request.unquote(href.split('?')[0].split('#')[0])
            sizes[clean_href] = size
            sizes[filename] = size

    # Pattern 4: Pre/listing block with sizes (FTP-style)
    pre_sections = re.findall(
        r'<(?:pre|code|listing)[^>]*>(.*?)</(?:pre|code|listing)>',
        html, re.IGNORECASE | re.DOTALL
    )

    for section in pre_sections:
        ftp_pattern = re.compile(
            r'[-drwx]{10}\s+\d+\s+\S+\s+\S+\s+(\d+)\s+\w+\s+\d+\s+[\d:]+\s+(\S+)',
            re.MULTILINE
        )
        for match in ftp_pattern.finditer(section):
            size = int(match.group(1))
            filename = match.group(2)
            if size > 0:
                sizes[filename] = size

        simple_pattern = re.compile(
            r'(\S+\.(?:zip|7z|rar|iso|chd|cue|bin))\s+(\d+)',
            re.IGNORECASE
        )
        for match in simple_pattern.finditer(section):
            filename = match.group(1)
            size = int(match.group(2))
            if size > 0:
                sizes[filename] = size

    return sizes


def get_filename_from_url(url: str) -> str:
    """Extract and decode filename from a URL."""
    url_clean = url.split('?')[0].split('#')[0]
    filename = urllib.request.unquote(url_clean.split('/')[-1])
    return filename


def parse_html_for_files(html: str, base_url: str) -> List[str]:
    """Parse HTML content and extract ROM file URLs."""
    files = []
    seen: set = set()

    links = extract_links_from_html(html)

    for href in links:
        url = normalize_url(href, base_url)
        if not url or url in seen:
            continue
        seen.add(url)
        if is_rom_file(url):
            files.append(url)

    return files


def parse_html_for_files_with_sizes(html: str, base_url: str) -> List[Tuple[str, int]]:
    """Parse HTML content and extract ROM file URLs with their sizes.

    Returns list of (url, size) tuples. Size is 0 if unknown.
    """
    files = []
    seen: set = set()

    size_map = extract_file_sizes_from_html(html)
    links = extract_links_from_html(html)

    for href in links:
        url = normalize_url(href, base_url)
        if not url or url in seen:
            continue
        seen.add(url)
        if is_rom_file(url):
            filename = get_filename_from_url(url)
            size = size_map.get(filename, 0) or size_map.get(href, 0)
            files.append((url, size))

    return files


def parse_html_for_directories(html: str, base_url: str) -> List[str]:
    """Parse HTML content and extract subdirectory URLs."""
    dirs = []
    seen: set = set()

    links = extract_links_from_html(html)

    for href in links:
        if not is_directory_link(href):
            continue
        url = normalize_url(href, base_url)
        if not url:
            continue
        if not url.endswith('/'):
            url += '/'
        if url in seen or url == base_url or url == base_url.rstrip('/') + '/':
            continue
        base_normalized = base_url.rstrip('/') + '/'
        if not url.startswith(base_normalized):
            continue
        seen.add(url)
        dirs.append(url)

    return dirs


# ---------------------------------------------------------------------------
# SSRF protection
# ---------------------------------------------------------------------------

_PRIVATE_IP_PREFIXES = (
    '127.', '10.', '192.168.', '0.',
)

_PRIVATE_172_RANGE = range(16, 32)


def _is_private_ip(ip_str: str) -> bool:
    """Return True if *ip_str* is a private/loopback IP literal."""
    bare = ip_str.strip('[]')
    if bare in ('::1', ''):
        return True
    for prefix in _PRIVATE_IP_PREFIXES:
        if bare.startswith(prefix):
            return True
    # 172.16.0.0 - 172.31.255.255
    if bare.startswith('172.'):
        parts = bare.split('.')
        try:
            if int(parts[1]) in _PRIVATE_172_RANGE:
                return True
        except (IndexError, ValueError):
            pass
    return False


def _is_private_host(hostname: str) -> bool:
    """Return True if *hostname* resolves to a private/loopback address."""
    if hostname in ('localhost', '[::1]'):
        return True
    if _is_private_ip(hostname):
        return True
    # Resolve DNS and check all resulting addresses
    try:
        addr_info = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC,
                                       socket.SOCK_STREAM)
        for _family, _type, _proto, _canonname, sockaddr in addr_info:
            if _is_private_ip(sockaddr[0]):
                return True
    except socket.gaierror:
        pass
    return False


# ---------------------------------------------------------------------------
# Source validation
# ---------------------------------------------------------------------------

def validate_source(source: str, timeout: int = 15) -> Tuple[bool, str]:
    """Validate a source path or URL is accessible.

    Returns (is_valid, message) tuple.
    Rejects URLs pointing to private/localhost addresses (SSRF protection).
    """
    if is_url(source):
        # SSRF check — reject private / loopback targets
        _scheme, host, _path = parse_url(source)
        # Strip port if present
        host_no_port = host.rsplit(':', 1)[0] if ':' in host else host
        if _is_private_host(host_no_port):
            return False, "URL points to a private/localhost address"
        try:
            request = urllib.request.Request(
                source,
                headers={
                    'User-Agent': 'Mozilla/5.0 (compatible; Retro-Refiner/1.0)',
                    'Accept': 'text/html,application/xhtml+xml,*/*',
                }
            )
            with urllib.request.urlopen(request, timeout=timeout) as response:
                if response.status == 200:
                    return True, ""
                return False, f"HTTP {response.status}"
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return False, "Not found (404)"
            if exc.code == 403:
                return False, "Access denied (403)"
            if exc.code == 401:
                return False, "Authentication required (401)"
            return False, f"HTTP error {exc.code}"
        except urllib.error.URLError as exc:
            return False, f"Connection failed: {exc.reason}"
        except socket.timeout:
            return False, "Connection timed out"
        except Exception as exc:  # pylint: disable=broad-except
            return False, str(exc)
    else:
        path = Path(source)
        if not path.exists():
            return False, "Path does not exist"
        if not path.is_dir():
            return False, "Path is not a directory"
        return True, ""


def validate_all_sources(local_sources: List[Path],
                         network_sources: List[str]) -> List[Tuple[str, str]]:
    """Validate all sources are accessible.

    Returns list of (source, error_message) tuples for failed sources.
    """
    errors = []

    for source in local_sources:
        success, error = validate_source(str(source))
        if not success:
            errors.append((str(source), error))

    for source in network_sources:
        print(f"Validating: {format_url(source)}...", end=" ", flush=True)
        success, error = validate_source(source)
        if success:
            print("OK")
        else:
            print(f"FAILED ({error})")
            errors.append((source, error))

    return errors


# ---------------------------------------------------------------------------
# URL fetching
# ---------------------------------------------------------------------------

def fetch_url(url: str, timeout: int = 30, max_redirects: int = 5,
              auth_header: Optional[str] = None) -> Tuple[bytes, str]:
    """Fetch content from a URL, following redirects.

    Returns (content, final_url) tuple.
    """
    current_url = url
    redirects = 0

    while redirects < max_redirects:
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (compatible; Retro-Refiner/1.0)',
                'Accept': 'text/html,application/xhtml+xml,*/*',
                'Accept-Language': 'en-US,en;q=0.9',
            }
            if auth_header:
                headers['Authorization'] = auth_header
            request = urllib.request.Request(current_url, headers=headers)
            with urllib.request.urlopen(request, timeout=timeout) as response:
                final_url = response.geturl()

                if 'archive.org/account/' in final_url:
                    raise Exception(  # pylint: disable=broad-exception-raised
                        "Archive.org requires authentication.\n"
                        "Get credentials at: https://archive.org/account/s3.php\n"
                        "Then set: export IA_ACCESS_KEY=your_key\n"
                        "         export IA_SECRET_KEY=your_secret"
                    )

                return response.read(), final_url
        except urllib.error.HTTPError as exc:
            if exc.code in (301, 302, 303, 307, 308):
                new_url = exc.headers.get('Location')
                if new_url:
                    if 'archive.org/account/' in new_url:
                        raise Exception(  # pylint: disable=broad-exception-raised
                            "Archive.org requires authentication.\n"
                            "Get credentials at: https://archive.org/account/s3.php\n"
                            "Then set: export IA_ACCESS_KEY=your_key\n"
                            "         export IA_SECRET_KEY=your_secret"
                        ) from exc
                    current_url = normalize_url(new_url, current_url) or new_url
                    redirects += 1
                    continue
            raise

    raise Exception(  # pylint: disable=broad-exception-raised
        f"Too many redirects for {url}"
    )


def fetch_urls_parallel(urls: List[str], max_workers: int = 16,
                        auth_header: Optional[str] = None,
                        progress_callback=None) -> Dict[str, Tuple[bytes, str]]:
    """Fetch multiple URLs in parallel using ThreadPoolExecutor.

    Returns dict of {url: (content, final_url)} for successful fetches.
    """
    results: Dict[str, Tuple[bytes, str]] = {}

    if not urls:
        return results

    def _fetch_one(target_url):
        try:
            check_shutdown()
            content, final_url = fetch_url(target_url, auth_header=auth_header)
            return target_url, (content, final_url), None
        except Exception as exc:  # pylint: disable=broad-except
            return target_url, None, str(exc)

    actual_workers = min(max_workers, len(urls))

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

    return results


# ---------------------------------------------------------------------------
# Archive.org / T-En / Myrient helpers
# ---------------------------------------------------------------------------

def is_archive_org_url(url: str) -> bool:
    """Check if URL is from Internet Archive (archive.org)."""
    return 'archive.org/' in url.lower()


def get_ia_auth_header(access_key: Optional[str] = None,
                       secret_key: Optional[str] = None) -> Optional[str]:
    """Build Internet Archive S3-style authorization header."""
    if access_key and secret_key:
        return f'LOW {access_key}:{secret_key}'
    return None


def is_ten_source(url: str) -> bool:
    """Check if a URL is a T-En (translation) collection source."""
    url_decoded = urllib.request.unquote(url).lower()
    return '[t-en]' in url_decoded or 't-en collection' in url_decoded


def is_myrient_tosec_url(url: str) -> bool:
    """Check if a URL is a Myrient TOSEC source."""
    return 'myrient.erista.me/files/TOSEC/' in url


# ---------------------------------------------------------------------------
# Scan cache
# ---------------------------------------------------------------------------

SCAN_CACHE_FILE = '_scan_cache.json'
SCAN_CACHE_MAX_AGE = 86400  # 24 hours


def load_scan_cache(cache_dir: Path,
                    url: str) -> Optional[Tuple[Dict[str, List[str]], Dict[str, int]]]:
    """Load cached network scan results if fresh (< 24h old)."""
    cache_path = cache_dir / SCAN_CACHE_FILE
    if not cache_path.exists():
        return None
    try:
        with open(cache_path, 'r', encoding='utf-8') as fh:
            cache = json.load(fh)
        entry = cache.get(url)
        if not entry:
            return None
        age = time.time() - entry.get('timestamp', 0)
        if age > SCAN_CACHE_MAX_AGE:
            return None
        url_dict = entry.get('urls', {})
        url_sizes = entry.get('sizes', {})
        return url_dict, url_sizes
    except (json.JSONDecodeError, IOError, KeyError):
        return None


def save_scan_cache(cache_dir: Path, url: str,
                    url_dict: Dict[str, List[str]],
                    url_sizes: Dict[str, int]):
    """Save network scan results to cache."""
    cache_path = cache_dir / SCAN_CACHE_FILE
    cache: dict = {}
    if cache_path.exists():
        try:
            with open(cache_path, 'r', encoding='utf-8') as fh:
                cache = json.load(fh)
        except (json.JSONDecodeError, IOError):
            cache = {}
    now = time.time()
    cache = {k: v for k, v in cache.items()
             if now - v.get('timestamp', 0) < SCAN_CACHE_MAX_AGE}
    cache[url] = {
        'timestamp': now,
        'urls': url_dict,
        'sizes': url_sizes,
    }
    try:
        import tempfile as _tmpmod  # pylint: disable=import-outside-toplevel
        cache_dir.mkdir(parents=True, exist_ok=True)
        # Write to a temp file first, then atomically rename to avoid
        # partial writes if the process is interrupted.
        fd, tmp_path = _tmpmod.mkstemp(
            dir=str(cache_dir), suffix='.tmp')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as fh:
                json.dump(cache, fh)
            # os.replace is atomic on POSIX; near-atomic on Windows
            os.replace(tmp_path, str(cache_path))
        except BaseException:
            # Clean up temp file on failure
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    except IOError:
        pass

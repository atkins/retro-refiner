#!/usr/bin/env python3
"""
Retro-Refiner - Refine your ROM collection down to the essentials.

A portable Python script that filters ROM collections and selects the best
English version of each game. Works on any machine with any ROM collection.

Selection Criteria:
- One ROM per unique game (groups regional variants)
- English priority: USA > World > Europe > Australia
- Includes fan translations for Japan-only games
- Keeps Japan exclusives when no English version exists
- Prefers latest revision
- Includes prototypes
- Excludes: betas, demos, promos, samples, re-releases, BIOS, pirate, compilations
"""

import os
import re
import sys
import signal
import shutil
import zipfile
import binascii
import fnmatch
import json
import urllib.request
import urllib.error
import socket
import http.client
import ssl
import subprocess
import threading
import curses
from urllib.parse import urlparse
from pathlib import Path
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Tuple

# Title mappings cache (loaded from title_mappings.json)
_title_mappings_cache: Optional[Dict[str, str]] = None


def load_title_mappings() -> Dict[str, str]:
    """
    Load title mappings from title_mappings.json.
    Returns a flat dict of {source_title: target_title}.
    Caches the result for subsequent calls.
    """
    global _title_mappings_cache

    if _title_mappings_cache is not None:
        return _title_mappings_cache

    mappings_path = Path(__file__).parent / 'title_mappings.json'
    flat_mappings = {}

    if mappings_path.exists():
        try:
            with open(mappings_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # Flatten the categorized structure into a single dict
            for category, entries in data.items():
                if category.startswith('_'):
                    continue  # Skip metadata
                if isinstance(entries, dict):
                    flat_mappings.update(entries)
        except (json.JSONDecodeError, IOError) as e:
            print(f"Warning: Could not load title_mappings.json: {e}")

    _title_mappings_cache = flat_mappings
    return flat_mappings


# Minimal YAML parser for config files (no external dependency)
def parse_simple_yaml(content: str) -> dict:
    """
    Parse a simple YAML subset: key-value pairs, lists, comments.
    Supports: strings, booleans, integers, floats, lists.
    Does NOT support: nested objects, anchors, multi-line strings.
    """
    result = {}
    current_key = None
    current_list = None

    for line in content.split('\n'):
        # Remove inline comments (but preserve # in quoted strings)
        if '#' in line:
            in_quote = False
            quote_char = None
            for i, char in enumerate(line):
                if char in ('"', "'") and (i == 0 or line[i-1] != '\\'):
                    if not in_quote:
                        in_quote = True
                        quote_char = char
                    elif char == quote_char:
                        in_quote = False
                elif char == '#' and not in_quote:
                    line = line[:i]
                    break

        stripped = line.rstrip()
        if not stripped:
            continue

        # List item (- value)
        if stripped.lstrip().startswith('- '):
            if current_key and current_list is not None:
                item = stripped.lstrip()[2:].strip()
                current_list.append(_parse_yaml_value(item))
            continue

        # Check indentation - if not indented, close any open list
        if not line.startswith(' ') and not line.startswith('\t'):
            if current_key and current_list is not None:
                result[current_key] = current_list
                current_list = None
                current_key = None

        # Key: value pair
        if ':' in stripped:
            colon_idx = stripped.index(':')
            key = stripped[:colon_idx].strip()
            value_part = stripped[colon_idx + 1:].strip()

            if not key:
                continue

            if value_part == '':
                # Could be start of a list
                current_key = key
                current_list = []
            else:
                result[key] = _parse_yaml_value(value_part)
                current_key = None
                current_list = None

    # Close any remaining open list
    if current_key and current_list is not None:
        result[current_key] = current_list

    return result


def _parse_yaml_value(value: str):
    """Parse a YAML value into Python type."""
    if not value:
        return None

    # Remove quotes
    if (value.startswith('"') and value.endswith('"')) or \
       (value.startswith("'") and value.endswith("'")):
        return value[1:-1]

    # Booleans
    if value.lower() in ('true', 'yes', 'on'):
        return True
    if value.lower() in ('false', 'no', 'off'):
        return False

    # Null
    if value.lower() in ('null', '~', ''):
        return None

    # Numbers
    try:
        if '.' in value:
            return float(value)
        return int(value)
    except ValueError:
        pass

    # Plain string
    return value

# Built-in progress bar (no external dependency)
import time as _time

class ProgressBar:
    """Progress bar with ETA and throughput metrics."""

    def __init__(self, iterable, desc='', unit='it', leave=True, total=None):
        self.iterable = iterable
        self.desc = desc
        self.unit = unit
        self.leave = leave
        self.total = total if total is not None else len(iterable) if hasattr(iterable, '__len__') else None
        self.current = 0
        self.start_time = None
        self.bar_width = 20

    def __iter__(self):
        self.start_time = _time.time()
        self._print_bar()
        for item in self.iterable:
            yield item
            self.current += 1
            self._print_bar()
        self._finish()

    def __enter__(self):
        self.start_time = _time.time()
        self._print_bar()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._finish()
        return False

    def update(self, n=1):
        """Manually update progress by n steps."""
        self.current += n
        self._print_bar()

    def _format_time(self, seconds):
        """Format seconds into human-readable string."""
        if seconds < 60:
            return f"{seconds:.0f}s"
        elif seconds < 3600:
            mins, secs = divmod(int(seconds), 60)
            return f"{mins}:{secs:02d}"
        else:
            hours, remainder = divmod(int(seconds), 3600)
            mins, secs = divmod(remainder, 60)
            return f"{hours}:{mins:02d}:{secs:02d}"

    def _print_bar(self):
        elapsed = _time.time() - self.start_time if self.start_time else 0

        if self.total and self.total > 0:
            pct = self.current / self.total
            filled = int(self.bar_width * pct)
            bar = '█' * filled + '░' * (self.bar_width - filled)

            # Calculate throughput and ETA
            if self.current > 0 and elapsed > 0:
                rate = self.current / elapsed
                remaining = (self.total - self.current) / rate if rate > 0 else 0
                rate_str = f"{rate:.1f}" if rate < 100 else f"{rate:.0f}"
                eta_str = self._format_time(remaining)
                elapsed_str = self._format_time(elapsed)
                stats = f" [{elapsed_str}<{eta_str}, {rate_str}{self.unit}/s]"
            else:
                stats = ""

            line = f"\r  {self.desc}: |{bar}| {self.current}/{self.total}{stats}"
        else:
            # Unknown total - just show count and rate
            if self.current > 0 and elapsed > 0:
                rate = self.current / elapsed
                rate_str = f"{rate:.1f}" if rate < 100 else f"{rate:.0f}"
                stats = f" [{rate_str}{self.unit}/s]"
            else:
                stats = ""
            line = f"\r  {self.desc}: {self.current} {self.unit}{stats}"

        # Pad to clear previous longer lines
        print(f"{line:<79}", end='', flush=True)

    def _finish(self):
        if self.leave:
            print()  # Move to next line
        else:
            # Clear the line
            print('\r' + ' ' * 79 + '\r', end='', flush=True)


def tqdm(iterable=None, **kwargs):
    """Compatibility wrapper matching tqdm's interface."""
    return ProgressBar(
        iterable if iterable is not None else [],
        desc=kwargs.get('desc', ''),
        unit=kwargs.get('unit', 'it'),
        leave=kwargs.get('leave', True),
        total=kwargs.get('total')
    )

# Global flag for graceful shutdown
_shutdown_requested = False

def _signal_handler(signum, frame):
    """Handle Ctrl+C for graceful shutdown."""
    global _shutdown_requested
    if _shutdown_requested:
        # Second Ctrl+C forces immediate exit
        print("\n\nForced exit.")
        sys.exit(1)
    _shutdown_requested = True
    print("\n\nShutdown requested (Ctrl+C again to force exit)...")

def check_shutdown():
    """Check if shutdown was requested and exit if so."""
    if _shutdown_requested:
        print("Exiting...")
        sys.exit(0)


def format_size(size_bytes: int) -> str:
    """Format a size in bytes to a human-readable string."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


def format_url(url: str, max_length: int = 0) -> str:
    """Format a URL for display: decode percent-encoding for readability."""
    decoded = urllib.request.unquote(url)

    if max_length > 0 and len(decoded) > max_length:
        return decoded[:max_length - 3] + "..."

    return decoded


def get_file_size(filepath: Path) -> int:
    """Get the size of a file in bytes."""
    try:
        return filepath.stat().st_size
    except (OSError, IOError):
        return 0


# =============================================================================
# Network Source Support
# =============================================================================

# Common ROM extensions for network scanning
ROM_EXTENSIONS = (
    '.zip', '.7z', '.rar', '.sfc', '.smc', '.nes', '.fds', '.gb', '.gbc',
    '.gba', '.n64', '.z64', '.v64', '.md', '.gen', '.smd', '.sms', '.gg',
    '.pce', '.col', '.a26', '.a52', '.a78', '.j64', '.jag', '.lnx',
    '.vb', '.ws', '.wsc', '.mx1', '.mx2', '.32x', '.sg', '.vec',
    '.int', '.st', '.gcm', '.gcz', '.rvz', '.wbfs', '.iso', '.cue',
    '.chd', '.nds', '.3ds', '.cia', '.nsp', '.xci', '.pbp', '.cso',
    '.ngp', '.ngc', '.neo', '.pco', '.min', '.ndd', '.fcf'
)


def is_url(source: str) -> bool:
    """Check if a source string is a URL."""
    return source.startswith('http://') or source.startswith('https://')


def parse_url(url: str) -> Tuple[str, str, str]:
    """Parse URL into (scheme, host, path) components."""
    # Handle scheme
    if '://' in url:
        scheme, rest = url.split('://', 1)
    else:
        scheme = 'https'
        rest = url

    # Handle host and path
    if '/' in rest:
        host, path = rest.split('/', 1)
        path = '/' + path
    else:
        host = rest
        path = '/'

    return scheme, host, path


def normalize_url(href: str, base_url: str) -> Optional[str]:
    """
    Normalize a URL reference relative to a base URL.
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
        # Get directory of base path
        base_path = base_path.rsplit('/', 1)[0] + '/'

    # Handle different URL types
    if href.startswith('//'):
        # Protocol-relative URL
        return f"{base_scheme}:{href}"

    elif href.startswith('http://') or href.startswith('https://'):
        # Full URL - check if same host
        href_scheme, href_host, href_path = parse_url(href)
        if href_host.lower() != base_host.lower():
            return None  # Different domain
        return href

    elif href.startswith('/'):
        # Absolute path on same host
        return f"{base_scheme}://{base_host}{href}"

    else:
        # Relative path - need to resolve against base
        # Handle ../ and ./
        # Remove empty parts from trailing slashes
        path_parts = [p for p in base_path.split('/') if p]
        href_parts = href.split('/')

        for part in href_parts:
            if part == '..':
                if path_parts:
                    path_parts.pop()
            elif part == '.' or part == '':
                continue
            else:
                path_parts.append(part)

        resolved_path = '/' + '/'.join(path_parts)

        return f"{base_scheme}://{base_host}{resolved_path}"


def extract_links_from_html(html: str) -> List[str]:
    """
    Extract all potential file/directory links from HTML content.
    Handles various HTML structures and link formats.
    """
    links = []

    # Pattern 1: Standard href attributes (most common)
    # Matches: href="url", href='url', href=url
    href_pattern = re.compile(
        r'href\s*=\s*["\']?([^"\'<>\s]+)["\']?',
        re.IGNORECASE
    )

    # Pattern 2: src attributes (for some file hosting sites)
    src_pattern = re.compile(
        r'src\s*=\s*["\']([^"\'<>]+)["\']',
        re.IGNORECASE
    )

    # Pattern 3: data-url, data-href, data-src attributes
    data_pattern = re.compile(
        r'data-(?:url|href|src|link|file)\s*=\s*["\']([^"\'<>]+)["\']',
        re.IGNORECASE
    )

    # Pattern 4: Direct URL patterns in text (for FTP-style listings)
    # Matches URLs that look like file paths
    url_pattern = re.compile(
        r'(?:^|\s|>)(/[^\s<>"\']+\.[a-zA-Z0-9]{2,4})(?:\s|<|$)',
        re.MULTILINE
    )

    # Pattern 5: onclick/onmousedown with URLs (some download sites)
    onclick_pattern = re.compile(
        r'on(?:click|mousedown)\s*=\s*["\'][^"\']*(?:location\.href\s*=\s*|window\.open\s*\()["\']([^"\']+)["\']',
        re.IGNORECASE
    )

    # Pattern 6: Plain text filenames in pre/code blocks (FTP listings)
    # Match lines that look like: "filename.zip  12345  2024-01-01"
    text_file_pattern = re.compile(
        r'(?:^|\s)([A-Za-z0-9][\w\s\-\.\(\)\[\]]+\.(?:' +
        '|'.join(ext[1:] for ext in ROM_EXTENSIONS) +
        r'))(?:\s|$)',
        re.IGNORECASE | re.MULTILINE
    )

    # Collect from all patterns
    for match in href_pattern.finditer(html):
        links.append(match.group(1))

    for match in src_pattern.finditer(html):
        link = match.group(1)
        # Only include if it looks like a file, not an image/script
        if any(link.lower().endswith(ext) for ext in ROM_EXTENSIONS):
            links.append(link)

    for match in data_pattern.finditer(html):
        links.append(match.group(1))

    for match in onclick_pattern.finditer(html):
        links.append(match.group(1))

    for match in url_pattern.finditer(html):
        links.append(match.group(1))

    # For text file patterns, only match within pre/code/listing sections
    pre_sections = re.findall(r'<(?:pre|code|listing)[^>]*>(.*?)</(?:pre|code|listing)>',
                              html, re.IGNORECASE | re.DOTALL)
    for section in pre_sections:
        for match in text_file_pattern.finditer(section):
            links.append(match.group(1))

    return links


def is_rom_file(filename: str) -> bool:
    """Check if a filename appears to be a ROM file."""
    # Remove query string and fragment
    clean_name = filename.split('?')[0].split('#')[0]
    lower_name = clean_name.lower()

    # URL decode
    try:
        lower_name = urllib.request.unquote(lower_name)
    except:
        pass

    return any(lower_name.endswith(ext) for ext in ROM_EXTENSIONS)


def is_directory_link(href: str) -> bool:
    """Check if a link appears to be a directory."""
    # Remove query string
    clean = href.split('?')[0].split('#')[0]

    # Directories typically end with /
    if clean.endswith('/'):
        return True

    # Check if it has no extension (might be a directory)
    last_part = clean.rstrip('/').split('/')[-1]
    if '.' not in last_part and last_part not in ('', '.', '..'):
        # Could be a directory - but only if it doesn't look like a file
        return not any(last_part.lower().endswith(ext) for ext in ROM_EXTENSIONS)

    return False


def parse_size_string(size_str: str) -> int:
    """
    Parse a human-readable size string into bytes.
    Handles formats like: 1.5M, 100K, 50G, 1.5 MB, 100 KB, 175.9 MiB, 1536000
    """
    if not size_str:
        return 0

    size_str = size_str.strip().upper()

    # Try to parse as raw number first
    try:
        return int(size_str)
    except ValueError:
        pass

    # Match patterns like "1.5M", "100K", "175.9 MIB", "1.5 MB", "100 KB"
    # Handle both "MB" and "MiB" (binary) formats
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
    """
    Extract file sizes from HTML directory listings.
    Returns dict mapping filename -> size in bytes.

    Handles formats:
    - Apache autoindex: <a href="file.zip">file.zip</a>  2024-01-01 12:00  1.5M
    - nginx autoindex: <a href="file.zip">file.zip</a>  01-Jan-2024 12:00  1536000
    - Table format: <td><a href="file.zip">file.zip</a></td><td>1.5 MB</td>
    - Myrient format: <td class="link"><a href="...">file</a></td><td class="size">175.9 MiB</td>
    """
    sizes = {}

    # Pattern 1: Myrient/structured table format (most efficient, check first)
    # Matches: <td class="link"><a href="...">filename</a></td><td class="size">size</td>
    myrient_pattern = re.compile(
        r'<td[^>]*class="link"[^>]*>\s*<a\s+href="([^"]+)"[^>]*>([^<]+)</a>\s*</td>\s*'
        r'<td[^>]*class="size"[^>]*>\s*([\d.]+\s*[KMGT]i?B|[\d.]+|-)\s*</td>',
        re.IGNORECASE
    )

    for match in myrient_pattern.finditer(html):
        href = match.group(1)
        filename = match.group(2).strip()
        size_str = match.group(3).strip()

        if size_str != '-':
            size = parse_size_string(size_str)
            if size > 0:
                clean_href = urllib.request.unquote(href.split('?')[0].split('#')[0])
                sizes[clean_href] = size
                sizes[filename] = size

    # If we found sizes with the Myrient pattern, skip slower patterns
    if sizes:
        return sizes

    # Pattern 2: Apache/nginx autoindex format
    # Matches: <a href="file.zip">file.zip</a>    date time    size
    autoindex_pattern = re.compile(
        r'<a\s+href=["\']?([^"\'<>\s]+)["\']?[^>]*>([^<]+)</a>\s*'
        r'(?:\d{1,2}[-/]\w{3}[-/]\d{2,4}\s+\d{1,2}:\d{2}|\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})\s*'
        r'([\d.]+\s*[KMGT]i?B?|\d+|-)',
        re.IGNORECASE
    )

    for match in autoindex_pattern.finditer(html):
        href = match.group(1)
        filename = match.group(2).strip()
        size_str = match.group(3).strip()

        if size_str != '-':
            size = parse_size_string(size_str)
            if size > 0:
                clean_href = urllib.request.unquote(href.split('?')[0].split('#')[0])
                sizes[clean_href] = size
                sizes[filename] = size

    # If we found sizes, skip the slow table pattern
    if sizes:
        return sizes

    # Pattern 3: Generic table format with size in separate cell (slower, last resort)
    # Matches rows like: <td><a href="file.zip">...</a></td>...<td>1.5 MB</td>
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

    # Pattern 3: Pre/listing block with sizes (FTP-style)
    # Matches: -rw-r--r-- 1 user group 1536000 Jan 1 12:00 file.zip
    # or:      file.zip    1536000
    pre_sections = re.findall(
        r'<(?:pre|code|listing)[^>]*>(.*?)</(?:pre|code|listing)>',
        html, re.IGNORECASE | re.DOTALL
    )

    for section in pre_sections:
        # FTP ls -l format
        ftp_pattern = re.compile(
            r'[-drwx]{10}\s+\d+\s+\S+\s+\S+\s+(\d+)\s+\w+\s+\d+\s+[\d:]+\s+(\S+)',
            re.MULTILINE
        )
        for match in ftp_pattern.finditer(section):
            size = int(match.group(1))
            filename = match.group(2)
            if size > 0:
                sizes[filename] = size

        # Simple "filename size" format
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


def parse_html_for_files(html: str, base_url: str) -> List[str]:
    """
    Parse HTML content and extract ROM file URLs.
    Handles various page formats including:
    - Apache/nginx autoindex
    - Custom download pages
    - FTP-style text listings
    - Table-based file listings
    """
    files = []
    seen = set()

    # Extract all links
    links = extract_links_from_html(html)

    for href in links:
        # Normalize the URL
        url = normalize_url(href, base_url)
        if not url:
            continue

        # Skip if already seen
        if url in seen:
            continue
        seen.add(url)

        # Check if it's a ROM file
        if is_rom_file(url):
            files.append(url)

    return files


def parse_html_for_files_with_sizes(html: str, base_url: str) -> List[Tuple[str, int]]:
    """
    Parse HTML content and extract ROM file URLs with their sizes.
    Returns list of (url, size) tuples. Size is 0 if unknown.
    """
    files = []
    seen = set()

    # Get file sizes from HTML
    size_map = extract_file_sizes_from_html(html)

    # Extract all links
    links = extract_links_from_html(html)

    for href in links:
        # Normalize the URL
        url = normalize_url(href, base_url)
        if not url:
            continue

        # Skip if already seen
        if url in seen:
            continue
        seen.add(url)

        # Check if it's a ROM file
        if is_rom_file(url):
            # Try to find size for this file
            filename = get_filename_from_url(url)
            size = size_map.get(filename, 0) or size_map.get(href, 0)
            files.append((url, size))

    return files


def parse_html_for_directories(html: str, base_url: str) -> List[str]:
    """
    Parse HTML content and extract subdirectory URLs.
    Handles various page formats.
    """
    dirs = []
    seen = set()

    # Extract all links
    links = extract_links_from_html(html)

    for href in links:
        # Check if it looks like a directory
        if not is_directory_link(href):
            continue

        # Normalize the URL
        url = normalize_url(href, base_url)
        if not url:
            continue

        # Ensure it ends with /
        if not url.endswith('/'):
            url += '/'

        # Skip if already seen or same as base
        if url in seen or url == base_url or url == base_url.rstrip('/') + '/':
            continue

        # Skip parent directories
        if url.count('/') < base_url.rstrip('/').count('/'):
            continue

        seen.add(url)
        dirs.append(url)

    return dirs


def validate_source(source: str, timeout: int = 15) -> Tuple[bool, str]:
    """
    Validate a source path or URL is accessible.
    Returns (success, error_message) tuple.
    """
    if is_url(source):
        # Network source - try to fetch
        try:
            request = urllib.request.Request(
                source,
                headers={
                    'User-Agent': 'Mozilla/5.0 (compatible; Retro-Refiner/1.0)',
                    'Accept': 'text/html,application/xhtml+xml,*/*',
                }
            )
            with urllib.request.urlopen(request, timeout=timeout) as response:
                # Check we got a successful response
                if response.status == 200:
                    return True, ""
                else:
                    return False, f"HTTP {response.status}"
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return False, "Not found (404)"
            elif e.code == 403:
                return False, "Access denied (403)"
            elif e.code == 401:
                return False, "Authentication required (401)"
            else:
                return False, f"HTTP error {e.code}"
        except urllib.error.URLError as e:
            return False, f"Connection failed: {e.reason}"
        except socket.timeout:
            return False, "Connection timed out"
        except Exception as e:
            return False, str(e)
    else:
        # Local path - check exists
        path = Path(source)
        if not path.exists():
            return False, "Path does not exist"
        if not path.is_dir():
            return False, "Path is not a directory"
        return True, ""


def validate_all_sources(local_sources: List[Path], network_sources: List[str]) -> List[Tuple[str, str]]:
    """
    Validate all sources are accessible.
    Returns list of (source, error_message) tuples for failed sources.
    """
    errors = []

    # Validate local sources
    for source in local_sources:
        success, error = validate_source(str(source))
        if not success:
            errors.append((str(source), error))

    # Validate network sources
    for source in network_sources:
        print(f"Validating: {format_url(source)}...", end=" ", flush=True)
        success, error = validate_source(source)
        if success:
            print("OK")
        else:
            print(f"FAILED ({error})")
            errors.append((source, error))

    return errors


def fetch_url(url: str, timeout: int = 30, max_redirects: int = 5) -> Tuple[bytes, str]:
    """
    Fetch content from a URL, following redirects.
    Returns (content, final_url) tuple.
    """
    current_url = url
    redirects = 0

    while redirects < max_redirects:
        try:
            request = urllib.request.Request(
                current_url,
                headers={
                    'User-Agent': 'Mozilla/5.0 (compatible; Retro-Refiner/1.0)',
                    'Accept': 'text/html,application/xhtml+xml,*/*',
                    'Accept-Language': 'en-US,en;q=0.9',
                }
            )
            with urllib.request.urlopen(request, timeout=timeout) as response:
                # Check for redirect
                if response.geturl() != current_url:
                    current_url = response.geturl()

                return response.read(), current_url
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 303, 307, 308):
                # Follow redirect
                new_url = e.headers.get('Location')
                if new_url:
                    current_url = normalize_url(new_url, current_url) or new_url
                    redirects += 1
                    continue
            raise
        except Exception:
            raise

    raise Exception(f"Too many redirects for {url}")


class ConnectionPool:
    """HTTP/HTTPS connection pool using raw sockets for maximum download speed."""

    def __init__(self):
        self._sockets: Dict[str, ssl.SSLSocket] = {}
        self._ssl_context = ssl.create_default_context()

    def _get_socket(self, host: str, port: int = 443) -> ssl.SSLSocket:
        """Get or create an SSL socket to the specified host."""
        key = f"{host}:{port}"

        if key in self._sockets:
            return self._sockets[key]

        # Create optimized socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        sock.settimeout(120)

        # Resolve and connect
        addr = socket.gethostbyname(host)
        sock.connect((addr, port))

        # Wrap with SSL
        ssock = self._ssl_context.wrap_socket(sock, server_hostname=host)
        self._sockets[key] = ssock
        return ssock

    def _remove_socket(self, host: str, port: int = 443):
        """Remove a socket from the pool."""
        key = f"{host}:{port}"
        if key in self._sockets:
            try:
                self._sockets[key].close()
            except Exception:
                pass
            del self._sockets[key]

    def download(self, url: str, _redirect_count: int = 0) -> Optional[bytes]:
        """Download a file using a pooled socket connection."""
        if _redirect_count > 5:
            return None

        parsed = urlparse(url)
        host = parsed.netloc
        path = parsed.path or '/'
        if parsed.query:
            path += '?' + parsed.query

        # Try up to 2 times (retry once on connection failure)
        for attempt in range(2):
            try:
                ssock = self._get_socket(host)

                # Send HTTP request
                request = (
                    f"GET {path} HTTP/1.1\r\n"
                    f"Host: {host}\r\n"
                    f"User-Agent: Mozilla/5.0 (compatible; Retro-Refiner/1.0)\r\n"
                    f"Accept: */*\r\n"
                    f"Connection: keep-alive\r\n"
                    f"\r\n"
                )
                ssock.sendall(request.encode())

                # Read response headers
                response = b''
                while b'\r\n\r\n' not in response:
                    chunk = ssock.recv(4096)
                    if not chunk:
                        break
                    response += chunk

                if not response:
                    raise ConnectionError("Empty response")

                # Parse headers
                header_end = response.index(b'\r\n\r\n')
                header_data = response[:header_end].decode('utf-8', errors='replace')
                body_start = response[header_end + 4:]

                # Parse status line
                lines = header_data.split('\r\n')
                status_line = lines[0]
                status_code = int(status_line.split()[1])

                # Parse headers into dict
                headers = {}
                for line in lines[1:]:
                    if ':' in line:
                        k, v = line.split(':', 1)
                        headers[k.lower().strip()] = v.strip()

                # Handle redirects
                if status_code in (301, 302, 303, 307, 308):
                    location = headers.get('location')
                    if location:
                        # Drain any remaining body
                        content_length = int(headers.get('content-length', 0))
                        remaining = content_length - len(body_start)
                        if remaining > 0:
                            ssock.recv(remaining)
                        return self.download(location, _redirect_count + 1)
                    return None

                if status_code != 200:
                    return None

                # Read body with large buffer
                content_length = headers.get('content-length')
                if content_length:
                    total_size = int(content_length)
                    body = body_start
                    while len(body) < total_size:
                        chunk = ssock.recv(min(1048576, total_size - len(body)))
                        if not chunk:
                            break
                        body += chunk
                    return body
                else:
                    # Chunked encoding or unknown - not fully supported, fall back
                    return body_start

            except Exception:
                # Connection failed, remove and retry
                self._remove_socket(host)
                if attempt == 0:
                    continue
                return None

        return None

    def close_all(self):
        """Close all sockets in the pool."""
        for ssock in self._sockets.values():
            try:
                ssock.close()
            except Exception:
                pass
        self._sockets.clear()


# Global connection pool
_connection_pool: Optional[ConnectionPool] = None


def get_connection_pool() -> ConnectionPool:
    """Get or create the global connection pool."""
    global _connection_pool
    if _connection_pool is None:
        _connection_pool = ConnectionPool()
    return _connection_pool


# Check for external download tools (much faster for some servers like Myrient)
_download_tool: Optional[str] = None  # 'aria2c', 'curl', or None


def get_download_tool() -> Optional[str]:
    """Check which download tool is available. Prefers aria2c, then curl."""
    global _download_tool
    if _download_tool is not None:
        return _download_tool if _download_tool != '' else None

    # Check for aria2c first (best: parallel + multi-connection per file)
    try:
        result = subprocess.run(['aria2c', '--version'], capture_output=True, timeout=5)
        if result.returncode == 0:
            _download_tool = 'aria2c'
            return 'aria2c'
    except Exception:
        pass

    # Check for curl (good: parallel downloads)
    try:
        result = subprocess.run(['curl', '--version'], capture_output=True, timeout=5)
        if result.returncode == 0:
            _download_tool = 'curl'
            return 'curl'
    except Exception:
        pass

    _download_tool = ''  # Mark as checked but not found
    return None


def download_with_external_tool(url: str, dest_path: Path, connections: int = 4) -> bool:
    """Download a file using aria2c or curl. Returns True on success."""
    tool = get_download_tool()
    if not tool:
        return False

    try:
        if tool == 'aria2c':
            # aria2c with multiple connections per file for faster large file downloads
            result = subprocess.run(
                ['aria2c', '-x', str(connections), '-s', str(connections), '-q',
                 '--connect-timeout=30', '--timeout=300', '-d', str(dest_path.parent),
                 '-o', dest_path.name, url],
                capture_output=True,
                timeout=310
            )
        else:  # curl
            result = subprocess.run(
                ['curl', '-sSL', '-o', str(dest_path), '--connect-timeout', '30', '--max-time', '300', url],
                capture_output=True,
                timeout=310
            )
        return result.returncode == 0 and dest_path.exists() and dest_path.stat().st_size > 0
    except Exception:
        return False


def download_batch_with_curl(downloads: List[Tuple[str, Path]], parallel: int = 4, timeout_per_file: int = 60) -> List[Path]:
    """
    Download multiple files with a single curl call (connection reuse).
    Returns list of successfully downloaded paths.
    """
    if not downloads:
        return []

    # Build curl command with multiple URL/output pairs
    cmd = ['curl', '-sSL', '--connect-timeout', '30', '--parallel', '--parallel-max', str(parallel)]

    for url, dest_path in downloads:
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        cmd.extend(['-o', str(dest_path), url])

    try:
        # Timeout scales with number of files (adjusted for parallelism)
        total_timeout = max(60, (len(downloads) // parallel + 1) * timeout_per_file)
        subprocess.run(cmd, capture_output=True, timeout=total_timeout)
    except subprocess.TimeoutExpired:
        pass  # Check which files succeeded anyway
    except Exception:
        return []

    # Return list of successfully downloaded files
    successful = []
    for url, dest_path in downloads:
        if dest_path.exists() and dest_path.stat().st_size > 0:
            successful.append(dest_path)

    return successful


def download_batch_with_aria2c(downloads: List[Tuple[str, Path]], parallel: int = 4, connections: int = 4, timeout_per_file: int = 60) -> List[Path]:
    """
    Download multiple files with aria2c (parallel downloads + multi-connection per file).
    Returns list of successfully downloaded paths.
    """
    if not downloads:
        return []

    # Create a temporary input file for aria2c
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        input_file = f.name
        for url, dest_path in downloads:
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            # aria2c input format: URL\n  dir=...\n  out=...\n
            f.write(f"{url}\n")
            f.write(f"  dir={dest_path.parent}\n")
            f.write(f"  out={dest_path.name}\n")

    try:
        # -j: concurrent downloads, -x: connections per server, -s: split count
        cmd = [
            'aria2c', '-q', '--console-log-level=error',
            '-j', str(parallel),      # concurrent downloads
            '-x', str(connections),   # connections per server
            '-s', str(connections),   # split file into N parts
            '--connect-timeout=30',
            '--timeout=300',
            '--file-allocation=none',  # faster startup
            '-i', input_file
        ]
        total_timeout = max(60, (len(downloads) // parallel + 1) * timeout_per_file)
        subprocess.run(cmd, capture_output=True, timeout=total_timeout)
    except subprocess.TimeoutExpired:
        pass  # Check which files succeeded anyway
    except Exception:
        pass
    finally:
        # Clean up input file
        try:
            os.unlink(input_file)
        except Exception:
            pass

    # Return list of successfully downloaded files
    successful = []
    for url, dest_path in downloads:
        if dest_path.exists() and dest_path.stat().st_size > 0:
            successful.append(dest_path)

    return successful


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
        self._manual_scroll = False

    def _is_tty(self) -> bool:
        """Check if running in a terminal."""
        return sys.stdout.isatty()

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
            return curses.wrapper(self._curses_main)
        except Exception:
            # Curses failed, fall back
            return self._run_simple_fallback()

    def _curses_main(self, stdscr) -> Dict[str, Path]:
        """Main curses loop."""
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


def download_files_cached_batch(
    urls: List[str],
    cache_dir: Path,
    batch_size: int = 50,
    parallel: int = 4,
    connections: int = 4,
    progress_callback=None
) -> Dict[str, Path]:
    """
    Download multiple files with batched downloads for connection reuse.
    Uses aria2c if available (best), otherwise curl.
    Returns dict of url -> cached_path for successful downloads.

    Args:
        parallel: Number of concurrent file downloads
        connections: Number of connections per file (aria2c only, useful for large files)
    """
    results = {}

    # Prepare download list with cache paths
    downloads_needed = []
    for url in urls:
        # Calculate cache path
        url_clean = url.split('?')[0].split('#')[0]
        filename = urllib.request.unquote(url_clean.split('/')[-1])
        filename = re.sub(r'[<>:"/\\|?*]', '_', filename) or 'unknown_file'

        url_path = url_clean.replace('://', '/').split('/', 1)[1] if '://' in url_clean else url_clean
        path_parts = [p for p in url_path.split('/') if p]
        subdir = path_parts[-2] if len(path_parts) >= 2 else 'misc'
        subdir = re.sub(r'[<>:"/\\|?*]', '_', subdir)

        cache_subdir = cache_dir / subdir
        cached_path = cache_subdir / filename

        # Check if already cached
        if cached_path.exists():
            results[url] = cached_path
            if progress_callback:
                progress_callback()
        else:
            downloads_needed.append((url, cached_path))

    # Download in batches using best available tool
    tool = get_download_tool()
    if downloads_needed and tool in ('aria2c', 'curl'):
        for i in range(0, len(downloads_needed), batch_size):
            batch = downloads_needed[i:i + batch_size]

            if tool == 'aria2c':
                successful = download_batch_with_aria2c(batch, parallel=parallel, connections=connections)
            else:  # curl
                successful = download_batch_with_curl(batch, parallel=parallel)

            for url, dest_path in batch:
                if dest_path in successful:
                    results[url] = dest_path
                if progress_callback:
                    progress_callback()

    # Fall back to individual downloads for any that failed or if no batch tool available
    for url, dest_path in downloads_needed:
        if url not in results:
            if download_with_external_tool(url, dest_path, connections=connections):
                results[url] = dest_path
            elif dest_path.exists():
                dest_path.unlink()  # Remove partial download
            if progress_callback:
                progress_callback()

    return results


def download_file_cached(url: str, cache_dir: Path, force: bool = False, use_pool: bool = True) -> Optional[Path]:
    """
    Download a file from URL to cache directory if not already cached.
    Returns the local path to the cached file.
    """
    # Extract filename from URL (handle query strings)
    url_clean = url.split('?')[0].split('#')[0]
    filename = urllib.request.unquote(url_clean.split('/')[-1])

    # Sanitize filename
    filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
    if not filename:
        filename = 'unknown_file'

    # Create cache subdirectory based on URL path
    url_path = url_clean.replace('://', '/').split('/', 1)[1] if '://' in url_clean else url_clean
    # Use just the last two path components for organization
    path_parts = [p for p in url_path.split('/') if p]
    if len(path_parts) >= 2:
        subdir = path_parts[-2]  # System folder
    else:
        subdir = 'misc'

    # Sanitize subdir
    subdir = re.sub(r'[<>:"/\\|?*]', '_', subdir)

    cache_subdir = cache_dir / subdir
    cache_subdir.mkdir(parents=True, exist_ok=True)

    cached_path = cache_subdir / filename

    # Check if already cached
    if cached_path.exists() and not force:
        return cached_path

    # Download the file - try external tools first (much faster for some servers like Myrient)
    try:
        if get_download_tool():
            if download_with_external_tool(url, cached_path):
                return cached_path

        # Fall back to Python methods
        content = None

        if use_pool and url.startswith('https://'):
            # Use connection pool for HTTPS
            pool = get_connection_pool()
            content = pool.download(url)
        else:
            # Fall back to urllib for non-HTTPS or when pool disabled
            request = urllib.request.Request(
                url,
                headers={
                    'User-Agent': 'Mozilla/5.0 (compatible; Retro-Refiner/1.0)',
                    'Accept': '*/*',
                }
            )
            with urllib.request.urlopen(request, timeout=120) as response:
                content = response.read()

        if content is None:
            print(f"  Warning: Failed to download {filename}")
            return None

        # Write to cache
        with open(cached_path, 'wb') as f:
            f.write(content)

        return cached_path
    except urllib.error.HTTPError as e:
        print(f"  Warning: HTTP {e.code} downloading {filename}")
        return None
    except urllib.error.URLError as e:
        print(f"  Warning: Network error downloading {filename}: {e.reason}")
        return None
    except Exception as e:
        print(f"  Warning: Failed to download {filename}: {e}")
        return None


def scan_network_source_urls(base_url: str, systems: List[str] = None,
                              recursive: bool = True, max_depth: int = 3,
                              _indent: str = "", _url_sizes: Dict[str, int] = None) -> Tuple[Dict[str, List[str]], Dict[str, int]]:
    """
    Scan a network source and collect ROM URLs (without downloading).
    Returns tuple of (dict of system -> list of URLs, dict of URL -> size in bytes).

    This allows filtering to happen before any files are downloaded.
    """
    detected = defaultdict(list)
    if _url_sizes is None:
        _url_sizes = {}

    if not _indent:
        print(f"Scanning network source: {format_url(base_url)}")

    try:
        content, final_url = fetch_url(base_url)
        html = content.decode('utf-8', errors='replace')
        base_url = final_url
    except Exception as e:
        print(f"{_indent}  Error fetching {format_url(base_url)}: {e}")
        return dict(detected), _url_sizes

    # Try to detect system from URL path (for Redump/Myrient style URLs)
    url_system = detect_system_from_path(base_url)

    # Check for ROM files directly in this location (with sizes)
    rom_files_with_sizes = parse_html_for_files_with_sizes(html, base_url)

    if rom_files_with_sizes:
        total_size = sum(size for _, size in rom_files_with_sizes)
        if not _indent:
            if total_size > 0:
                print(f"  Found {len(rom_files_with_sizes)} ROM files in root ({format_size(total_size)})")
            else:
                print(f"  Found {len(rom_files_with_sizes)} ROM files in root")
        # Auto-detect system from extensions, fall back to URL path detection
        for url, size in rom_files_with_sizes:
            url_clean = url.split('?')[0].split('#')[0]
            ext = '.' + url_clean.rsplit('.', 1)[-1].lower() if '.' in url_clean else ''
            system = EXTENSION_TO_SYSTEM.get(ext)
            # If extension didn't give a system, use URL path detection
            if not system and url_system:
                system = url_system
            elif not system:
                system = 'unknown'
            if systems is None or system in systems:
                detected[system].append(url)
                if size > 0:
                    _url_sizes[url] = size

    # Get subdirectories
    if recursive and max_depth > 0:
        subdirs = parse_html_for_directories(html, base_url)

        for subdir_url in subdirs:
            check_shutdown()

            folder_name = urllib.request.unquote(subdir_url.rstrip('/').split('/')[-1])
            folder_lower = folder_name.lower()

            system = FOLDER_ALIASES.get(folder_lower, folder_lower)
            is_system_folder = system in KNOWN_SYSTEMS

            if is_system_folder:
                if systems and system not in systems:
                    continue

                print(f"{_indent}  Scanning {folder_name} ({system})...")

                try:
                    content, final_url = fetch_url(subdir_url)
                    subdir_html = content.decode('utf-8', errors='replace')
                    sub_files_with_sizes = parse_html_for_files_with_sizes(subdir_html, final_url)

                    if sub_files_with_sizes:
                        sub_rom_urls = [url for url, _ in sub_files_with_sizes]
                        total_size = sum(size for _, size in sub_files_with_sizes)
                        if total_size > 0:
                            print(f"{_indent}    Found {len(sub_rom_urls)} ROM URLs ({format_size(total_size)})")
                        else:
                            print(f"{_indent}    Found {len(sub_rom_urls)} ROM URLs")
                        detected[system].extend(sub_rom_urls)
                        for url, size in sub_files_with_sizes:
                            if size > 0:
                                _url_sizes[url] = size

                    # Check for nested subdirectories (region folders, etc.)
                    if max_depth > 1:
                        nested_subdirs = parse_html_for_directories(subdir_html, final_url)
                        for nested_url in nested_subdirs:
                            check_shutdown()
                            try:
                                nested_content, nested_final = fetch_url(nested_url)
                                nested_html = nested_content.decode('utf-8', errors='replace')
                                nested_files = parse_html_for_files_with_sizes(nested_html, nested_final)
                                if nested_files:
                                    nested_name = urllib.request.unquote(nested_url.rstrip('/').split('/')[-1])
                                    nested_roms = [url for url, _ in nested_files]
                                    nested_size = sum(size for _, size in nested_files)
                                    if nested_size > 0:
                                        print(f"{_indent}      Found {len(nested_roms)} ROM URLs in {nested_name} ({format_size(nested_size)})")
                                    else:
                                        print(f"{_indent}      Found {len(nested_roms)} ROM URLs in {nested_name}")
                                    detected[system].extend(nested_roms)
                                    for url, size in nested_files:
                                        if size > 0:
                                            _url_sizes[url] = size
                            except Exception:
                                pass

                except Exception as e:
                    print(f"{_indent}    Error scanning {folder_name}: {e}")
                    continue
            else:
                # Recursively scan non-system folders
                if max_depth > 1:
                    sub_detected, _ = scan_network_source_urls(
                        subdir_url, systems,
                        recursive=True, max_depth=max_depth - 1,
                        _indent=_indent + "  ", _url_sizes=_url_sizes
                    )
                    for sys, urls in sub_detected.items():
                        detected[sys].extend(urls)

    return dict(detected), _url_sizes


def get_filename_from_url(url: str) -> str:
    """Extract and decode filename from a URL."""
    url_clean = url.split('?')[0].split('#')[0]
    filename = urllib.request.unquote(url_clean.split('/')[-1])
    return filename


def filter_network_roms(rom_urls: List[str], system: str,
                        include_patterns: List[str] = None,
                        exclude_patterns: List[str] = None,
                        exclude_protos: bool = False,
                        include_betas: bool = False,
                        include_unlicensed: bool = False,
                        region_priority: List[str] = None,
                        keep_regions: List[str] = None,
                        year_from: int = None,
                        year_to: int = None,
                        verbose: bool = False,
                        url_sizes: Dict[str, int] = None) -> Tuple[List[str], Dict[str, int]]:
    """
    Filter network ROM URLs based on filename parsing (no downloading required).
    Returns tuple of (list of URLs to download, dict with size info).
    """
    if region_priority is None:
        region_priority = DEFAULT_REGION_PRIORITY
    if url_sizes is None:
        url_sizes = {}

    # Parse all ROMs from URLs
    all_roms = []
    url_map = {}  # Map filename to URL
    size_map = {}  # Map filename to size
    filtered_by_pattern = 0
    total_source_size = 0

    for url in rom_urls:
        filename = get_filename_from_url(url)

        # Apply include/exclude patterns
        if include_patterns and not matches_patterns(filename, include_patterns):
            filtered_by_pattern += 1
            if verbose:
                print(f"  [SKIP] {filename}: doesn't match include patterns")
            continue
        if exclude_patterns and matches_patterns(filename, exclude_patterns):
            filtered_by_pattern += 1
            if verbose:
                print(f"  [SKIP] {filename}: matches exclude pattern")
            continue

        rom_info = parse_rom_filename(filename)

        # Filter by proto/beta/unlicensed unless explicitly included
        if rom_info.is_proto and exclude_protos:
            if verbose:
                print(f"  [SKIP] {filename}: prototype")
            continue
        if rom_info.is_beta and not include_betas:
            if verbose:
                print(f"  [SKIP] {filename}: beta")
            continue
        if rom_info.is_unlicensed and not include_unlicensed:
            if verbose:
                print(f"  [SKIP] {filename}: unlicensed")
            continue

        # Filter by year if specified
        if rom_info.year > 0:
            if year_from and rom_info.year < year_from:
                if verbose:
                    print(f"  [SKIP] {filename}: year {rom_info.year} < {year_from}")
                continue
            if year_to and rom_info.year > year_to:
                if verbose:
                    print(f"  [SKIP] {filename}: year {rom_info.year} > {year_to}")
                continue

        all_roms.append(rom_info)
        url_map[filename] = url
        file_size = url_sizes.get(url, 0)
        size_map[filename] = file_size
        total_source_size += file_size

    if total_source_size > 0:
        print(f"{system.upper()}: {len(all_roms)} ROMs after filtering ({format_size(total_source_size)})")
    else:
        print(f"{system.upper()}: {len(all_roms)} ROMs after filtering")
    if filtered_by_pattern:
        print(f"{system.upper()}: {filtered_by_pattern} filtered by include/exclude patterns")

    # Group by normalized title
    grouped = defaultdict(list)
    for rom in all_roms:
        normalized = normalize_title(rom.base_title)
        grouped[normalized].append(rom)

    print(f"{system.upper()}: {len(grouped)} unique game titles")

    # Select best ROM from each group
    selected_urls = []
    for title, roms in grouped.items():
        if keep_regions:
            # Keep one ROM per specified region
            seen_regions = set()
            for region in keep_regions:
                for rom in sorted(roms, key=lambda r: (
                    r.is_translation, r.is_hack, -r.revision
                )):
                    if rom.region == region and region not in seen_regions:
                        if rom.filename in url_map:
                            selected_urls.append(url_map[rom.filename])
                            seen_regions.add(region)
                            if verbose:
                                print(f"  [SELECT] {rom.filename} ({region} version of '{title}')")
                        break
            # If no regions matched, select best overall
            if not seen_regions:
                best = select_best_rom(roms, region_priority)
                if best and best.filename in url_map:
                    selected_urls.append(url_map[best.filename])
                    if verbose:
                        print(f"  [SELECT] {best.filename} (fallback for '{title}')")
        else:
            # Select single best ROM
            best = select_best_rom(roms, region_priority)
            if best and best.filename in url_map:
                selected_urls.append(url_map[best.filename])
                if verbose:
                    print(f"  [SELECT] {best.filename} (best of {len(roms)} for '{title}')")

    # Calculate selected size
    selected_size = sum(size_map.get(get_filename_from_url(url), 0) for url in selected_urls)

    if total_source_size > 0:
        print(f"{system.upper()}: Selected {len(selected_urls)} ROMs to download ({format_size(selected_size)})")
        size_saved = total_source_size - selected_size
        reduction_pct = (size_saved / total_source_size) * 100
        print(f"{system.upper()}: Size reduction: {format_size(size_saved)} saved ({reduction_pct:.1f}%)")
    else:
        print(f"{system.upper()}: Selected {len(selected_urls)} ROMs to download")

    return selected_urls, {'source_size': total_source_size, 'selected_size': selected_size}


DEFAULT_CONFIG_CONTENT = """# =============================================================================
# Retro-Refiner Configuration File
# =============================================================================
# Place this file in your ROM source directory or specify with --config
# CLI arguments override these settings
# =============================================================================

# -----------------------------------------------------------------------------
# Source and Destination
# -----------------------------------------------------------------------------

# Source directories (list for multiple sources)
# Supports both local paths and network URLs (https://)
# source:
#   - /path/to/roms
#   - /path/to/more/roms
#   - https://myserver.com/roms/

# Destination directory (default: refined/ in script dir)
# dest: /path/to/output

# Prefer ROMs from this source when duplicates exist across multiple sources
# prefer_source: /path/to/preferred/source

# -----------------------------------------------------------------------------
# System Selection
# -----------------------------------------------------------------------------

# Systems to process (default: auto-detect all)
# Use --list-systems to see all supported system names
# systems:
#   - nes
#   - snes
#   - genesis
#   - gba
#   - mame

# -----------------------------------------------------------------------------
# Region Handling
# -----------------------------------------------------------------------------

# Region priority order (first = highest priority)
# Default: USA, World, Europe, Australia, England, Spain, France, Germany,
#          Italy, Netherlands, Sweden, Asia, Japan, Korea, China, Taiwan, Brazil
region_priority: "USA,World,Europe,Australia,Japan"

# Keep multiple regional versions (one ROM per listed region)
# Useful for collectors or language learners
# keep_regions: "USA,Japan"

# -----------------------------------------------------------------------------
# File Operations
# -----------------------------------------------------------------------------

# Transfer mode: copy (default), link (symlink), hardlink, or move
# link: true       # Use symbolic links (saves disk space)
# hardlink: true   # Use hard links (same filesystem only)
# move: true       # Move files (destructive - use with caution!)

# Output all ROMs to a single flat folder (no system subfolders)
flat: false

# -----------------------------------------------------------------------------
# Inclusion Filters
# -----------------------------------------------------------------------------

# Include only ROMs matching these glob patterns
# Multiple patterns act as OR (match any)
# include:
#   - "*Mario*"
#   - "*Zelda*"
#   - "*Metroid*"

# Exclude ROMs matching these glob patterns
# Applied after include filter
# exclude:
#   - "*Beta*"
#   - "*Demo*"
#   - "*Sample*"

# Exclude prototype ROMs (included by default)
exclude_protos: false

# Include beta ROMs (normally excluded)
include_betas: false

# Include unlicensed/pirate ROMs (normally excluded)
include_unlicensed: false

# -----------------------------------------------------------------------------
# Metadata Filters
# -----------------------------------------------------------------------------

# Filter by release year (requires year in filename or DAT)
# year_from: 1985
# year_to: 1995

# Filter by genre (for arcade systems with catver.ini)
# genres: "platformer,shooter,puzzle"

# -----------------------------------------------------------------------------
# Selection Mode
# -----------------------------------------------------------------------------
# DAT File Options
# -----------------------------------------------------------------------------

# Skip ROM checksum verification against DAT files
# Faster but less accurate
no_verify: false

# Use filename parsing instead of DAT metadata
# Faster but less accurate region detection
no_dat: false

# Delete and re-download all DAT files (standalone operation, no ROM processing)
# Typically used via command line: python retro-refiner.py --update-dats
# update_dats: false

# Custom directory for DAT files
# dat_dir: /path/to/dat_files

# -----------------------------------------------------------------------------
# Network Source Options
# -----------------------------------------------------------------------------

# Cache directory for files downloaded from network sources
# Downloaded ROMs are cached here to avoid re-downloading
# cache_dir: /path/to/cache

# Skip confirmation prompt before downloading from network sources (--commit mode only)
# In dry run mode, no downloads occur regardless of this setting
yes: false

# -----------------------------------------------------------------------------
# MAME/Arcade Options
# -----------------------------------------------------------------------------

# MAME version for auto-downloading data files
# mame_version: "0.274"

# Skip copying CHD files for MAME (saves significant space)
no_chd: false

# Exclude adult/mature MAME games (included by default)
no_adult: false

# -----------------------------------------------------------------------------
# Export Options
# -----------------------------------------------------------------------------

# Generate M3U playlists for each system
playlists: false

# Generate EmulationStation gamelist.xml files
gamelist: false

# Generate Retroarch .lpl playlists to this directory
# retroarch_playlists: /path/to/retroarch/playlists

# -----------------------------------------------------------------------------
# Example Configurations
# -----------------------------------------------------------------------------

# --- Minimal English-only collection ---
# region_priority: "USA,World,Europe"
# no_verify: true
# no_dat: true

# --- Japanese games collector ---
# region_priority: "Japan,USA,World"
# keep_regions: "Japan,USA"

# --- Retro gaming (pre-2000) ---
# year_to: 1999
# playlists: true

# --- Space-saving setup ---
# link: true

# --- Mario/Nintendo fan ---
# include:
#   - "*Mario*"
#   - "*Zelda*"
#   - "*Metroid*"
#   - "*Kirby*"
#   - "*Pokemon*"
# playlists: true
# gamelist: true
"""


def generate_default_config(config_path: Path) -> bool:
    """Generate a default config file if it doesn't exist."""
    try:
        with open(config_path, 'w', encoding='utf-8') as f:
            f.write(DEFAULT_CONFIG_CONTENT)
        return True
    except Exception as e:
        print(f"Warning: Could not create config file: {e}")
        return False


def load_config(config_path: Path) -> dict:
    """Load configuration from YAML or JSON file."""
    if not config_path.exists():
        return {}

    with open(config_path, 'r', encoding='utf-8') as f:
        content = f.read()

    if config_path.suffix.lower() in ('.yaml', '.yml'):
        try:
            return parse_simple_yaml(content) or {}
        except Exception as e:
            print(f"Warning: Failed to parse {config_path.name}: {e}")
            return {}
    elif config_path.suffix.lower() == '.json':
        return json.loads(content) or {}
    else:
        # Try YAML first, then JSON
        try:
            return parse_simple_yaml(content) or {}
        except:
            pass
        try:
            return json.loads(content) or {}
        except:
            pass
    return {}


def apply_config_to_args(args, config: dict):
    """Apply config file settings to args (CLI args take precedence)."""
    # Map config keys to arg names
    config_map = {
        'source': 'source',
        'dest': 'dest',
        'systems': 'systems',
        'region_priority': 'region_priority',
        'keep_regions': 'keep_regions',
        'include': 'include',
        'exclude': 'exclude',
        'exclude_protos': 'exclude_protos',
        'include_betas': 'include_betas',
        'include_unlicensed': 'include_unlicensed',
        'genres': 'genres',
        'year_from': 'year_from',
        'year_to': 'year_to',
        'flat': 'flat',
        'link': 'link',
        'hardlink': 'hardlink',
        'move': 'move',
        'playlists': 'playlists',
        'gamelist': 'gamelist',
        'retroarch_playlists': 'retroarch_playlists',
        'prefer_source': 'prefer_source',
        'no_verify': 'no_verify',
        'no_dat': 'no_dat',
        'update_dats': 'update_dats',
        'no_chd': 'no_chd',
        'no_adult': 'no_adult',
        'verbose': 'verbose',
        'mame_version': 'mame_version',
        'dat_dir': 'dat_dir',
        'cache_dir': 'cache_dir',
        'yes': 'yes',
    }

    for config_key, arg_name in config_map.items():
        if config_key in config:
            current_value = getattr(args, arg_name, None)
            # Only apply config if CLI didn't set it
            if current_value is None or current_value == False or current_value == []:
                setattr(args, arg_name, config[config_key])


def matches_patterns(name: str, patterns: List[str]) -> bool:
    """Check if name matches any of the glob patterns."""
    if not patterns:
        return False
    for pattern in patterns:
        if fnmatch.fnmatch(name.lower(), pattern.lower()):
            return True
    return False


def transfer_file(src: Path, dst: Path, mode: str = 'copy'):
    """Transfer a file using the specified mode (copy, link, hardlink, move)."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if mode == 'link':
        # Create symbolic link
        if dst.exists() or dst.is_symlink():
            dst.unlink()
        dst.symlink_to(src.resolve())
    elif mode == 'hardlink':
        # Create hard link
        if dst.exists():
            dst.unlink()
        os.link(src, dst)
    elif mode == 'move':
        # Move file
        shutil.move(src, dst)
    else:
        # Default: copy
        shutil.copy2(src, dst)


def generate_m3u_playlist(system: str, rom_files: List[Path], dest_path: Path):
    """Generate M3U playlist for a system."""
    playlist_path = dest_path / f"{system}.m3u"
    with open(playlist_path, 'w', encoding='utf-8') as f:
        for rom in sorted(rom_files, key=lambda x: x.name.lower()):
            f.write(f"{rom.name}\n")
    return playlist_path


def generate_retroarch_playlist(system: str, rom_files: List[Path],
                                 rom_dir: Path, playlist_dir: Path, core_path: str = "DETECT"):
    """Generate Retroarch .lpl playlist."""
    playlist_path = playlist_dir / f"{system}.lpl"

    entries = []
    for rom in sorted(rom_files, key=lambda x: x.name.lower()):
        # Extract display name (remove extension)
        display_name = rom.stem
        entries.append({
            "path": str(rom_dir / rom.name),
            "label": display_name,
            "core_path": core_path,
            "core_name": "DETECT",
            "crc32": "",
            "db_name": f"{system}.lpl"
        })

    playlist = {
        "version": "1.5",
        "default_core_path": core_path,
        "default_core_name": "DETECT",
        "label_display_mode": 0,
        "right_thumbnail_mode": 0,
        "left_thumbnail_mode": 0,
        "sort_mode": 0,
        "items": entries
    }

    playlist_dir.mkdir(parents=True, exist_ok=True)
    with open(playlist_path, 'w', encoding='utf-8') as f:
        json.dump(playlist, f, indent=2)
    return playlist_path


def generate_gamelist_xml(system: str, rom_files: List[Path], dest_path: Path):
    """Generate EmulationStation gamelist.xml."""
    gamelist_path = dest_path / "gamelist.xml"

    lines = ['<?xml version="1.0"?>', '<gameList>']
    for rom in sorted(rom_files, key=lambda x: x.name.lower()):
        name = rom.stem
        # Escape XML special characters
        name_escaped = name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')
        lines.append(f'  <game>')
        lines.append(f'    <path>./{rom.name}</path>')
        lines.append(f'    <name>{name_escaped}</name>')
        lines.append(f'  </game>')
    lines.append('</gameList>')

    with open(gamelist_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    return gamelist_path


# Default region priority order
DEFAULT_REGION_PRIORITY = ['USA', 'World', 'Europe', 'Australia', 'England', 'Spain',
                           'France', 'Germany', 'Italy', 'Netherlands', 'Sweden',
                           'Asia', 'Japan', 'Korea', 'China', 'Taiwan', 'Brazil']


@dataclass
class RomInfo:
    filename: str
    base_title: str
    region: str
    revision: int
    is_english: bool
    is_translation: bool
    is_beta: bool
    is_demo: bool
    is_promo: bool
    is_sample: bool
    is_proto: bool
    is_bios: bool
    is_pirate: bool
    is_unlicensed: bool
    is_homebrew: bool
    is_rerelease: bool
    is_compilation: bool
    is_lock_on: bool
    translation_version: str = ""
    has_hacks: bool = False
    languages: list = field(default_factory=list)
    year: int = 0  # Release year if available


# =============================================================================
# LIBRETRO DAT FILE SUPPORT
# =============================================================================

@dataclass
class DatRomEntry:
    """ROM entry from a DAT file."""
    name: str  # Game name/description
    rom_name: str  # ROM filename
    size: int  # File size in bytes
    crc: str  # CRC32 checksum (hex)
    md5: str  # MD5 checksum (hex)
    sha1: str  # SHA1 checksum (hex)
    region: str  # Detected region
    is_parent: bool  # Is this a parent ROM
    parent_name: str  # Parent ROM name if clone


# System name mappings for libretro-database (No-Intro DATs)
LIBRETRO_DAT_SYSTEMS = {
    # Nintendo - Consoles
    'nes': 'Nintendo - Nintendo Entertainment System',
    'fds': 'Nintendo - Family Computer Disk System',
    'snes': 'Nintendo - Super Nintendo Entertainment System',
    'n64': 'Nintendo - Nintendo 64',
    'n64dd': 'Nintendo - Nintendo 64DD',
    'gamecube': 'Nintendo - GameCube',
    'wii': 'Nintendo - Wii',
    'wiiu': 'Nintendo - Wii U',
    # Nintendo - Handhelds
    'gameboy': 'Nintendo - Game Boy',
    'gameboy-color': 'Nintendo - Game Boy Color',
    'gba': 'Nintendo - Game Boy Advance',
    'nds': 'Nintendo - Nintendo DS',
    '3ds': 'Nintendo - Nintendo 3DS',
    'virtualboy': 'Nintendo - Virtual Boy',
    'pokemini': 'Nintendo - Pokemon Mini',
    # Sega
    'genesis': 'Sega - Mega Drive - Genesis',
    'mastersystem': 'Sega - Master System - Mark III',
    'gamegear': 'Sega - Game Gear',
    'sg1000': 'Sega - SG-1000',
    'sega32x': 'Sega - 32X',
    'segapico': 'Sega - PICO',
    'saturn': 'Sega - Saturn',
    'dreamcast': 'Sega - Dreamcast',
    'segacd': 'Sega - Mega-CD - Sega CD',
    # Sony
    'psx': 'Sony - PlayStation',
    'ps2': 'Sony - PlayStation 2',
    'ps3': 'Sony - PlayStation 3',
    'psp': 'Sony - PlayStation Portable',
    'psvita': 'Sony - PlayStation Vita',
    # NEC
    'tg16': 'NEC - PC Engine - TurboGrafx 16',
    'supergrafx': 'NEC - PC Engine SuperGrafx',
    'tgcd': 'NEC - PC Engine CD - TurboGrafx-CD',
    'pcfx': 'NEC - PC-FX',
    'pc98': 'NEC - PC-98',
    # SNK
    'neogeo': 'SNK - Neo Geo',
    'neogeocd': 'SNK - Neo Geo CD',
    'ngp': 'SNK - Neo Geo Pocket',
    'ngpc': 'SNK - Neo Geo Pocket Color',
    # Atari
    'atari2600': 'Atari - 2600',
    'atari5200': 'Atari - 5200',
    'atari7800': 'Atari - 7800',
    'atari800': 'Atari - 8-bit Family',
    'atarilynx': 'Atari - Lynx',
    'atarijaguar': 'Atari - Jaguar',
    'atarijaguarcd': 'Atari - Jaguar CD',
    'atarist': 'Atari - ST',
    # Microsoft
    'xbox': 'Microsoft - Xbox',
    'xbox360': 'Microsoft - Xbox 360',
    # Other consoles
    '3do': 'The 3DO Company - 3DO',
    'colecovision': 'Coleco - ColecoVision',
    'intellivision': 'Mattel - Intellivision',
    'vectrex': 'GCE - Vectrex',
    'wonderswan': 'Bandai - WonderSwan',
    'wonderswan-color': 'Bandai - WonderSwan Color',
    'odyssey2': 'Magnavox - Odyssey2',
    'videopac': 'Philips - Videopac+',
    'cdi': 'Philips - CD-i',
    'channelf': 'Fairchild - Channel F',
    'supervision': 'Watara - Supervision',
    'arcadia': 'Emerson - Arcadia 2001',
    'loopy': 'Casio - Loopy',
    'pv1000': 'Casio - PV-1000',
    'advision': 'Entex - Adventure Vision',
    'superacan': 'Funtech - Super Acan',
    'studio2': 'RCA - Studio II',
    'gamecom': 'Tiger - Game.com',
    'scv': 'Epoch - Super Cassette Vision',
    # Nintendo add-ons
    'satellaview': 'Nintendo - Satellaview',
    'sufami': 'Nintendo - Sufami Turbo',
    'dsi': 'Nintendo - Nintendo DSi',
    'ereader': 'Nintendo - e-Reader',
    # Sega add-ons/arcade
    'beena': 'Sega - Beena',
    'naomi': 'Sega - Naomi',
    'naomi2': 'Sega - Naomi 2',
    # Handhelds
    'gp32': 'GamePark - GP32',
    'gamemaster': 'Hartung - Game Master',
    'pocketchallenge': 'Benesse - Pocket Challenge V2',
    # Educational
    'picno': 'Konami - Picno',
    'leappad': 'LeapFrog - LeapPad',
    'leapster': 'LeapFrog - Leapster Learning Game System',
    'creativision': 'VTech - CreatiVision',
    'vsmile': 'VTech - V.Smile',
    # Computers
    'msx': 'Microsoft - MSX',
    'msx2': 'Microsoft - MSX2',
    'zxspectrum': 'Sinclair - ZX Spectrum +3',
    'zx81': 'Sinclair - ZX 81',
    'c64': 'Commodore - 64',
    'plus4': 'Commodore - Plus-4',
    'vic20': 'Commodore - VIC-20',
    'amiga': 'Commodore - Amiga',
    'amigacd32': 'Commodore - CD32',
    'cdtv': 'Commodore - CDTV',
    'amstradcpc': 'Amstrad - CPC',
    'sharp-x1': 'Sharp - X1',
    'x68000': 'Sharp - X68000',
    'enterprise': 'Enterprise - 128',
    'tvcomputer': 'Videoton - TV-Computer',
    # Mobile
    'j2me': 'Mobile - J2ME',
    'palmos': 'Mobile - Palm OS',
    'symbian': 'Mobile - Symbian',
    'zeebo': 'Mobile - Zeebo',
}

# Redump DAT names for CD/DVD-based systems
REDUMP_DAT_SYSTEMS = {
    # Sony
    'psx': 'Sony - PlayStation',
    'ps2': 'Sony - PlayStation 2',
    'ps3': 'Sony - PlayStation 3',
    'psp': 'Sony - PlayStation Portable',
    'psvita': 'Sony - PlayStation Vita',
    # Sega
    'segacd': 'Sega - Mega-CD - Sega CD',
    'saturn': 'Sega - Saturn',
    'dreamcast': 'Sega - Dreamcast',
    # NEC
    'tgcd': 'NEC - PC Engine CD - TurboGrafx-CD',
    'pcfx': 'NEC - PC-FX',
    # SNK
    'neogeocd': 'SNK - Neo Geo CD',
    # Microsoft
    'xbox': 'Microsoft - Xbox',
    'xbox360': 'Microsoft - Xbox 360',
    # Nintendo
    'gamecube': 'Nintendo - GameCube',
    'wii': 'Nintendo - Wii',
    'wiiu': 'Nintendo - Wii U',
    '3ds': 'Nintendo - Nintendo 3DS',
    # Other
    '3do': 'Panasonic - 3DO Interactive Multiplayer',
    'cdi': 'Philips - CD-i',
    'amigacd32': 'Commodore - Amiga CD32',
    'cdtv': 'Commodore - CDTV',
    'atarijaguarcd': 'Atari - Jaguar CD Interactive Multimedia System',
    'fmtowns': 'Fujitsu - FM Towns series',
    'pc98': 'NEC - PC-98 series',
    'x68000': 'Sharp - X68000',
}

# Reverse mapping: No-Intro/Redump DAT name -> system name (for URL detection)
DAT_NAME_TO_SYSTEM = {v.lower(): k for k, v in LIBRETRO_DAT_SYSTEMS.items()}
# Add Redump names
DAT_NAME_TO_SYSTEM.update({v.lower(): k for k, v in REDUMP_DAT_SYSTEMS.items()})


def detect_system_from_path(path: str) -> Optional[str]:
    """
    Detect system from a URL path or folder name.
    Handles No-Intro style names like 'GCE - Vectrex' and simple names like 'vectrex'.
    """
    path_decoded = urllib.request.unquote(path)

    for part in path_decoded.split('/'):
        part_clean = part.strip()
        if not part_clean:
            continue

        part_lower = part_clean.lower()

        # Check simple folder names first
        if part_lower in FOLDER_ALIASES:
            return FOLDER_ALIASES[part_lower]
        if part_lower in KNOWN_SYSTEMS:
            return part_lower

        # Check No-Intro style names (e.g., "GCE - Vectrex")
        if part_lower in DAT_NAME_TO_SYSTEM:
            return DAT_NAME_TO_SYSTEM[part_lower]

        # Partial match: check if any DAT name is contained in the path part
        # This handles cases like "No-Intro/GCE - Vectrex" or "Redump/Sony - PlayStation"
        for dat_name, system in DAT_NAME_TO_SYSTEM.items():
            if dat_name in part_lower:
                return system

        # Partial match against folder aliases (handles "Nintendo - Super Famicom [T-En]" etc.)
        # Normalize by removing non-alphanumeric chars for matching
        # Sort by length (longest first) to match "superfamicom" before "famicom"
        part_normalized = re.sub(r'[^a-z0-9]', '', part_lower)
        sorted_aliases = sorted(FOLDER_ALIASES.items(), key=lambda x: len(x[0]), reverse=True)
        for alias, system in sorted_aliases:
            alias_normalized = re.sub(r'[^a-z0-9]', '', alias)
            if len(alias_normalized) >= 4 and alias_normalized in part_normalized:
                return system

    return None


# Base URL for No-Intro DATs in libretro-database
LIBRETRO_DB_NOINTO_URL = "https://raw.githubusercontent.com/libretro/libretro-database/master/metadat/no-intro"
# Alternative: main dat folder for some systems
LIBRETRO_DB_DAT_URL = "https://raw.githubusercontent.com/libretro/libretro-database/master/dat"
# Redump DATs for CD-based systems
LIBRETRO_DB_REDUMP_URL = "https://raw.githubusercontent.com/libretro/libretro-database/master/metadat/redump"


def get_libretro_dat_url(system: str) -> list:
    """Get possible libretro DAT URLs for a system (returns list to try)."""
    dat_name = LIBRETRO_DAT_SYSTEMS.get(system)
    if not dat_name:
        return []

    # URL encode the name
    encoded_name = urllib.request.quote(dat_name)

    # Return multiple URLs to try (no-intro, dat folder, redump for CD systems)
    return [
        f"{LIBRETRO_DB_NOINTO_URL}/{encoded_name}.dat",
        f"{LIBRETRO_DB_DAT_URL}/{encoded_name}.dat",
        f"{LIBRETRO_DB_REDUMP_URL}/{encoded_name}.dat",
    ]


def download_libretro_dat(system: str, dest_dir: Path, force: bool = False) -> Optional[Path]:
    """Download libretro DAT file for a system."""
    urls = get_libretro_dat_url(system)
    if not urls:
        print(f"  No DAT mapping for system: {system}")
        return None

    dest_dir.mkdir(parents=True, exist_ok=True)
    dat_path = dest_dir / f"{system}.dat"

    if dat_path.exists() and not force:
        return dat_path

    if dat_path.exists() and force:
        print(f"  Updating DAT for {system}...")
        dat_path.unlink()

    # Try each URL until one works
    for url in urls:
        try:
            print(f"  Downloading DAT for {system}...")
            req = urllib.request.Request(url, headers={'User-Agent': 'Retro-Refiner/1.0'})
            with urllib.request.urlopen(req, timeout=30) as response:
                with open(dat_path, 'wb') as f:
                    shutil.copyfileobj(response, f)
            print(f"  Downloaded: {dat_path.name}")
            return dat_path
        except urllib.error.HTTPError:
            continue  # Try next URL
        except Exception as e:
            print(f"  Download error: {e}")
            continue

    print(f"  Could not download DAT for {system}")
    return None


def parse_clrmamepro_dat(dat_path: Path) -> Dict[str, DatRomEntry]:
    """Parse a ClrMamePro format DAT file."""
    entries = {}

    with open(dat_path, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()

    # Parse game entries
    game_pattern = r'game\s*\(\s*name\s+"([^"]+)"[^)]*\)'
    rom_pattern = r'rom\s*\(\s*name\s+"([^"]+)"\s+size\s+(\d+)\s+crc\s+([a-fA-F0-9]+)(?:\s+md5\s+([a-fA-F0-9]+))?(?:\s+sha1\s+([a-fA-F0-9]+))?\s*\)'

    # More robust parsing using state machine
    in_game = False
    current_game = None
    brace_count = 0

    lines = content.split('\n')
    i = 0
    while i < len(lines):
        line = lines[i].strip()

        if line.startswith('game') and '(' in line:
            in_game = True
            brace_count = line.count('(') - line.count(')')
            # Extract game name
            name_match = re.search(r'name\s+"([^"]+)"', line)
            if name_match:
                current_game = name_match.group(1)
        elif in_game:
            brace_count += line.count('(') - line.count(')')

            # Look for ROM entry
            if 'rom' in line and 'name' in line:
                rom_match = re.search(r'name\s+"([^"]+)"', line)
                size_match = re.search(r'size\s+(\d+)', line)
                crc_match = re.search(r'crc\s+([a-fA-F0-9]+)', line)
                md5_match = re.search(r'md5\s+([a-fA-F0-9]+)', line)
                sha1_match = re.search(r'sha1\s+([a-fA-F0-9]+)', line)

                if rom_match and crc_match:
                    rom_name = rom_match.group(1)
                    crc = crc_match.group(1).lower()

                    # Detect region from game name
                    region = detect_dat_region(current_game) if current_game else 'Unknown'

                    entry = DatRomEntry(
                        name=current_game or rom_name,
                        rom_name=rom_name,
                        size=int(size_match.group(1)) if size_match else 0,
                        crc=crc,
                        md5=md5_match.group(1).lower() if md5_match else '',
                        sha1=sha1_match.group(1).lower() if sha1_match else '',
                        region=region,
                        is_parent=True,
                        parent_name='',
                    )
                    # Index by CRC for quick lookup
                    entries[crc] = entry

            if brace_count <= 0:
                in_game = False
                current_game = None

        i += 1

    return entries


def detect_dat_region(name: str) -> str:
    """Detect region from DAT game name."""
    name_lower = name.lower()
    if '(usa)' in name_lower or '(us)' in name_lower:
        return 'USA'
    elif '(world)' in name_lower:
        return 'World'
    elif '(europe)' in name_lower or '(eu)' in name_lower:
        return 'Europe'
    elif '(japan)' in name_lower or '(jp)' in name_lower:
        return 'Japan'
    elif '(australia)' in name_lower or '(au)' in name_lower:
        return 'Australia'
    elif '(asia)' in name_lower:
        return 'Asia'
    elif '(korea)' in name_lower:
        return 'Korea'
    return 'Unknown'


def calculate_crc32(filepath: Path) -> str:
    """Calculate CRC32 checksum of a file."""
    crc = 0
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            crc = binascii.crc32(chunk, crc)
    return format(crc & 0xFFFFFFFF, '08x')


def calculate_crc32_from_zip(zip_path: Path) -> str:
    """Calculate CRC32 of the first file inside a ZIP."""
    try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            # Get the first non-directory file
            for name in zf.namelist():
                if not name.endswith('/'):
                    with zf.open(name) as f:
                        crc = 0
                        for chunk in iter(lambda: f.read(65536), b''):
                            crc = binascii.crc32(chunk, crc)
                        return format(crc & 0xFFFFFFFF, '08x')
    except:
        pass
    return None


def verify_roms_against_dat(rom_files: List[Path], dat_entries: Dict[str, DatRomEntry],
                            system: str) -> Tuple[List, List, List]:
    """
    Verify ROM files against DAT entries.
    Returns (verified, unverified, bad) lists.
    """
    verified = []
    unverified = []
    bad = []

    for rom_path in tqdm(rom_files, desc=f"{system.upper()} Verifying", unit="ROM", leave=False):
        if _shutdown_requested:
            break
        # Calculate CRC
        if rom_path.suffix.lower() == '.zip':
            crc = calculate_crc32_from_zip(rom_path)
        else:
            crc = calculate_crc32(rom_path)

        if crc and crc in dat_entries:
            verified.append((rom_path, dat_entries[crc]))
        elif crc:
            # CRC calculated but not in DAT - might be unknown ROM
            unverified.append((rom_path, crc))
        else:
            # Couldn't calculate CRC
            bad.append(rom_path)

    return verified, unverified, bad


def parse_rom_filename(filename: str) -> RomInfo:
    """Parse a ROM filename and extract metadata."""

    # Remove file extension (covers all common ROM formats)
    name = re.sub(r'\.(zip|7z|rar|sfc|smc|nes|n64|z64|v64|md|gen|bin|gb|gbc|gba|nds|gcm|iso|cue|pce|col|a26|a52|a78|jag|lnx|st|int|gg|sms|sg|32x|vb|ws|wsc|rom|mx1|mx2)$', '', filename, flags=re.IGNORECASE)

    # Check for BIOS
    is_bios = name.startswith('[BIOS]') or '(BIOS)' in name

    # Check for documentation/metadata files (start with underscore)
    if name.startswith('_'):
        # Treat as BIOS to filter out
        is_bios = True

    # Check for pirate
    is_pirate = '(Pirate)' in name

    # Check for unlicensed
    is_unlicensed = '(Unl)' in name

    # Check for beta/demo/promo/sample/proto
    is_beta = bool(re.search(r'\(Beta[^)]*\)', name))
    is_demo = '(Demo)' in name or '(Kiosk)' in name or 'Caravan' in name or 'Taikenban' in name
    is_promo = '(Promo)' in name or '(Movie Promo)' in name or 'Present Campaign' in name or 'Senyou Cartridge' in name or 'Hot Mario Campaign' in name
    is_sample = '(Sample)' in name
    is_proto = '(Proto)' in name or bool(re.search(r'\(Proto[^)]*\)', name))

    # Check for re-releases
    # Note: Some patterns don't require surrounding parens because they may be
    # combined with other tags like "(Virtual Console, Classic Mini, Switch Online)"
    rerelease_patterns = [
        r'Virtual Console', r'GameCube\)', r'\(LodgeNet\)',
        r'\(Arcade\)', r'Sega Channel', r'Switch Online',
        r'Classic Mini', r'Retro-Bit', r'Evercade',
        r'Wii Virtual Console', r'Mega Drive Mini',
        r'Collection\)', r'\(NP\)',  # Nintendo Power
        r'\(e-Reader\)', r'\(FamicomBox\)', r'Animal Crossing',
        r'Sonic Classic Collection', r'Sonic Mega Collection',
        r'Disney Classic Games', r'Castlevania Anniversary',
        r'Castlevania Advance Collection', r'Sega Smash Pack',
        r'Game no Kanzume', r'Sega Game Toshokan',
        r'SegaNet', r'Sega 3D Classics',
        r'Capcom Town', r'iam8bit',  # Modern re-releases
        r'GameCube Edition',  # Special editions
        r'Genesis Mini', r'Mega Drive Mini',  # Sega mini consoles
        r'Contra Anniversary Collection', r'Konami Collector',  # Konami collections
        r'Arcade Legends',  # Arcade re-releases
    ]
    is_rerelease = any(re.search(p, name) for p in rerelease_patterns)

    # Check for compilations/collections (multi-game carts)
    compilation_patterns = [
        r'\d+.in.1\b', r'\d+ Super Jogos', r'^\d+-Pak',  # X-in-1, X in 1
        r'Compilation',
        r'\+ .+ \+',  # Multiple games combined like "SMB + Duck Hunt + Track Meet"
        r'Super Mario All-Stars',  # Specifically filter Mario compilation
        r'Double Pack', r'^2 Games in 1', r'^2 Games in One',
        r'^2.in.1 Game Pack', r'^Combo Pack', r'^2 Game Pack',
        r'Classics\)', r'Competition Cartridge',  # DK Classics, Competition carts
        r'Twin Pack',
    ]
    is_compilation = any(re.search(p, name) for p in compilation_patterns)

    # Special handling for multi-game carts that should be excluded
    if re.search(r'\+ .+ \(', name) and not 'All-Stars' in name:
        # Like "Super Mario Bros. + Duck Hunt (USA)"
        is_compilation = True
    # Games with "Game 1 & 2" or "Game 3 & 4" pattern (numbered sequels combined)
    if re.search(r'\b(\d) & (\d)\b', name):
        is_compilation = True

    # Check for lock-on combinations (Sonic & Knuckles + other games)
    is_lock_on = '(Lock-on Combination)' in name or (
        'Sonic & Knuckles +' in name and 'Sonic' in name
    )

    # Check for translations
    translation_match = re.search(r'\[T-En[^\]]*\]', name)
    is_translation = bool(translation_match)
    translation_version = ""
    if translation_match:
        # Extract version from translation tag
        ver_match = re.search(r'v(\d+\.?\d*[a-z]?)', translation_match.group())
        if ver_match:
            translation_version = ver_match.group(1)

    # Check for hacks (but not translation-related patches)
    # These are modifications beyond just translation
    hack_patterns = [
        r'\[Hack by',      # General hacks
        r'\[Add by',       # Addendum patches
        r'Edition\]',      # Special editions (Namingway, Woolsey, etc.)
        r'\[FastROM',      # FastROM hacks
        r'\[Bugfix',       # Bug fix patches
        r'patch\]',        # Various patches
        r'\[Retranslated\]',  # Retranslation patches (beyond original translation)
        r'GBA Script',     # Script ports from other versions
    ]
    has_hacks = any(re.search(p, name, re.IGNORECASE) for p in hack_patterns)

    # Extract region - handle multi-region releases like "(Japan, USA)" or "(USA, Europe)"
    region_match = re.search(r'\(([^)]+)\)', name)
    region = "Unknown"
    if region_match:
        region_str = region_match.group(1)
        # Priority order for multi-region releases
        region_priority = ['USA', 'World', 'Europe', 'Australia', 'Japan', 'Korea',
                          'Brazil', 'France', 'Germany', 'Spain', 'Italy', 'Asia',
                          'Taiwan', 'Hong Kong', 'China']
        for r in region_priority:
            if r in region_str:
                region = r
                break

    # Check for English language support
    is_english = False
    languages = []

    # Check for explicit language tags like "(En)" or "(En,Fr,De)" or "(Japan) (En)"
    # Look for standalone (En) or language list containing En
    if re.search(r'\(En\)', name) or re.search(r'\([^)]*\bEn\b[^)]*\)', name):
        is_english = True
        languages.append('En')

    # Extract other language tags
    lang_match = re.search(r'\((?:En,?)?(?:Fr|De|Es|It|Ja|Nl|Sv|Pt)(?:,[A-Za-z]+)*\)', name)
    if lang_match:
        lang_str = lang_match.group()
        if 'Fr' in lang_str:
            languages.append('Fr')
        if 'De' in lang_str:
            languages.append('De')
        if 'Es' in lang_str:
            languages.append('Es')
        if 'Ja' in lang_str:
            languages.append('Ja')

    # Region-based English detection (only if no explicit language tag says otherwise)
    if region in ['USA', 'World', 'Europe', 'Australia']:
        is_english = True

    # If it's a translation to English, mark as English
    if is_translation:
        is_english = True

    # Extract revision number
    revision = 0
    rev_match = re.search(r'\(Rev\s*([A-Z0-9]+)\)', name)
    if rev_match:
        rev_str = rev_match.group(1)
        if rev_str.isdigit():
            revision = int(rev_str)
        else:
            # Convert letter revisions (A=1, B=2, etc.)
            revision = ord(rev_str[0].upper()) - ord('A') + 1

    # Also check for version numbers
    ver_match = re.search(r'\(v(\d+)\.(\d+)\)', name)
    if ver_match:
        revision = max(revision, int(ver_match.group(1)) * 100 + int(ver_match.group(2)))

    # Extract base title (remove all tags)
    base_title = name
    # Remove square bracket tags first
    base_title = re.sub(r'\[[^\]]+\]', '', base_title)
    # Remove parenthetical tags
    base_title = re.sub(r'\s*\([^)]+\)', '', base_title)
    # Clean up
    base_title = base_title.strip()
    base_title = re.sub(r'\s+', ' ', base_title)

    # Check for homebrew indicators
    homebrew_indicators = ['(Aftermarket)', '(Homebrew)', 'Homebrew']
    is_homebrew = any(ind in name for ind in homebrew_indicators)

    # Extract year if present (look for 4-digit year in parentheses, e.g. "(1990)")
    year = 0
    year_match = re.search(r'\((\d{4})\)', name)
    if year_match:
        potential_year = int(year_match.group(1))
        # Sanity check: year should be between 1970 and 2030
        if 1970 <= potential_year <= 2030:
            year = potential_year

    return RomInfo(
        filename=filename,
        base_title=base_title,
        region=region,
        revision=revision,
        is_english=is_english,
        is_translation=is_translation,
        is_beta=is_beta,
        is_demo=is_demo,
        is_promo=is_promo,
        is_sample=is_sample,
        is_proto=is_proto,
        is_bios=is_bios,
        is_pirate=is_pirate,
        is_unlicensed=is_unlicensed,
        is_homebrew=is_homebrew,
        is_rerelease=is_rerelease,
        is_compilation=is_compilation,
        is_lock_on=is_lock_on,
        translation_version=translation_version,
        has_hacks=has_hacks,
        languages=languages,
        year=year,
    )

def normalize_title(title: str) -> str:
    """Normalize a title for grouping purposes."""
    # Lowercase
    normalized = title.lower()

    # Remove common articles and punctuation differences
    # Handle "Title, The" pattern (common in ROM naming)
    normalized = re.sub(r',\s*(the|a|an)\s*', ' ', normalized)
    normalized = re.sub(r'^(the|a|an)\s+', '', normalized)

    # Normalize punctuation (remove colons, hyphens, apostrophes, periods, commas)
    normalized = re.sub(r'[:\-\'.,]', ' ', normalized)
    normalized = re.sub(r'\s+', ' ', normalized)
    normalized = normalized.strip()

    # Normalize roman numerals to arabic (but be careful not to break words)
    # Only convert when they appear as standalone words (game numbers)
    roman_map = [
        (r'\bviii\b', '8'), (r'\bvii\b', '7'), (r'\bvi\b', '6'),
        (r'\biv\b', '4'), (r'\bv\b', '5'), (r'\biii\b', '3'),
        (r'\bii\b', '2'), (r'\bi\b', '1'),
    ]
    for pattern, replacement in roman_map:
        normalized = re.sub(pattern, replacement, normalized)

    # Load title mappings from external JSON file
    # This allows easier maintenance and automated updates
    title_mappings = load_title_mappings()
    for variant, canonical in title_mappings.items():
        if normalized == variant:  # Exact match only
            normalized = canonical

    return normalized

def select_best_rom(roms: list[RomInfo], region_priority: List[str] = None) -> Optional[RomInfo]:
    """Select the best ROM from a group of ROMs for the same game.

    Priority order:
    1. English versions (USA/Europe/World)
    2. English translations of foreign games
    3. Foreign versions (Japan, etc.) if no English option exists
    """

    if not roms:
        return None

    if region_priority is None:
        region_priority = DEFAULT_REGION_PRIORITY

    # Filter out universally unwanted ROMs first
    base_filtered = []
    for rom in roms:
        # Skip BIOS, pirate, homebrew, unlicensed
        if rom.is_bios or rom.is_pirate or rom.is_homebrew or rom.is_unlicensed:
            continue
        # Skip betas, demos, promos, samples (but keep protos)
        if rom.is_beta or rom.is_demo or rom.is_promo or rom.is_sample:
            continue
        # Skip re-releases
        if rom.is_rerelease:
            continue
        # Skip compilations
        if rom.is_compilation:
            continue
        # Skip lock-on combinations
        if rom.is_lock_on:
            continue

        base_filtered.append(rom)

    if not base_filtered:
        return None

    # Separate into English and non-English pools
    english_roms = [r for r in base_filtered if r.is_english]
    foreign_roms = [r for r in base_filtered if not r.is_english]

    # Try to find an English version first
    if english_roms:
        candidates = english_roms
    else:
        # No English version available - use foreign versions
        candidates = foreign_roms

    if not candidates:
        return None

    # Separate prototypes from regular releases
    protos = [r for r in candidates if r.is_proto]
    regular = [r for r in candidates if not r.is_proto]

    # Prefer regular releases over prototypes if available
    candidates = regular if regular else protos

    # Among candidates, prefer official English releases over translations,
    # but prefer translations over untranslated foreign-language ROMs
    english_regions = {'USA', 'World', 'Europe', 'Australia', 'England'}
    non_trans = [r for r in candidates if not r.is_translation]
    translations = [r for r in candidates if r.is_translation]

    # Check if we have official English non-translation ROMs
    english_non_trans = [r for r in non_trans if r.region in english_regions]

    if english_non_trans:
        # Prefer official English releases over fan translations
        non_hacked = [r for r in english_non_trans if not r.has_hacks]
        candidates = non_hacked if non_hacked else english_non_trans
    elif translations:
        # For non-English games, prefer translations over untranslated
        pure_trans = [r for r in translations if not r.has_hacks]
        candidates = pure_trans if pure_trans else translations
    elif non_trans:
        # Fall back to untranslated if no translations available
        non_hacked = [r for r in non_trans if not r.has_hacks]
        candidates = non_hacked if non_hacked else non_trans

    # Sort by preference based on region priority
    # Higher revision number, Non-hacked preferred (tie-breaker)
    def sort_key(rom: RomInfo):
        # Build priority dict from the list
        priority_dict = {region: idx for idx, region in enumerate(region_priority)}
        return (
            priority_dict.get(rom.region, 99),
            -rom.revision,  # Higher revision = better
            1 if rom.has_hacks else 0,  # Non-hacked preferred
        )

    candidates.sort(key=sort_key)

    return candidates[0] if candidates else None


# =============================================================================
# MAME ARCADE FILTERING
# =============================================================================

# Default MAME version (updated periodically)
DEFAULT_MAME_VERSION = "0.274"

# Download URLs for MAME data files
MAME_DATA_SOURCES = {
    'catver': {
        'url': 'https://www.progettosnaps.net/catver/packs/pS_CatVer_{version}.zip',
        'filename': 'catver.ini',
        'inside_zip': 'catver.ini',
    },
    'dat': {
        'url': 'https://github.com/mamedev/mame/releases/download/mame{version_nodot}/mame{version_nodot}lx.zip',
        'filename': 'mame.xml',
        'inside_zip': 'mame.xml',
        'alt_url': 'https://www.progettosnaps.net/dats/MAME/pS_MAME_{version}_DATs.7z',
    },
}


def get_latest_mame_version() -> str:
    """Try to detect the latest MAME version from GitHub releases."""
    try:
        url = "https://api.github.com/repos/mamedev/mame/releases/latest"
        req = urllib.request.Request(url, headers={'User-Agent': 'Retro-Refiner/1.0'})
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode())
            tag = data.get('tag_name', '')
            # Tag format is "mame0274" -> "0.274"
            if tag.startswith('mame'):
                version_num = tag[4:]  # "0274"
                if len(version_num) >= 4:
                    return f"0.{version_num[1:]}"  # "0.274"
    except Exception as e:
        print(f"  Could not detect latest MAME version: {e}")
    return DEFAULT_MAME_VERSION


def download_file(url: str, dest_path: Path, description: str = "file") -> bool:
    """Download a file from URL to destination path."""
    try:
        print(f"  Downloading {description}...")
        print(f"  URL: {url}")
        req = urllib.request.Request(url, headers={'User-Agent': 'Retro-Refiner/1.0'})
        with urllib.request.urlopen(req, timeout=60) as response:
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            with open(dest_path, 'wb') as f:
                shutil.copyfileobj(response, f)
        print(f"  Downloaded to {dest_path}")
        return True
    except urllib.error.HTTPError as e:
        print(f"  HTTP Error {e.code}: {e.reason}")
        return False
    except urllib.error.URLError as e:
        print(f"  URL Error: {e.reason}")
        return False
    except Exception as e:
        print(f"  Download failed: {e}")
        return False


def extract_from_zip(zip_path: Path, filename: str, dest_path: Path) -> bool:
    """Extract a specific file from a zip archive."""
    try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            # Find the file (may be in a subdirectory)
            for name in zf.namelist():
                if name.endswith(filename) or name == filename:
                    # Extract to temp and move
                    with zf.open(name) as src:
                        dest_path.parent.mkdir(parents=True, exist_ok=True)
                        with open(dest_path, 'wb') as dst:
                            shutil.copyfileobj(src, dst)
                    print(f"  Extracted {filename} to {dest_path}")
                    return True
        print(f"  File {filename} not found in archive")
        return False
    except zipfile.BadZipFile:
        print(f"  Invalid zip file: {zip_path}")
        return False
    except Exception as e:
        print(f"  Extraction failed: {e}")
        return False


def download_mame_data(mame_data_dir: Path, version: str = None, force: bool = False) -> tuple:
    """
    Download MAME catver.ini and DAT files.
    Returns (catver_path, dat_path) or (None, None) on failure.
    """
    if version is None:
        print("MAME: Detecting latest MAME version...")
        version = get_latest_mame_version()

    print(f"MAME: Using version {version}")

    # Format version for URLs
    version_clean = version.replace(".", "")  # "0274"
    version_dot = version  # "0.274"

    mame_data_dir.mkdir(parents=True, exist_ok=True)

    catver_path = mame_data_dir / 'catver.ini'
    dat_path = mame_data_dir / 'mame.xml'

    # Remove existing files if force update
    if force:
        if catver_path.exists():
            print("MAME: Removing existing catver.ini for update...")
            catver_path.unlink()
        if dat_path.exists():
            print("MAME: Removing existing MAME data for update...")
            dat_path.unlink()

    # Download catver.ini
    if not catver_path.exists():
        print("\nMAME: Downloading catver.ini...")
        catver_url = f"https://www.progettosnaps.net/catver/packs/pS_CatVer_{version_clean}.zip"
        zip_path = mame_data_dir / 'catver.zip'

        if download_file(catver_url, zip_path, "catver.ini pack"):
            if extract_from_zip(zip_path, 'catver.ini', catver_path):
                zip_path.unlink()  # Clean up zip
            else:
                print("  Failed to extract catver.ini")
        else:
            # Try alternative: version without leading zero
            alt_version = version_clean.lstrip('0')
            catver_url = f"https://www.progettosnaps.net/catver/packs/pS_CatVer_{alt_version}.zip"
            if download_file(catver_url, zip_path, "catver.ini pack (alt)"):
                if extract_from_zip(zip_path, 'catver.ini', catver_path):
                    zip_path.unlink()
    else:
        print(f"MAME: Using existing catver.ini at {catver_path}")

    # Download MAME XML/DAT
    if not dat_path.exists():
        print("\nMAME: Downloading MAME XML database...")

        # Try official MAME release first
        mame_xml_url = f"https://github.com/mamedev/mame/releases/download/mame{version_clean}/mame{version_clean}lx.zip"
        zip_path = mame_data_dir / 'mame_xml.zip'

        if download_file(mame_xml_url, zip_path, "MAME XML"):
            if extract_from_zip(zip_path, '.xml', dat_path):
                zip_path.unlink()
            else:
                print("  Failed to extract MAME XML")
        else:
            # Try Progetto Snaps DAT pack
            print("  Trying alternative source...")
            alt_url = f"https://www.progettosnaps.net/dats/MAME/pS_MAME_{version_clean}_DATs.zip"
            if download_file(alt_url, zip_path, "MAME DAT pack"):
                # Look for arcade dat
                if extract_from_zip(zip_path, 'arcade).dat', dat_path):
                    zip_path.unlink()
                elif extract_from_zip(zip_path, 'MAME', dat_path):
                    zip_path.unlink()
    else:
        print(f"MAME: Using existing MAME data at {dat_path}")

    # Verify files exist
    if catver_path.exists() and dat_path.exists():
        return catver_path, dat_path
    elif catver_path.exists():
        # Check for any existing DAT in the directory
        existing_dats = list(mame_data_dir.glob('*.dat')) + list(mame_data_dir.glob('*.xml'))
        if existing_dats:
            return catver_path, existing_dats[0]

    return (catver_path if catver_path.exists() else None,
            dat_path if dat_path.exists() else None)


@dataclass
class MameGameInfo:
    """Information about a MAME game parsed from DAT and catver.ini."""
    name: str  # ROM name (e.g., "sf2")
    description: str  # Full title
    year: str
    manufacturer: str
    category: str
    is_parent: bool
    parent_name: str  # Empty if is_parent, otherwise parent ROM name
    is_bios: bool
    is_device: bool
    has_chd: bool
    chd_names: list  # List of CHD filenames
    region: str  # Detected region (USA, Japan, Europe, World, etc.)


# Categories to INCLUDE (playable with keyboard/mouse/gamepad/lightgun)
MAME_INCLUDE_CATEGORIES = {
    # Action/Arcade
    'Ball & Paddle',
    'Climbing',
    'Fighter',
    'Maze',
    'Platform',
    'Puzzle',
    'Shooter',
    'Sports',
    'Whac-A-Mole',
    'Driving',
    'Multiplay',
    'MultiGame',
    # TTL games (early arcade)
    'TTL',
}

# Categories to EXCLUDE
MAME_EXCLUDE_CATEGORIES = {
    # User requested exclusions
    'Casino',
    'Gambling',
    'Quiz',
    'Tabletop / Mahjong',
    'Tabletop / Hanafuda',
    'Slot Machine',
    # Mechanical/special hardware
    'Electromechanical',
    'Arcade / Strength Tester',
    'Arcade / Fortune Teller',
    'Arcade / Physical Ability',
    'Music Game / Dance',
    'Music Game / Instruments',
    'Redemption Game',
    'Medal Game',
    # Non-game
    'System / BIOS',
    'System / Device',
    'Computer',
    'Calculator',
    'Printer',
    'Telephone',
    'Utilities',
    'Medical Equipment',
    'Musical Instrument',
    'Radio',
    'Watch',
    'Misc. / Clock',
    'Misc. / Prediction',
    'Misc. / Love Test',
    'Game Console',
    'Handheld',
    'Board Game',
    'Music Player',
    'Player',
    'Tablet',
    'TV Bundle',
    'Non Arcade',
    'Digital Camera',
    'Digital Simulator',
    'Robot',
    'Simulation',
    'Card Games / Solitaire',
}

# Specific subcategories to exclude even if parent category is included
MAME_EXCLUDE_SUBCATEGORIES = {
    'Music Game / Dance',
    'Handheld / Plug n\' Play TV Game / Dance',
    'Handheld / Plug n\' Play TV Game / Mahjong',
    'Handheld / Plug n\' Play TV Game / Quiz',
    'Handheld / Plug n\' Play TV Game / Casino',
    'Tabletop / Mahjong',
    'Tabletop / Mahjong * Mature *',
    'Tabletop / Hanafuda',
    'Tabletop / Hanafuda * Mature *',
}


def parse_catver_ini(catver_path: str) -> dict:
    """Parse catver.ini and return a dict of romname -> category."""
    categories = {}
    in_category_section = False

    with open(catver_path, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            line = line.strip()
            if line == '[Category]':
                in_category_section = True
                continue
            elif line.startswith('[') and in_category_section:
                break  # End of category section
            elif in_category_section and '=' in line:
                parts = line.split('=', 1)
                if len(parts) == 2:
                    romname = parts[0].strip()
                    category = parts[1].strip()
                    categories[romname] = category

    return categories


def parse_mame_dat(dat_path: str) -> dict:
    """Parse MAME DAT file and return game info dict."""
    import xml.etree.ElementTree as ET

    games = {}

    # Check if it's XML format
    with open(dat_path, 'r', encoding='utf-8', errors='ignore') as f:
        first_line = f.readline()

    if '<?xml' in first_line or '<datafile' in first_line or '<mame' in first_line:
        # XML format
        tree = ET.parse(dat_path)
        root = tree.getroot()

        # Handle different XML formats
        game_elements = root.findall('.//machine') or root.findall('.//game')

        for game in game_elements:
            name = game.get('name', '')
            if not name:
                continue

            # Check if it's a BIOS or device
            is_bios = game.get('isbios', 'no') == 'yes'
            is_device = game.get('isdevice', 'no') == 'yes'

            # Get parent info
            parent_name = game.get('cloneof', '') or game.get('romof', '')
            is_parent = not parent_name or parent_name == name

            # Get description
            desc_elem = game.find('description')
            description = desc_elem.text if desc_elem is not None else name

            # Get year
            year_elem = game.find('year')
            year = year_elem.text if year_elem is not None else ''

            # Get manufacturer
            mfr_elem = game.find('manufacturer') or game.find('publisher')
            manufacturer = mfr_elem.text if mfr_elem is not None else ''

            # Check for CHDs (disk elements)
            chd_names = []
            for disk in game.findall('.//disk'):
                disk_name = disk.get('name', '')
                if disk_name:
                    chd_names.append(disk_name + '.chd')

            # Detect region from description
            region = detect_mame_region(description)

            games[name] = MameGameInfo(
                name=name,
                description=description,
                year=year,
                manufacturer=manufacturer or '',
                category='',  # Will be filled from catver.ini
                is_parent=is_parent,
                parent_name=parent_name if not is_parent else '',
                is_bios=is_bios,
                is_device=is_device,
                has_chd=len(chd_names) > 0,
                chd_names=chd_names,
                region=region,
            )
    else:
        # ClrMamePro DAT format - simplified parsing
        # This is more complex, so we'll just handle the XML format primarily
        print(f"Warning: Non-XML DAT format detected. Using simplified parsing.")

    return games


def detect_mame_region(description: str) -> str:
    """Detect region from MAME game description."""
    desc_lower = description.lower()

    # Check for explicit region markers
    if '(us)' in desc_lower or '(usa)' in desc_lower or '[us]' in desc_lower:
        return 'USA'
    elif '(world)' in desc_lower or '[world]' in desc_lower:
        return 'World'
    elif '(europe)' in desc_lower or '(euro)' in desc_lower or '[europe]' in desc_lower:
        return 'Europe'
    elif '(japan)' in desc_lower or '(jpn)' in desc_lower or '[japan]' in desc_lower:
        return 'Japan'
    elif '(asia)' in desc_lower or '[asia]' in desc_lower:
        return 'Asia'
    elif '(korea)' in desc_lower or '[korea]' in desc_lower:
        return 'Korea'
    elif '(hispanic)' in desc_lower or '(brazil)' in desc_lower:
        return 'LatinAmerica'

    # Check description patterns
    if ' usa ' in desc_lower or desc_lower.endswith(' usa'):
        return 'USA'

    return 'Unknown'


def should_include_mame_game(game: MameGameInfo, category: str, include_adult: bool = True) -> tuple:
    """
    Determine if a MAME game should be included.
    Returns (should_include, reason).
    """
    # Always exclude BIOS and devices
    if game.is_bios:
        return False, "BIOS"
    if game.is_device:
        return False, "Device"

    # Check category
    if not category:
        return False, "No category"

    # Check for adult/mature content
    if not include_adult and '* Mature *' in category:
        return False, "Adult/mature content"

    # Check for excluded subcategories first (exact match)
    if category in MAME_EXCLUDE_SUBCATEGORIES:
        return False, f"Excluded subcategory: {category}"

    # Check main category exclusions
    for exclude_cat in MAME_EXCLUDE_CATEGORIES:
        if category.startswith(exclude_cat):
            return False, f"Excluded category: {exclude_cat}"

    # Check for specific exclusions within category text
    cat_lower = category.lower()
    if 'mahjong' in cat_lower:
        return False, "Mahjong game"
    if 'quiz' in cat_lower:
        return False, "Quiz game"
    if 'casino' in cat_lower or 'gambling' in cat_lower:
        return False, "Casino/Gambling game"
    if 'slot machine' in cat_lower:
        return False, "Slot machine"
    if 'pachinko' in cat_lower:
        return False, "Pachinko"
    if 'medal game' in cat_lower:
        return False, "Medal game"
    if 'dance' in cat_lower and 'game' in cat_lower:
        return False, "Dance game (requires pad)"

    # Check for included categories
    for include_cat in MAME_INCLUDE_CATEGORIES:
        if category.startswith(include_cat):
            return True, f"Included category: {include_cat}"

    # Special case: Arcade pinball is fine
    if 'pinball' in cat_lower and 'electromechanical' not in cat_lower:
        return True, "Video pinball"

    # Light gun games - check for shooter/gallery types
    if 'shooter / gallery' in cat_lower or 'gun' in cat_lower:
        return True, "Light gun game"

    # Default: exclude unknown categories
    return False, f"Unknown category: {category}"


def get_mame_region_priority(region: str) -> int:
    """Get priority for MAME regions (lower is better)."""
    priorities = {
        'USA': 0,
        'World': 1,
        'Europe': 2,
        'Asia': 3,
        'Japan': 4,
        'Korea': 5,
        'LatinAmerica': 6,
        'Unknown': 10,
    }
    return priorities.get(region, 10)


def select_best_mame_clone(parent_name: str, clones: list, games: dict) -> MameGameInfo:
    """Select the best clone based on region preference."""
    if not clones:
        return games.get(parent_name)

    # Include parent in consideration
    candidates = [games[parent_name]] if parent_name in games else []
    candidates.extend([games[c] for c in clones if c in games])

    if not candidates:
        return None

    # Sort by region priority
    candidates.sort(key=lambda g: get_mame_region_priority(g.region))

    return candidates[0]


def filter_mame_roms(source_dir: str, dest_dir: str, catver_path: str, dat_path: str,
                     copy_chds: bool = True, dry_run: bool = False, system_name: str = 'mame',
                     include_adult: bool = True):
    """Filter MAME/FBNeo ROMs based on category and region preferences."""
    label = system_name.upper()

    print(f"\n{label}: Loading catver.ini...")
    categories = parse_catver_ini(catver_path)
    print(f"{label}: Loaded {len(categories)} game categories")

    print(f"{label}: Loading DAT...")
    games = parse_mame_dat(dat_path)
    print(f"{label}: Loaded {len(games)} games from DAT")

    # Apply categories to games
    for name, game in games.items():
        game.category = categories.get(name, '')

    # Scan source directory for available ROMs
    source_path = Path(source_dir)
    available_roms = set()
    available_chds = {}  # rom_name -> [chd_paths]
    rom_sizes = {}  # rom_name -> file size
    chd_sizes = {}  # rom_name -> total CHD size
    total_source_size = 0

    if source_path.exists():
        for f in source_path.iterdir():
            if f.suffix.lower() == '.zip':
                available_roms.add(f.stem)
                size = get_file_size(f)
                rom_sizes[f.stem] = size
                total_source_size += size
            elif f.is_dir():
                # Check for CHDs in subdirectory
                chds = list(f.glob('*.chd'))
                if chds:
                    available_chds[f.name] = [c.name for c in chds]
                    chd_size = sum(get_file_size(c) for c in chds)
                    chd_sizes[f.name] = chd_size
                    total_source_size += chd_size

    print(f"{label}: Found {len(available_roms)} ROM files ({format_size(sum(rom_sizes.values()))})")
    print(f"{label}: Found {len(available_chds)} games with CHDs ({format_size(sum(chd_sizes.values()))})")

    # Group clones by parent
    parent_clones = defaultdict(list)
    for name, game in games.items():
        if not game.is_parent and game.parent_name:
            parent_clones[game.parent_name].append(name)

    # Filter and select best versions
    selected_roms = []
    skipped_games = []
    included_reasons = defaultdict(int)
    excluded_reasons = defaultdict(int)

    # Process each parent game
    for name, game in games.items():
        if not game.is_parent:
            continue  # Process clones through their parent

        # Check if we have this ROM or any of its clones
        available_versions = []
        if name in available_roms:
            available_versions.append(name)
        for clone in parent_clones.get(name, []):
            if clone in available_roms:
                available_versions.append(clone)

        if not available_versions:
            continue  # No ROMs available for this game

        # Check if the game should be included
        # Use parent's category for decision, but select best regional version
        should_include, reason = should_include_mame_game(game, game.category, include_adult)

        if not should_include:
            excluded_reasons[reason] += 1
            skipped_games.append((game.description, name, reason))
            continue

        included_reasons[reason] += 1

        # Select best version based on region
        best_rom = select_best_mame_clone(name, parent_clones.get(name, []), games)
        if best_rom and best_rom.name in available_versions:
            selected_roms.append(best_rom)
        elif available_versions:
            # Fallback to first available
            selected_roms.append(games[available_versions[0]])

    # Calculate selected size
    selected_size = 0
    for game in selected_roms:
        selected_size += rom_sizes.get(game.name, 0)
        if copy_chds and game.name in chd_sizes:
            selected_size += chd_sizes.get(game.name, 0)

    print(f"{label}: Selected {len(selected_roms)} games ({format_size(selected_size)})")
    if total_source_size > 0:
        size_saved = total_source_size - selected_size
        reduction_pct = (size_saved / total_source_size) * 100
        print(f"{label}: Size reduction: {format_size(size_saved)} saved ({reduction_pct:.1f}%)")

    # Print inclusion/exclusion stats
    print(f"\n{label} Inclusion reasons:")
    for reason, count in sorted(included_reasons.items(), key=lambda x: -x[1])[:10]:
        print(f"  {reason}: {count}")

    print(f"\n{label} Exclusion reasons (top 10):")
    for reason, count in sorted(excluded_reasons.items(), key=lambda x: -x[1])[:10]:
        print(f"  {reason}: {count}")

    # Copy files
    if not dry_run:
        dest_path = Path(dest_dir) / system_name

        # Clear destination
        if dest_path.exists():
            shutil.rmtree(dest_path)
        dest_path.mkdir(parents=True, exist_ok=True)

        copied = 0
        copied_chds = 0

        for game in tqdm(selected_roms, desc=f"{label} Copying", unit="ROM", leave=False):
            if _shutdown_requested:
                break
            # Copy ROM
            src_rom = source_path / f"{game.name}.zip"
            if src_rom.exists():
                shutil.copy2(src_rom, dest_path / f"{game.name}.zip")
                copied += 1

            # Copy CHDs if requested
            if copy_chds and game.name in available_chds:
                chd_dest = dest_path / game.name
                chd_dest.mkdir(exist_ok=True)
                src_chd_dir = source_path / game.name
                for chd_name in available_chds[game.name]:
                    src_chd = src_chd_dir / chd_name
                    if src_chd.exists():
                        shutil.copy2(src_chd, chd_dest / chd_name)
                        copied_chds += 1

        print(f"\n{label}: Copied {copied} ROMs to {dest_path}")
        if copied_chds:
            print(f"{label}: Copied {copied_chds} CHD files")

    # Write selection log
    log_path = Path(dest_dir) / system_name / '_selection_log.txt'
    if not dry_run:
        log_path.parent.mkdir(parents=True, exist_ok=True)

    with open(log_path, 'w', encoding='utf-8') if not dry_run else open(os.devnull, 'w') as f:
        if not dry_run:
            f.write(f"{label} Selection Log\n")
            f.write("=" * 60 + "\n\n")
            f.write(f"Total ROMs available: {len(available_roms)}\n")
            f.write(f"Games with CHDs: {len(available_chds)}\n")
            f.write(f"Selected: {len(selected_roms)}\n")
            f.write(f"Skipped: {len(skipped_games)}\n\n")
            size_saved = total_source_size - selected_size
            f.write(f"Source size: {format_size(total_source_size)}\n")
            f.write(f"Selected size: {format_size(selected_size)}\n")
            f.write(f"Size saved: {format_size(size_saved)}\n\n")

            f.write("SELECTED GAMES\n")
            f.write("-" * 60 + "\n")
            for game in sorted(selected_roms, key=lambda g: g.description):
                f.write(f"{game.name}: {game.description}\n")
                f.write(f"  Category: {game.category}\n")
                f.write(f"  Year: {game.year} | Manufacturer: {game.manufacturer}\n")
                if game.has_chd:
                    f.write(f"  CHDs: {', '.join(game.chd_names)}\n")
                f.write("\n")

            f.write("\nSKIPPED GAMES\n")
            f.write("-" * 60 + "\n")
            for desc, name, reason in sorted(skipped_games):
                f.write(f"{name}: {desc}\n")
                f.write(f"  Reason: {reason}\n\n")

    if not dry_run:
        print(f"{label}: Selection log written to {log_path}")

    return selected_roms, {'source_size': total_source_size, 'selected_size': selected_size}


# File extension to system mapping for auto-detection
EXTENSION_TO_SYSTEM = {
    # Nintendo - Consoles
    '.nes': 'nes',
    '.fds': 'fds',
    '.sfc': 'snes',
    '.smc': 'snes',
    '.gb': 'gameboy',
    '.gbc': 'gameboy-color',
    '.gba': 'gba',
    '.n64': 'n64',
    '.z64': 'n64',
    '.v64': 'n64',
    '.ndd': 'n64dd',
    '.gcm': 'gamecube',
    '.gcz': 'gamecube',
    '.rvz': 'gamecube',
    '.wbfs': 'wii',
    '.wia': 'wii',
    '.vb': 'virtualboy',
    '.nds': 'nds',
    '.dsi': 'nds',
    '.3ds': '3ds',
    '.cia': '3ds',
    '.nsp': 'switch',
    '.xci': 'switch',
    '.min': 'pokemini',
    # Sega - Consoles
    '.md': 'genesis',
    '.gen': 'genesis',
    '.smd': 'genesis',
    '.gg': 'gamegear',
    '.sms': 'mastersystem',
    '.sg': 'sg1000',
    '.sc': 'sc3000',
    '.32x': 'sega32x',
    '.cue': 'segacd',  # Also used by other CD systems
    '.gdi': 'dreamcast',
    '.cdi': 'dreamcast',
    '.chd': 'segacd',  # Generic CD format
    '.pco': 'segapico',
    # Sony
    '.pbp': 'psp',
    '.cso': 'psp',
    '.iso': 'psx',  # Ambiguous - also used by others
    # Atari - Consoles
    '.a26': 'atari2600',
    '.a52': 'atari5200',
    '.a78': 'atari7800',
    '.j64': 'atarijaguar',
    '.jag': 'atarijaguar',
    '.lnx': 'atarilynx',
    # Atari - Computers
    '.st': 'atarist',
    '.stx': 'atarist',
    '.xex': 'atari800',
    '.atr': 'atari800',
    '.a8': 'atari800',
    '.xfd': 'atari800',
    # NEC
    '.pce': 'tg16',
    '.sgx': 'tg16',
    # SNK
    '.neo': 'neogeo',
    '.ngp': 'ngp',
    '.ngc': 'ngpc',
    # Other Consoles
    '.col': 'colecovision',
    '.int': 'intellivision',
    '.vec': 'vectrex',
    '.ws': 'wonderswan',
    '.wsc': 'wonderswan-color',
    '.o2': 'odyssey2',
    '.bin': 'odyssey2',  # Also used by many systems
    '.ch8': 'chip8',
    '.3do': '3do',
    '.fcf': 'channelf',
    # Computers
    '.mx1': 'msx',
    '.mx2': 'msx2',
    '.cas': 'msx',
    '.dsk': 'amstradcpc',  # Also used by others
    '.cdt': 'amstradcpc',
    '.tzx': 'zxspectrum',
    '.tap': 'zxspectrum',
    '.z80': 'zxspectrum',
    '.sna': 'zxspectrum',
    '.d64': 'c64',
    '.t64': 'c64',
    '.prg': 'c64',
    '.crt': 'c64',
    '.g64': 'c64',
    '.d81': 'c64',
    '.adf': 'amiga',
    '.adz': 'amiga',
    '.ipf': 'amiga',
    '.hdf': 'amiga',
    '.lha': 'amiga',
    '.vz': 'vtech',
    '.rom': 'msx',
    # Handhelds
    '.sv': 'supervision',
    '.mgw': 'gameandwatch',
    # Arcade (folder-based mostly)
    # .zip is too generic
}

# Known system folder names (for folder-based detection)
KNOWN_SYSTEMS = [
    # Nintendo
    'nes', 'fds', 'snes', 'n64', 'n64dd', 'gamecube', 'wii', 'wiiu', 'switch',
    'gameboy', 'gameboy-color', 'gba', 'virtualboy', 'nds', 'dsi', '3ds', 'pokemini',
    'satellaview', 'sufami', 'ereader',
    # Sega
    'sg1000', 'sc3000', 'mastersystem', 'genesis', 'sega32x', 'segacd', 'saturn', 'dreamcast',
    'gamegear', 'segapico', 'beena',
    # Sony
    'psx', 'ps2', 'ps3', 'psp', 'psvita',
    # Microsoft
    'xbox', 'xbox360',
    # Atari
    'atari2600', 'atari5200', 'atari7800', 'atarijaguar', 'atarijaguarcd', 'atarilynx',
    'atari800', 'atari400', 'atarist',
    # NEC
    'tg16', 'tgcd', 'pcfx', 'supergrafx',
    # SNK
    'neogeo', 'neogeocdjapan', 'ngp', 'ngpc', 'neogeocd',
    # Other Consoles
    'colecovision', 'intellivision', 'vectrex', 'odyssey2', 'videopac', 'channelf',
    '3do', 'cdi', 'actionmax', 'astrocade', 'supervision',
    'loopy', 'pv1000', 'advision', 'superacan', 'studio2', 'gamecom',
    # Bandai
    'wonderswan', 'wonderswan-color',
    # Handhelds
    'gp32', 'gamemaster', 'pocketchallenge',
    # Educational
    'picno', 'leappad', 'leapster', 'creativision', 'vsmile',
    # Computers
    'msx', 'msx2', 'amstradcpc', 'zxspectrum', 'zx81',
    'c64', 'c128', 'plus4', 'vic20', 'amiga', 'amigacd32', 'cdtv',
    'atari800', 'atarist', 'x68000', 'pc88', 'pc98', 'sharp-x1',
    'apple2', 'bbc', 'dragon32', 'electron', 'oric', 'samcoupe', 'ti994a',
    'trs80', 'tandy', 'fm7', 'fmtowns', 'scv', 'enterprise', 'tvcomputer',
    # Arcade
    'mame', 'cps1', 'cps2', 'cps3', 'naomi', 'naomi2', 'atomiswave', 'model2', 'model3',
    'fba', 'fbneo', 'daphne',
    # Mobile
    'j2me', 'palmos', 'symbian', 'zeebo',
    # Misc
    'chip8', 'pico8', 'tic80', 'lowresnx', 'lutro', 'scummvm', 'dosbox',
    'gameandwatch', 'arduboy', 'uzebox', 'vtech', 'gamate', 'megaduck',
]

# Normalize folder names to standard system names
FOLDER_ALIASES = {
    # Nintendo
    'famicom': 'nes',
    'fc': 'nes',
    'nintendo': 'nes',
    'famicom-disk-system': 'fds',
    'famicon-disk-system': 'fds',
    'supernes': 'snes',
    'super-nes': 'snes',
    'superfamicom': 'snes',
    'super-famicom': 'snes',
    'sfc': 'snes',
    'super-nintendo': 'snes',
    'gb': 'gameboy',
    'game-boy': 'gameboy',
    'gbc': 'gameboy-color',
    'game-boy-color': 'gameboy-color',
    'gbcolor': 'gameboy-color',
    'game-boy-advance': 'gba',
    'gameboy-advance': 'gba',
    'gbadvance': 'gba',
    'nintendo64': 'n64',
    'nintendo-64': 'n64',
    '64dd': 'n64dd',
    'nintendo-64-dd': 'n64dd',
    'gc': 'gamecube',
    'ngc': 'gamecube',
    'nintendo-gamecube': 'gamecube',
    'nintendo-wii': 'wii',
    'wii-u': 'wiiu',
    'nintendo-switch': 'switch',
    'virtual-boy': 'virtualboy',
    'vboy': 'virtualboy',
    'nintendo-ds': 'nds',
    'ds': 'nds',
    'nintendo-dsi': 'dsi',
    'ndsi': 'dsi',
    'nintendo-3ds': '3ds',
    'new3ds': '3ds',
    'pokemon-mini': 'pokemini',
    # Sega
    'megadrive': 'genesis',
    'mega-drive': 'genesis',
    'md': 'genesis',
    'sega-genesis': 'genesis',
    'sega-mega-drive': 'genesis',
    'master-system': 'mastersystem',
    'sms': 'mastersystem',
    'sega-master-system': 'mastersystem',
    'game-gear': 'gamegear',
    'sega-game-gear': 'gamegear',
    'sega-32x': 'sega32x',
    '32x': 'sega32x',
    'megacd': 'segacd',
    'mega-cd': 'segacd',
    'sega-cd': 'segacd',
    'sega-saturn': 'saturn',
    'ss': 'saturn',
    'sega-dreamcast': 'dreamcast',
    'dc': 'dreamcast',
    'sega-sg-1000': 'sg1000',
    'sega-sc-3000': 'sc3000',
    'sega-pico': 'segapico',
    'pico': 'segapico',
    # Sony
    'playstation': 'psx',
    'ps1': 'psx',
    'psone': 'psx',
    'sony-playstation': 'psx',
    'sony - playstation': 'psx',  # Redump naming
    'playstation-2': 'ps2',
    'playstation2': 'ps2',
    'sony - playstation 2': 'ps2',  # Redump naming
    'playstation-3': 'ps3',
    'playstation3': 'ps3',
    'sony - playstation 3': 'ps3',  # Redump naming
    'playstation-portable': 'psp',
    'sony - playstation portable': 'psp',  # Redump naming
    'playstation-vita': 'psvita',
    'sony - playstation vita': 'psvita',  # Redump naming
    'vita': 'psvita',
    # NEC
    'turbografx16': 'tg16',
    'turbografx-16': 'tg16',
    'pcengine': 'tg16',
    'pc-engine': 'tg16',
    'pce': 'tg16',
    'turbografx-cd': 'tgcd',
    'pc-engine-cd': 'tgcd',
    'pcecd': 'tgcd',
    'pc-fx': 'pcfx',
    'super-grafx': 'supergrafx',
    # SNK
    'neo-geo': 'neogeo',
    'neogeo-aes': 'neogeo',
    'neogeo-mvs': 'neogeo',
    'neo-geo-cd': 'neogeocd',
    'neo-geo-pocket': 'ngp',
    'neogeo-pocket': 'ngp',
    'neo-geo-pocket-color': 'ngpc',
    'neogeo-pocket-color': 'ngpc',
    # Atari
    'atari-2600': 'atari2600',
    'vcs': 'atari2600',
    'atari-5200': 'atari5200',
    'atari-7800': 'atari7800',
    'atari-jaguar': 'atarijaguar',
    'jaguar': 'atarijaguar',
    'atari-jaguar-cd': 'atarijaguarcd',
    'jaguarcd': 'atarijaguarcd',
    'atari-lynx': 'atarilynx',
    'lynx': 'atarilynx',
    'atari-st': 'atarist',
    'atari-ste': 'atarist',
    'atari-800': 'atari800',
    'atari-400': 'atari800',
    'atari800xl': 'atari800',
    'atari-xe': 'atari800',
    # Computers
    'amstrad-cpc': 'amstradcpc',
    'cpc': 'amstradcpc',
    'zx-spectrum': 'zxspectrum',
    'spectrum': 'zxspectrum',
    'sinclair': 'zxspectrum',
    'zx-81': 'zx81',
    'commodore-64': 'c64',
    'commodore64': 'c64',
    'commodore-128': 'c128',
    'commodore128': 'c128',
    'commodore-vic20': 'vic20',
    'commodore-amiga': 'amiga',
    'amiga-cd32': 'amigacd32',
    'x68000': 'x68000',
    'sharp-x68000': 'x68000',
    'pc-88': 'pc88',
    'nec-pc88': 'pc88',
    'pc-98': 'pc98',
    'nec-pc98': 'pc98',
    'x1': 'sharp-x1',
    'apple-ii': 'apple2',
    'apple-iie': 'apple2',
    'bbc-micro': 'bbc',
    'acorn': 'bbc',
    'ti-99-4a': 'ti994a',
    'ti99': 'ti994a',
    'trs-80': 'trs80',
    'tandy-coco': 'tandy',
    'coco': 'tandy',
    'fm-towns': 'fmtowns',
    'fujitsu-fm-towns': 'fmtowns',
    'fm-7': 'fm7',
    'epoch-scv': 'scv',
    # Other
    'bandai-wonderswan': 'wonderswan',
    'bandai-wonderswan-color': 'wonderswan-color',
    'wonderswancolor': 'wonderswan-color',
    'wsc': 'wonderswan-color',
    'channel-f': 'channelf',
    'fairchild': 'channelf',
    'fairchild-channel-f': 'channelf',
    'magnavox-odyssey2': 'odyssey2',
    'philips-videopac': 'videopac',
    'videopac-plus': 'videopac',
    'philips-cdi': 'cdi',
    'philips-cd-i': 'cdi',
    'panasonic-3do': '3do',
    'bally-astrocade': 'astrocade',
    'watara-supervision': 'supervision',
    # Arcade
    'arcade': 'mame',
    'capcom-cps1': 'cps1',
    'capcom-cps2': 'cps2',
    'capcom-cps3': 'cps3',
    'sega-naomi': 'naomi',
    'sega-naomi2': 'naomi2',
    'sega-naomi-2': 'naomi2',
    'sega-model2': 'model2',
    'sega-model3': 'model3',
    'final-burn-alpha': 'fba',
    'finalburn-neo': 'fbneo',
    # Fantasy/Modern
    'pico-8': 'pico8',
    'tic-80': 'tic80',
    'game-and-watch': 'gameandwatch',
    # Nintendo add-ons
    'bs-x': 'satellaview',
    'bsx': 'satellaview',
    'nintendo-satellaview': 'satellaview',
    'sufami-turbo': 'sufami',
    'nintendo-sufami': 'sufami',
    'e-reader': 'ereader',
    'nintendo-e-reader': 'ereader',
    # Sega
    'sega-beena': 'beena',
    # Obscure consoles
    'casio-loopy': 'loopy',
    'casio-pv1000': 'pv1000',
    'casio-pv-1000': 'pv1000',
    'entex-adventure-vision': 'advision',
    'adventure-vision': 'advision',
    'funtech-super-acan': 'superacan',
    'super-acan': 'superacan',
    'rca-studio-ii': 'studio2',
    'rca-studio2': 'studio2',
    'tiger-gamecom': 'gamecom',
    'game-com': 'gamecom',
    'super-cassette-vision': 'scv',
    # Handhelds
    'gamepark-gp32': 'gp32',
    'hartung-game-master': 'gamemaster',
    'benesse-pocket-challenge': 'pocketchallenge',
    'pocket-challenge-v2': 'pocketchallenge',
    # Educational
    'konami-picno': 'picno',
    'leapfrog-leappad': 'leappad',
    'leapfrog-leapster': 'leapster',
    'vtech-creativision': 'creativision',
    'vtech-vsmile': 'vsmile',
    'v-smile': 'vsmile',
    # Computers
    'commodore-plus4': 'plus4',
    'commodore-plus-4': 'plus4',
    'c16': 'plus4',
    'enterprise-128': 'enterprise',
    'enterprise128': 'enterprise',
    'videoton-tvc': 'tvcomputer',
    'videoton-tv-computer': 'tvcomputer',
    # Mobile
    'java-me': 'j2me',
    'java-mobile': 'j2me',
    'palm': 'palmos',
}


def detect_system_from_extension(filename: str) -> Optional[str]:
    """Detect system type from file extension."""
    # Check direct file extension
    ext = Path(filename).suffix.lower()
    if ext in EXTENSION_TO_SYSTEM:
        return EXTENSION_TO_SYSTEM[ext]

    # For archives, try to detect from filename patterns or inner extension
    if ext in ('.zip', '.7z', '.rar'):
        # Check if filename contains extension hint before archive extension
        # e.g., "Game Name.nes.zip" or "Game Name [!].sfc.7z"
        name_without_archive = filename[:-len(ext)]
        inner_ext_match = re.search(r'\.([a-z0-9]{2,4})$', name_without_archive, re.IGNORECASE)
        if inner_ext_match:
            inner_ext = '.' + inner_ext_match.group(1).lower()
            if inner_ext in EXTENSION_TO_SYSTEM:
                return EXTENSION_TO_SYSTEM[inner_ext]

    return None


def detect_system_from_folder(folder_name: str) -> str:
    """Normalize folder name to standard system name."""
    name = folder_name.lower().strip()
    if name in FOLDER_ALIASES:
        return FOLDER_ALIASES[name]
    return name


def scan_for_systems(source_dir: str) -> dict:
    """Scan source directory and detect available systems.

    Returns dict mapping system name to list of ROM files.
    Supports both folder-based organization and flat directories.
    """
    source_path = Path(source_dir)
    systems = defaultdict(list)

    # Check if source has system subdirectories
    subdirs = [d for d in source_path.iterdir() if d.is_dir() and not d.name.startswith('_')]

    if subdirs:
        # Folder-based organization
        for subdir in subdirs:
            system = detect_system_from_folder(subdir.name)
            for f in subdir.iterdir():
                if f.is_file() and f.suffix.lower() in ('.zip', '.7z', '.rar', '.sfc', '.smc', '.nes',
                    '.gb', '.gbc', '.gba', '.n64', '.z64', '.v64', '.md', '.gen', '.sms', '.gg',
                    '.pce', '.col', '.a26', '.a52', '.a78', '.j64', '.jag', '.lnx', '.vb', '.ws',
                    '.wsc', '.mx1', '.mx2', '.32x', '.sg', '.vec', '.int', '.st', '.gcm'):
                    systems[system].append(f)

    # Also check for ROMs directly in source directory (flat structure)
    for f in source_path.iterdir():
        if f.is_file():
            detected = detect_system_from_extension(f.name)
            if detected:
                systems[detected].append(f)

    return dict(systems)


def filter_roms_from_files(rom_files: list, dest_dir: str, system: str, dry_run: bool = False,
                           dat_entries: Dict[str, DatRomEntry] = None,
                           include_patterns: List[str] = None,
                           exclude_patterns: List[str] = None,
                           exclude_protos: bool = False,
                           include_betas: bool = False,
                           include_unlicensed: bool = False,
                           region_priority: List[str] = None,
                           keep_regions: List[str] = None,
                           flat_output: bool = False,
                           transfer_mode: str = 'copy',
                           year_from: int = None,
                           year_to: int = None,
                           verbose: bool = False):
    """Filter ROMs from a list of file paths.

    If dat_entries is provided, uses DAT metadata to enhance/override filename parsing.
    """
    if flat_output:
        dest_path = Path(dest_dir)
    else:
        dest_path = Path(dest_dir) / system

    if region_priority is None:
        region_priority = DEFAULT_REGION_PRIORITY

    # Build CRC lookup if using DAT
    crc_to_dat = dat_entries or {}
    dat_matched = 0

    # Parse all ROMs
    all_roms = []
    file_map = {}  # Map filename to full path
    size_map = {}  # Map filename to file size
    filtered_by_pattern = 0
    total_source_size = 0

    for filepath in tqdm(rom_files, desc=f"{system.upper()} Parsing", unit="ROM", leave=False):
        if _shutdown_requested:
            break
        filename = filepath.name

        # Apply include/exclude patterns
        if include_patterns and not matches_patterns(filename, include_patterns):
            filtered_by_pattern += 1
            if verbose:
                print(f"  [SKIP] {filename}: doesn't match include patterns")
            continue
        if exclude_patterns and matches_patterns(filename, exclude_patterns):
            filtered_by_pattern += 1
            if verbose:
                print(f"  [SKIP] {filename}: matches exclude pattern")
            continue

        rom_info = parse_rom_filename(filename)

        # Filter by proto/beta/unlicensed unless explicitly included
        if rom_info.is_proto and exclude_protos:
            if verbose:
                print(f"  [SKIP] {filename}: prototype (excluded via --exclude-protos)")
            continue
        if rom_info.is_beta and not include_betas:
            if verbose:
                print(f"  [SKIP] {filename}: beta (use --include-betas to include)")
            continue
        if rom_info.is_unlicensed and not include_unlicensed:
            if verbose:
                print(f"  [SKIP] {filename}: unlicensed (use --include-unlicensed to include)")
            continue

        # Filter by year if specified (only if year is known)
        if rom_info.year > 0:
            if year_from and rom_info.year < year_from:
                if verbose:
                    print(f"  [SKIP] {filename}: year {rom_info.year} < {year_from}")
                continue
            if year_to and rom_info.year > year_to:
                if verbose:
                    print(f"  [SKIP] {filename}: year {rom_info.year} > {year_to}")
                continue

        # Try to enhance with DAT metadata
        if crc_to_dat:
            crc = None
            if filepath.suffix.lower() == '.zip':
                crc = calculate_crc32_from_zip(filepath)
            else:
                crc = calculate_crc32(filepath)

            if crc and crc in crc_to_dat:
                dat_entry = crc_to_dat[crc]
                # Override region from DAT if available
                if dat_entry.region != 'Unknown':
                    rom_info.region = dat_entry.region
                # Note: Don't override base_title with dat_entry.name as it includes
                # region/extension (e.g., "Game (USA).nes") which breaks grouping
                dat_matched += 1

        all_roms.append(rom_info)
        file_map[filename] = filepath
        file_size = get_file_size(filepath)
        size_map[filename] = file_size
        total_source_size += file_size

    print(f"\n{system.upper()}: Found {len(all_roms)} total ROMs ({format_size(total_source_size)})")
    if filtered_by_pattern:
        print(f"{system.upper()}: {filtered_by_pattern} filtered by include/exclude patterns")
    if dat_entries:
        print(f"{system.upper()}: {dat_matched} ROMs matched to DAT entries")

    # Group by normalized title
    grouped = defaultdict(list)
    for rom in all_roms:
        normalized = normalize_title(rom.base_title)
        grouped[normalized].append(rom)

    print(f"{system.upper()}: Found {len(grouped)} unique game titles")

    # Select best ROM from each group (or multiple if keep_regions)
    selected_roms = []
    skipped_games = []

    for title, roms in grouped.items():
        if keep_regions:
            # Keep one ROM per requested region
            for region in keep_regions:
                region_roms = [r for r in roms if r.region.lower() == region.lower()]
                if region_roms:
                    best = select_best_rom(region_roms, region_priority)
                    if best:
                        selected_roms.append(best)
                        if verbose:
                            print(f"  [SELECT] {best.filename} ({region} version of '{title}')")
            # If no regions matched, fall back to best overall
            if not any(r in selected_roms for r in roms):
                best = select_best_rom(roms, region_priority)
                if best:
                    selected_roms.append(best)
                    if verbose:
                        print(f"  [SELECT] {best.filename} (fallback for '{title}')")
        else:
            best = select_best_rom(roms, region_priority)
            if best:
                selected_roms.append(best)
                if verbose:
                    candidates = len(roms)
                    print(f"  [SELECT] {best.filename} (best of {candidates} for '{title}')")
            else:
                sample = roms[0].filename if roms else "unknown"
                skipped_games.append((title, sample))
                if verbose:
                    print(f"  [SKIP] No suitable ROM for '{title}' (sample: {sample})")

    # Calculate selected size
    selected_size = sum(size_map.get(rom.filename, 0) for rom in selected_roms)
    size_saved = total_source_size - selected_size

    print(f"{system.upper()}: Selected {len(selected_roms)} ROMs ({format_size(selected_size)})")
    if total_source_size > 0:
        reduction_pct = (size_saved / total_source_size) * 100
        print(f"{system.upper()}: Size reduction: {format_size(size_saved)} saved ({reduction_pct:.1f}%)")

    if dry_run:
        return selected_roms, {'source_size': total_source_size, 'selected_size': selected_size}

    # Create destination directory (clear existing files first for non-flat)
    if not flat_output:
        if dest_path.exists():
            for old_file in dest_path.iterdir():
                if old_file.is_file():
                    old_file.unlink()
    dest_path.mkdir(parents=True, exist_ok=True)

    # Transfer selected ROMs
    copied = 0
    action_verb = {'copy': 'Copying', 'link': 'Linking', 'hardlink': 'Hardlinking', 'move': 'Moving'}
    for rom in tqdm(selected_roms, desc=f"{system.upper()} {action_verb.get(transfer_mode, 'Copying')}", unit="ROM", leave=False):
        if _shutdown_requested:
            break
        src = file_map.get(rom.filename)
        if src and src.exists():
            dst = dest_path / rom.filename
            transfer_file(src, dst, transfer_mode)
            copied += 1

    action_past = {'copy': 'Copied', 'link': 'Linked', 'hardlink': 'Hardlinked', 'move': 'Moved'}
    print(f"\n{system.upper()}: {action_past.get(transfer_mode, 'Copied')} {copied} ROMs to {dest_path}")

    # Write selection log
    log_path = dest_path / "_selection_log.txt"
    with open(log_path, 'w', encoding='utf-8') as f:
        f.write(f"ROM Selection Log for {system.upper()}\n")
        f.write("=" * 60 + "\n\n")
        f.write(f"Total ROMs scanned: {len(all_roms)}\n")
        f.write(f"Unique games found: {len(grouped)}\n")
        f.write(f"ROMs selected: {len(selected_roms)}\n\n")
        f.write(f"Source size: {format_size(total_source_size)}\n")
        f.write(f"Selected size: {format_size(selected_size)}\n")
        f.write(f"Size saved: {format_size(size_saved)}\n\n")

        f.write("SELECTED ROMS:\n")
        f.write("-" * 60 + "\n")
        for rom in sorted(selected_roms, key=lambda r: r.base_title.lower()):
            f.write(f"{rom.filename}\n")
            f.write(f"  Title: {rom.base_title}\n")
            f.write(f"  Region: {rom.region}, Rev: {rom.revision}")
            if rom.is_translation:
                f.write(f", Translation: Yes")
            if rom.is_proto:
                f.write(f", Prototype: Yes")
            f.write("\n\n")

        if skipped_games:
            f.write("\n\nSKIPPED GAMES (no suitable English version found):\n")
            f.write("-" * 60 + "\n")
            for title, sample in sorted(skipped_games):
                f.write(f"{title}\n  Sample: {sample}\n\n")

    print(f"{system.upper()}: Selection log written to {log_path}")

    return selected_roms, {'source_size': total_source_size, 'selected_size': selected_size}


def main():
    """Main entry point."""
    # Show header
    print(r"""
   ___  ___ _____  ___  ___        ___  ___ ___ ___ _  _ ___ ___
  | _ \| __|_   _|| _ \/ _ \  ___ | _ \| __| __|_ _| \| | __| _ \
  |   /| _|  | |  |   / (_) ||___||   /| _|| _| | || .` | _||   /
  |_|_\|___| |_|  |_|_\\___/      |_|_\|___|_| |___|_|\_|___|_|_\
  ─────────────────────────────────────────────────────────────────
             R E F I N E   Y O U R   C O L L E C T I O N
""", flush=True)

    import argparse

    parser = argparse.ArgumentParser(
        description='Retro-Refiner - Refine your ROM collection down to the essentials',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s -s https://archive.example.com/roms/   # Fetch from network archive
  %(prog)s -s https://archive.example.com/roms/ --commit  # Download selected ROMs
  %(prog)s -s /local/roms -s https://example.com/roms/    # Mix local and network
  %(prog)s -s /path/to/roms          # Filter local ROM collection
  %(prog)s -s ./roms -d ./filtered   # Specify source and destination
  %(prog)s --systems nes snes gba    # Process only specific systems
  %(prog)s -v                        # Verbose output (show filtering decisions)

Pattern examples (--include / --exclude):
  --include "*Plumber*"              # Games with "Plumber" in the name
  --include "*Plumber*" --include "*Quest*" --include "*Hunter*"  # Multiple patterns
  --include "*(USA)*"                # Only USA region
  --include "Super *"                # Games starting with "Super"
  --exclude "*Beta*" --exclude "*Proto*"  # Exclude betas and prototypes
  --exclude "*(Japan)*"              # Exclude Japan-only releases
        """
    )
    parser.add_argument('--source', '-s', action='append', default=None,
                        help='Source ROM directory (can specify multiple times)')
    parser.add_argument('--dest', '-d', default=None,
                        help='Destination directory (default: refined/ in script dir)')
    parser.add_argument('--systems', '-y', nargs='+', default=None,
                        help='Systems to process (default: auto-detect from folders)')
    parser.add_argument('--auto-detect', '-a', action='store_true',
                        help='Auto-detect systems from file extensions (for flat directories)')
    parser.add_argument('--commit', '-c', action='store_true',
                        help='Actually transfer files (default is dry run which only shows what would be selected)')
    parser.add_argument('--config', default=None,
                        help='Path to config file (default: retro-refiner.yaml in source dir)')
    parser.add_argument('--list-systems', action='store_true',
                        help='List all known system names and exit')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Show detailed output during processing')

    # File operation modes (mutually exclusive)
    op_group = parser.add_mutually_exclusive_group()
    op_group.add_argument('--link', action='store_true',
                        help='Create symbolic links instead of copying')
    op_group.add_argument('--hardlink', action='store_true',
                        help='Create hard links instead of copying')
    op_group.add_argument('--move', action='store_true',
                        help='Move files instead of copying')

    # Output structure
    parser.add_argument('--flat', action='store_true',
                        help='Output all ROMs to a single folder (no system subfolders)')

    # Region handling
    parser.add_argument('--region-priority', default=None,
                        help='Custom region priority order (comma-separated, e.g., "USA,Europe,Japan")')
    parser.add_argument('--keep-regions', default=None,
                        help='Keep multiple regional versions (comma-separated, e.g., "USA,Japan")')

    # Inclusion filters
    parser.add_argument('--include', action='append', default=None,
                        help='Include only ROMs matching pattern (glob-style, can specify multiple)')
    parser.add_argument('--exclude', action='append', default=None,
                        help='Exclude ROMs matching pattern (glob-style, can specify multiple)')
    parser.add_argument('--exclude-protos', action='store_true',
                        help='Exclude prototype ROMs (included by default)')
    parser.add_argument('--include-betas', action='store_true',
                        help='Include beta ROMs (excluded by default)')
    parser.add_argument('--include-unlicensed', action='store_true',
                        help='Include unlicensed/pirate ROMs (excluded by default)')

    # Metadata filtering
    parser.add_argument('--genres', default=None,
                        help='Filter by genre (comma-separated, e.g., "platformer,rpg")')
    parser.add_argument('--year-from', type=int, default=None,
                        help='Include only ROMs from this year or later')
    parser.add_argument('--year-to', type=int, default=None,
                        help='Include only ROMs up to this year')

    # Export options
    parser.add_argument('--playlists', action='store_true',
                        help='Generate M3U playlists for each system')
    parser.add_argument('--gamelist', action='store_true',
                        help='Generate EmulationStation gamelist.xml files')
    parser.add_argument('--retroarch-playlists', default=None,
                        help='Generate Retroarch .lpl playlists to specified directory')

    # Multi-source options
    parser.add_argument('--prefer-source', default=None,
                        help='Prefer ROMs from this source directory when duplicates exist')

    # DAT and verification
    parser.add_argument('--mame-version', default=None,
                        help='MAME version for downloads (e.g., 0.274). Default: auto-detect latest')
    parser.add_argument('--no-chd', action='store_true',
                        help='Skip copying CHD files for MAME (saves space)')
    parser.add_argument('--no-adult', action='store_true',
                        help='Exclude adult/mature MAME games (included by default)')
    parser.add_argument('--no-verify', action='store_true',
                        help='Skip ROM verification against DAT files')
    parser.add_argument('--no-dat', action='store_true',
                        help='Use filename parsing instead of DAT metadata')
    parser.add_argument('--update-dats', action='store_true',
                        help='Delete and re-download all DAT files, then exit (no ROM processing)')
    parser.add_argument('--clean', action='store_true',
                        help='Delete cache, DAT files, and other generated data, then exit')
    parser.add_argument('--dat-dir', default=None,
                        help='Directory for all DAT files (default: <source>/dat_files/)')
    parser.add_argument('--cache-dir', default=None,
                        help='Directory for caching network downloads (default: <source>/cache/)')
    parser.add_argument('--parallel', '-p', type=int, default=4,
                        help='Number of parallel downloads for network sources (default: 4). '
                             'With aria2c, also sets connections per file for large downloads.')

    args = parser.parse_args()

    # List systems mode
    if args.list_systems:
        print("Known system names:")
        for system in sorted(set(KNOWN_SYSTEMS)):
            print(f"  {system}")
        print("\nFolder name aliases:")
        for alias, system in sorted(FOLDER_ALIASES.items()):
            print(f"  {alias} -> {system}")
        print("\nFile extension mappings:")
        ext_systems = defaultdict(list)
        for ext, system in EXTENSION_TO_SYSTEM.items():
            ext_systems[system].append(ext)
        for system, exts in sorted(ext_systems.items()):
            print(f"  {system}: {', '.join(sorted(exts))}")
        return

    # Update DATs mode - standalone operation
    if args.update_dats:
        print("=" * 60)
        print("UPDATING DAT FILES")
        print("=" * 60)

        # Determine DAT directory
        if args.dat_dir:
            dat_dir = Path(args.dat_dir).resolve()
        elif args.source and not is_url(args.source[0]):
            dat_dir = Path(args.source[0]).resolve() / 'dat_files'
        else:
            dat_dir = Path('.').resolve() / 'dat_files'

        print(f"DAT directory: {dat_dir}")
        dat_dir.mkdir(parents=True, exist_ok=True)

        # Delete all existing DAT files
        existing_dats = list(dat_dir.glob('*.dat')) + list(dat_dir.glob('*.xml')) + list(dat_dir.glob('*.ini'))
        if existing_dats:
            print(f"\nRemoving {len(existing_dats)} existing DAT files...")
            for dat_file in existing_dats:
                print(f"  Deleting: {dat_file.name}")
                dat_file.unlink()

        # Download all libretro DATs
        print(f"\n--- Downloading No-Intro DATs ({len(LIBRETRO_DAT_SYSTEMS)} systems) ---")
        downloaded = 0
        failed = 0
        for system in sorted(LIBRETRO_DAT_SYSTEMS.keys()):
            result = download_libretro_dat(system, dat_dir, force=True)
            if result:
                downloaded += 1
            else:
                failed += 1

        print(f"\nNo-Intro DATs: {downloaded} downloaded, {failed} failed")

        # Download MAME data
        print("\n--- Downloading MAME Data ---")
        catver_path, mame_dat_path = download_mame_data(dat_dir, version=args.mame_version, force=True)

        if catver_path and mame_dat_path:
            print("MAME data: Downloaded successfully")
        else:
            print("MAME data: Some files failed to download")

        # Summary
        final_dats = list(dat_dir.glob('*.dat')) + list(dat_dir.glob('*.xml')) + list(dat_dir.glob('*.ini'))
        print("\n" + "=" * 60)
        print(f"DAT UPDATE COMPLETE: {len(final_dats)} files in {dat_dir}")
        print("=" * 60)
        return

    # Clean mode - delete generated data
    if args.clean:
        print("=" * 60)
        print("CLEANING GENERATED DATA")
        print("=" * 60)

        # Determine base directory
        if args.source and not is_url(args.source[0]):
            base_dir = Path(args.source[0]).resolve()
        else:
            base_dir = Path('.').resolve()

        # Determine directories to clean
        dat_dir = Path(args.dat_dir).resolve() if args.dat_dir else base_dir / 'dat_files'
        cache_dir = Path(args.cache_dir).resolve() if args.cache_dir else base_dir / 'cache'

        cleaned_count = 0
        cleaned_size = 0

        # Clean DAT directory
        if dat_dir.exists():
            dat_files = list(dat_dir.glob('**/*'))
            dat_files = [f for f in dat_files if f.is_file()]
            if dat_files:
                print(f"\nDAT directory: {dat_dir}")
                for f in dat_files:
                    size = f.stat().st_size
                    cleaned_size += size
                    cleaned_count += 1
                    f.unlink()
                print(f"  Deleted {len(dat_files)} files")
                # Remove empty directories
                for d in sorted(dat_dir.glob('**/*'), reverse=True):
                    if d.is_dir() and not any(d.iterdir()):
                        d.rmdir()
                if dat_dir.exists() and not any(dat_dir.iterdir()):
                    dat_dir.rmdir()
                    print(f"  Removed directory")

        # Clean cache directory
        if cache_dir.exists():
            cache_files = list(cache_dir.glob('**/*'))
            cache_files = [f for f in cache_files if f.is_file()]
            if cache_files:
                print(f"\nCache directory: {cache_dir}")
                for f in cache_files:
                    size = f.stat().st_size
                    cleaned_size += size
                    cleaned_count += 1
                    f.unlink()
                print(f"  Deleted {len(cache_files)} files")
                # Remove empty directories
                for d in sorted(cache_dir.glob('**/*'), reverse=True):
                    if d.is_dir() and not any(d.iterdir()):
                        d.rmdir()
                if cache_dir.exists() and not any(cache_dir.iterdir()):
                    cache_dir.rmdir()
                    print(f"  Removed directory")

        # Summary
        print("\n" + "=" * 60)
        if cleaned_count > 0:
            size_str = f"{cleaned_size / 1024 / 1024:.1f} MB" if cleaned_size > 1024*1024 else f"{cleaned_size / 1024:.1f} KB"
            print(f"CLEAN COMPLETE: Removed {cleaned_count} files ({size_str})")
        else:
            print("CLEAN COMPLETE: No generated data found")
        print("=" * 60)
        return

    # Handle source directories (default to current directory)
    if args.source is None:
        args.source = ['.']

    # Separate local paths from network URLs
    local_sources = []
    network_sources = []
    for s in args.source:
        if is_url(s):
            network_sources.append(s)
        else:
            local_sources.append(Path(s).resolve())

    # Primary source is first local source, or current directory if all network
    if local_sources:
        primary_source = local_sources[0]
    else:
        primary_source = Path('.').resolve()

    # Set up cache directory for network sources
    if args.cache_dir:
        cache_dir = Path(args.cache_dir).resolve()
    else:
        cache_dir = primary_source / 'cache'

    # For backward compatibility
    source_paths = local_sources

    # Validate all sources are accessible before proceeding
    if network_sources:
        print("Validating sources...")
    source_errors = validate_all_sources(local_sources, network_sources)
    if source_errors:
        print("\n" + "=" * 60)
        print("ERROR: One or more sources could not be accessed")
        print("=" * 60)
        for source, error in source_errors:
            print(f"  ✗ {source}")
            print(f"    {error}")
        print("\nPlease check your source paths/URLs and try again.")
        sys.exit(1)

    # Load config file
    if args.config:
        config_path = Path(args.config)
    else:
        # Look for config in primary source directory
        config_path = primary_source / 'retro-refiner.yaml'
        if not config_path.exists():
            json_config = primary_source / 'retro-refiner.json'
            if json_config.exists():
                config_path = json_config
            else:
                # Generate default config file on first run
                print(f"Creating default config file: {config_path}")
                generate_default_config(config_path)

    config = load_config(config_path) if config_path.exists() else {}
    if config:
        print(f"Loaded config from: {config_path}")
        apply_config_to_args(args, config)

    # Set default destination (refined/ subfolder where script is located)
    if args.dest is None:
        script_dir = Path(__file__).parent.resolve()
        args.dest = str(script_dir / "refined")

    # Parse region priority
    if args.region_priority:
        region_priority = [r.strip() for r in args.region_priority.split(',')]
    else:
        region_priority = DEFAULT_REGION_PRIORITY

    # Parse keep regions
    keep_regions = None
    if args.keep_regions:
        keep_regions = [r.strip() for r in args.keep_regions.split(',')]

    # Parse genres
    genre_filter = None
    if args.genres:
        genre_filter = [g.strip().lower() for g in args.genres.split(',')]

    # Determine file transfer mode
    if args.link:
        transfer_mode = 'link'
    elif args.hardlink:
        transfer_mode = 'hardlink'
    elif args.move:
        transfer_mode = 'move'
    else:
        transfer_mode = 'copy'

    if len(source_paths) > 1:
        print(f"Sources: {', '.join(str(p) for p in source_paths)}")
    else:
        print(f"Source: {primary_source}")
    print(f"Destination: {args.dest}")

    # Default behaviors (inverted from args)
    dry_run = not args.commit
    verify = not args.no_verify
    use_dat = not args.no_dat

    # If using network sources, default to no verification (can't verify without downloading first)
    has_network_sources = len(network_sources) > 0
    if has_network_sources and not args.no_verify:
        print("Note: Verification disabled for network sources (files filtered before download)")
        verify = False

    # Show active options
    options = []
    if args.flat:
        options.append("flat output")
    if transfer_mode != 'copy':
        options.append(f"mode: {transfer_mode}")
    if keep_regions:
        options.append(f"keep regions: {','.join(keep_regions)}")
    if args.include:
        options.append(f"include: {args.include}")
    if args.exclude:
        options.append(f"exclude: {args.exclude}")
    if args.exclude_protos:
        options.append("exclude protos")
    if args.include_betas:
        options.append("include betas")
    if args.include_unlicensed:
        options.append("include unlicensed")
    if genre_filter:
        options.append(f"genres: {','.join(genre_filter)}")
    if args.year_from or args.year_to:
        year_range = f"{args.year_from or '...'}-{args.year_to or '...'}"
        options.append(f"years: {year_range}")
    if options:
        print(f"Options: {', '.join(options)}")

    if dry_run:
        print("\n*** DRY RUN - No files will be copied, moved, linked, or downloaded ***")
        print("*** Use --commit to actually transfer files ***\n")

    # Detect available systems from all source directories
    detected = defaultdict(list)
    rom_sources = {}  # Track which source each ROM came from

    for source_path in source_paths:
        if args.auto_detect or args.systems is None:
            source_detected = scan_for_systems(str(source_path))

            if args.systems:
                # Filter to only requested systems
                source_detected = {k: v for k, v in source_detected.items() if k in args.systems}

            for system, files in source_detected.items():
                for f in files:
                    # Track source and handle duplicates
                    if f.name not in [x.name for x in detected[system]]:
                        detected[system].append(f)
                        rom_sources[str(f)] = source_path
                    elif args.prefer_source and str(source_path) == args.prefer_source:
                        # Replace with preferred source
                        detected[system] = [x for x in detected[system] if x.name != f.name]
                        detected[system].append(f)
                        rom_sources[str(f)] = source_path
        else:
            # Use specified systems with folder-based organization
            for system in args.systems:
                system_dir = source_path / system
                if system_dir.exists():
                    rom_files = [f for f in system_dir.iterdir()
                                if f.is_file() and f.suffix.lower() in
                                ('.zip', '.7z', '.rar', '.sfc', '.smc', '.nes', '.gb', '.gbc',
                                 '.gba', '.n64', '.z64', '.v64', '.md', '.gen', '.sms', '.gg',
                                 '.pce', '.col', '.a26', '.a52', '.a78', '.j64', '.jag', '.lnx',
                                 '.vb', '.ws', '.wsc', '.mx1', '.mx2', '.32x', '.sg', '.vec',
                                 '.int', '.st', '.gcm')]
                    for f in rom_files:
                        if f.name not in [x.name for x in detected[system]]:
                            detected[system].append(f)
                            rom_sources[str(f)] = source_path
                        elif args.prefer_source and str(source_path) == args.prefer_source:
                            detected[system] = [x for x in detected[system] if x.name != f.name]
                            detected[system].append(f)
                            rom_sources[str(f)] = source_path

    # Process network sources with optimized filter-before-download flow
    # Step 1: Scan ALL network sources first to collect URLs (no filtering yet)
    all_network_urls = defaultdict(list)  # {system: [urls from all sources]}
    all_url_sizes = {}  # {url: size}
    url_to_source = {}  # {url: network_url} - track which source each URL came from
    empty_network_sources = []

    for network_url in network_sources:
        check_shutdown()
        print()  # Blank line before network source

        # Scan for URLs only (no downloading yet)
        url_dict, url_sizes = scan_network_source_urls(network_url, args.systems)

        # Check if this source returned any ROMs at all
        total_urls_from_source = sum(len(urls) for urls in url_dict.values())
        if total_urls_from_source == 0:
            empty_network_sources.append(network_url)

        # Collect URLs from all sources per system
        for system, urls in url_dict.items():
            for url in urls:
                all_network_urls[system].append(url)
                url_to_source[url] = network_url
            all_url_sizes.update(url_sizes)

    # Step 2: Filter combined URL pool per system (select best ROM across ALL sources)
    network_downloads = {}  # {system: [selected_urls]}
    total_network_files = 0
    total_network_source_size = 0
    total_network_selected_size = 0
    network_system_stats = {}

    for system, urls in all_network_urls.items():
        if not urls:
            continue

        print(f"\n{system.upper()}: Filtering {len(urls)} remote ROMs from {len(network_sources)} source(s)...")

        # Filter URLs using filter_network_roms (handles patterns, flags, and best ROM selection)
        # This now selects the BEST ROM across ALL sources for each game
        filtered_urls, size_info = filter_network_roms(
            urls, system,
            include_patterns=args.include,
            exclude_patterns=args.exclude,
            exclude_protos=args.exclude_protos,
            include_betas=args.include_betas,
            include_unlicensed=args.include_unlicensed,
            region_priority=region_priority,
            keep_regions=keep_regions,
            year_from=args.year_from,
            year_to=args.year_to,
            verbose=args.verbose,
            url_sizes=all_url_sizes
        )

        if filtered_urls:
            network_downloads[system] = filtered_urls
            total_network_files += len(filtered_urls)
            network_system_stats[system] = {
                'source_size': size_info['source_size'],
                'selected_size': size_info['selected_size']
            }
            total_network_source_size += size_info['source_size']
            total_network_selected_size += size_info['selected_size']
        else:
            print(f"{system.upper()}: No ROMs remaining after filtering")

    # Check if any network sources returned no ROMs
    if empty_network_sources:
        # If ALL network sources are empty and there are no local sources with ROMs, fail
        has_local_roms = bool(detected)
        if len(empty_network_sources) == len(network_sources) and not has_local_roms:
            print("\n" + "=" * 60)
            print("ERROR: Network source(s) returned no ROM files")
            print("=" * 60)
            for src in empty_network_sources:
                print(f"  ✗ {src}")
            print("\nPossible causes:")
            print("  • URL points to an empty directory")
            print("  • URL points to a page without ROM download links")
            print("  • ROM files use unrecognized extensions")
            print("  • The page format is not supported for scraping")
            sys.exit(1)
        else:
            # Just warn about empty sources if we have other data
            print("\nWarning: The following source(s) returned no ROM files:")
            for src in empty_network_sources:
                print(f"  • {src}")

    # Show download summary and prompt for confirmation (only when actually downloading)
    if total_network_files > 0:
        if dry_run:
            # In dry run mode, skip downloads entirely
            network_downloads = {}
        else:
            # Show download summary only when committing
            print("\n" + "=" * 60)
            print("NETWORK DOWNLOAD SUMMARY")
            print("=" * 60)

            for system, urls in sorted(network_downloads.items()):
                # Check how many are already cached
                cached_count = 0
                for url in urls:
                    filename = get_filename_from_url(url)
                    url_clean = url.split('?')[0].split('#')[0]
                    url_path = url_clean.replace('://', '/').split('/', 1)[1] if '://' in url_clean else url_clean
                    path_parts = [p for p in url_path.split('/') if p]
                    subdir = path_parts[-2] if len(path_parts) >= 2 else 'misc'
                    cached_path = cache_dir / subdir / filename
                    if cached_path.exists():
                        cached_count += 1

                new_count = len(urls) - cached_count
                sys_size = network_system_stats.get(system, {}).get('selected_size', 0)
                size_str = f" ({format_size(sys_size)})" if sys_size > 0 else ""
                if cached_count > 0:
                    print(f"  {system}: {len(urls)} files{size_str} ({cached_count} cached, {new_count} to download)")
                else:
                    print(f"  {system}: {len(urls)} files{size_str} to download")

            if total_network_selected_size > 0:
                print(f"\nTotal: {total_network_files} files ({format_size(total_network_selected_size)})")
            else:
                print(f"\nTotal: {total_network_files} files")
            print(f"Cache directory: {cache_dir}")

            # Show download tool info
            tool = get_download_tool()
            if tool == 'aria2c':
                print(f"Download tool: aria2c ({args.parallel} parallel, {args.parallel} connections/file)")
            elif tool == 'curl':
                print(f"Download tool: curl ({args.parallel} parallel)")
            else:
                print("Download tool: Python urllib (sequential)")
            print("=" * 60)

    # Step 3: Download the selected files (best ROM per game across all sources)
    for system, filtered_urls in network_downloads.items():
        if not filtered_urls:
            continue

        print(f"\n{system.upper()}: Downloading {len(filtered_urls)} ROMs...")

        # Use batch downloading for connection reuse and parallelism
        with tqdm(total=len(filtered_urls), desc=f"  {system.upper()} Downloading", unit="file", leave=False) as pbar:
            cached_files = download_files_cached_batch(
                filtered_urls, cache_dir,
                parallel=args.parallel,
                connections=args.parallel,  # Also use for multi-connection per file (aria2c)
                progress_callback=lambda: pbar.update(1)
            )

        check_shutdown()

        # Add successfully downloaded files to detected
        for url, cached in cached_files.items():
            source_url = url_to_source.get(url, network_sources[0] if network_sources else '')
            # Add to detected, handling duplicates
            if cached.name not in [x.name for x in detected[system]]:
                detected[system].append(cached)
                rom_sources[str(cached)] = source_url
            elif args.prefer_source and source_url == args.prefer_source:
                detected[system] = [x for x in detected[system] if x.name != cached.name]
                detected[system].append(cached)
                rom_sources[str(cached)] = source_url

    detected = dict(detected)  # Convert from defaultdict

    if not detected:
        if dry_run:
            print("\nNo ROM files found. No files changed (dry run).")
            sys.exit(0)
        else:
            print("\n" + "=" * 60)
            print("ERROR: No ROM files found in any source")
            print("=" * 60)
            if local_sources:
                print("\nLocal sources checked:")
                for src in local_sources:
                    print(f"  • {src}")
            if network_sources:
                print("\nNetwork sources checked:")
                for src in network_sources:
                    print(f"  • {src}")
            print("\nPossible causes:")
            print("  • Source directory/URL contains no ROM files")
            print("  • ROM files are in subdirectories not being scanned")
            print("  • File extensions not recognized (use --list-systems to see supported extensions)")
            print("  • All ROMs were filtered out by include/exclude patterns")
            if args.systems:
                print(f"  • Specified systems ({', '.join(args.systems)}) not found in sources")
            sys.exit(1)

    if args.systems:
        print(f"Systems: {', '.join(sorted(detected.keys()))}")
    else:
        print(f"Detected systems: {', '.join(sorted(detected.keys()))}")

    print()
    total_selected = 0
    total_source_size = 0
    total_selected_size = 0
    system_stats = {}  # Track stats per system

    for system in sorted(detected.keys()):
        check_shutdown()
        rom_files = detected[system]

        # Special handling for MAME and FBNeo (arcade systems)
        if system in ('mame', 'fbneo', 'fba', 'arcade'):
            arcade_system = system.upper()
            if system in ('fba', 'arcade'):
                system = 'fbneo'  # Normalize to fbneo

            # Use consolidated dat_files directory
            dat_dir = Path(args.dat_dir) if args.dat_dir else primary_source / 'dat_files'

            # Check for existing data files
            catver_path = None
            arcade_dat_path = None

            # Look for catver.ini
            if (dat_dir / 'catver.ini').exists():
                catver_path = dat_dir / 'catver.ini'

            # Look for DAT file based on system
            if dat_dir.exists():
                dat_candidates = []

                if system == 'fbneo':
                    # FBNeo: prefer FBNeo DAT
                    for f in dat_dir.glob('*[Ff][Bb][Nn]eo*.dat'):
                        dat_candidates.append(f)
                    for f in dat_dir.glob('*[Ff][Bb][Aa]*.dat'):
                        dat_candidates.append(f)
                else:
                    # MAME: prefer full MAME arcade DAT
                    dat_candidates.extend(sorted(dat_dir.glob('MAME*arcade*.dat'), reverse=True))
                    dat_candidates.extend(sorted(dat_dir.glob('MAME*.dat'), reverse=True))
                    dat_candidates.extend(sorted(dat_dir.glob('ARCADE*.dat'), reverse=True))
                    if (dat_dir / 'mame.xml').exists():
                        dat_candidates.append(dat_dir / 'mame.xml')
                    # Any DAT in root (but not FBNeo)
                    for f in dat_dir.glob('*.dat'):
                        if 'fbneo' not in f.name.lower() and 'fba' not in f.name.lower():
                            dat_candidates.append(f)

                if dat_candidates:
                    arcade_dat_path = dat_candidates[0]

            # Download missing files (for MAME only - FBNeo uses existing DAT)
            if system == 'mame' and (not catver_path or not arcade_dat_path):
                print(f"\n{arcade_system}: Data files not found, downloading...")
                downloaded_catver, downloaded_dat = download_mame_data(
                    dat_dir,
                    version=args.mame_version
                )
                if downloaded_catver:
                    catver_path = downloaded_catver
                if downloaded_dat:
                    arcade_dat_path = downloaded_dat

            # Verify we have required files
            if not catver_path or not catver_path.exists():
                print(f"{arcade_system}: catver.ini not available. Skipping.")
                continue
            if not arcade_dat_path or not arcade_dat_path.exists():
                print(f"{arcade_system}: DAT file not available. Skipping.")
                continue

            # Get ROM source directory (check all sources)
            rom_source = None
            for sp in source_paths:
                if (sp / system).exists():
                    rom_source = sp / system
                    break
            if not rom_source:
                print(f"{arcade_system}: ROM directory not found in any source")
                continue

            print(f"{arcade_system}: Using catver.ini from {catver_path}")
            print(f"{arcade_system}: Using DAT from {arcade_dat_path}")

            result = filter_mame_roms(
                str(rom_source),
                args.dest,
                str(catver_path),
                str(arcade_dat_path),
                copy_chds=not args.no_chd,
                dry_run=dry_run,
                system_name=system,
                include_adult=not args.no_adult
            )
            selected, size_info = result
            system_stats[system] = size_info
            total_source_size += size_info['source_size']
            total_selected_size += size_info['selected_size']
            if selected:
                total_selected += len(selected)
            print()
        else:
            # DAT verification/matching for non-MAME systems
            dat_entries = None
            if verify or use_dat:
                dat_dir = Path(args.dat_dir) if args.dat_dir else primary_source / 'dat_files'
                dat_path = download_libretro_dat(system, dat_dir)
                if dat_path:
                    print(f"{system.upper()}: Loading DAT file...")
                    dat_entries = parse_clrmamepro_dat(dat_path)
                    print(f"{system.upper()}: Loaded {len(dat_entries)} DAT entries")

            if verify and dat_entries:
                verified, unverified, bad = verify_roms_against_dat(rom_files, dat_entries, system)
                print(f"{system.upper()}: {len(verified)} verified, {len(unverified)} unknown, {len(bad)} bad")

                # Write verification report
                if not dry_run:
                    report_path = Path(args.dest) / system / '_verification_report.txt'
                    report_path.parent.mkdir(parents=True, exist_ok=True)
                    with open(report_path, 'w', encoding='utf-8') as f:
                        f.write(f"ROM Verification Report - {system.upper()}\n")
                        f.write("=" * 60 + "\n\n")
                        f.write(f"Verified: {len(verified)}\n")
                        f.write(f"Unknown: {len(unverified)}\n")
                        f.write(f"Bad/Unreadable: {len(bad)}\n\n")

                        if verified:
                            f.write("VERIFIED ROMS\n")
                            f.write("-" * 40 + "\n")
                            for rom_path, entry in sorted(verified, key=lambda x: x[0].name):
                                f.write(f"{rom_path.name}\n")
                                f.write(f"  DAT: {entry.name}\n")
                                f.write(f"  CRC: {entry.crc}\n\n")

                        if unverified:
                            f.write("\nUNKNOWN ROMS (not in DAT)\n")
                            f.write("-" * 40 + "\n")
                            for rom_path, crc in sorted(unverified, key=lambda x: x[0].name):
                                f.write(f"{rom_path.name} (CRC: {crc})\n")

                        if bad:
                            f.write("\nBAD/UNREADABLE ROMS\n")
                            f.write("-" * 40 + "\n")
                            for rom_path in sorted(bad, key=lambda x: x.name):
                                f.write(f"{rom_path.name}\n")

                    print(f"{system.upper()}: Verification report written to {report_path}")

            result = filter_roms_from_files(
                rom_files, args.dest, system, dry_run,
                dat_entries=dat_entries if use_dat else None,
                include_patterns=args.include,
                exclude_patterns=args.exclude,
                exclude_protos=args.exclude_protos,
                include_betas=args.include_betas,
                include_unlicensed=args.include_unlicensed,
                region_priority=region_priority,
                keep_regions=keep_regions,
                flat_output=args.flat,
                transfer_mode=transfer_mode,
                year_from=args.year_from,
                year_to=args.year_to,
                verbose=args.verbose
            )
            selected, size_info = result
            system_stats[system] = size_info
            total_source_size += size_info['source_size']
            total_selected_size += size_info['selected_size']

            # Generate playlists if requested
            if selected and not dry_run:
                selected_paths = [Path(args.dest) / (system if not args.flat else '') / r.filename for r in selected]
                if args.playlists:
                    playlist_path = generate_m3u_playlist(system, selected_paths,
                                                          Path(args.dest) / system if not args.flat else Path(args.dest))
                    print(f"{system.upper()}: Generated playlist: {playlist_path}")
                if args.gamelist:
                    gamelist_path = generate_gamelist_xml(system, selected_paths,
                                                          Path(args.dest) / system if not args.flat else Path(args.dest))
                    print(f"{system.upper()}: Generated gamelist: {gamelist_path}")
                if args.retroarch_playlists:
                    rom_dir = Path(args.dest) / system if not args.flat else Path(args.dest)
                    playlist_path = generate_retroarch_playlist(system, selected_paths, rom_dir,
                                                                 Path(args.retroarch_playlists))
                    print(f"{system.upper()}: Generated Retroarch playlist: {playlist_path}")

            if selected:
                total_selected += len(selected)
            print()

    check_shutdown()
    print("=" * 60)
    print(f"Total ROMs selected: {total_selected}")

    # Print size summary if we have data
    if system_stats:
        print()
        print("SIZE SUMMARY")
        print("-" * 60)
        print(f"{'System':<15} {'Source':>12} {'Selected':>12} {'Saved':>12} {'%':>6}")
        print("-" * 60)
        for sys_name in sorted(system_stats.keys()):
            stats = system_stats[sys_name]
            src = stats['source_size']
            sel = stats['selected_size']
            saved = src - sel
            pct = (saved / src * 100) if src > 0 else 0
            print(f"{sys_name:<15} {format_size(src):>12} {format_size(sel):>12} {format_size(saved):>12} {pct:>5.1f}%")
        print("-" * 60)
        total_saved = total_source_size - total_selected_size
        total_pct = (total_saved / total_source_size * 100) if total_source_size > 0 else 0
        print(f"{'TOTAL':<15} {format_size(total_source_size):>12} {format_size(total_selected_size):>12} {format_size(total_saved):>12} {total_pct:>5.1f}%")
        print("=" * 60)


if __name__ == '__main__':
    # Set up graceful shutdown handler
    signal.signal(signal.SIGINT, _signal_handler)
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nInterrupted.")
        sys.exit(1)

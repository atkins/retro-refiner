#!/usr/bin/env python3
"""Comprehensive tests for retro_refiner/network.py.

Covers every public function: URL utilities, size parsing, HTML parsing,
SSRF validation, scan cache, and helper functions.
"""

import json
import os
import sys
import tempfile
import time
from pathlib import Path

# Add project root to path so retro_refiner package is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from retro_refiner.network import (
    is_url, get_filename_from_url, normalize_url, is_rom_file,
    is_directory_link, format_url, format_size, parse_size_string,
    parse_budget_size, extract_links_from_html, extract_file_sizes_from_html,
    parse_html_for_files_with_sizes, parse_html_for_files,
    parse_html_for_directories, _is_private_ip, _is_private_host,
    validate_source, load_scan_cache, save_scan_cache, parse_url,
    is_archive_org_url, get_ia_auth_header, is_ten_source,
    is_myrient_tosec_url, request_shutdown, check_shutdown, reset_shutdown,
    SCAN_CACHE_MAX_AGE,
)


class TestResult:
    """Track test results."""
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.errors = []

    def ok(self, name):
        self.passed += 1
        print(f"  [PASS] {name}")

    def fail(self, name, expected, actual):
        self.failed += 1
        self.errors.append((name, expected, actual))
        print(f"  [FAIL] {name}")
        print(f"    Expected: {expected}")
        print(f"    Actual:   {actual}")

    def summary(self):
        total = self.passed + self.failed
        print(f"\n{'='*60}")
        print(f"Results: {self.passed}/{total} passed")
        if self.failed > 0:
            print(f"Failed tests: {self.failed}")
        print(f"{'='*60}")
        return self.failed == 0


results = TestResult()


# =============================================================================
# Sample HTML for parser tests
# =============================================================================

MYRIENT_HTML = '''<table>
<tr>
<td class="link"><a href="Super%20Mario%20World.zip">Super Mario World.zip</a></td>
<td class="size">1.5 MB</td>
</tr>
<tr>
<td class="link"><a href="Zelda.zip">Zelda.zip</a></td>
<td class="size">2.3 MB</td>
</tr>
<tr>
<td class="link"><a href="readme.txt">readme.txt</a></td>
<td class="size">1024</td>
</tr>
</table>'''

AUTOINDEX_HTML = '''<pre>
<a href="rom.zip">rom.zip</a>                    01-Jan-2024 12:00  1234
<a href="game.7z">game.7z</a>                    15-Mar-2024 09:30  5678
<a href="readme.txt">readme.txt</a>                 20-Feb-2024 15:45  100
</pre>'''

AUTOINDEX_HTML_ALT = '''<pre>
<a href="big_rom.iso">big_rom.iso</a>   2024-01-15 10:00  2048000
<a href="small.zip">small.zip</a>     2024-03-20 14:30  512
</pre>'''

GENERIC_TABLE_HTML = '''<table>
<tr><td><a href="game1.zip">game1.zip</a></td><td>info</td><td>1048576</td></tr>
<tr><td><a href="game2.7z">game2.7z</a></td><td>info</td><td>2097152</td></tr>
</table>'''

FTP_LISTING_HTML = '''<pre>
-rw-r--r--   1 user group   1536000 Jan 01 12:00 rom_file.zip
-rw-r--r--   1 user group    512000 Feb 15 09:30 another.7z
drwxr-xr-x   2 user group      4096 Mar 20 14:00 subdir
</pre>'''

SIMPLE_SIZE_HTML = '''<pre>
game.zip 1048576
rom.iso 2097152
</pre>'''

DIRECTORY_HTML = '''
<a href="subdir/">subdir/</a>
<a href="another_dir/">another_dir/</a>
<a href="game.zip">game.zip</a>
<a href="../">../</a>
'''


# =============================================================================
# is_url tests
# =============================================================================

def test_is_url():
    print("\n--- is_url ---")

    if is_url("http://example.com"):
        results.ok("is_url: http URL")
    else:
        results.fail("is_url: http URL", True, False)

    if is_url("https://example.com/roms/snes/"):
        results.ok("is_url: https URL with path")
    else:
        results.fail("is_url: https URL with path", True, False)

    if not is_url("/home/user/roms"):
        results.ok("is_url: local path is not URL")
    else:
        results.fail("is_url: local path is not URL", False, True)

    if not is_url("C:\\Users\\roms"):
        results.ok("is_url: Windows path is not URL")
    else:
        results.fail("is_url: Windows path is not URL", False, True)

    if not is_url(""):
        results.ok("is_url: empty string")
    else:
        results.fail("is_url: empty string", False, True)

    if not is_url("ftp://example.com"):
        results.ok("is_url: ftp is not http/https")
    else:
        results.fail("is_url: ftp is not http/https", False, True)

    if not is_url("file:///etc/passwd"):
        results.ok("is_url: file scheme is not URL")
    else:
        results.fail("is_url: file scheme is not URL", False, True)


# =============================================================================
# get_filename_from_url tests
# =============================================================================

def test_get_filename_from_url():
    print("\n--- get_filename_from_url ---")

    result = get_filename_from_url("https://example.com/roms/game.zip")
    if result == "game.zip":
        results.ok("get_filename: simple URL")
    else:
        results.fail("get_filename: simple URL", "game.zip", result)

    result = get_filename_from_url("https://example.com/roms/Super%20Mario%20World.zip")
    if result == "Super Mario World.zip":
        results.ok("get_filename: percent-encoded spaces")
    else:
        results.fail("get_filename: percent-encoded spaces", "Super Mario World.zip", result)

    result = get_filename_from_url("https://example.com/roms/game.zip?key=value&other=1")
    if result == "game.zip":
        results.ok("get_filename: query params stripped")
    else:
        results.fail("get_filename: query params stripped", "game.zip", result)

    result = get_filename_from_url("https://example.com/roms/game.zip#section")
    if result == "game.zip":
        results.ok("get_filename: fragment stripped")
    else:
        results.fail("get_filename: fragment stripped", "game.zip", result)

    result = get_filename_from_url("https://example.com/roms/game.zip?dl=1#top")
    if result == "game.zip":
        results.ok("get_filename: query + fragment stripped")
    else:
        results.fail("get_filename: query + fragment stripped", "game.zip", result)

    result = get_filename_from_url("https://example.com/a/b/c/deep_file.7z")
    if result == "deep_file.7z":
        results.ok("get_filename: deep path")
    else:
        results.fail("get_filename: deep path", "deep_file.7z", result)

    result = get_filename_from_url("https://example.com/roms/T%C3%A9tris%20%28Japan%29.zip")
    if "tris" in result and "(Japan)" in result:
        results.ok("get_filename: unicode percent-encoding")
    else:
        results.fail("get_filename: unicode percent-encoding", "contains decoded chars", result)


# =============================================================================
# normalize_url tests
# =============================================================================

def test_normalize_url():
    print("\n--- normalize_url ---")
    base = "https://example.com/roms/snes/"

    # Relative path
    result = normalize_url("game.zip", base)
    if result == "https://example.com/roms/snes/game.zip":
        results.ok("normalize_url: relative path")
    else:
        results.fail("normalize_url: relative path", "https://example.com/roms/snes/game.zip", result)

    # Absolute path
    result = normalize_url("/other/file.zip", base)
    if result == "https://example.com/other/file.zip":
        results.ok("normalize_url: absolute path")
    else:
        results.fail("normalize_url: absolute path", "https://example.com/other/file.zip", result)

    # Full URL same host
    result = normalize_url("https://example.com/roms/nes/game.zip", base)
    if result == "https://example.com/roms/nes/game.zip":
        results.ok("normalize_url: full URL same host")
    else:
        results.fail("normalize_url: full URL same host", "https://example.com/roms/nes/game.zip", result)

    # Full URL different host - rejected
    result = normalize_url("https://other.com/roms/game.zip", base)
    if result is None:
        results.ok("normalize_url: different host rejected")
    else:
        results.fail("normalize_url: different host rejected", None, result)

    # Protocol-relative
    result = normalize_url("//example.com/roms/file.zip", base)
    if result == "https://example.com/roms/file.zip":
        results.ok("normalize_url: protocol-relative")
    else:
        results.fail("normalize_url: protocol-relative", "https://example.com/roms/file.zip", result)

    # Anchor link skipped
    result = normalize_url("#section", base)
    if result is None:
        results.ok("normalize_url: anchor link skipped")
    else:
        results.fail("normalize_url: anchor link skipped", None, result)

    # javascript: skipped
    result = normalize_url("javascript:void(0)", base)
    if result is None:
        results.ok("normalize_url: javascript skipped")
    else:
        results.fail("normalize_url: javascript skipped", None, result)

    # mailto: skipped
    result = normalize_url("mailto:user@example.com", base)
    if result is None:
        results.ok("normalize_url: mailto skipped")
    else:
        results.fail("normalize_url: mailto skipped", None, result)

    # data: URI skipped
    result = normalize_url("data:text/plain;base64,abc", base)
    if result is None:
        results.ok("normalize_url: data URI skipped")
    else:
        results.fail("normalize_url: data URI skipped", None, result)

    # Parent directory links skipped
    for href in ('.', '..', '../', './'):
        result = normalize_url(href, base)
        if result is None:
            results.ok(f"normalize_url: '{href}' skipped")
        else:
            results.fail(f"normalize_url: '{href}' skipped", None, result)

    # Query-only link skipped
    result = normalize_url("?sort=name", base)
    if result is None:
        results.ok("normalize_url: query-only link skipped")
    else:
        results.fail("normalize_url: query-only link skipped", None, result)

    # Empty href skipped
    result = normalize_url("", base)
    if result is None:
        results.ok("normalize_url: empty href skipped")
    else:
        results.fail("normalize_url: empty href skipped", None, result)

    # HTML entity decoding
    result = normalize_url("game.zip?a=1&amp;b=2", base)
    if result and "&amp;" not in result and "&" in result:
        results.ok("normalize_url: HTML entity decoded")
    else:
        results.fail("normalize_url: HTML entity decoded", "decoded &amp; to &", result)

    # Relative path with ..
    result = normalize_url("../nes/game.zip", base)
    if result == "https://example.com/roms/nes/game.zip":
        results.ok("normalize_url: relative with ..")
    else:
        results.fail("normalize_url: relative with ..", "https://example.com/roms/nes/game.zip", result)

    # Base URL without trailing slash
    result = normalize_url("game.zip", "https://example.com/roms/snes")
    if result == "https://example.com/roms/game.zip":
        results.ok("normalize_url: base without trailing slash")
    else:
        results.fail("normalize_url: base without trailing slash", "https://example.com/roms/game.zip", result)


# =============================================================================
# is_rom_file tests
# =============================================================================

def test_is_rom_file():
    print("\n--- is_rom_file ---")

    rom_extensions = ['.zip', '.7z', '.rar', '.nes', '.sfc', '.smc', '.gba',
                      '.gb', '.gbc', '.n64', '.iso', '.chd', '.nds', '.cue',
                      '.pbp', '.cso', '.nsp', '.xci']
    for ext in rom_extensions:
        if is_rom_file(f"game{ext}"):
            results.ok(f"is_rom_file: {ext}")
        else:
            results.fail(f"is_rom_file: {ext}", True, False)

    non_rom = ['.html', '.htm', '.css', '.js', '.png', '.jpg', '.txt', '.xml',
               '.pdf', '.exe', '.py']
    for ext in non_rom:
        if not is_rom_file(f"file{ext}"):
            results.ok(f"is_rom_file: {ext} rejected")
        else:
            results.fail(f"is_rom_file: {ext} rejected", False, True)

    # Case insensitivity
    if is_rom_file("GAME.ZIP"):
        results.ok("is_rom_file: uppercase .ZIP")
    else:
        results.fail("is_rom_file: uppercase .ZIP", True, False)

    if is_rom_file("game.Zip"):
        results.ok("is_rom_file: mixed case .Zip")
    else:
        results.fail("is_rom_file: mixed case .Zip", True, False)

    # With query params
    if is_rom_file("game.zip?download=true"):
        results.ok("is_rom_file: with query params")
    else:
        results.fail("is_rom_file: with query params", True, False)

    # With fragment
    if is_rom_file("game.zip#section"):
        results.ok("is_rom_file: with fragment")
    else:
        results.fail("is_rom_file: with fragment", True, False)

    # Percent-encoded
    if is_rom_file("Super%20Mario%20World.zip"):
        results.ok("is_rom_file: percent-encoded")
    else:
        results.fail("is_rom_file: percent-encoded", True, False)


# =============================================================================
# is_directory_link tests
# =============================================================================

def test_is_directory_link():
    print("\n--- is_directory_link ---")

    if is_directory_link("subdir/"):
        results.ok("is_directory_link: trailing slash")
    else:
        results.fail("is_directory_link: trailing slash", True, False)

    if is_directory_link("https://example.com/roms/snes/"):
        results.ok("is_directory_link: full URL with trailing slash")
    else:
        results.fail("is_directory_link: full URL with trailing slash", True, False)

    if not is_directory_link("game.zip"):
        results.ok("is_directory_link: file with extension")
    else:
        results.fail("is_directory_link: file with extension", False, True)

    if is_directory_link("subdir"):
        results.ok("is_directory_link: no extension no slash")
    else:
        results.fail("is_directory_link: no extension no slash", True, False)

    # Parent directory
    if not is_directory_link("game.zip?sort=name"):
        results.ok("is_directory_link: file with query params")
    else:
        results.fail("is_directory_link: file with query params", False, True)

    if is_directory_link("folder-name"):
        results.ok("is_directory_link: hyphenated no extension")
    else:
        results.fail("is_directory_link: hyphenated no extension", True, False)


# =============================================================================
# format_url tests
# =============================================================================

def test_format_url():
    print("\n--- format_url ---")

    result = format_url("https://example.com/roms/Super%20Mario.zip")
    if result == "https://example.com/roms/Super Mario.zip":
        results.ok("format_url: decodes percent-encoding")
    else:
        results.fail("format_url: decodes percent-encoding", "https://example.com/roms/Super Mario.zip", result)

    result = format_url("https://example.com/roms/game.zip")
    if result == "https://example.com/roms/game.zip":
        results.ok("format_url: no encoding needed")
    else:
        results.fail("format_url: no encoding needed", "https://example.com/roms/game.zip", result)

    result = format_url("https://example.com/roms/game.zip", max_length=20)
    if result.endswith("...") and len(result) == 20:
        results.ok("format_url: truncation with max_length")
    else:
        results.fail("format_url: truncation with max_length", "20 chars ending with ...", result)

    result = format_url("https://example.com/roms/game.zip", max_length=0)
    if result == "https://example.com/roms/game.zip":
        results.ok("format_url: max_length=0 means no truncation")
    else:
        results.fail("format_url: max_length=0 means no truncation",
                      "https://example.com/roms/game.zip", result)

    result = format_url("short", max_length=100)
    if result == "short":
        results.ok("format_url: string shorter than max_length")
    else:
        results.fail("format_url: string shorter than max_length", "short", result)


# =============================================================================
# format_size tests
# =============================================================================

def test_format_size():
    print("\n--- format_size ---")

    result = format_size(0)
    if result == "0 B":
        results.ok("format_size: 0 bytes")
    else:
        results.fail("format_size: 0 bytes", "0 B", result)

    result = format_size(500)
    if result == "500 B":
        results.ok("format_size: 500 bytes")
    else:
        results.fail("format_size: 500 bytes", "500 B", result)

    result = format_size(1023)
    if result == "1023 B":
        results.ok("format_size: 1023 bytes (just under 1 KB)")
    else:
        results.fail("format_size: 1023 bytes (just under 1 KB)", "1023 B", result)

    result = format_size(1024)
    if result == "1.0 KB":
        results.ok("format_size: exactly 1 KB")
    else:
        results.fail("format_size: exactly 1 KB", "1.0 KB", result)

    result = format_size(1536)
    if result == "1.5 KB":
        results.ok("format_size: 1.5 KB")
    else:
        results.fail("format_size: 1.5 KB", "1.5 KB", result)

    result = format_size(1048576)
    if result == "1.0 MB":
        results.ok("format_size: exactly 1 MB")
    else:
        results.fail("format_size: exactly 1 MB", "1.0 MB", result)

    result = format_size(1073741824)
    if result == "1.00 GB":
        results.ok("format_size: exactly 1 GB")
    else:
        results.fail("format_size: exactly 1 GB", "1.00 GB", result)

    result = format_size(1099511627776)
    if result == "1.00 TB":
        results.ok("format_size: exactly 1 TB")
    else:
        results.fail("format_size: exactly 1 TB", "1.00 TB", result)

    result = format_size(1)
    if result == "1 B":
        results.ok("format_size: 1 byte")
    else:
        results.fail("format_size: 1 byte", "1 B", result)

    result = format_size(5 * 1024 * 1024 * 1024)
    if "5.00 GB" in result:
        results.ok("format_size: 5 GB")
    else:
        results.fail("format_size: 5 GB", "5.00 GB", result)


# =============================================================================
# parse_size_string tests
# =============================================================================

def test_parse_size_string():
    print("\n--- parse_size_string ---")

    result = parse_size_string("1.5M")
    if result == int(1.5 * 1024 * 1024):
        results.ok("parse_size_string: 1.5M")
    else:
        results.fail("parse_size_string: 1.5M", int(1.5 * 1024 * 1024), result)

    result = parse_size_string("100K")
    if result == 100 * 1024:
        results.ok("parse_size_string: 100K")
    else:
        results.fail("parse_size_string: 100K", 100 * 1024, result)

    result = parse_size_string("50G")
    if result == 50 * 1024 * 1024 * 1024:
        results.ok("parse_size_string: 50G")
    else:
        results.fail("parse_size_string: 50G", 50 * 1024 * 1024 * 1024, result)

    result = parse_size_string("1234")
    if result == 1234:
        results.ok("parse_size_string: bare number")
    else:
        results.fail("parse_size_string: bare number", 1234, result)

    result = parse_size_string("1.5 MB")
    if result == int(1.5 * 1024 * 1024):
        results.ok("parse_size_string: 1.5 MB with space")
    else:
        results.fail("parse_size_string: 1.5 MB with space", int(1.5 * 1024 * 1024), result)

    result = parse_size_string("175.9 MiB")
    if result == int(175.9 * 1024 * 1024):
        results.ok("parse_size_string: 175.9 MiB")
    else:
        results.fail("parse_size_string: 175.9 MiB", int(175.9 * 1024 * 1024), result)

    result = parse_size_string("2T")
    if result == 2 * 1024 ** 4:
        results.ok("parse_size_string: 2T")
    else:
        results.fail("parse_size_string: 2T", 2 * 1024 ** 4, result)

    result = parse_size_string("")
    if result == 0:
        results.ok("parse_size_string: empty string")
    else:
        results.fail("parse_size_string: empty string", 0, result)

    result = parse_size_string("not_a_size")
    if result == 0:
        results.ok("parse_size_string: invalid input")
    else:
        results.fail("parse_size_string: invalid input", 0, result)

    result = parse_size_string("0")
    if result == 0:
        results.ok("parse_size_string: zero")
    else:
        results.fail("parse_size_string: zero", 0, result)

    result = parse_size_string("10KB")
    if result == 10 * 1024:
        results.ok("parse_size_string: 10KB")
    else:
        results.fail("parse_size_string: 10KB", 10 * 1024, result)

    result = parse_size_string("2.5GB")
    if result == int(2.5 * 1024 ** 3):
        results.ok("parse_size_string: 2.5GB")
    else:
        results.fail("parse_size_string: 2.5GB", int(2.5 * 1024 ** 3), result)


# =============================================================================
# parse_budget_size tests
# =============================================================================

def test_parse_budget_size():
    print("\n--- parse_budget_size ---")

    result = parse_budget_size("10GB")
    if result == int(10 * 1024 ** 3):
        results.ok("parse_budget_size: 10GB")
    else:
        results.fail("parse_budget_size: 10GB", int(10 * 1024 ** 3), result)

    result = parse_budget_size("500MB")
    if result == int(500 * 1024 ** 2):
        results.ok("parse_budget_size: 500MB")
    else:
        results.fail("parse_budget_size: 500MB", int(500 * 1024 ** 2), result)

    result = parse_budget_size("1TB")
    if result == 1024 ** 4:
        results.ok("parse_budget_size: 1TB")
    else:
        results.fail("parse_budget_size: 1TB", 1024 ** 4, result)

    result = parse_budget_size("256KB")
    if result == 256 * 1024:
        results.ok("parse_budget_size: 256KB")
    else:
        results.fail("parse_budget_size: 256KB", 256 * 1024, result)

    result = parse_budget_size("")
    if result is None:
        results.ok("parse_budget_size: empty string")
    else:
        results.fail("parse_budget_size: empty string", None, result)

    result = parse_budget_size(None)
    if result is None:
        results.ok("parse_budget_size: None")
    else:
        results.fail("parse_budget_size: None", None, result)

    result = parse_budget_size("not_a_size")
    if result is None:
        results.ok("parse_budget_size: invalid string")
    else:
        results.fail("parse_budget_size: invalid string", None, result)

    result = parse_budget_size("1024")
    if result == 1024:
        results.ok("parse_budget_size: bare number")
    else:
        results.fail("parse_budget_size: bare number", 1024, result)

    result = parse_budget_size("1.5G")
    if result == int(1.5 * 1024 ** 3):
        results.ok("parse_budget_size: 1.5G short suffix")
    else:
        results.fail("parse_budget_size: 1.5G short suffix", int(1.5 * 1024 ** 3), result)

    result = parse_budget_size("100B")
    if result == 100:
        results.ok("parse_budget_size: 100B")
    else:
        results.fail("parse_budget_size: 100B", 100, result)

    result = parse_budget_size("  500MB  ")
    if result == int(500 * 1024 ** 2):
        results.ok("parse_budget_size: whitespace trimmed")
    else:
        results.fail("parse_budget_size: whitespace trimmed", int(500 * 1024 ** 2), result)

    result = parse_budget_size("500mb")
    if result == int(500 * 1024 ** 2):
        results.ok("parse_budget_size: lowercase")
    else:
        results.fail("parse_budget_size: lowercase", int(500 * 1024 ** 2), result)


# =============================================================================
# extract_links_from_html tests
# =============================================================================

def test_extract_links_from_html():
    print("\n--- extract_links_from_html ---")

    # href extraction
    html = '<a href="game.zip">game</a>'
    links = extract_links_from_html(html)
    if "game.zip" in links:
        results.ok("extract_links: href tag")
    else:
        results.fail("extract_links: href tag", "game.zip in links", links)

    # src extraction (ROM file)
    html = '<img src="rom.zip">'
    links = extract_links_from_html(html)
    if "rom.zip" in links:
        results.ok("extract_links: src with ROM extension")
    else:
        results.fail("extract_links: src with ROM extension", "rom.zip in links", links)

    # src extraction (non-ROM ignored)
    html = '<img src="image.png">'
    links = extract_links_from_html(html)
    if "image.png" not in links:
        results.ok("extract_links: src non-ROM ignored")
    else:
        results.fail("extract_links: src non-ROM ignored", "image.png not in links", links)

    # data-url attribute
    html = '<div data-url="download.zip">click</div>'
    links = extract_links_from_html(html)
    if "download.zip" in links:
        results.ok("extract_links: data-url attribute")
    else:
        results.fail("extract_links: data-url attribute", "download.zip in links", links)

    # data-href attribute
    html = '<div data-href="rom.7z">click</div>'
    links = extract_links_from_html(html)
    if "rom.7z" in links:
        results.ok("extract_links: data-href attribute")
    else:
        results.fail("extract_links: data-href attribute", "rom.7z in links", links)

    # onclick handler
    html = '<button onclick="location.href=\'game.zip\'">Download</button>'
    links = extract_links_from_html(html)
    if "game.zip" in links:
        results.ok("extract_links: onclick handler")
    else:
        results.fail("extract_links: onclick handler", "game.zip in links", links)

    # Multiple links in one HTML
    html = '<a href="a.zip">a</a><a href="b.7z">b</a><a href="c.nes">c</a>'
    links = extract_links_from_html(html)
    if "a.zip" in links and "b.7z" in links and "c.nes" in links:
        results.ok("extract_links: multiple hrefs")
    else:
        results.fail("extract_links: multiple hrefs", "a.zip, b.7z, c.nes", links)

    # Text files in pre block
    html = '<pre>Super Mario World.zip\n  Zelda.7z\n</pre>'
    links = extract_links_from_html(html)
    if any("Super Mario World.zip" in l for l in links):
        results.ok("extract_links: text files in pre block")
    else:
        results.fail("extract_links: text files in pre block", "Super Mario World.zip in links", links)

    # Empty HTML
    links = extract_links_from_html("")
    if links == []:
        results.ok("extract_links: empty HTML")
    else:
        results.fail("extract_links: empty HTML", [], links)


# =============================================================================
# extract_file_sizes_from_html tests
# =============================================================================

def test_extract_file_sizes_from_html():
    print("\n--- extract_file_sizes_from_html ---")

    # Myrient format
    sizes = extract_file_sizes_from_html(MYRIENT_HTML)
    if "Super Mario World.zip" in sizes and sizes["Super Mario World.zip"] == int(1.5 * 1024 * 1024):
        results.ok("extract_file_sizes: Myrient format - Mario size")
    else:
        results.fail("extract_file_sizes: Myrient format - Mario size",
                      int(1.5 * 1024 * 1024), sizes.get("Super Mario World.zip"))

    if "Zelda.zip" in sizes and sizes["Zelda.zip"] == int(2.3 * 1024 * 1024):
        results.ok("extract_file_sizes: Myrient format - Zelda size")
    else:
        results.fail("extract_file_sizes: Myrient format - Zelda size",
                      int(2.3 * 1024 * 1024), sizes.get("Zelda.zip"))

    # Myrient: href key is decoded (unquoted) before storage
    if "Super Mario World.zip" in sizes:
        results.ok("extract_file_sizes: Myrient format - decoded href key present")
    else:
        results.fail("extract_file_sizes: Myrient format - decoded href key present",
                      "Super Mario World.zip in sizes", list(sizes.keys()))

    # Apache autoindex format
    sizes = extract_file_sizes_from_html(AUTOINDEX_HTML)
    if "rom.zip" in sizes and sizes["rom.zip"] == 1234:
        results.ok("extract_file_sizes: autoindex - rom.zip")
    else:
        results.fail("extract_file_sizes: autoindex - rom.zip", 1234, sizes.get("rom.zip"))

    if "game.7z" in sizes and sizes["game.7z"] == 5678:
        results.ok("extract_file_sizes: autoindex - game.7z")
    else:
        results.fail("extract_file_sizes: autoindex - game.7z", 5678, sizes.get("game.7z"))

    # Alternative autoindex date format
    sizes = extract_file_sizes_from_html(AUTOINDEX_HTML_ALT)
    if "big_rom.iso" in sizes and sizes["big_rom.iso"] == 2048000:
        results.ok("extract_file_sizes: autoindex alt date format")
    else:
        results.fail("extract_file_sizes: autoindex alt date format",
                      2048000, sizes.get("big_rom.iso"))

    # Generic table format
    sizes = extract_file_sizes_from_html(GENERIC_TABLE_HTML)
    if "game1.zip" in sizes and sizes["game1.zip"] == 1048576:
        results.ok("extract_file_sizes: generic table - game1")
    else:
        results.fail("extract_file_sizes: generic table - game1", 1048576, sizes.get("game1.zip"))

    if "game2.7z" in sizes and sizes["game2.7z"] == 2097152:
        results.ok("extract_file_sizes: generic table - game2")
    else:
        results.fail("extract_file_sizes: generic table - game2", 2097152, sizes.get("game2.7z"))

    # FTP listing format
    sizes = extract_file_sizes_from_html(FTP_LISTING_HTML)
    if "rom_file.zip" in sizes and sizes["rom_file.zip"] == 1536000:
        results.ok("extract_file_sizes: FTP listing - rom_file.zip")
    else:
        results.fail("extract_file_sizes: FTP listing - rom_file.zip",
                      1536000, sizes.get("rom_file.zip"))

    if "another.7z" in sizes and sizes["another.7z"] == 512000:
        results.ok("extract_file_sizes: FTP listing - another.7z")
    else:
        results.fail("extract_file_sizes: FTP listing - another.7z",
                      512000, sizes.get("another.7z"))

    # Simple size format
    sizes = extract_file_sizes_from_html(SIMPLE_SIZE_HTML)
    if "game.zip" in sizes and sizes["game.zip"] == 1048576:
        results.ok("extract_file_sizes: simple format - game.zip")
    else:
        results.fail("extract_file_sizes: simple format - game.zip",
                      1048576, sizes.get("game.zip"))

    # Empty HTML
    sizes = extract_file_sizes_from_html("")
    if sizes == {}:
        results.ok("extract_file_sizes: empty HTML")
    else:
        results.fail("extract_file_sizes: empty HTML", {}, sizes)

    # Myrient dash size (directory, ignored)
    dash_html = '''<table><tr>
    <td class="link"><a href="subdir/">subdir/</a></td>
    <td class="size">-</td></tr></table>'''
    sizes = extract_file_sizes_from_html(dash_html)
    if "subdir/" not in sizes:
        results.ok("extract_file_sizes: Myrient dash size ignored")
    else:
        results.fail("extract_file_sizes: Myrient dash size ignored",
                      "subdir/ not in sizes", sizes)


# =============================================================================
# parse_html_for_files_with_sizes tests
# =============================================================================

def test_parse_html_for_files_with_sizes():
    print("\n--- parse_html_for_files_with_sizes ---")

    base = "https://example.com/roms/snes/"

    files = parse_html_for_files_with_sizes(MYRIENT_HTML, base)
    urls = [url for url, _ in files]
    sizes = {url: sz for url, sz in files}

    # Should find ROM files
    mario_url = "https://example.com/roms/snes/Super%20Mario%20World.zip"
    if mario_url in urls:
        results.ok("parse_files_with_sizes: Mario URL found")
    else:
        results.fail("parse_files_with_sizes: Mario URL found", mario_url, urls)

    zelda_url = "https://example.com/roms/snes/Zelda.zip"
    if zelda_url in urls:
        results.ok("parse_files_with_sizes: Zelda URL found")
    else:
        results.fail("parse_files_with_sizes: Zelda URL found", zelda_url, urls)

    # Should have sizes
    if mario_url in sizes and sizes[mario_url] > 0:
        results.ok("parse_files_with_sizes: Mario has size")
    else:
        results.fail("parse_files_with_sizes: Mario has size", "> 0", sizes.get(mario_url, "missing"))

    # readme.txt should NOT be included (not a ROM extension)
    readme_urls = [u for u in urls if "readme" in u]
    if not readme_urls:
        results.ok("parse_files_with_sizes: readme.txt excluded")
    else:
        results.fail("parse_files_with_sizes: readme.txt excluded", "no readme URLs", readme_urls)

    # No duplicates
    if len(urls) == len(set(urls)):
        results.ok("parse_files_with_sizes: no duplicate URLs")
    else:
        results.fail("parse_files_with_sizes: no duplicate URLs", "unique URLs", len(urls))

    # Empty HTML
    files = parse_html_for_files_with_sizes("", base)
    if files == []:
        results.ok("parse_files_with_sizes: empty HTML")
    else:
        results.fail("parse_files_with_sizes: empty HTML", [], files)


# =============================================================================
# parse_html_for_files tests
# =============================================================================

def test_parse_html_for_files():
    print("\n--- parse_html_for_files ---")

    base = "https://example.com/roms/snes/"
    html = '<a href="game.zip">game.zip</a><a href="readme.txt">readme</a>'

    files = parse_html_for_files(html, base)
    if len(files) == 1 and "game.zip" in files[0]:
        results.ok("parse_html_for_files: finds ROM, skips non-ROM")
    else:
        results.fail("parse_html_for_files: finds ROM, skips non-ROM",
                      ["game.zip URL"], files)

    # Deduplication
    html = '<a href="game.zip">link1</a><a href="game.zip">link2</a>'
    files = parse_html_for_files(html, base)
    if len(files) == 1:
        results.ok("parse_html_for_files: deduplicates URLs")
    else:
        results.fail("parse_html_for_files: deduplicates URLs", 1, len(files))


# =============================================================================
# parse_html_for_directories tests
# =============================================================================

def test_parse_html_for_directories():
    print("\n--- parse_html_for_directories ---")

    base = "https://example.com/roms/"

    dirs = parse_html_for_directories(DIRECTORY_HTML, base)

    # Should find subdirectories
    expected_subdir = "https://example.com/roms/subdir/"
    if expected_subdir in dirs:
        results.ok("parse_html_for_dirs: subdir found")
    else:
        results.fail("parse_html_for_dirs: subdir found", expected_subdir, dirs)

    expected_another = "https://example.com/roms/another_dir/"
    if expected_another in dirs:
        results.ok("parse_html_for_dirs: another_dir found")
    else:
        results.fail("parse_html_for_dirs: another_dir found", expected_another, dirs)

    # Should NOT include parent directory
    parent_urls = [d for d in dirs if d.endswith("/../") or d == base]
    if not parent_urls:
        results.ok("parse_html_for_dirs: parent dir excluded")
    else:
        results.fail("parse_html_for_dirs: parent dir excluded", "no parent dirs", parent_urls)

    # Should NOT include files (game.zip)
    file_dirs = [d for d in dirs if "game.zip" in d]
    if not file_dirs:
        results.ok("parse_html_for_dirs: file links excluded")
    else:
        results.fail("parse_html_for_dirs: file links excluded", "no file links", file_dirs)

    # Empty HTML
    dirs = parse_html_for_directories("", base)
    if dirs == []:
        results.ok("parse_html_for_dirs: empty HTML")
    else:
        results.fail("parse_html_for_dirs: empty HTML", [], dirs)

    # Subdirectories must be under base URL
    html_external = '<a href="https://other.com/dir/">external</a>'
    dirs = parse_html_for_directories(html_external, base)
    if dirs == []:
        results.ok("parse_html_for_dirs: external dirs excluded")
    else:
        results.fail("parse_html_for_dirs: external dirs excluded", [], dirs)


# =============================================================================
# _is_private_ip tests
# =============================================================================

def test_is_private_ip():
    print("\n--- _is_private_ip ---")

    # Loopback
    if _is_private_ip("127.0.0.1"):
        results.ok("is_private_ip: 127.0.0.1")
    else:
        results.fail("is_private_ip: 127.0.0.1", True, False)

    if _is_private_ip("127.0.0.99"):
        results.ok("is_private_ip: 127.0.0.99")
    else:
        results.fail("is_private_ip: 127.0.0.99", True, False)

    # 10.x.x.x
    if _is_private_ip("10.0.0.1"):
        results.ok("is_private_ip: 10.0.0.1")
    else:
        results.fail("is_private_ip: 10.0.0.1", True, False)

    if _is_private_ip("10.255.255.255"):
        results.ok("is_private_ip: 10.255.255.255")
    else:
        results.fail("is_private_ip: 10.255.255.255", True, False)

    # 192.168.x.x
    if _is_private_ip("192.168.0.1"):
        results.ok("is_private_ip: 192.168.0.1")
    else:
        results.fail("is_private_ip: 192.168.0.1", True, False)

    if _is_private_ip("192.168.255.255"):
        results.ok("is_private_ip: 192.168.255.255")
    else:
        results.fail("is_private_ip: 192.168.255.255", True, False)

    # 172.16.x.x - 172.31.x.x
    if _is_private_ip("172.16.0.1"):
        results.ok("is_private_ip: 172.16.0.1")
    else:
        results.fail("is_private_ip: 172.16.0.1", True, False)

    if _is_private_ip("172.31.255.255"):
        results.ok("is_private_ip: 172.31.255.255")
    else:
        results.fail("is_private_ip: 172.31.255.255", True, False)

    # 172.15 and 172.32 are NOT private
    if not _is_private_ip("172.15.0.1"):
        results.ok("is_private_ip: 172.15.0.1 is public")
    else:
        results.fail("is_private_ip: 172.15.0.1 is public", False, True)

    if not _is_private_ip("172.32.0.1"):
        results.ok("is_private_ip: 172.32.0.1 is public")
    else:
        results.fail("is_private_ip: 172.32.0.1 is public", False, True)

    # IPv6 loopback
    if _is_private_ip("::1"):
        results.ok("is_private_ip: ::1")
    else:
        results.fail("is_private_ip: ::1", True, False)

    if _is_private_ip("[::1]"):
        results.ok("is_private_ip: [::1] with brackets")
    else:
        results.fail("is_private_ip: [::1] with brackets", True, False)

    # 0.x.x.x
    if _is_private_ip("0.0.0.0"):
        results.ok("is_private_ip: 0.0.0.0")
    else:
        results.fail("is_private_ip: 0.0.0.0", True, False)

    # Public IPs
    if not _is_private_ip("8.8.8.8"):
        results.ok("is_private_ip: 8.8.8.8 is public")
    else:
        results.fail("is_private_ip: 8.8.8.8 is public", False, True)

    if not _is_private_ip("93.184.216.34"):
        results.ok("is_private_ip: 93.184.216.34 is public")
    else:
        results.fail("is_private_ip: 93.184.216.34 is public", False, True)

    # Empty string
    if _is_private_ip(""):
        results.ok("is_private_ip: empty string is private")
    else:
        results.fail("is_private_ip: empty string is private", True, False)


# =============================================================================
# _is_private_host tests
# =============================================================================

def test_is_private_host():
    print("\n--- _is_private_host ---")

    if _is_private_host("localhost"):
        results.ok("is_private_host: localhost")
    else:
        results.fail("is_private_host: localhost", True, False)

    if _is_private_host("[::1]"):
        results.ok("is_private_host: [::1]")
    else:
        results.fail("is_private_host: [::1]", True, False)

    if _is_private_host("127.0.0.1"):
        results.ok("is_private_host: 127.0.0.1")
    else:
        results.fail("is_private_host: 127.0.0.1", True, False)

    if _is_private_host("10.0.0.1"):
        results.ok("is_private_host: 10.0.0.1")
    else:
        results.fail("is_private_host: 10.0.0.1", True, False)

    if _is_private_host("192.168.1.1"):
        results.ok("is_private_host: 192.168.1.1")
    else:
        results.fail("is_private_host: 192.168.1.1", True, False)


# =============================================================================
# validate_source tests
# =============================================================================

def test_validate_source():
    print("\n--- validate_source ---")

    # Local path that exists
    with tempfile.TemporaryDirectory() as tmpdir:
        valid, msg = validate_source(tmpdir)
        if valid and msg == "":
            results.ok("validate_source: valid local dir")
        else:
            results.fail("validate_source: valid local dir", (True, ""), (valid, msg))

    # Local path that doesn't exist
    valid, msg = validate_source("/nonexistent/path/nowhere")
    if not valid and "does not exist" in msg:
        results.ok("validate_source: nonexistent path")
    else:
        results.fail("validate_source: nonexistent path", (False, "does not exist"), (valid, msg))

    # Local path that is a file, not a directory
    with tempfile.NamedTemporaryFile(delete=False) as f:
        tmpfile = f.name
    try:
        valid, msg = validate_source(tmpfile)
        if not valid and "not a directory" in msg:
            results.ok("validate_source: file not dir")
        else:
            results.fail("validate_source: file not dir", (False, "not a directory"), (valid, msg))
    finally:
        os.unlink(tmpfile)

    # SSRF: localhost URL
    valid, msg = validate_source("http://localhost/roms/")
    if not valid and "private" in msg.lower():
        results.ok("validate_source: localhost SSRF blocked")
    else:
        results.fail("validate_source: localhost SSRF blocked",
                      (False, "private"), (valid, msg))

    # SSRF: 127.0.0.1
    valid, msg = validate_source("http://127.0.0.1/roms/")
    if not valid and "private" in msg.lower():
        results.ok("validate_source: 127.0.0.1 SSRF blocked")
    else:
        results.fail("validate_source: 127.0.0.1 SSRF blocked",
                      (False, "private"), (valid, msg))

    # SSRF: 10.x private IP
    valid, msg = validate_source("http://10.0.0.1/roms/")
    if not valid and "private" in msg.lower():
        results.ok("validate_source: 10.0.0.1 SSRF blocked")
    else:
        results.fail("validate_source: 10.0.0.1 SSRF blocked",
                      (False, "private"), (valid, msg))

    # SSRF: 192.168.x
    valid, msg = validate_source("http://192.168.1.1:8080/roms/")
    if not valid and "private" in msg.lower():
        results.ok("validate_source: 192.168.1.1 SSRF blocked")
    else:
        results.fail("validate_source: 192.168.1.1 SSRF blocked",
                      (False, "private"), (valid, msg))


# =============================================================================
# parse_url tests
# =============================================================================

def test_parse_url():
    print("\n--- parse_url ---")

    scheme, host, path = parse_url("https://example.com/roms/snes/")
    if scheme == "https" and host == "example.com" and path == "/roms/snes/":
        results.ok("parse_url: full URL")
    else:
        results.fail("parse_url: full URL", ("https", "example.com", "/roms/snes/"),
                      (scheme, host, path))

    scheme, host, path = parse_url("http://example.com")
    if scheme == "http" and host == "example.com" and path == "/":
        results.ok("parse_url: no path")
    else:
        results.fail("parse_url: no path", ("http", "example.com", "/"),
                      (scheme, host, path))

    scheme, host, path = parse_url("example.com/roms/")
    if scheme == "https" and host == "example.com" and path == "/roms/":
        results.ok("parse_url: no scheme defaults to https")
    else:
        results.fail("parse_url: no scheme defaults to https",
                      ("https", "example.com", "/roms/"), (scheme, host, path))

    scheme, host, path = parse_url("http://host:8080/path")
    if scheme == "http" and host == "host:8080" and path == "/path":
        results.ok("parse_url: with port")
    else:
        results.fail("parse_url: with port", ("http", "host:8080", "/path"),
                      (scheme, host, path))


# =============================================================================
# Scan cache tests
# =============================================================================

def test_scan_cache():
    print("\n--- scan_cache ---")

    with tempfile.TemporaryDirectory() as tmpdir:
        cache_dir = Path(tmpdir)
        url = "https://example.com/roms/"
        url_dict = {"snes": ["game1.zip", "game2.zip"]}
        url_sizes = {"game1.zip": 1000, "game2.zip": 2000}

        # Save and load round-trip
        save_scan_cache(cache_dir, url, url_dict, url_sizes)
        result = load_scan_cache(cache_dir, url)
        if result is not None:
            loaded_dict, loaded_sizes = result
            if loaded_dict == url_dict and loaded_sizes == url_sizes:
                results.ok("scan_cache: round-trip save/load")
            else:
                results.fail("scan_cache: round-trip save/load",
                              (url_dict, url_sizes), (loaded_dict, loaded_sizes))
        else:
            results.fail("scan_cache: round-trip save/load", "not None", None)

        # Non-existent URL returns None
        result = load_scan_cache(cache_dir, "https://other.com/")
        if result is None:
            results.ok("scan_cache: unknown URL returns None")
        else:
            results.fail("scan_cache: unknown URL returns None", None, result)

        # Non-existent cache dir returns None
        result = load_scan_cache(Path(tmpdir) / "nonexistent", url)
        if result is None:
            results.ok("scan_cache: missing cache dir returns None")
        else:
            results.fail("scan_cache: missing cache dir returns None", None, result)

        # Empty results NOT cached
        empty_url = "https://example.com/empty/"
        save_scan_cache(cache_dir, empty_url, {"snes": []}, {})
        result = load_scan_cache(cache_dir, empty_url)
        if result is None:
            results.ok("scan_cache: empty results not cached")
        else:
            results.fail("scan_cache: empty results not cached", None, result)

        # Expired cache returns None
        cache_path = cache_dir / "_scan_cache.json"
        with open(cache_path, 'r', encoding='utf-8') as f:
            cache_data = json.load(f)
        # Set timestamp to old
        for key in cache_data:
            cache_data[key]['timestamp'] = time.time() - SCAN_CACHE_MAX_AGE - 100
        with open(cache_path, 'w', encoding='utf-8') as f:
            json.dump(cache_data, f)
        result = load_scan_cache(cache_dir, url)
        if result is None:
            results.ok("scan_cache: expired cache returns None")
        else:
            results.fail("scan_cache: expired cache returns None", None, result)

    # Multiple URLs in same cache
    with tempfile.TemporaryDirectory() as tmpdir:
        cache_dir = Path(tmpdir)
        url1 = "https://example.com/roms/snes/"
        url2 = "https://example.com/roms/nes/"
        dict1 = {"snes": ["mario.zip"]}
        dict2 = {"nes": ["contra.zip"]}

        save_scan_cache(cache_dir, url1, dict1, {"mario.zip": 100})
        save_scan_cache(cache_dir, url2, dict2, {"contra.zip": 200})

        result1 = load_scan_cache(cache_dir, url1)
        result2 = load_scan_cache(cache_dir, url2)

        if result1 is not None and result1[0] == dict1:
            results.ok("scan_cache: multiple URLs - first")
        else:
            results.fail("scan_cache: multiple URLs - first", dict1,
                          result1[0] if result1 else None)

        if result2 is not None and result2[0] == dict2:
            results.ok("scan_cache: multiple URLs - second")
        else:
            results.fail("scan_cache: multiple URLs - second", dict2,
                          result2[0] if result2 else None)

    # Corrupt cache file
    with tempfile.TemporaryDirectory() as tmpdir:
        cache_dir = Path(tmpdir)
        cache_path = cache_dir / "_scan_cache.json"
        cache_path.write_text("not valid json{{{", encoding='utf-8')
        result = load_scan_cache(cache_dir, "https://example.com/")
        if result is None:
            results.ok("scan_cache: corrupt JSON returns None")
        else:
            results.fail("scan_cache: corrupt JSON returns None", None, result)


# =============================================================================
# archive.org and helper function tests
# =============================================================================

def test_archive_helpers():
    print("\n--- archive/helper functions ---")

    if is_archive_org_url("https://archive.org/download/snes-roms/"):
        results.ok("is_archive_org_url: archive.org URL")
    else:
        results.fail("is_archive_org_url: archive.org URL", True, False)

    if not is_archive_org_url("https://example.com/roms/"):
        results.ok("is_archive_org_url: non-archive URL")
    else:
        results.fail("is_archive_org_url: non-archive URL", False, True)

    # Auth header
    header = get_ia_auth_header("mykey", "mysecret")
    if header == "LOW mykey:mysecret":
        results.ok("get_ia_auth_header: valid keys")
    else:
        results.fail("get_ia_auth_header: valid keys", "LOW mykey:mysecret", header)

    header = get_ia_auth_header(None, None)
    if header is None:
        results.ok("get_ia_auth_header: no keys")
    else:
        results.fail("get_ia_auth_header: no keys", None, header)

    header = get_ia_auth_header("key", None)
    if header is None:
        results.ok("get_ia_auth_header: missing secret")
    else:
        results.fail("get_ia_auth_header: missing secret", None, header)

    header = get_ia_auth_header(None, "secret")
    if header is None:
        results.ok("get_ia_auth_header: missing access")
    else:
        results.fail("get_ia_auth_header: missing access", None, header)

    # T-En source detection
    if is_ten_source("https://archive.org/download/[T-En]%20Collection/"):
        results.ok("is_ten_source: T-En URL encoded")
    else:
        results.fail("is_ten_source: T-En URL encoded", True, False)

    if is_ten_source("https://example.com/t-en collection/"):
        results.ok("is_ten_source: T-En collection text")
    else:
        results.fail("is_ten_source: T-En collection text", True, False)

    if not is_ten_source("https://example.com/roms/snes/"):
        results.ok("is_ten_source: non-T-En URL")
    else:
        results.fail("is_ten_source: non-T-En URL", False, True)

    # Myrient TOSEC
    if is_myrient_tosec_url("https://myrient.erista.me/files/TOSEC/roms/"):
        results.ok("is_myrient_tosec_url: TOSEC URL")
    else:
        results.fail("is_myrient_tosec_url: TOSEC URL", True, False)

    if not is_myrient_tosec_url("https://myrient.erista.me/files/No-Intro/"):
        results.ok("is_myrient_tosec_url: non-TOSEC URL")
    else:
        results.fail("is_myrient_tosec_url: non-TOSEC URL", False, True)


# =============================================================================
# Shutdown mechanism tests
# =============================================================================

def test_shutdown_mechanism():
    print("\n--- shutdown mechanism ---")

    # Start clean
    reset_shutdown()

    # check_shutdown should NOT raise when clear
    try:
        check_shutdown()
        results.ok("shutdown: check_shutdown no-op when clear")
    except SystemExit:
        results.fail("shutdown: check_shutdown no-op when clear", "no exception", "SystemExit")

    # Request shutdown and verify check raises
    request_shutdown()
    try:
        check_shutdown()
        results.fail("shutdown: check_shutdown raises after request", "SystemExit", "no exception")
    except SystemExit:
        results.ok("shutdown: check_shutdown raises after request")

    # Reset clears the flag
    reset_shutdown()
    try:
        check_shutdown()
        results.ok("shutdown: reset clears flag")
    except SystemExit:
        results.fail("shutdown: reset clears flag", "no exception", "SystemExit")


# =============================================================================
# Edge case and integration tests
# =============================================================================

def test_edge_cases():
    print("\n--- edge cases ---")

    # normalize_url with http base and https link to same host
    result = normalize_url("https://example.com/file.zip", "http://example.com/roms/")
    if result == "https://example.com/file.zip":
        results.ok("normalize_url: cross-scheme same host")
    else:
        results.fail("normalize_url: cross-scheme same host",
                      "https://example.com/file.zip", result)

    # is_rom_file with double extension
    if is_rom_file("game.zip.bak"):
        results.fail("is_rom_file: .zip.bak should not match", False, True)
    else:
        results.ok("is_rom_file: .zip.bak not a ROM")

    # format_size edge: negative number (implementation handles as bytes < 1024)
    result = format_size(-1)
    if "B" in result:
        results.ok("format_size: negative number returns B")
    else:
        results.fail("format_size: negative number returns B", "contains B", result)

    # parse_budget_size with float
    result = parse_budget_size("1.5GB")
    if result == int(1.5 * 1024 ** 3):
        results.ok("parse_budget_size: float GB")
    else:
        results.fail("parse_budget_size: float GB", int(1.5 * 1024 ** 3), result)

    # is_directory_link edge: just a slash
    if is_directory_link("/"):
        results.ok("is_directory_link: bare slash")
    else:
        results.fail("is_directory_link: bare slash", True, False)

    # parse_size_string with KB suffix (includes B)
    result = parse_size_string("100KB")
    if result == 100 * 1024:
        results.ok("parse_size_string: 100KB full suffix")
    else:
        results.fail("parse_size_string: 100KB full suffix", 100 * 1024, result)

    # Extract links: data-file attribute
    html = '<div data-file="secret.zip">x</div>'
    links = extract_links_from_html(html)
    if "secret.zip" in links:
        results.ok("extract_links: data-file attribute")
    else:
        results.fail("extract_links: data-file attribute", "secret.zip in links", links)

    # parse_html_for_files_with_sizes: autoindex with sizes
    html = '''<pre>
<a href="rom.zip">rom.zip</a>                    01-Jan-2024 12:00  1234
</pre>'''
    base = "https://example.com/roms/"
    files = parse_html_for_files_with_sizes(html, base)
    if len(files) == 1:
        url, size = files[0]
        if "rom.zip" in url and size == 1234:
            results.ok("parse_files_with_sizes: autoindex with size")
        else:
            results.fail("parse_files_with_sizes: autoindex with size",
                          ("rom.zip URL", 1234), (url, size))
    else:
        results.fail("parse_files_with_sizes: autoindex with size", 1, len(files))

    # format_url with already decoded URL
    result = format_url("https://example.com/plain url.zip")
    if result == "https://example.com/plain url.zip":
        results.ok("format_url: already decoded URL unchanged")
    else:
        results.fail("format_url: already decoded URL unchanged",
                      "https://example.com/plain url.zip", result)

    # parse_budget_size edge: "0"
    result = parse_budget_size("0")
    if result == 0:
        results.ok("parse_budget_size: zero")
    else:
        results.fail("parse_budget_size: zero", 0, result)

    # is_rom_file with just an extension
    if is_rom_file(".zip"):
        results.ok("is_rom_file: bare extension")
    else:
        results.fail("is_rom_file: bare extension", True, False)

    # Myrient HTML: href key is decoded (unquoted), name key also present
    sizes = extract_file_sizes_from_html(MYRIENT_HTML)
    # Both decoded href and display name should be keys (they are the same after unquoting)
    found_name_key = "Super Mario World.zip" in sizes
    found_zelda_key = "Zelda.zip" in sizes
    if found_name_key and found_zelda_key:
        results.ok("extract_file_sizes: decoded href and name keys present")
    else:
        results.fail("extract_file_sizes: decoded href and name keys present",
                      "both keys present", f"name={found_name_key}, zelda={found_zelda_key}")


# =============================================================================
# Main
# =============================================================================

if __name__ == '__main__':
    test_is_url()
    test_get_filename_from_url()
    test_normalize_url()
    test_is_rom_file()
    test_is_directory_link()
    test_format_url()
    test_format_size()
    test_parse_size_string()
    test_parse_budget_size()
    test_extract_links_from_html()
    test_extract_file_sizes_from_html()
    test_parse_html_for_files_with_sizes()
    test_parse_html_for_files()
    test_parse_html_for_directories()
    test_is_private_ip()
    test_is_private_host()
    test_validate_source()
    test_parse_url()
    test_scan_cache()
    test_archive_helpers()
    test_shutdown_mechanism()
    test_edge_cases()
    success = results.summary()
    sys.exit(0 if success else 1)

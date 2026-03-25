#!/usr/bin/env python3
"""Comprehensive tests for retro_refiner/network.py.

Covers every public function: URL utilities, size parsing, HTML parsing,
SSRF validation, scan cache, and helper functions.
"""

import json
import os
import sys
import time
from pathlib import Path

import pytest

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

@pytest.mark.parametrize("url,expected", [
    ("http://example.com", True),
    ("https://example.com/roms/snes/", True),
    ("/home/user/roms", False),
    ("C:\\Users\\roms", False),
    ("", False),
    ("ftp://example.com", False),
    ("file:///etc/passwd", False),
])
def test_is_url(url, expected):
    assert is_url(url) == expected


# =============================================================================
# get_filename_from_url tests
# =============================================================================

@pytest.mark.parametrize("url,expected", [
    ("https://example.com/roms/game.zip", "game.zip"),
    ("https://example.com/roms/Super%20Mario%20World.zip", "Super Mario World.zip"),
    ("https://example.com/roms/game.zip?key=value&other=1", "game.zip"),
    ("https://example.com/roms/game.zip#section", "game.zip"),
    ("https://example.com/roms/game.zip?dl=1#top", "game.zip"),
    ("https://example.com/a/b/c/deep_file.7z", "deep_file.7z"),
])
def test_get_filename_from_url(url, expected):
    assert get_filename_from_url(url) == expected


def test_get_filename_from_url_unicode():
    result = get_filename_from_url(
        "https://example.com/roms/T%C3%A9tris%20%28Japan%29.zip")
    assert "tris" in result
    assert "(Japan)" in result


# =============================================================================
# normalize_url tests
# =============================================================================

class TestNormalizeUrl:
    BASE = "https://example.com/roms/snes/"

    @pytest.mark.parametrize("href,expected", [
        ("game.zip", "https://example.com/roms/snes/game.zip"),
        ("/other/file.zip", "https://example.com/other/file.zip"),
        ("https://example.com/roms/nes/game.zip",
         "https://example.com/roms/nes/game.zip"),
        ("//example.com/roms/file.zip",
         "https://example.com/roms/file.zip"),
        ("../nes/game.zip", "https://example.com/roms/nes/game.zip"),
    ])
    def test_valid_urls(self, href, expected):
        assert normalize_url(href, self.BASE) == expected

    @pytest.mark.parametrize("href", [
        "https://other.com/roms/game.zip",
        "#section",
        "javascript:void(0)",
        "mailto:user@example.com",
        "data:text/plain;base64,abc",
        ".", "..", "../", "./",
        "?sort=name",
        "",
    ])
    def test_rejected_urls(self, href):
        assert normalize_url(href, self.BASE) is None

    def test_html_entity_decoding(self):
        result = normalize_url("game.zip?a=1&amp;b=2", self.BASE)
        assert result is not None
        assert "&amp;" not in result
        assert "&" in result

    def test_base_without_trailing_slash(self):
        result = normalize_url("game.zip",
                               "https://example.com/roms/snes")
        assert result == "https://example.com/roms/game.zip"


# =============================================================================
# is_rom_file tests
# =============================================================================

class TestIsRomFile:
    ROM_EXTENSIONS = [
        '.zip', '.7z', '.rar', '.nes', '.sfc', '.smc', '.gba',
        '.gb', '.gbc', '.n64', '.iso', '.chd', '.nds', '.cue',
        '.pbp', '.cso', '.nsp', '.xci',
    ]
    NON_ROM_EXTENSIONS = [
        '.html', '.htm', '.css', '.js', '.png', '.jpg', '.txt',
        '.xml', '.pdf', '.exe', '.py',
    ]

    @pytest.mark.parametrize("ext", ROM_EXTENSIONS)
    def test_rom_extension_accepted(self, ext):
        assert is_rom_file(f"game{ext}")

    @pytest.mark.parametrize("ext", NON_ROM_EXTENSIONS)
    def test_non_rom_extension_rejected(self, ext):
        assert not is_rom_file(f"file{ext}")

    @pytest.mark.parametrize("filename", [
        "GAME.ZIP", "game.Zip",
        "game.zip?download=true", "game.zip#section",
        "Super%20Mario%20World.zip",
    ])
    def test_edge_cases_accepted(self, filename):
        assert is_rom_file(filename)


# =============================================================================
# is_directory_link tests
# =============================================================================

@pytest.mark.parametrize("link,expected", [
    ("subdir/", True),
    ("https://example.com/roms/snes/", True),
    ("game.zip", False),
    ("subdir", True),
    ("game.zip?sort=name", False),
    ("folder-name", True),
])
def test_is_directory_link(link, expected):
    assert is_directory_link(link) == expected


# =============================================================================
# format_url tests
# =============================================================================

def test_format_url_decodes_percent_encoding():
    assert format_url("https://example.com/roms/Super%20Mario.zip") == \
        "https://example.com/roms/Super Mario.zip"


def test_format_url_no_encoding():
    assert format_url("https://example.com/roms/game.zip") == \
        "https://example.com/roms/game.zip"


def test_format_url_truncation():
    result = format_url("https://example.com/roms/game.zip", max_length=20)
    assert result.endswith("...")
    assert len(result) == 20


def test_format_url_max_length_zero():
    assert format_url("https://example.com/roms/game.zip", max_length=0) == \
        "https://example.com/roms/game.zip"


def test_format_url_shorter_than_max():
    assert format_url("short", max_length=100) == "short"


# =============================================================================
# format_size tests
# =============================================================================

@pytest.mark.parametrize("size,expected", [
    (0, "0 Bytes"),
    (500, "500 Bytes"),
    (1023, "1023 Bytes"),
    (1024, "1.0 KiB"),
    (1536, "1.5 KiB"),
    (1048576, "1.0 MiB"),
    (1073741824, "1.0 GiB"),
    (1099511627776, "1.0 TiB"),
    (1, "1 Byte"),
])
def test_format_size(size, expected):
    assert format_size(size) == expected


def test_format_size_5gb():
    assert "5.0 GiB" in format_size(5 * 1024 * 1024 * 1024)


# =============================================================================
# parse_size_string tests
# =============================================================================

@pytest.mark.parametrize("input_str,expected", [
    ("1.5M", int(1.5 * 1024 * 1024)),
    ("100K", 100 * 1024),
    ("50G", 50 * 1024 * 1024 * 1024),
    ("1234", 1234),
    ("1.5 MB", int(1.5 * 1024 * 1024)),
    ("175.9 MiB", int(175.9 * 1024 * 1024)),
    ("2T", 2 * 1024 ** 4),
    ("", 0),
    ("not_a_size", 0),
    ("0", 0),
    ("10KB", 10 * 1024),
    ("2.5GB", int(2.5 * 1024 ** 3)),
])
def test_parse_size_string(input_str, expected):
    assert parse_size_string(input_str) == expected


# =============================================================================
# parse_budget_size tests
# =============================================================================

@pytest.mark.parametrize("input_str,expected", [
    ("10GB", int(10 * 1024 ** 3)),
    ("500MB", int(500 * 1024 ** 2)),
    ("1TB", 1024 ** 4),
    ("256KB", 256 * 1024),
    ("", None),
    (None, None),
    ("not_a_size", None),
    ("1024", 1024),
    ("1.5G", int(1.5 * 1024 ** 3)),
    ("100B", 100),
    ("  500MB  ", int(500 * 1024 ** 2)),
    ("500mb", int(500 * 1024 ** 2)),
])
def test_parse_budget_size(input_str, expected):
    assert parse_budget_size(input_str) == expected


# =============================================================================
# extract_links_from_html tests
# =============================================================================

class TestExtractLinksFromHtml:
    def test_href_tag(self):
        links = extract_links_from_html('<a href="game.zip">game</a>')
        assert "game.zip" in links

    def test_src_rom_extension(self):
        links = extract_links_from_html('<img src="rom.zip">')
        assert "rom.zip" in links

    def test_src_non_rom_ignored(self):
        links = extract_links_from_html('<img src="image.png">')
        assert "image.png" not in links

    def test_data_url_attribute(self):
        links = extract_links_from_html(
            '<div data-url="download.zip">click</div>')
        assert "download.zip" in links

    def test_data_href_attribute(self):
        links = extract_links_from_html(
            '<div data-href="rom.7z">click</div>')
        assert "rom.7z" in links

    def test_onclick_handler(self):
        html = "<button onclick=\"location.href='game.zip'\">Download</button>"
        links = extract_links_from_html(html)
        assert "game.zip" in links

    def test_multiple_hrefs(self):
        html = ('<a href="a.zip">a</a><a href="b.7z">b</a>'
                '<a href="c.nes">c</a>')
        links = extract_links_from_html(html)
        assert "a.zip" in links
        assert "b.7z" in links
        assert "c.nes" in links

    def test_text_files_in_pre_block(self):
        html = '<pre>Super Mario World.zip\n  Zelda.7z\n</pre>'
        links = extract_links_from_html(html)
        assert any("Super Mario World.zip" in l for l in links)

    def test_empty_html(self):
        assert extract_links_from_html("") == []


# =============================================================================
# extract_file_sizes_from_html tests
# =============================================================================

class TestExtractFileSizesFromHtml:
    def test_myrient_format_mario_size(self):
        sizes = extract_file_sizes_from_html(MYRIENT_HTML)
        assert sizes["Super Mario World.zip"] == int(1.5 * 1024 * 1024)

    def test_myrient_format_zelda_size(self):
        sizes = extract_file_sizes_from_html(MYRIENT_HTML)
        assert sizes["Zelda.zip"] == int(2.3 * 1024 * 1024)

    def test_myrient_format_decoded_href_key(self):
        sizes = extract_file_sizes_from_html(MYRIENT_HTML)
        assert "Super Mario World.zip" in sizes

    def test_autoindex_format(self):
        sizes = extract_file_sizes_from_html(AUTOINDEX_HTML)
        assert sizes["rom.zip"] == 1234
        assert sizes["game.7z"] == 5678

    def test_autoindex_alt_date_format(self):
        sizes = extract_file_sizes_from_html(AUTOINDEX_HTML_ALT)
        assert sizes["big_rom.iso"] == 2048000

    def test_generic_table_format(self):
        sizes = extract_file_sizes_from_html(GENERIC_TABLE_HTML)
        assert sizes["game1.zip"] == 1048576
        assert sizes["game2.7z"] == 2097152

    def test_ftp_listing_format(self):
        sizes = extract_file_sizes_from_html(FTP_LISTING_HTML)
        assert sizes["rom_file.zip"] == 1536000
        assert sizes["another.7z"] == 512000

    def test_simple_format(self):
        sizes = extract_file_sizes_from_html(SIMPLE_SIZE_HTML)
        assert sizes["game.zip"] == 1048576

    def test_empty_html(self):
        assert extract_file_sizes_from_html("") == {}

    def test_myrient_dash_size_ignored(self):
        html = '''<table><tr>
        <td class="link"><a href="subdir/">subdir/</a></td>
        <td class="size">-</td></tr></table>'''
        sizes = extract_file_sizes_from_html(html)
        assert "subdir/" not in sizes


# =============================================================================
# parse_html_for_files_with_sizes tests
# =============================================================================

class TestParseHtmlForFilesWithSizes:
    BASE = "https://example.com/roms/snes/"

    def test_mario_url_found(self):
        files = parse_html_for_files_with_sizes(MYRIENT_HTML, self.BASE)
        urls = [url for url, _ in files]
        assert "https://example.com/roms/snes/Super%20Mario%20World.zip" in urls

    def test_zelda_url_found(self):
        files = parse_html_for_files_with_sizes(MYRIENT_HTML, self.BASE)
        urls = [url for url, _ in files]
        assert "https://example.com/roms/snes/Zelda.zip" in urls

    def test_mario_has_size(self):
        files = parse_html_for_files_with_sizes(MYRIENT_HTML, self.BASE)
        sizes = {url: sz for url, sz in files}
        mario_url = "https://example.com/roms/snes/Super%20Mario%20World.zip"
        assert mario_url in sizes
        assert sizes[mario_url] > 0

    def test_readme_excluded(self):
        files = parse_html_for_files_with_sizes(MYRIENT_HTML, self.BASE)
        urls = [url for url, _ in files]
        assert not any("readme" in u for u in urls)

    def test_no_duplicates(self):
        files = parse_html_for_files_with_sizes(MYRIENT_HTML, self.BASE)
        urls = [url for url, _ in files]
        assert len(urls) == len(set(urls))

    def test_empty_html(self):
        assert parse_html_for_files_with_sizes("", self.BASE) == []


# =============================================================================
# parse_html_for_files tests
# =============================================================================

def test_parse_html_for_files_finds_rom_skips_non_rom():
    base = "https://example.com/roms/snes/"
    html = '<a href="game.zip">game.zip</a><a href="readme.txt">readme</a>'
    files = parse_html_for_files(html, base)
    assert len(files) == 1
    assert "game.zip" in files[0]


def test_parse_html_for_files_deduplicates():
    base = "https://example.com/roms/snes/"
    html = '<a href="game.zip">link1</a><a href="game.zip">link2</a>'
    files = parse_html_for_files(html, base)
    assert len(files) == 1


# =============================================================================
# parse_html_for_directories tests
# =============================================================================

class TestParseHtmlForDirectories:
    BASE = "https://example.com/roms/"

    def test_subdir_found(self):
        dirs = parse_html_for_directories(DIRECTORY_HTML, self.BASE)
        assert "https://example.com/roms/subdir/" in dirs

    def test_another_dir_found(self):
        dirs = parse_html_for_directories(DIRECTORY_HTML, self.BASE)
        assert "https://example.com/roms/another_dir/" in dirs

    def test_parent_dir_excluded(self):
        dirs = parse_html_for_directories(DIRECTORY_HTML, self.BASE)
        parent_urls = [d for d in dirs
                       if d.endswith("/../") or d == self.BASE]
        assert not parent_urls

    def test_file_links_excluded(self):
        dirs = parse_html_for_directories(DIRECTORY_HTML, self.BASE)
        assert not any("game.zip" in d for d in dirs)

    def test_empty_html(self):
        assert parse_html_for_directories("", self.BASE) == []

    def test_external_dirs_excluded(self):
        html = '<a href="https://other.com/dir/">external</a>'
        assert parse_html_for_directories(html, self.BASE) == []


# =============================================================================
# _is_private_ip tests
# =============================================================================

@pytest.mark.parametrize("ip,expected", [
    # Loopback
    ("127.0.0.1", True),
    ("127.0.0.99", True),
    # 10.x.x.x
    ("10.0.0.1", True),
    ("10.255.255.255", True),
    # 192.168.x.x
    ("192.168.0.1", True),
    ("192.168.255.255", True),
    # 172.16-31.x.x
    ("172.16.0.1", True),
    ("172.31.255.255", True),
    # NOT private: 172.15 and 172.32
    ("172.15.0.1", False),
    ("172.32.0.1", False),
    # IPv6 loopback
    ("::1", True),
    ("[::1]", True),
    # 0.x.x.x
    ("0.0.0.0", True),
    # Public IPs
    ("8.8.8.8", False),
    ("93.184.216.34", False),
    # Empty string
    ("", True),
])
def test_is_private_ip(ip, expected):
    assert _is_private_ip(ip) == expected


# =============================================================================
# _is_private_host tests
# =============================================================================

@pytest.mark.parametrize("host,expected", [
    ("localhost", True),
    ("[::1]", True),
    ("127.0.0.1", True),
    ("10.0.0.1", True),
    ("192.168.1.1", True),
])
def test_is_private_host(host, expected):
    assert _is_private_host(host) == expected


# =============================================================================
# validate_source tests
# =============================================================================

def test_validate_source_valid_local_dir(tmp_path):
    valid, msg = validate_source(str(tmp_path))
    assert valid is True
    assert msg == ""


def test_validate_source_nonexistent_path():
    valid, msg = validate_source("/nonexistent/path/nowhere")
    assert valid is False
    assert "does not exist" in msg


def test_validate_source_file_not_dir(tmp_path):
    tmpfile = tmp_path / "testfile"
    tmpfile.write_text("x")
    valid, msg = validate_source(str(tmpfile))
    assert valid is False
    assert "not a directory" in msg


@pytest.mark.parametrize("url", [
    "http://localhost/roms/",
    "http://127.0.0.1/roms/",
    "http://10.0.0.1/roms/",
    "http://192.168.1.1:8080/roms/",
])
def test_validate_source_ssrf_blocked(url):
    valid, msg = validate_source(url)
    assert valid is False
    assert "private" in msg.lower()


# =============================================================================
# parse_url tests
# =============================================================================

@pytest.mark.parametrize("url,expected", [
    ("https://example.com/roms/snes/",
     ("https", "example.com", "/roms/snes/")),
    ("http://example.com", ("http", "example.com", "/")),
    ("example.com/roms/", ("https", "example.com", "/roms/")),
    ("http://host:8080/path", ("http", "host:8080", "/path")),
])
def test_parse_url(url, expected):
    assert parse_url(url) == expected


# =============================================================================
# Scan cache tests
# =============================================================================

class TestScanCache:
    def test_round_trip(self, tmp_path):
        url = "https://example.com/roms/"
        url_dict = {"snes": ["game1.zip", "game2.zip"]}
        url_sizes = {"game1.zip": 1000, "game2.zip": 2000}

        save_scan_cache(tmp_path, url, url_dict, url_sizes)
        result = load_scan_cache(tmp_path, url)
        assert result is not None
        loaded_dict, loaded_sizes = result
        assert loaded_dict == url_dict
        assert loaded_sizes == url_sizes

    def test_unknown_url_returns_none(self, tmp_path):
        url_dict = {"snes": ["game.zip"]}
        save_scan_cache(tmp_path, "https://example.com/", url_dict, {})
        result = load_scan_cache(tmp_path, "https://other.com/")
        assert result is None

    def test_missing_cache_dir_returns_none(self, tmp_path):
        result = load_scan_cache(tmp_path / "nonexistent",
                                 "https://example.com/")
        assert result is None

    def test_empty_results_not_cached(self, tmp_path):
        save_scan_cache(tmp_path, "https://example.com/empty/",
                        {"snes": []}, {})
        result = load_scan_cache(tmp_path, "https://example.com/empty/")
        assert result is None

    def test_expired_cache_returns_none(self, tmp_path):
        url = "https://example.com/roms/"
        save_scan_cache(tmp_path, url,
                        {"snes": ["game.zip"]}, {"game.zip": 100})

        cache_path = tmp_path / "_scan_cache.json"
        with open(cache_path, 'r', encoding='utf-8') as f:
            cache_data = json.load(f)
        for key in cache_data:
            cache_data[key]['timestamp'] = (
                time.time() - SCAN_CACHE_MAX_AGE - 100)
        with open(cache_path, 'w', encoding='utf-8') as f:
            json.dump(cache_data, f)

        assert load_scan_cache(tmp_path, url) is None

    def test_multiple_urls(self, tmp_path):
        url1 = "https://example.com/roms/snes/"
        url2 = "https://example.com/roms/nes/"
        dict1 = {"snes": ["mario.zip"]}
        dict2 = {"nes": ["contra.zip"]}

        save_scan_cache(tmp_path, url1, dict1, {"mario.zip": 100})
        save_scan_cache(tmp_path, url2, dict2, {"contra.zip": 200})

        result1 = load_scan_cache(tmp_path, url1)
        result2 = load_scan_cache(tmp_path, url2)
        assert result1 is not None and result1[0] == dict1
        assert result2 is not None and result2[0] == dict2

    def test_corrupt_json_returns_none(self, tmp_path):
        cache_path = tmp_path / "_scan_cache.json"
        cache_path.write_text("not valid json{{{", encoding='utf-8')
        assert load_scan_cache(tmp_path, "https://example.com/") is None


# =============================================================================
# archive.org and helper function tests
# =============================================================================

@pytest.mark.parametrize("url,expected", [
    ("https://archive.org/download/snes-roms/", True),
    ("https://example.com/roms/", False),
])
def test_is_archive_org_url(url, expected):
    assert is_archive_org_url(url) == expected


@pytest.mark.parametrize("access,secret,expected", [
    ("mykey", "mysecret", "LOW mykey:mysecret"),
    (None, None, None),
    ("key", None, None),
    (None, "secret", None),
])
def test_get_ia_auth_header(access, secret, expected):
    assert get_ia_auth_header(access, secret) == expected


@pytest.mark.parametrize("url,expected", [
    ("https://archive.org/download/[T-En]%20Collection/", True),
    ("https://example.com/t-en collection/", True),
    ("https://example.com/roms/snes/", False),
])
def test_is_ten_source(url, expected):
    assert is_ten_source(url) == expected


@pytest.mark.parametrize("url,expected", [
    ("https://myrient.erista.me/files/TOSEC/roms/", True),
    ("https://myrient.erista.me/files/No-Intro/", False),
])
def test_is_myrient_tosec_url(url, expected):
    assert is_myrient_tosec_url(url) == expected


# =============================================================================
# Shutdown mechanism tests
# =============================================================================

class TestShutdownMechanism:
    def setup_method(self):
        reset_shutdown()

    def test_check_shutdown_no_op_when_clear(self):
        check_shutdown()  # should not raise

    def test_check_shutdown_raises_after_request(self):
        request_shutdown()
        with pytest.raises(SystemExit):
            check_shutdown()

    def test_reset_clears_flag(self):
        request_shutdown()
        reset_shutdown()
        check_shutdown()  # should not raise


# =============================================================================
# Edge case and integration tests
# =============================================================================

def test_normalize_url_cross_scheme_same_host():
    result = normalize_url("https://example.com/file.zip",
                           "http://example.com/roms/")
    assert result == "https://example.com/file.zip"


def test_is_rom_file_double_extension():
    assert not is_rom_file("game.zip.bak")


def test_format_size_negative():
    assert "Byte" in format_size(-1)


def test_parse_budget_size_float_gb():
    assert parse_budget_size("1.5GB") == int(1.5 * 1024 ** 3)


def test_is_directory_link_bare_slash():
    assert is_directory_link("/")


def test_parse_size_string_100kb_full_suffix():
    assert parse_size_string("100KB") == 100 * 1024


def test_extract_links_data_file_attribute():
    html = '<div data-file="secret.zip">x</div>'
    links = extract_links_from_html(html)
    assert "secret.zip" in links


def test_parse_files_with_sizes_autoindex():
    html = '''<pre>
<a href="rom.zip">rom.zip</a>                    01-Jan-2024 12:00  1234
</pre>'''
    base = "https://example.com/roms/"
    files = parse_html_for_files_with_sizes(html, base)
    assert len(files) == 1
    url, size = files[0]
    assert "rom.zip" in url
    assert size == 1234


def test_format_url_already_decoded():
    assert format_url("https://example.com/plain url.zip") == \
        "https://example.com/plain url.zip"


def test_parse_budget_size_zero():
    assert parse_budget_size("0") == 0


def test_is_rom_file_bare_extension():
    assert is_rom_file(".zip")


def test_myrient_decoded_href_and_name_keys():
    sizes = extract_file_sizes_from_html(MYRIENT_HTML)
    assert "Super Mario World.zip" in sizes
    assert "Zelda.zip" in sizes

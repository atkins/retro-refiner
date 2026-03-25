"""DAT file operations: loading, parsing, CRC verification, title normalization.

Standalone implementations extracted from the monolith.  Console output is
replaced by plain stderr for errors; verbose callbacks come from callers.
"""
import binascii
import io
import json
import re
import shutil
import sys
import threading
import time
import unicodedata
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional

from retro_refiner.paths import get_base_path
from retro_refiner.systems import load_system_data


# =============================================================================
# Dataclasses
# =============================================================================

@dataclass
class RomInfo:
    """Parsed ROM metadata from a filename."""
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
    has_hacks: bool = False
    year: int = 0
    disc_number: int = 0


@dataclass
class DatRomEntry:
    """ROM entry from a DAT file."""
    name: str
    rom_name: str
    size: int
    crc: str
    md5: str
    sha1: str
    region: str
    is_parent: bool
    parent_name: str


# =============================================================================
# Title Mappings
# =============================================================================

_title_mappings_cache: Optional[Dict[str, str]] = None


def load_title_mappings() -> Dict[str, str]:
    """Load title mappings from data/title_mappings.json.

    Returns a flat dict of {source_title: target_title}.
    Caches the result for subsequent calls.
    """
    global _title_mappings_cache  # pylint: disable=global-statement

    if _title_mappings_cache is not None:
        return _title_mappings_cache

    mappings_path = get_base_path() / 'data' / 'title_mappings.json'
    flat_mappings = {}

    if mappings_path.exists():
        try:
            with open(mappings_path, 'r', encoding='utf-8') as fh:
                data = json.load(fh)
            for category, entries in data.items():
                if category.startswith('_'):
                    continue
                if isinstance(entries, dict):
                    flat_mappings.update(entries)
        except (json.JSONDecodeError, IOError) as exc:
            print(f"WARNING: Could not load title_mappings.json: {exc}",
                  file=sys.stderr)

    _title_mappings_cache = flat_mappings
    return flat_mappings


def reset_title_mappings_cache() -> None:
    """Clear the title mappings cache (used in tests)."""
    global _title_mappings_cache  # pylint: disable=global-statement
    _title_mappings_cache = None


# =============================================================================
# Title Normalization
# =============================================================================

# Pre-compiled patterns used in normalize_title()
_RE_ARTICLE_COMMA = re.compile(r',\s*(the|a|an)\s*')
_RE_ARTICLE_START = re.compile(r'^(the|a|an)\s+')
_RE_PUNCTUATION = re.compile(r'[:\-\'.,]')
_RE_WHITESPACE_NORM = re.compile(r'\s+')
_RE_ROMAN_NUMERALS = [
    (re.compile(r'\bviii\b'), '8'), (re.compile(r'\bvii\b'), '7'),
    (re.compile(r'\bvi\b'), '6'), (re.compile(r'\biv\b'), '4'),
    (re.compile(r'\bv\b'), '5'), (re.compile(r'\biii\b'), '3'),
    (re.compile(r'\bii\b'), '2'), (re.compile(r'\bi\b'), '1'),
]


def normalize_title(title: str, strip_articles: bool = True) -> str:
    """Normalize a ROM title for grouping.

    Lowercases, strips punctuation, converts Roman numerals to Arabic,
    and applies title mappings from data/title_mappings.json.

    Args:
        title: The ROM title to normalize.
        strip_articles: If True (default), strip leading articles
            (the/a/an) and handle "Title, The" patterns.  Set to
            False for cross-platform dedupe to avoid false positives
            like 'The Bully' colliding with 'Bully'.
    """
    normalized = title.lower()

    # Strip accented characters to ASCII equivalents
    normalized = unicodedata.normalize('NFKD', normalized)
    normalized = ''.join(c for c in normalized if not unicodedata.combining(c))

    # Handle "Title, The" pattern (only when stripping articles)
    if strip_articles:
        normalized = _RE_ARTICLE_COMMA.sub(' ', normalized)
        normalized = _RE_ARTICLE_START.sub('', normalized)

    # Normalize punctuation
    normalized = _RE_PUNCTUATION.sub(' ', normalized)
    normalized = _RE_WHITESPACE_NORM.sub(' ', normalized)
    normalized = normalized.strip()

    # Normalize roman numerals to arabic
    for pattern, replacement in _RE_ROMAN_NUMERALS:
        normalized = pattern.sub(replacement, normalized)

    # Apply title mappings (O(1) dict lookup)
    title_mappings = load_title_mappings()
    if normalized in title_mappings:
        normalized = title_mappings[normalized]

    return normalized


def normalize_title_for_dedupe(title: str) -> str:
    """Normalize a title for cross-platform dedupe (preserves leading articles).

    Same as normalize_title() but skips article stripping to avoid false
    positives like 'The Bully' (DOS) colliding with 'Bully' (PS2).
    """
    return normalize_title(title, strip_articles=False)


# =============================================================================
# DAT URL construction
# =============================================================================

# Base URLs for DATs in libretro-database
LIBRETRO_DB_NOINTRO_URL = (
    "https://raw.githubusercontent.com/libretro/"
    "libretro-database/master/metadat/no-intro"
)
LIBRETRO_DB_DAT_URL = (
    "https://raw.githubusercontent.com/libretro/"
    "libretro-database/master/dat"
)
LIBRETRO_DB_REDUMP_URL = (
    "https://raw.githubusercontent.com/libretro/"
    "libretro-database/master/metadat/redump"
)

# Base URL for T-En DAT files
TEN_DAT_BASE_URL = "https://archive.org/download/En-ROMs/DATs/"


def get_libretro_dat_url(system: str) -> list:
    """Get possible libretro DAT URLs for a system (returns list to try).

    For disc-based systems (in REDUMP_DAT_SYSTEMS), tries the Redump URL
    first since the dat/ folder may contain a stub file instead of the full
    DAT.
    """
    sdata = load_system_data()
    dat_name = sdata.libretro_dat_systems.get(system)
    if not dat_name:
        return []

    encoded_name = urllib.request.quote(dat_name)

    if system in sdata.redump_dat_systems:
        return [
            f"{LIBRETRO_DB_REDUMP_URL}/{encoded_name}.dat",
            f"{LIBRETRO_DB_DAT_URL}/{encoded_name}.dat",
            f"{LIBRETRO_DB_NOINTRO_URL}/{encoded_name}.dat",
        ]

    return [
        f"{LIBRETRO_DB_NOINTRO_URL}/{encoded_name}.dat",
        f"{LIBRETRO_DB_DAT_URL}/{encoded_name}.dat",
        f"{LIBRETRO_DB_REDUMP_URL}/{encoded_name}.dat",
    ]


# =============================================================================
# DAT Download Functions
# =============================================================================

def download_libretro_dat(system: str, dest_dir: Path,
                          force: bool = False,
                          on_progress: Callable = None) -> Optional[Path]:
    """Download libretro DAT file for a system.

    Returns the path to the downloaded file, or None on failure.
    """
    _ = on_progress  # Reserved for future progress reporting
    urls = get_libretro_dat_url(system)
    if not urls:
        print(f"ERROR: No DAT mapping for: {system}", file=sys.stderr)
        return None

    dest_dir.mkdir(parents=True, exist_ok=True)
    dat_path = dest_dir / f"{system}.dat"

    if dat_path.exists() and not force:
        return dat_path

    if dat_path.exists() and force:
        dat_path.unlink()

    for url in urls:
        try:
            req = urllib.request.Request(
                url, headers={'User-Agent': 'Retro-Refiner/1.0'})
            with urllib.request.urlopen(req, timeout=30) as response:
                with open(dat_path, 'wb') as fh:
                    shutil.copyfileobj(response, fh)
            return dat_path
        except urllib.error.HTTPError:
            continue
        except Exception:  # pylint: disable=broad-except
            continue

    print(f"ERROR: Failed to download DAT for: {system}", file=sys.stderr)
    return None


def download_additional_dats(system: str, dest_dir: Path,
                             force: bool = False) -> List[Path]:
    """Download additional DAT files for a system (digital/PSN variants)."""
    sdata = load_system_data()
    additional_names = sdata.additional_dat_systems.get(system, [])
    if not additional_names:
        return []

    dest_dir.mkdir(parents=True, exist_ok=True)
    downloaded = []

    for i, dat_name in enumerate(additional_names, 1):
        dat_path = dest_dir / f"{system}_extra{i}.dat"
        if dat_path.exists() and not force:
            downloaded.append(dat_path)
            continue

        if dat_path.exists() and force:
            dat_path.unlink()

        encoded = urllib.request.quote(dat_name)
        urls = [
            f"{LIBRETRO_DB_NOINTRO_URL}/{encoded}.dat",
            f"{LIBRETRO_DB_DAT_URL}/{encoded}.dat",
        ]
        for url in urls:
            try:
                req = urllib.request.Request(
                    url, headers={'User-Agent': 'Retro-Refiner/1.0'})
                with urllib.request.urlopen(req, timeout=30) as response:
                    with open(dat_path, 'wb') as fh:
                        shutil.copyfileobj(response, fh)
                downloaded.append(dat_path)
                break
            except Exception:  # pylint: disable=broad-except
                continue

    return downloaded


# =============================================================================
# T-En DAT support
# =============================================================================

# is_ten_source lives in network.py — import from there if needed.
from retro_refiner.network import is_ten_source  # pylint: disable=unused-import  # re-export


def fetch_ten_dat_listing() -> Dict[str, str]:
    """Fetch the T-En DAT directory listing from Archive.org.

    Returns a dict mapping system prefix to ZIP filename.
    """
    try:
        req = urllib.request.Request(
            TEN_DAT_BASE_URL,
            headers={'User-Agent': 'Retro-Refiner/1.0'})
        with urllib.request.urlopen(req, timeout=30) as response:
            html = response.read().decode('utf-8', errors='ignore')

        zip_files = {}

        for match in re.finditer(r'href="([^"]+\.zip)"', html):
            href = urllib.request.unquote(match.group(1))
            if '[T-En] Collection' in href:
                prefix = href.split(' [T-En] Collection')[0]
                zip_files[prefix] = href

        for match in re.finditer(r'<td>([^<]+\.zip)</td>', html):
            filename = match.group(1)
            if '[T-En] Collection' in filename:
                prefix = filename.split(' [T-En] Collection')[0]
                if prefix not in zip_files:
                    zip_files[prefix] = filename

        return zip_files
    except Exception:  # pylint: disable=broad-except
        return {}


def download_ten_dat(system: str, dest_dir: Path, force: bool = False,
                     auth_header: Optional[str] = None,
                     listing_cache: Optional[Dict[str, str]] = None
                     ) -> Optional[Path]:
    """Download T-En DAT file for a system from Archive.org.

    T-En DATs are ZIP files containing a DAT file inside.
    Requires Archive.org authentication (auth_header).
    """
    sdata = load_system_data()
    dat_prefix = sdata.ten_dat_systems.get(system)
    if not dat_prefix:
        return None

    dest_dir.mkdir(parents=True, exist_ok=True)
    dat_path = dest_dir / f"{system}_t-en.dat"

    if dat_path.exists() and not force:
        return dat_path

    if listing_cache is not None:
        zip_filename = listing_cache.get(dat_prefix)
    else:
        listing = fetch_ten_dat_listing()
        zip_filename = listing.get(dat_prefix)

    if not zip_filename:
        return None

    zip_url = (TEN_DAT_BASE_URL
               + urllib.request.quote(zip_filename, safe='[]()-'))

    headers = {'User-Agent': 'Retro-Refiner/1.0'}
    if auth_header:
        headers['Authorization'] = auth_header

    max_retries = 3
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(zip_url, headers=headers)
            with urllib.request.urlopen(req, timeout=60) as response:
                zip_data = response.read()

            with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
                dat_files = [n for n in zf.namelist()
                             if n.lower().endswith('.dat')]
                if not dat_files:
                    return None

                with zf.open(dat_files[0]) as src:
                    with open(dat_path, 'wb') as dst:
                        shutil.copyfileobj(src, dst)

            return dat_path

        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            if attempt < max_retries - 1:
                time.sleep((attempt + 1) * 2)
            else:
                return None
        except Exception:  # pylint: disable=broad-except
            if attempt < max_retries - 1:
                time.sleep((attempt + 1) * 2)
            else:
                return None

    return None


# =============================================================================
# DAT Parsing
# =============================================================================

def detect_dat_region(name: str) -> str:
    """Detect region from DAT game name."""
    name_lower = name.lower()
    if '(usa)' in name_lower or '(us)' in name_lower:
        return 'USA'
    if '(world)' in name_lower:
        return 'World'
    if '(europe)' in name_lower or '(eu)' in name_lower:
        return 'Europe'
    if '(japan)' in name_lower or '(jp)' in name_lower:
        return 'Japan'
    if '(australia)' in name_lower or '(au)' in name_lower:
        return 'Australia'
    if '(asia)' in name_lower:
        return 'Asia'
    if '(korea)' in name_lower:
        return 'Korea'
    return 'Unknown'


def parse_dat_file(dat_path: Path) -> Dict[str, DatRomEntry]:
    """Parse a DAT file (auto-detects ClrMamePro text or Logiqx XML)."""
    with open(dat_path, 'r', encoding='utf-8-sig', errors='ignore') as fh:
        first_line = fh.readline().strip()

    if first_line.startswith('<?xml') or first_line.startswith('<'):
        return parse_logiqx_xml_dat(dat_path)
    return parse_clrmamepro_dat(dat_path)


def parse_logiqx_xml_dat(dat_path: Path) -> Dict[str, DatRomEntry]:
    """Parse a Logiqx XML format DAT file."""
    entries = {}

    with open(dat_path, 'r', encoding='utf-8-sig', errors='ignore') as fh:
        content = fh.read()

    for machine_match in re.finditer(
            r'<(?:machine|game)\s+name="([^"]+)"[^>]*>'
            r'(.*?)</(?:machine|game)>', content, re.DOTALL):
        game_name = machine_match.group(1)
        machine_content = machine_match.group(2)

        for rom_match in re.finditer(r'<rom\s+([^>]+)/>', machine_content):
            rom_attrs = rom_match.group(1)

            name_match = re.search(r'name="([^"]+)"', rom_attrs)
            size_match = re.search(r'size="(\d+)"', rom_attrs)
            crc_match = re.search(r'crc="([a-fA-F0-9]+)"', rom_attrs)
            md5_match = re.search(r'md5="([a-fA-F0-9]+)"', rom_attrs)
            sha1_match = re.search(r'sha1="([a-fA-F0-9]+)"', rom_attrs)

            if name_match and crc_match:
                rom_name = name_match.group(1)
                crc = crc_match.group(1).lower()
                region = detect_dat_region(game_name)

                entry = DatRomEntry(
                    name=game_name,
                    rom_name=rom_name,
                    size=int(size_match.group(1)) if size_match else 0,
                    crc=crc,
                    md5=md5_match.group(1).lower() if md5_match else '',
                    sha1=sha1_match.group(1).lower() if sha1_match else '',
                    region=region,
                    is_parent=True,
                    parent_name='',
                )
                entries[crc] = entry

    return entries


def parse_clrmamepro_dat(dat_path: Path) -> Dict[str, DatRomEntry]:
    """Parse a ClrMamePro format DAT file."""
    entries = {}

    with open(dat_path, 'r', encoding='utf-8', errors='ignore') as fh:
        content = fh.read()

    in_game = False
    current_game = None
    brace_count = 0

    lines = content.split('\n')
    for line in lines:
        line = line.strip()

        if line.startswith('game') and '(' in line:
            in_game = True
            brace_count = line.count('(') - line.count(')')
            name_match = re.search(r'name\s+"([^"]+)"', line)
            if name_match:
                current_game = name_match.group(1)
        elif in_game:
            brace_count += line.count('(') - line.count(')')

            if 'rom' in line and 'name' in line:
                rom_match = re.search(r'name\s+"([^"]+)"', line)
                size_match = re.search(r'size\s+(\d+)', line)
                crc_match = re.search(r'crc\s+([a-fA-F0-9]+)', line)
                md5_match = re.search(r'md5\s+([a-fA-F0-9]+)', line)
                sha1_match = re.search(r'sha1\s+([a-fA-F0-9]+)', line)

                if rom_match and crc_match:
                    rom_name = rom_match.group(1)
                    crc = crc_match.group(1).lower()
                    region = (detect_dat_region(current_game)
                              if current_game else 'Unknown')

                    entry = DatRomEntry(
                        name=current_game or rom_name,
                        rom_name=rom_name,
                        size=int(size_match.group(1)) if size_match else 0,
                        crc=crc,
                        md5=(md5_match.group(1).lower()
                             if md5_match else ''),
                        sha1=(sha1_match.group(1).lower()
                              if sha1_match else ''),
                        region=region,
                        is_parent=True,
                        parent_name='',
                    )
                    entries[crc] = entry

            if brace_count <= 0:
                in_game = False
                current_game = None

    return entries


# =============================================================================
# DAT Loading
# =============================================================================

def load_all_system_dats(system: str,
                         dat_dir: Path) -> Dict[str, DatRomEntry]:
    """Load primary + additional DAT files for a system and merge entries."""
    all_entries: Dict[str, DatRomEntry] = {}
    dat_path = dat_dir / f"{system}.dat"
    if dat_path.exists():
        all_entries.update(parse_dat_file(dat_path))

    for extra in sorted(dat_dir.glob(f"{system}_extra*.dat")):
        try:
            entries = parse_dat_file(extra)
            all_entries.update(entries)
        except Exception:  # pylint: disable=broad-except
            pass

    return all_entries


# =============================================================================
# CRC Verification
# =============================================================================

def calculate_crc32(filepath: Path) -> str:
    """Calculate CRC32 checksum of a file."""
    crc = 0
    with open(filepath, 'rb') as fh:
        for chunk in iter(lambda: fh.read(65536), b''):
            crc = binascii.crc32(chunk, crc)
    return format(crc & 0xFFFFFFFF, '08x')


def calculate_crc32_from_zip(zip_path: Path) -> Optional[str]:
    """Calculate CRC32 of the first file inside a ZIP."""
    try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            for name in zf.namelist():
                if not name.endswith('/'):
                    with zf.open(name) as fh:
                        crc = 0
                        # pylint: disable=cell-var-from-loop
                        for chunk in iter(lambda: fh.read(65536), b''):
                            crc = binascii.crc32(chunk, crc)
                        return format(crc & 0xFFFFFFFF, '08x')
    except Exception:  # pylint: disable=broad-except
        pass
    return None


def load_crc_cache(cache_path: Path) -> dict:
    """Load CRC cache from JSON.

    Returns {filepath_str: {"crc": ..., "mtime": ..., "size": ...}}.
    """
    if cache_path.exists():
        try:
            with open(cache_path, 'r', encoding='utf-8') as fh:
                return json.load(fh)
        except (json.JSONDecodeError, IOError):
            pass
    return {}


def save_crc_cache(cache_path: Path, cache: dict):
    """Save CRC cache to JSON."""
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with open(cache_path, 'w', encoding='utf-8') as fh:
            json.dump(cache, fh)
    except IOError:
        pass


def get_cached_crc(filepath: Path, crc_cache: dict,
                   download_crc_index: dict = None) -> Optional[str]:
    """Get CRC from cache or calculate and cache it.

    Uses mtime+size to invalidate.
    """
    key = str(filepath)
    stat = filepath.stat()
    mtime = stat.st_mtime
    size = stat.st_size

    cached = crc_cache.get(key)
    if cached and cached.get('mtime') == mtime and cached.get('size') == size:
        return cached['crc']

    if download_crc_index:
        indexed = download_crc_index.get(key)
        if (indexed and indexed.get('mtime') == mtime
                and indexed.get('size') == size):
            crc = indexed['crc']
            crc_cache[key] = {'crc': crc, 'mtime': mtime, 'size': size}
            return crc

    if filepath.suffix.lower() == '.zip':
        crc = calculate_crc32_from_zip(filepath)
    else:
        crc = calculate_crc32(filepath)

    if crc:
        crc_cache[key] = {'crc': crc, 'mtime': mtime, 'size': size}
    return crc


class BackgroundCrcIndexer:
    """Compute CRC32 checksums in background threads as files finish downloading.

    Receives file paths via submit() and computes CRCs in a thread pool,
    so verification overlaps with ongoing downloads.
    """

    def __init__(self, cache_dir: Path, max_workers: int = 2):
        self.cache_dir = cache_dir
        self.index_path = cache_dir / '_crc_index.json'
        self._lock = threading.Lock()
        self._index: dict = {}
        self._executor = _ThreadPoolExecutor(max_workers=max_workers)
        self._futures: list = []
        self._new_count = 0
        self._cached_count = 0
        self._submitted_count = 0

        if self.index_path.exists():
            try:
                with open(self.index_path, 'r', encoding='utf-8') as fh:
                    self._index = json.load(fh)
            except (json.JSONDecodeError, IOError):
                pass

    @property
    def verified_count(self) -> int:
        """Number of files that have completed CRC verification."""
        with self._lock:
            return self._new_count + self._cached_count

    def submit(self, filepath: Path) -> None:
        """Queue a file for background CRC computation."""
        future = self._executor.submit(self._compute_crc, filepath)
        with self._lock:
            self._futures.append(future)
            self._submitted_count += 1

    def _compute_crc(self, filepath: Path) -> None:
        """Compute CRC for a single file and store in the index."""
        if not filepath.exists():
            return
        try:
            stat = filepath.stat()
        except OSError:
            return
        mtime = stat.st_mtime
        size = stat.st_size
        key = str(filepath)

        with self._lock:
            existing = self._index.get(key)
            if (existing and existing.get('mtime') == mtime
                    and existing.get('size') == size):
                self._cached_count += 1
                return

        if filepath.suffix.lower() == '.zip':
            crc = calculate_crc32_from_zip(filepath)
        else:
            crc = calculate_crc32(filepath)

        if crc:
            with self._lock:
                self._index[key] = {
                    'crc': crc, 'mtime': mtime, 'size': size}
                self._new_count += 1

    def wait_and_save(self) -> dict:
        """Wait for all pending CRC computations, save index, return it."""
        self._executor.shutdown(wait=True)

        try:
            with open(self.index_path, 'w', encoding='utf-8') as fh:
                json.dump(self._index, fh)
        except IOError:
            pass

        return self._index


# Lazy import to avoid pulling in concurrent.futures at module load
def _ThreadPoolExecutor(**kwargs):  # pylint: disable=invalid-name
    from concurrent.futures import ThreadPoolExecutor  # pylint: disable=import-outside-toplevel
    return ThreadPoolExecutor(**kwargs)

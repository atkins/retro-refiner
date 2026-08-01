"""TeknoParrot-specific filtering: version dedup, platform filtering.

Standalone implementations extracted from the monolith.  Console output is
replaced by optional callbacks and plain stderr for errors.
"""
import json
import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from retro_refiner.log import logger
from retro_refiner.network import get_filename_from_entry

from retro_refiner.filter import matches_patterns


# =============================================================================
# Dataclass
# =============================================================================

@dataclass
class TeknoParrotGameInfo:
    """Information about a TeknoParrot ROM parsed from filename or DAT.

    TeknoParrot ROM naming format:
    Game Title (Version) (Date) [Hardware Platform] [TP].zip
    """
    filename: str
    name: str
    base_title: str
    description: str
    version: str
    version_tuple: tuple
    date: str
    year: int
    region: str
    platform: str
    is_parent: bool
    parent_name: str
    has_chd: bool
    chd_names: list


# =============================================================================
# Platform sets
# =============================================================================

TEKNOPARROT_INCLUDE_PLATFORMS = {
    'Sega Lindbergh', 'Sega RingEdge', 'Sega RingEdge 2',
    'Sega RingWide', 'Sega Nu', 'Sega Nu 1.1', 'Sega Nu 2',
    'Sega ALLS', 'Sega ALLS UX',
    'Taito Type X', 'Taito Type X2', 'Taito Type X3', 'Taito Type X4',
    'Taito NESiCAxLive', 'Taito NESiCAxLive 2',
    'Namco System 246', 'Namco System 256', 'Namco System 357',
    'Namco System ES1', 'Namco System ES3',
    'Examu eX-BOARD', 'Raw Thrills PC', 'IGS PGM2',
    'Konami PC', 'Windows PC',
}

TEKNOPARROT_EXCLUDE_PLATFORMS: set = set()


# =============================================================================
# Version parsing
# =============================================================================

def parse_teknoparrot_version(version_str: str) -> tuple:
    """Parse a version string into a comparable tuple.

    Handles formats like: "1.30.01", "Ver.2", "2.30.00", "Rev.6"
    """
    if not version_str:
        return (0,)

    version_str = re.sub(
        r'^(Ver\.?|Version|Rev\.?|v)\s*', '', version_str,
        flags=re.IGNORECASE)

    parts = re.findall(r'\d+', version_str)
    if parts:
        return tuple(int(p) for p in parts)
    return (0,)


# =============================================================================
# Filename parsing
# =============================================================================

def parse_teknoparrot_filename(
        filename: str) -> Optional[TeknoParrotGameInfo]:
    """Parse a TeknoParrot ROM filename into structured info.

    Expected format: Game Title (Version) (Date) [Hardware Platform] [TP].zip
    """
    if '[TP]' not in filename and '[tp]' not in filename.lower():
        return None

    name = filename
    for ext in ('.zip', '.7z', '.rar'):
        if name.lower().endswith(ext):
            name = name[:-len(ext)]
            break

    # Extract hardware platform
    platform_match = re.search(
        r'\[([^\]]+)\](?=.*\[TP\])', name, re.IGNORECASE)
    platform = platform_match.group(1) if platform_match else 'Unknown'

    # Remove [TP] tag and platform
    clean_name = re.sub(r'\s*\[TP\]\s*', '', name, flags=re.IGNORECASE)
    clean_name = re.sub(r'\s*\[[^\]]+\]\s*$', '', clean_name)

    # Extract version
    version = ''
    version_tuple = (0,)
    version_patterns = [
        r'\((\d+\.\d+(?:\.\d+)?)\)',
        r'Ver\.?\s*(\d+(?:\.\d+)*)',
        r'\((Rev\.?\s*\d+[^\)]*)\)',
    ]
    for pattern in version_patterns:
        match = re.search(pattern, clean_name, re.IGNORECASE)
        if match:
            version = match.group(1)
            version_tuple = parse_teknoparrot_version(version)
            break

    # Extract date
    date = ''
    year = 0
    date_match = re.search(r'\((\d{4}(?:-\d{2}-\d{2})?)\)', clean_name)
    if date_match:
        date = date_match.group(1)
        year = int(date[:4])

    # Extract region — match with or without parentheses so that both
    # "Game (Export) [HW] [TP].zip" and "Game Export [HW] [TP].zip" work.
    region = 'World'
    region_patterns = [
        (r'\bExport\b', 'Export'),
        (r'\bUSA\b', 'USA'),
        (r'\bJapan\b', 'Japan'),
        (r'\bAsia\b', 'Asia'),
        (r'\bEurope\b', 'Europe'),
        (r'\bKorea\b', 'Korea'),
        (r'[\[\(]En[\]\)]', 'Export'),
    ]
    for pattern, reg in region_patterns:
        if re.search(pattern, clean_name, re.IGNORECASE):
            region = reg
            break

    # Extract base title
    base_title = clean_name
    base_title = re.sub(r'\s*\([^)]*\)\s*', ' ', base_title)
    base_title = re.sub(
        r'\s*Ver\.?\s*\d+(?:\.\d+)*\s*', ' ', base_title,
        flags=re.IGNORECASE)
    base_title = ' '.join(base_title.split()).strip()

    return TeknoParrotGameInfo(
        filename=filename,
        name=name,
        base_title=base_title,
        description=name,
        version=version,
        version_tuple=version_tuple,
        date=date,
        year=year,
        region=region,
        platform=platform,
        is_parent=True,
        parent_name='',
        has_chd=False,
        chd_names=[],
    )


# =============================================================================
# Title normalization
# =============================================================================

def normalize_teknoparrot_title(title: str) -> str:
    """Normalize a TeknoParrot game title for grouping."""
    normalized = title.lower()
    normalized = re.sub(
        r'\s*ver\.?\s*\d+(?:\.\d+)*\s*$', '', normalized)
    normalized = re.sub(
        r'\s*(arcade stage|arcade|stage)\s*$', '', normalized)
    normalized = re.sub(r'[^\w\s]', '', normalized)
    normalized = ' '.join(normalized.split())
    return normalized


# =============================================================================
# DAT parsing
# =============================================================================

def parse_teknoparrot_dat(dat_path: str) -> dict:
    """Parse TeknoParrot DAT file and return game info dict.

    Returns dict mapping ROM name -> TeknoParrotGameInfo.
    """
    games = {}

    try:
        tree = ET.parse(dat_path)
        root = tree.getroot()

        game_elements = (root.findall('.//game')
                         or root.findall('.//machine'))

        for game in game_elements:
            name = game.get('name', '')
            if not name:
                continue

            desc_elem = game.find('description')
            description = (desc_elem.text
                           if desc_elem is not None else name)

            filename_to_parse = (description if '[TP]' in description
                                 else f"{name} [TP].zip")
            info = parse_teknoparrot_filename(filename_to_parse)

            if info:
                info.name = name
                info.description = description

                chd_names = []
                for disk in game.findall('.//disk'):
                    disk_name = disk.get('name', '')
                    if disk_name:
                        chd_names.append(disk_name + '.chd')

                if chd_names:
                    info.has_chd = True
                    info.chd_names = chd_names

                games[name] = info
            else:
                games[name] = TeknoParrotGameInfo(
                    filename=f"{name}.zip",
                    name=name,
                    base_title=name,
                    description=description,
                    version='',
                    version_tuple=(0,),
                    date='',
                    year=0,
                    region='World',
                    platform='Unknown',
                    is_parent=True,
                    parent_name='',
                    has_chd=False,
                    chd_names=[],
                )

    except ET.ParseError as exc:
        logger.error("TeknoParrot: Error parsing DAT file: {}", exc)
    except Exception as exc:  # pylint: disable=broad-except
        logger.error("TeknoParrot: Error reading DAT file: {}", exc)

    return games


def download_teknoparrot_dat(dat_dir: Path,
                             force: bool = False) -> Optional[Path]:
    """Download TeknoParrot DAT file from GitHub releases."""
    dat_path = dat_dir / 'teknoparrot.dat'

    if dat_path.exists() and not force:
        return dat_path

    dat_dir.mkdir(parents=True, exist_ok=True)

    try:
        api_url = ('https://api.github.com/repos/Eggmansworld/'
                   'Datfiles/releases/tags/teknoparrot')
        req = urllib.request.Request(api_url)
        req.add_header('User-Agent', 'retro-refiner/1.0')
        req.add_header('Accept', 'application/vnd.github.v3+json')

        with urllib.request.urlopen(req, timeout=30) as response:
            release_data = json.loads(response.read().decode('utf-8'))

        zip_url = None
        for asset in release_data.get('assets', []):
            asset_name = asset.get('name', '').lower()
            if 'teknoparrot' in asset_name and asset_name.endswith('.zip'):
                zip_url = asset.get('browser_download_url')
                break

        if not zip_url:
            return None

        zip_path = dat_dir / 'teknoparrot_dat.zip'

        req = urllib.request.Request(zip_url)
        req.add_header('User-Agent', 'retro-refiner/1.0')

        with urllib.request.urlopen(req, timeout=60) as response:
            with open(zip_path, 'wb') as fh:
                fh.write(response.read())

        with zipfile.ZipFile(zip_path, 'r') as zf:
            dat_files = [n for n in zf.namelist()
                         if n.lower().endswith('.dat')]
            if not dat_files:
                zip_path.unlink()
                return None

            with zf.open(dat_files[0]) as src:
                with open(dat_path, 'wb') as dst:
                    dst.write(src.read())

        zip_path.unlink()
        return dat_path

    except urllib.error.URLError:
        return None
    except Exception:  # pylint: disable=broad-except
        return None


# =============================================================================
# Region priority and selection
# =============================================================================

def get_teknoparrot_region_priority(region: str,
                                    region_priority: List[str] = None
                                    ) -> int:
    """Get priority for TeknoParrot regions (lower is better)."""
    if region_priority:
        region_upper = region.upper()
        for i, reg in enumerate(region_priority):
            if reg.upper() == region_upper:
                return i
        return len(region_priority) + 1

    priorities = {
        'Export': 0, 'USA': 1, 'World': 2, 'Europe': 3,
        'Asia': 4, 'Japan': 5, 'Korea': 6, 'Unknown': 10,
    }
    return priorities.get(region, 10)


def select_best_teknoparrot_version(
        games: List[TeknoParrotGameInfo],
        region_priority: List[str] = None,
        verbose: bool = False) -> Optional[TeknoParrotGameInfo]:
    """Select the best version from a group of TeknoParrot ROMs.

    Prioritizes by: version_tuple (desc), year (desc), region priority.
    """
    _ = verbose  # Reserved for future callback-based logging
    if not games:
        return None
    if len(games) == 1:
        return games[0]

    def sort_key(game):
        version_score = (tuple(-v for v in game.version_tuple)
                         if game.version_tuple else (0,))
        year_score = -(game.year or 0)
        region_score = get_teknoparrot_region_priority(
            game.region, region_priority)
        return (version_score, year_score, region_score)

    sorted_games = sorted(games, key=sort_key)
    return sorted_games[0]


def should_include_teknoparrot_game(
        game: TeknoParrotGameInfo,
        include_platforms: set = None,
        exclude_platforms: set = None) -> Tuple[bool, str]:
    """Determine if a TeknoParrot game should be included based on platform.

    Returns (should_include, reason).
    """
    platform = game.platform

    if exclude_platforms:
        for excluded in exclude_platforms:
            if excluded.lower() in platform.lower():
                return False, f"Excluded platform: {platform}"

    if not include_platforms:
        return True, f"Platform: {platform}"

    for included in include_platforms:
        if included.lower() in platform.lower():
            return True, f"Included platform: {platform}"

    return False, f"Platform not in include list: {platform}"


# =============================================================================
# Network TeknoParrot filtering (standalone)
# =============================================================================

def filter_teknoparrot_network_roms(
        rom_urls,
        include_platforms=None,
        exclude_platforms=None,
        region_priority=None,
        keep_all_versions=False,
        include_patterns=None,
        exclude_patterns=None,
        url_sizes=None,
        verbose=False,
        no_filter=False,
        english_only=False):
    # type: (List[str], set, set, list, bool, list, list, dict, bool, bool, bool) -> Tuple[List[str], dict]
    """Filter TeknoParrot ROMs with TP-specific logic.

    ``rom_urls`` entries may be URLs or local filesystem paths; only the
    basename is consulted and entries are returned as given.

    Returns:
        (selected_urls, size_info_dict)
    """
    if url_sizes is None:
        url_sizes = {}

    effective_include = (include_platforms if include_platforms
                         else None)
    effective_exclude = (exclude_platforms if exclude_platforms
                         else TEKNOPARROT_EXCLUDE_PLATFORMS)

    all_roms: List[TeknoParrotGameInfo] = []
    url_map: Dict[str, str] = {}
    size_map: Dict[str, int] = {}
    total_source_size = 0
    excluded_reasons: Dict[str, str] = {}  # url -> reason
    unparsed_local: List[Tuple[str, int]] = []  # (entry, size)

    for url in rom_urls:
        filename = get_filename_from_entry(url)
        file_size = url_sizes.get(url, 0)
        total_source_size += file_size

        if not no_filter:
            if (include_patterns
                    and not matches_patterns(filename, include_patterns)):
                excluded_reasons[url] = 'pattern exclude'
                continue
            if (exclude_patterns
                    and matches_patterns(filename, exclude_patterns)):
                excluded_reasons[url] = 'pattern exclude'
                continue

        rom_info = parse_teknoparrot_filename(filename)
        if not rom_info:
            if no_filter:
                url_map[filename] = url
                size_map[filename] = file_size
                continue
            if '://' not in url:
                # A local folder is just files on disk and has no reason to
                # carry the '[TP]' naming convention that network listings
                # use.  Before local paths reached this filter such files
                # passed through untouched, so dropping them here would
                # exclude an entire plainly-named local library -- and
                # delete it under the 'remove' file action.
                unparsed_local.append((url, file_size))
                continue
            excluded_reasons[url] = 'unrecognized filename'
            continue

        if not no_filter:
            should_include, reason = should_include_teknoparrot_game(
                rom_info, effective_include, effective_exclude)
            if not should_include:
                excluded_reasons[url] = reason or 'excluded platform'
                continue

        all_roms.append(rom_info)
        url_map[filename] = url
        size_map[filename] = file_size

    if no_filter:
        selected_urls = list(url_map.values())
        selected_size = sum(size_map.values())
    else:
        grouped: Dict[str, List[TeknoParrotGameInfo]] = defaultdict(list)
        for rom in all_roms:
            normalized = normalize_teknoparrot_title(rom.base_title)
            grouped[normalized].append(rom)

        selected_urls = []
        selected_size = 0

        for _title, roms in grouped.items():
            if keep_all_versions:
                for rom in roms:
                    if rom.filename in url_map:
                        selected_urls.append(url_map[rom.filename])
                        selected_size += size_map.get(rom.filename, 0)
            else:
                best = select_best_teknoparrot_version(
                    roms, region_priority, verbose=verbose)
                if not best or best.filename not in url_map:
                    for rom in roms:
                        url = url_map.get(rom.filename)
                        if url:
                            excluded_reasons[url] = 'no best version'
                    continue

                if (english_only
                        and best.region in ('Japan', 'JPN', 'Korea')):
                    has_english = any(
                        r.region in ('World', 'USA', 'Export',
                                     'Unknown', '')
                        for r in roms)
                    if not has_english:
                        for rom in roms:
                            url = url_map.get(rom.filename)
                            if url:
                                excluded_reasons[url] = (
                                    f'non-english ({best.region})')
                        continue

                selected_urls.append(url_map[best.filename])
                selected_size += size_map.get(best.filename, 0)
                # Mark non-best versions as excluded
                for rom in roms:
                    if rom.filename != best.filename:
                        url = url_map.get(rom.filename)
                        if url:
                            excluded_reasons[url] = 'duplicate version'

        for entry, entry_size in unparsed_local:
            selected_urls.append(entry)
            selected_size += entry_size

    selected_set = set(selected_urls)
    excluded_urls = [u for u in rom_urls if u not in selected_set]
    logger.debug("TeknoParrot filter result: {} selected, {} excluded",
                 len(selected_urls), len(excluded_urls))
    for url in selected_urls:
        logger.debug("  SELECTED: {}", get_filename_from_entry(url))
    for url in excluded_urls:
        reason = excluded_reasons.get(url, 'unknown')
        logger.debug("  EXCLUDED: {} ({})", get_filename_from_entry(url),
                     reason)

    return selected_urls, {
        'source_size': total_source_size,
        'selected_size': selected_size,
        'excluded_reasons': excluded_reasons,
    }

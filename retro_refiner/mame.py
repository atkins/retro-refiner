"""MAME-specific filtering: category filtering, clone selection, CHD handling.

Standalone implementations extracted from the monolith.  Console output is
replaced by optional callbacks and plain stderr for errors.
"""
import fnmatch
import json
import shutil
import subprocess
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from retro_refiner.config import Config
from retro_refiner.models import FilterResult


# =============================================================================
# Dataclass
# =============================================================================

@dataclass
class MameGameInfo:
    """Information about a MAME game parsed from DAT and catver.ini."""
    name: str
    description: str
    year: str
    manufacturer: str
    category: str
    is_parent: bool
    parent_name: str
    is_bios: bool
    is_device: bool
    has_chd: bool
    chd_names: list
    region: str
    bios_name: str = ''
    rom_files: list = None


# =============================================================================
# Category sets
# =============================================================================

MAME_INCLUDE_CATEGORIES = {
    'Ball & Paddle', 'Climbing', 'Fighter', 'Maze', 'Platform',
    'Puzzle', 'Shooter', 'Sports', 'Whac-A-Mole', 'Driving',
    'Multiplay', 'MultiGame', 'TTL',
}

MAME_EXCLUDE_CATEGORIES = {
    'Casino', 'Gambling', 'Quiz',
    'Tabletop / Mahjong', 'Tabletop / Hanafuda',
    'Slot Machine',
    'Electromechanical',
    'Arcade / Strength Tester', 'Arcade / Fortune Teller',
    'Arcade / Physical Ability',
    'Music Game / Dance', 'Music Game / Instruments',
    'Redemption Game', 'Medal Game',
    'System / BIOS', 'System / Device',
    'Computer', 'Calculator', 'Printer', 'Telephone',
    'Utilities', 'Medical Equipment', 'Musical Instrument',
    'Radio', 'Watch', 'Misc. / Clock', 'Misc. / Prediction',
    'Misc. / Love Test', 'Game Console', 'Handheld',
    'Board Game', 'Music Player', 'Player', 'Tablet',
    'TV Bundle', 'Non Arcade', 'Digital Camera',
    'Digital Simulator', 'Robot', 'Simulation',
    'Card Games / Solitaire',
}

MAME_EXCLUDE_SUBCATEGORIES = {
    'Music Game / Dance',
    "Handheld / Plug n' Play TV Game / Dance",
    "Handheld / Plug n' Play TV Game / Mahjong",
    "Handheld / Plug n' Play TV Game / Quiz",
    "Handheld / Plug n' Play TV Game / Casino",
    'Tabletop / Mahjong',
    'Tabletop / Mahjong * Mature *',
    'Tabletop / Hanafuda',
    'Tabletop / Hanafuda * Mature *',
}


# =============================================================================
# MAME version / download constants
# =============================================================================

DEFAULT_MAME_VERSION = "0.274"


def get_latest_mame_version() -> str:
    """Try to detect the latest MAME version from GitHub releases."""
    try:
        url = "https://api.github.com/repos/mamedev/mame/releases/latest"
        req = urllib.request.Request(
            url, headers={'User-Agent': 'Retro-Refiner/1.0'})
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode())
            tag = data.get('tag_name', '')
            if tag.startswith('mame'):
                version_num = tag[4:]
                if len(version_num) >= 4:
                    return f"0.{version_num[1:]}"
    except Exception:  # pylint: disable=broad-except
        pass
    return DEFAULT_MAME_VERSION


def _download_file(url: str, dest_path: Path,
                   description: str = "file") -> bool:
    """Download a file from URL to destination path."""
    _ = description  # Logged in monolith; kept for API compat
    try:
        req = urllib.request.Request(
            url, headers={'User-Agent': 'Retro-Refiner/1.0'})
        with urllib.request.urlopen(req, timeout=60) as response:
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            with open(dest_path, 'wb') as fh:
                shutil.copyfileobj(response, fh)
        return True
    except Exception:  # pylint: disable=broad-except
        return False


def _extract_from_zip(zip_path: Path, filename: str,
                      dest_path: Path) -> bool:
    """Extract a specific file from a zip archive."""
    try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            for name in zf.namelist():
                if name.endswith(filename) or name == filename:
                    with zf.open(name) as src:
                        dest_path.parent.mkdir(parents=True, exist_ok=True)
                        with open(dest_path, 'wb') as dst:
                            shutil.copyfileobj(src, dst)
                    return True
        return False
    except (zipfile.BadZipFile, Exception):
        return False


def download_mame_data(dat_dir, version=None, force=False,
                       on_progress=None):
    # type: (Path, Optional[str], bool, Callable) -> tuple
    """Download MAME catver.ini and DAT files.

    Returns (catver_path, dat_path) or (None, None) on failure.
    """
    _ = on_progress
    dat_dir = Path(dat_dir)

    if version is None:
        version = get_latest_mame_version()

    version_clean = version.replace(".", "")
    dat_dir.mkdir(parents=True, exist_ok=True)

    catver_path = dat_dir / 'catver.ini'
    dat_path = dat_dir / 'mame.xml'

    if force:
        if catver_path.exists():
            catver_path.unlink()
        if dat_path.exists():
            dat_path.unlink()

    # Download catver.ini
    if not catver_path.exists():
        alt_version = version_clean.lstrip('0')
        catver_url = (
            "https://www.progettosnaps.net/download/"
            f"?tipo=catver&file=pS_CatVer_{alt_version}.zip")
        zip_path = dat_dir / 'catver.zip'

        if _download_file(catver_url, zip_path, "catver.ini pack"):
            if _extract_from_zip(zip_path, 'catver.ini', catver_path):
                zip_path.unlink()
        else:
            prev_version = str(int(alt_version) - 1)
            catver_url = (
                "https://www.progettosnaps.net/download/"
                f"?tipo=catver&file=pS_CatVer_{prev_version}.zip")
            if _download_file(catver_url, zip_path,
                              "catver.ini pack (prev version)"):
                if _extract_from_zip(zip_path, 'catver.ini', catver_path):
                    zip_path.unlink()

    # Download MAME XML/DAT
    if not dat_path.exists():
        mame_xml_url = (
            f"https://github.com/mamedev/mame/releases/download/"
            f"mame{version_clean}/mame{version_clean}lx.zip")
        zip_path = dat_dir / 'mame_xml.zip'

        if _download_file(mame_xml_url, zip_path, "MAME XML"):
            if _extract_from_zip(zip_path, '.xml', dat_path):
                zip_path.unlink()
        else:
            alt_version = version_clean.lstrip('0')
            alt_url = (
                "https://www.progettosnaps.net/download/"
                f"?tipo=dat_mame&file=/dats/MAME/packs/"
                f"MAME_Dats_{alt_version}.7z")
            archive_path = dat_dir / 'mame_dats.7z'
            if _download_file(alt_url, archive_path, "MAME DAT pack"):
                try:
                    result = subprocess.run(
                        ['7z', 'x', '-y', f'-o{dat_dir}',
                         str(archive_path)],
                        capture_output=True, text=True, check=False)
                    if result.returncode == 0:
                        for dat in dat_dir.glob('*arcade*.dat'):
                            dat.rename(dat_path)
                            break
                        archive_path.unlink()
                except FileNotFoundError:
                    pass

    if catver_path.exists() and dat_path.exists():
        return catver_path, dat_path
    if catver_path.exists():
        existing_dats = (list(dat_dir.glob('*.dat'))
                         + list(dat_dir.glob('*.xml')))
        if existing_dats:
            return catver_path, existing_dats[0]

    return (catver_path if catver_path.exists() else None,
            dat_path if dat_path.exists() else None)


# =============================================================================
# Parsing
# =============================================================================

def parse_catver_ini(catver_path: str) -> dict:
    """Parse catver.ini and return a dict of romname -> category."""
    categories = {}
    in_category_section = False

    with open(catver_path, 'r', encoding='utf-8', errors='ignore') as fh:
        for line in fh:
            line = line.strip()
            if line == '[Category]':
                in_category_section = True
                continue
            if line.startswith('[') and in_category_section:
                break
            if in_category_section and '=' in line:
                parts = line.split('=', 1)
                if len(parts) == 2:
                    romname = parts[0].strip()
                    category = parts[1].strip()
                    categories[romname] = category

    return categories


def parse_mame_dat(dat_path: str) -> dict:
    """Parse MAME DAT file and return game info dict.

    Returns dict mapping ROM name -> MameGameInfo.
    """
    games = {}

    with open(dat_path, 'r', encoding='utf-8', errors='ignore') as fh:
        first_line = fh.readline()

    if not ('<?xml' in first_line or '<datafile' in first_line
            or '<mame' in first_line):
        return games

    game_tags = ('machine', 'game')

    parser = ET.XMLPullParser(events=('end',))
    with open(dat_path, 'rb') as fh:
        while True:
            chunk = fh.read(65536)
            if not chunk:
                break
            parser.feed(chunk)
            for _, elem in parser.read_events():
                if elem.tag not in game_tags:
                    continue

                name = elem.get('name', '')
                if not name:
                    elem.clear()
                    continue

                is_bios = elem.get('isbios', 'no') == 'yes'
                is_device = elem.get('isdevice', 'no') == 'yes'

                cloneof = elem.get('cloneof', '')
                romof = elem.get('romof', '')
                parent_name = cloneof
                is_parent = not cloneof or cloneof == name
                bios_name = (romof if romof and romof != cloneof
                             else '')

                desc_elem = elem.find('description')
                description = (desc_elem.text
                               if desc_elem is not None else name)

                year_elem = elem.find('year')
                year_val = year_elem.text if year_elem is not None else ''

                mfr_elem = (elem.find('manufacturer')
                            or elem.find('publisher'))
                manufacturer = (mfr_elem.text
                                if mfr_elem is not None else '')

                chd_names = []
                for disk in elem.findall('.//disk'):
                    disk_name = disk.get('name', '')
                    if disk_name:
                        chd_names.append(disk_name + '.chd')

                rom_files = []
                for rom_elem in elem.findall('.//rom'):
                    rom_name_attr = rom_elem.get('name', '')
                    if rom_name_attr:
                        rom_files.append(rom_name_attr)

                region = detect_mame_region(description)

                games[name] = MameGameInfo(
                    name=name,
                    description=description,
                    year=year_val,
                    manufacturer=manufacturer or '',
                    category='',
                    is_parent=is_parent,
                    parent_name=parent_name if not is_parent else '',
                    is_bios=is_bios,
                    is_device=is_device,
                    has_chd=bool(chd_names),
                    chd_names=chd_names,
                    region=region,
                    bios_name=bios_name,
                    rom_files=rom_files,
                )
                elem.clear()

    return games


def detect_mame_region(description: str) -> str:
    """Detect region from MAME game description."""
    desc_lower = description.lower()

    if '(us)' in desc_lower or '(usa)' in desc_lower or '[us]' in desc_lower:
        return 'USA'
    if '(world)' in desc_lower or '[world]' in desc_lower:
        return 'World'
    if ('(europe)' in desc_lower or '(euro)' in desc_lower
            or '[europe]' in desc_lower):
        return 'Europe'
    if ('(japan)' in desc_lower or '(jpn)' in desc_lower
            or '[japan]' in desc_lower):
        return 'Japan'
    if '(asia)' in desc_lower or '[asia]' in desc_lower:
        return 'Asia'
    if '(korea)' in desc_lower or '[korea]' in desc_lower:
        return 'Korea'
    if '(hispanic)' in desc_lower or '(brazil)' in desc_lower:
        return 'LatinAmerica'

    if ' usa ' in desc_lower or desc_lower.endswith(' usa'):
        return 'USA'

    return 'Unknown'


# =============================================================================
# Game filtering decisions
# =============================================================================

def should_include_mame_game(game: MameGameInfo, category: str,
                             include_adult: bool = True) -> tuple:
    """Determine if a MAME game should be included.

    Returns (should_include, reason).
    """
    if game.is_bios:
        return False, "BIOS"
    if game.is_device:
        return False, "Device"

    if not category:
        return False, "No category"

    if not include_adult and '* Mature *' in category:
        return False, "Adult/mature content"

    if category in MAME_EXCLUDE_SUBCATEGORIES:
        return False, f"Excluded subcategory: {category}"

    for exclude_cat in MAME_EXCLUDE_CATEGORIES:
        if category.startswith(exclude_cat):
            return False, f"Excluded category: {exclude_cat}"

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

    for include_cat in MAME_INCLUDE_CATEGORIES:
        if category.startswith(include_cat):
            return True, f"Included category: {include_cat}"

    if 'pinball' in cat_lower and 'electromechanical' not in cat_lower:
        return True, "Video pinball"

    if 'shooter / gallery' in cat_lower or 'gun' in cat_lower:
        return True, "Light gun game"

    return False, f"Unknown category: {category}"


def get_mame_region_priority(region: str) -> int:
    """Get priority for MAME regions (lower is better)."""
    priorities = {
        'USA': 0, 'World': 1, 'Europe': 2, 'Asia': 3,
        'Japan': 4, 'Korea': 5, 'LatinAmerica': 6, 'Unknown': 10,
    }
    return priorities.get(region, 10)


def select_best_mame_clone(parent_name: str, clones: list,
                           games: dict,
                           verbose: bool = False) -> Optional[MameGameInfo]:
    """Select the best clone based on region preference."""
    _ = verbose  # Reserved for future callback-based logging
    if not clones:
        return games.get(parent_name)

    candidates = ([games[parent_name]] if parent_name in games else [])
    candidates.extend([games[c] for c in clones if c in games])

    if not candidates:
        return None

    candidates.sort(key=lambda g: get_mame_region_priority(g.region))
    return candidates[0]


# =============================================================================
# ROM set format detection and dependency resolution
# =============================================================================

def detect_mame_set_format(source_path, games, available_roms):
    """Detect MAME ROM set format: 'merged', 'split', or 'non-merged'.

    Checks up to 5 parent/clone groups using majority vote.
    """
    source_path = Path(source_path)
    parent_clones = defaultdict(list)
    for name, game in games.items():
        if not game.is_parent and game.parent_name:
            parent_clones[game.parent_name].append(name)

    votes = []
    for parent_name, clones in parent_clones.items():
        if len(votes) >= 5:
            break
        if parent_name not in available_roms:
            continue

        clone_zips_exist = [c for c in clones if c in available_roms]

        if not clone_zips_exist:
            votes.append('merged')
            continue

        clone_name = clone_zips_exist[0]
        clone_zip_path = source_path / f"{clone_name}.zip"
        parent_game = games.get(parent_name)

        if (not parent_game or not parent_game.rom_files
                or not clone_zip_path.exists()):
            votes.append('non-merged')
            continue

        try:
            with zipfile.ZipFile(clone_zip_path, 'r') as zf:
                clone_contents = set(zf.namelist())
            parent_rom_set = set(parent_game.rom_files)
            overlap = parent_rom_set & clone_contents
            if len(overlap) > len(parent_rom_set) * 0.5:
                votes.append('non-merged')
            else:
                votes.append('split')
        except (zipfile.BadZipFile, OSError):
            votes.append('non-merged')

    if not votes:
        return 'non-merged'

    vote_counts = Counter(votes)
    return vote_counts.most_common(1)[0][0]


def build_mame_copy_set(selected_roms, games, available_roms, set_format):
    """Build the set of zip names to copy based on ROM set format.

    Returns (copy_set, dependency_list) where copy_set is a set of ROM
    names and dependency_list is a list of (name, reason) tuples.
    """
    copy_set = set()
    dependencies = []

    if set_format == 'non-merged':
        for game in selected_roms:
            if game.name in available_roms:
                copy_set.add(game.name)
    elif set_format == 'split':
        for game in selected_roms:
            if game.name in available_roms:
                copy_set.add(game.name)
            if not game.is_parent and game.parent_name:
                if (game.parent_name in available_roms
                        and game.parent_name not in copy_set):
                    dependencies.append(
                        (game.parent_name, f"parent of {game.name}"))
                copy_set.add(game.parent_name)
    elif set_format == 'merged':
        for game in selected_roms:
            if game.name in available_roms:
                copy_set.add(game.name)
            elif (game.parent_name
                  and game.parent_name in available_roms):
                if game.parent_name not in copy_set:
                    dependencies.append(
                        (game.parent_name,
                         f"merged parent, contains {game.name}"))
                copy_set.add(game.parent_name)

    # Collect required BIOS zips
    required_bios = set()
    for game in selected_roms:
        if game.bios_name and game.bios_name in available_roms:
            required_bios.add(game.bios_name)
        if game.parent_name:
            parent = games.get(game.parent_name)
            if (parent and parent.bios_name
                    and parent.bios_name in available_roms):
                required_bios.add(parent.bios_name)

    for bios_name in required_bios:
        if bios_name not in copy_set:
            dependencies.append((bios_name, "BIOS"))
        copy_set.add(bios_name)

    return copy_set, dependencies


# =============================================================================
# Network MAME filtering (standalone)
# =============================================================================

def filter_mame_network(urls, config, url_sizes=None,
                        on_progress=None):
    # type: (List[str], Config, Dict[str, int], Callable) -> FilterResult
    """Filter MAME network ROM URLs.

    This is a stub that returns an empty FilterResult.
    The full network filtering requires pre-loaded categories and games
    dicts, which are loaded separately via parse_catver_ini / parse_mame_dat.
    Use filter_mame_network_roms() for the full implementation.
    """
    _ = urls, config, url_sizes, on_progress
    return FilterResult(system='mame')


def filter_mame_network_roms(rom_urls, categories, games,
                             include_patterns=None,
                             exclude_patterns=None,
                             include_adult=True,
                             url_sizes=None,
                             verbose=False,
                             no_filter=False,
                             english_only=False):
    # type: (List[str], dict, dict, list, list, bool, dict, bool, bool, bool) -> Tuple[List[str], dict]
    """Filter MAME/FBNeo ROMs from network sources using category filtering.

    Standalone implementation extracted from the monolith.

    Returns:
        (selected_urls, size_info_dict)
    """
    if url_sizes is None:
        url_sizes = {}

    url_map: Dict[str, str] = {}
    size_map: Dict[str, int] = {}
    url_game_map: Dict[str, str] = {}
    total_source_size = 0

    for url in rom_urls:
        url_clean = url.split('?')[0].split('#')[0]
        filename = urllib.request.unquote(url_clean.split('/')[-1])
        url_map[filename] = url
        size = url_sizes.get(url, 0)
        size_map[filename] = size
        total_source_size += size
        url_parts = url_clean.rstrip('/').split('/')
        if len(url_parts) >= 2:
            parent_folder = urllib.request.unquote(url_parts[-2])
            url_game_map[filename] = parent_folder

    # Build CHD name -> parent game lookup
    chd_to_game: Dict[str, str] = {}
    for name, game in games.items():
        if game.chd_names:
            for chd_name in game.chd_names:
                chd_to_game[chd_name] = name

    for name, game in games.items():
        if not game.category:
            game.category = categories.get(name, '')

    parent_clones: Dict[str, List[str]] = defaultdict(list)
    for name, game in games.items():
        if not game.is_parent and game.parent_name:
            parent_clones[game.parent_name].append(name)

    selected_urls: List[str] = []
    selected_size = 0
    excluded_counts: Dict[str, int] = defaultdict(int)

    if no_filter:
        selected_urls = list(url_map.values())
        selected_size = sum(size_map.values())
    else:
        processed: set = set()

        for filename, url in url_map.items():
            rom_name = (filename.rsplit('.', 1)[0]
                        if '.' in filename else filename)

            if rom_name in processed:
                continue

            if include_patterns:
                if not any(fnmatch.fnmatch(filename.lower(), pat.lower())
                           for pat in include_patterns):
                    excluded_counts['pattern exclude'] += 1
                    continue
            if exclude_patterns:
                if any(fnmatch.fnmatch(filename.lower(), pat.lower())
                       for pat in exclude_patterns):
                    excluded_counts['pattern exclude'] += 1
                    continue

            game = games.get(rom_name)
            if not game and rom_name in chd_to_game:
                rom_name = chd_to_game[rom_name]
                game = games.get(rom_name)
            if not game and filename in url_game_map:
                folder_game = url_game_map[filename]
                if folder_game in games:
                    rom_name = folder_game
                    game = games[folder_game]
            if not game:
                selected_urls.append(url)
                selected_size += size_map.get(filename, 0)
                processed.add(rom_name)
                continue

            if not game.is_parent and game.parent_name:
                parent_name = game.parent_name
                if parent_name in processed:
                    continue
                parent_game = games.get(parent_name)
                if parent_game:
                    game = parent_game
                    rom_name = parent_name

            category = categories.get(rom_name, game.category or '')
            should_include, reason = should_include_mame_game(
                game, category, include_adult)

            if not should_include:
                excluded_counts[reason] += 1
                processed.add(rom_name)
                for clone in parent_clones.get(rom_name, []):
                    processed.add(clone)
                continue

            best_rom = select_best_mame_clone(
                rom_name, parent_clones.get(rom_name, []), games,
                verbose=verbose)
            if not best_rom:
                best_rom = game

            if (english_only
                    and best_rom.region in (
                        'Japan', 'Korea', 'LatinAmerica')):
                excluded_counts[
                    f'Non-English ({best_rom.region})'] += 1
                processed.add(rom_name)
                for clone in parent_clones.get(rom_name, []):
                    processed.add(clone)
                continue

            best_filename = f"{best_rom.name}.zip"
            if best_filename in url_map:
                selected_urls.append(url_map[best_filename])
                selected_size += size_map.get(best_filename, 0)
            elif filename in url_map:
                selected_urls.append(url)
                selected_size += size_map.get(filename, 0)

            processed.add(rom_name)
            for clone in parent_clones.get(rom_name, []):
                processed.add(clone)

    return selected_urls, {
        'source_size': total_source_size,
        'selected_size': selected_size,
    }

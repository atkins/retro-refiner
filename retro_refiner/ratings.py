"""Rating operations: combining sources, boosting exclusives, budget filtering.

Standalone implementations extracted from the monolith. Console output is
replaced by plain stderr for informational messages; verbose callbacks
come from callers.
"""
import json
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Callable, List, Optional

from retro_refiner.dat import RomInfo, normalize_title
from retro_refiner.log import logger
from retro_refiner.systems import load_system_data


# =============================================================================
# Combine IGDB and LaunchBox ratings
# =============================================================================

def combine_ratings(igdb_cache: dict, lb_cache: dict) -> dict:
    """Combine IGDB and LaunchBox ratings using vote-weighted averaging.

    For games rated by both sources, the combined rating is weighted by
    vote count so the source with more votes has more influence. Games
    rated by only one source use that rating unchanged.

    Args:
        igdb_cache: IGDB ratings {system: {title: {rating, votes, name}}}
        lb_cache: LaunchBox ratings {system: {title: {rating, votes, name}}}

    Returns:
        Combined ratings in the same format
    """
    combined = {}
    all_systems = set(list(igdb_cache.keys()) + list(lb_cache.keys()))

    for system in all_systems:
        igdb_games = igdb_cache.get(system, {})
        lb_games = lb_cache.get(system, {})
        merged = {}

        all_titles = set(list(igdb_games.keys()) + list(lb_games.keys()))

        for title in all_titles:
            igdb_entry = igdb_games.get(title)
            lb_entry = lb_games.get(title)

            if igdb_entry and lb_entry:
                ig_r = igdb_entry['rating']
                ig_v = igdb_entry['votes']
                lb_r = lb_entry['rating']
                lb_v = lb_entry['votes']
                total_v = ig_v + lb_v
                if total_v > 0:
                    avg_rating = (ig_r * ig_v + lb_r * lb_v) / total_v
                else:
                    avg_rating = (ig_r + lb_r) / 2.0
                merged[title] = {
                    'rating': round(avg_rating, 2),
                    'votes': total_v,
                    'name': igdb_entry.get('name', lb_entry.get('name', '')),
                }
            elif igdb_entry:
                merged[title] = igdb_entry
            else:
                merged[title] = lb_entry

        if merged:
            combined[system] = merged

    return combined


# =============================================================================
# Boost exclusive ratings
# =============================================================================

def boost_exclusive_ratings(ratings: dict, boost: float = 1.0) -> dict:
    """Boost ratings for platform-exclusive games.

    Identifies games that appear on only one system in the ratings cache
    and applies a rating boost to them, making them sort higher in
    top-N and size-budget filtering.

    Args:
        ratings: Full ratings dict {system: {title: {rating, votes, name}}}
        boost: Rating points to add to exclusives (default: 1.0 on 0-10 scale)

    Returns:
        New ratings dict with boosted exclusive ratings (capped at 10.0)
    """
    title_systems = defaultdict(set)
    for system, games in ratings.items():
        for title in games:
            title_systems[title].add(system)

    boosted = {}
    for system, games in ratings.items():
        boosted_games = {}
        for title, entry in games.items():
            if len(title_systems[title]) == 1:
                boosted_games[title] = {
                    'rating': min(10.0, entry['rating'] + boost),
                    'votes': entry['votes'],
                    'name': entry.get('name', ''),
                }
            else:
                boosted_games[title] = entry
        boosted[system] = boosted_games

    return boosted


# =============================================================================
# Top-N and size budget helpers
# =============================================================================

def resolve_top_n(top_value, total_count: int) -> int:
    """Resolve a top-N value to an absolute count.

    Args:
        top_value: Integer, or string like "10" or "10%"
        total_count: Total number of items (used for percentage calculation)

    Returns:
        Integer count (minimum 1 for percentage mode)
    """
    if top_value is None:
        return None
    if isinstance(top_value, (int, float)) and not isinstance(top_value, bool):
        return int(top_value)
    top_str = str(top_value).strip()
    if top_str.endswith('%'):
        pct = float(top_str[:-1])
        return max(1, int(round(pct / 100.0 * total_count)))
    return int(top_str)


def format_top_label(top_value) -> str:
    """Format top value for display (e.g., 'Top 10' or 'Top 10%')."""
    if top_value is None:
        return "Top ?"
    top_str = str(top_value).strip()
    if top_str.endswith('%'):
        return f"Top {top_str}"
    return f"Top {top_str}"


def apply_top_n_filter(roms: List[RomInfo], ratings: dict, top_n,
                       include_unrated: bool = False) -> List[RomInfo]:
    """Filter ROMs to top N by rating.

    Args:
        roms: List of RomInfo objects (already selected best per game)
        ratings: Dict of {normalized_title: {"rating": float, "votes": int}}
        top_n: Number of top games to keep, or percentage string like "10%"
        include_unrated: If True, append unrated games after rated ones

    Returns:
        Filtered list of RomInfo, sorted by rating descending
    """
    rated_roms = []
    unrated_roms = []

    for rom in roms:
        normalized = normalize_title(rom.base_title)
        rating_entry = ratings.get(normalized)

        if rating_entry:
            rated_roms.append((rom, rating_entry['rating'], rating_entry['votes']))
        else:
            unrated_roms.append(rom)

    rated_roms.sort(key=lambda x: (-x[1], -x[2]))

    count = resolve_top_n(top_n, len(roms))

    result = [rom for rom, _rating, _votes in rated_roms[:count]]

    if include_unrated:
        result.extend(unrated_roms)

    return result


def apply_size_budget(items, item_sizes, budget, ratings=None,
                      name_fn=None, rating_name_fn=None):
    """Truncate items to fit within a size budget, prioritized by rating.

    Args:
        items: list of selected items (RomInfo, MameGameInfo, etc.)
        item_sizes: dict mapping item identifier -> size in bytes
        budget: remaining size budget in bytes
        ratings: optional ratings dict for sorting {normalized_title: {rating, votes}}
        name_fn: function to extract size key from an item (for item_sizes lookup)
        rating_name_fn: function to extract rating key from an item (for ratings lookup);
                        if None, uses name_fn result

    Returns:
        (kept_items, total_size_used)
    """
    if not items:
        return [], 0

    if budget <= 0:
        return [], 0

    entries = []
    for item in items:
        size_key = name_fn(item) if name_fn else item
        size = item_sizes.get(size_key, 0)
        rating_val = 0.0
        votes_val = 0
        if ratings:
            if rating_name_fn:
                rating_key = rating_name_fn(item)
            else:
                rating_key = str(size_key)
            normalized = normalize_title(rating_key)
            entry = ratings.get(normalized)
            if entry:
                rating_val = entry['rating']
                votes_val = entry['votes']
        entries.append((item, size, rating_val, votes_val))

    if ratings:
        entries.sort(key=lambda x: (-x[2], -x[3]))

    kept = []
    used = 0
    for item, size, _, _ in entries:
        if used + size <= budget:
            kept.append(item)
            used += size

    return kept, used


# =============================================================================
# Build ratings cache from LaunchBox XML
# =============================================================================

def build_ratings_cache(xml_path: Path, cache_path: Path = None,
                        on_progress: Callable = None) -> dict:
    """Parse LaunchBox Metadata.xml and build ratings cache.

    If a JSON cache exists and is newer than the XML, loads from cache
    instead of re-parsing the full XML (~486MB).

    Args:
        xml_path: Path to Metadata.xml
        cache_path: Optional path to save JSON cache
        on_progress: Optional callback(bytes_read, total_size, game_count)

    Returns:
        Dict of {system: {normalized_title: {"rating": float, "votes": int}}}
    """
    # Use cached JSON if it exists and is newer than the XML
    if cache_path and cache_path.exists():
        if cache_path.stat().st_mtime >= xml_path.stat().st_mtime:
            try:
                with open(cache_path, encoding='utf-8') as f:
                    cache = json.load(f)
                total_rated = sum(len(v) for v in cache.values())
                logger.debug("Loaded ratings from cache: {} rated across {} systems",
                             total_rated, len(cache))
                return cache
            except (json.JSONDecodeError, OSError):
                logger.debug("Ratings cache corrupt, re-parsing XML")

    sdata = load_system_data()
    launchbox_platform_map = sdata.launchbox_platform_map

    total_file_size = xml_path.stat().st_size

    cache = {}
    game_count = 0
    rated_count = 0
    bytes_read = 0

    parser = ET.XMLPullParser(events=('end',))

    with open(xml_path, 'rb') as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            parser.feed(chunk)
            bytes_read += len(chunk)

            for _, elem in parser.read_events():
                if elem.tag != 'Game':
                    continue

                name = elem.findtext('Name')
                platform = elem.findtext('Platform')
                rating_str = elem.findtext('CommunityRating')
                votes_str = elem.findtext('CommunityRatingCount')

                if name and platform:
                    game_count += 1

                    system = launchbox_platform_map.get(platform)
                    if system and rating_str and votes_str:
                        try:
                            rating = float(rating_str)
                            votes = int(votes_str)

                            normalized = normalize_title(name)

                            if system not in cache:
                                cache[system] = {}

                            existing = cache[system].get(normalized)
                            if not existing or votes > existing['votes']:
                                cache[system][normalized] = {
                                    'rating': rating,
                                    'votes': votes,
                                    'name': name
                                }

                            rated_count += 1
                        except (ValueError, TypeError):
                            pass

                elem.clear()

            if on_progress and total_file_size > 0:
                on_progress(bytes_read, total_file_size, game_count)

    total_rated = sum(len(v) for v in cache.values())
    logger.debug("Ratings parsed: {} games, {} rated across {} systems",
                 game_count, total_rated, len(cache))

    if cache_path:
        with open(cache_path, 'w', encoding='utf-8') as f:
            json.dump(cache, f)
        logger.debug("Ratings cache saved to {}", cache_path)

    return cache


# =============================================================================
# LaunchBox data download
# =============================================================================

LAUNCHBOX_METADATA_URL = "https://gamesdb.launchbox-app.com/Metadata.zip"


def download_launchbox_data(dat_dir: Path, force: bool = False,
                            on_progress: Callable = None
                            ) -> Optional[Path]:
    """Download LaunchBox Metadata.xml for game ratings.

    Args:
        dat_dir: Directory to store downloaded files.
        force: Re-download even if file exists.
        on_progress: Optional callback(downloaded, total_size).

    Returns:
        Path to Metadata.xml or None if download failed.
    """
    launchbox_dir = dat_dir / "launchbox"
    launchbox_dir.mkdir(parents=True, exist_ok=True)

    xml_path = launchbox_dir / "Metadata.xml"
    zip_path = launchbox_dir / "Metadata.zip"

    if xml_path.exists() and not force:
        logger.debug("LaunchBox data cached at {}", xml_path)
        return xml_path

    logger.info("Downloading LaunchBox metadata from {}", LAUNCHBOX_METADATA_URL)
    try:
        req = urllib.request.Request(
            LAUNCHBOX_METADATA_URL,
            headers={'User-Agent': 'Retro-Refiner/1.0'}
        )

        with urllib.request.urlopen(req, timeout=120) as response:
            total_size = int(response.headers.get('content-length', 0))
            downloaded = 0

            with open(zip_path, 'wb') as f:
                while True:
                    chunk = response.read(8192)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if on_progress and total_size > 0:
                        on_progress(downloaded, total_size)

        with zipfile.ZipFile(zip_path, 'r') as zf:
            zf.extract('Metadata.xml', launchbox_dir)

        zip_path.unlink()
        logger.info("LaunchBox metadata extracted to {}", xml_path)
        return xml_path

    except Exception as exc:  # pylint: disable=broad-except
        logger.error("LaunchBox download failed: {}", exc)
        if zip_path.exists():
            zip_path.unlink()
        return None

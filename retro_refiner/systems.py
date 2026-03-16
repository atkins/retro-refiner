"""System data loading for retro-refiner.

Loads system definitions from data/systems.json and returns a SystemData
dataclass. No module-level globals or side effects.
"""
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from retro_refiner.paths import get_base_path


@dataclass
class SystemData:
    """All system lookup tables loaded from data/systems.json."""
    known_systems: List[str]
    extension_to_system: Dict[str, str]
    folder_aliases: Dict[str, str]
    libretro_dat_systems: Dict[str, str]
    additional_dat_systems: Dict[str, list]
    redump_dat_systems: Dict[str, str]
    ten_dat_systems: Dict[str, str]
    launchbox_platform_map: Dict[str, str]
    igdb_platform_map: Dict[str, int]
    dat_name_to_system: Dict[str, str]
    system_to_launchbox: Dict[str, str]
    sorted_dat_names: List[Tuple[str, str]]
    sorted_aliases: List[Tuple[str, str]]


_cache: Optional[SystemData] = None


def reset_cache() -> None:
    """Clear the cached SystemData (used in tests)."""
    global _cache  # pylint: disable=global-statement
    _cache = None


def load_system_data(systems_json_path: Optional[Path] = None) -> SystemData:
    """Load system definitions from data/systems.json.

    Parses the JSON file and builds all lookup dicts. Caches the result;
    subsequent calls return the same SystemData instance.

    Args:
        systems_json_path: Optional explicit path to systems.json. Defaults to
            ``get_base_path() / 'data' / 'systems.json'``.

    Returns:
        A populated SystemData instance.

    Raises:
        SystemExit: If the JSON file cannot be read or parsed.
    """
    global _cache  # pylint: disable=global-statement

    if _cache is not None:
        return _cache

    if systems_json_path is None:
        systems_json_path = get_base_path() / 'data' / 'systems.json'

    try:
        with open(systems_json_path, 'r', encoding='utf-8') as fh:
            raw = json.load(fh)
    except (json.JSONDecodeError, IOError) as exc:
        # Mirror the original behaviour: print and exit
        print(f"ERROR: Could not load systems.json: {exc}", flush=True)
        import sys  # pylint: disable=import-outside-toplevel
        sys.exit(1)

    systems = raw.get('systems', {})

    known: List[str] = list(systems.keys())
    ext_map: Dict[str, str] = {}
    alias_map: Dict[str, str] = {}
    dat_map: Dict[str, str] = {}
    additional_map: Dict[str, list] = {}
    redump_map: Dict[str, str] = {}
    ten_map: Dict[str, str] = {}
    lb_map: Dict[str, str] = {}
    igdb_map: Dict[str, int] = {}

    for system_code, info in systems.items():
        for ext in info.get('extensions', []):
            ext_map[ext] = system_code

        for alias in info.get('folder_aliases', []):
            alias_map[alias] = system_code

        dat_name = info.get('dat_name')
        if dat_name:
            dat_map[system_code] = dat_name

        additional = info.get('additional_dat_names')
        if additional:
            additional_map[system_code] = additional

        redump_name = info.get('redump_dat_name')
        if redump_name:
            redump_map[system_code] = redump_name

        ten_prefix = info.get('ten_dat_prefix')
        if ten_prefix:
            ten_map[system_code] = ten_prefix

        for lb_name in info.get('launchbox_platforms', []):
            lb_map[lb_name] = system_code

        igdb_id = info.get('igdb_id')
        if igdb_id is not None:
            igdb_map[system_code] = igdb_id

    # Reverse mappings
    dat_name_to_sys: Dict[str, str] = {v.lower(): k for k, v in dat_map.items()}
    dat_name_to_sys.update({v.lower(): k for k, v in redump_map.items()})

    sys_to_lb: Dict[str, str] = {}
    for lb_name, sys_code in lb_map.items():
        if sys_code not in sys_to_lb:
            sys_to_lb[sys_code] = lb_name

    # Pre-sorted lists for greedy longest-match detection
    sorted_dat_names: List[Tuple[str, str]] = sorted(
        dat_name_to_sys.items(), key=lambda x: len(x[0]), reverse=True
    )
    sorted_aliases: List[Tuple[str, str]] = sorted(
        alias_map.items(), key=lambda x: len(x[0]), reverse=True
    )

    _cache = SystemData(
        known_systems=known,
        extension_to_system=ext_map,
        folder_aliases=alias_map,
        libretro_dat_systems=dat_map,
        additional_dat_systems=additional_map,
        redump_dat_systems=redump_map,
        ten_dat_systems=ten_map,
        launchbox_platform_map=lb_map,
        igdb_platform_map=igdb_map,
        dat_name_to_system=dat_name_to_sys,
        system_to_launchbox=sys_to_lb,
        sorted_dat_names=sorted_dat_names,
        sorted_aliases=sorted_aliases,
    )
    return _cache

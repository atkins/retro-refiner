#!/usr/bin/env python3
"""
Generate data/systems.json from the hardcoded dicts in retro-refiner.py.

One-time migration script. After running, the generated JSON becomes the
canonical source and the hardcoded dicts are removed from retro-refiner.py.

Usage:
    python tools/generate_systems_json.py
"""

import json
import importlib.util
from pathlib import Path
from collections import defaultdict


def main():
    # Import retro-refiner module
    project_root = Path(__file__).parent.parent
    spec = importlib.util.spec_from_file_location(
        "retro_refiner", project_root / "retro-refiner.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    # Extract all dicts
    known_systems = module.KNOWN_SYSTEMS
    ext_to_system = module.EXTENSION_TO_SYSTEM
    folder_aliases = module.FOLDER_ALIASES
    libretro_dat = module.LIBRETRO_DAT_SYSTEMS
    redump_dat = module.REDUMP_DAT_SYSTEMS
    ten_dat = module.TEN_DAT_SYSTEMS
    launchbox_map = module.LAUNCHBOX_PLATFORM_MAP

    # Collect all system codes from all sources
    all_systems = set(known_systems)
    all_systems.update(ext_to_system.values())
    all_systems.update(folder_aliases.values())
    all_systems.update(libretro_dat.keys())
    all_systems.update(redump_dat.keys())
    all_systems.update(ten_dat.keys())
    all_systems.update(launchbox_map.values())

    # Invert extension map: system -> [extensions]
    system_extensions = defaultdict(list)
    for ext, system in ext_to_system.items():
        system_extensions[system].append(ext)
    # Sort extensions for deterministic output
    for system in system_extensions:
        system_extensions[system].sort()

    # Invert folder aliases: system -> [aliases]
    system_aliases = defaultdict(list)
    for alias, system in folder_aliases.items():
        system_aliases[system].append(alias)
    for system in system_aliases:
        system_aliases[system].sort()

    # Invert launchbox map: system -> [platform names]
    system_launchbox = defaultdict(list)
    for lb_name, system in launchbox_map.items():
        system_launchbox[system].append(lb_name)
    for system in system_launchbox:
        system_launchbox[system].sort()

    # Human-readable display names (derived from DAT names or generated)
    system_names = {}
    for system in sorted(all_systems):
        # Try libretro DAT name first (most descriptive)
        if system in libretro_dat:
            system_names[system] = libretro_dat[system]
        elif system in redump_dat:
            system_names[system] = redump_dat[system]
        else:
            # Generate a reasonable name from the system code
            system_names[system] = system.replace('-', ' ').title()

    # Build the JSON structure
    systems = {}
    for system in sorted(all_systems):
        entry = {"name": system_names[system]}

        if system in system_extensions:
            entry["extensions"] = system_extensions[system]

        if system in system_aliases:
            entry["folder_aliases"] = system_aliases[system]

        if system in libretro_dat:
            entry["dat_name"] = libretro_dat[system]

        if system in redump_dat:
            entry["redump_dat_name"] = redump_dat[system]

        if system in ten_dat:
            entry["ten_dat_prefix"] = ten_dat[system]

        if system in system_launchbox:
            entry["launchbox_platforms"] = system_launchbox[system]

        systems[system] = entry

    output = {
        "_meta": {
            "description": "Canonical system definitions for retro-refiner",
            "version": "1.0",
            "updated": "2026-02-05"
        },
        "systems": systems
    }

    # Write output
    output_path = project_root / "data" / "systems.json"
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"Generated {output_path}")
    print(f"  Systems: {len(systems)}")
    print(f"  With extensions: {sum(1 for s in systems.values() if 'extensions' in s)}")
    print(f"  With folder aliases: {sum(1 for s in systems.values() if 'folder_aliases' in s)}")
    print(f"  With DAT name: {sum(1 for s in systems.values() if 'dat_name' in s)}")
    print(f"  With Redump DAT: {sum(1 for s in systems.values() if 'redump_dat_name' in s)}")
    print(f"  With T-En prefix: {sum(1 for s in systems.values() if 'ten_dat_prefix' in s)}")
    print(f"  With LaunchBox: {sum(1 for s in systems.values() if 'launchbox_platforms' in s)}")


if __name__ == '__main__':
    main()

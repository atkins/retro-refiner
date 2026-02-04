#!/usr/bin/env python3
"""
Generate title mappings by comparing No-Intro DATs with T-En translation DATs.
Finds Japan-only games and their English translation titles.
"""

import re
import json
from pathlib import Path
from collections import defaultdict


def parse_clrmamepro_dat(dat_path: Path) -> list:
    """Parse ClrMamePro format DAT file, return list of game names."""
    games = []
    with open(dat_path, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()

    for match in re.finditer(r'game\s*\(\s*name\s+"([^"]+)"', content):
        games.append(match.group(1))

    return games


def parse_logiqx_xml_dat(dat_path: Path) -> list:
    """Parse Logiqx XML format DAT file, return list of game names."""
    games = []
    with open(dat_path, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()

    for match in re.finditer(r'<machine\s+name="([^"]+)"', content):
        games.append(match.group(1))

    return games


def parse_dat(dat_path: Path) -> list:
    """Auto-detect DAT format and parse."""
    with open(dat_path, 'r', encoding='utf-8', errors='ignore') as f:
        first_line = f.readline().strip()

    if first_line.startswith('<?xml') or first_line.startswith('<'):
        return parse_logiqx_xml_dat(dat_path)
    else:
        return parse_clrmamepro_dat(dat_path)


def normalize_title(title: str) -> str:
    """Normalize a title for comparison."""
    # Remove region/revision/tag info
    title = re.sub(r'\s*\([^)]*\)', '', title)
    title = re.sub(r'\s*\[[^\]]*\]', '', title)

    # Lowercase
    title = title.lower().strip()

    # Remove punctuation except spaces
    title = re.sub(r'[^\w\s]', '', title)

    # Normalize whitespace
    title = ' '.join(title.split())

    # Convert roman numerals
    roman_map = {
        ' ii': ' 2', ' iii': ' 3', ' iv': ' 4', ' v ': ' 5 ',
        ' vi': ' 6', ' vii': ' 7', ' viii': ' 8', ' ix': ' 9', ' x ': ' 10 '
    }
    for roman, arabic in roman_map.items():
        title = title.replace(roman, arabic)

    return title


def extract_base_title(filename: str) -> str:
    """Extract base title from a ROM filename (before region/tags)."""
    # Remove extension
    title = re.sub(r'\.(nes|zip|7z|rar)$', '', filename, flags=re.IGNORECASE)

    # Remove [T-En ...] translation tag and everything after
    title = re.sub(r'\s*\[T-En[^\]]*\].*$', '', title)

    # Remove (Japan), (USA), etc region tags
    title = re.sub(r'\s*\([^)]*\)\s*$', '', title)

    # Remove [n], [i], etc tags
    title = re.sub(r'\s*\[[^\]]*\]', '', title)

    return title.strip()


def find_translation_mappings(nointro_games: list, ten_games: list) -> dict:
    """
    Find mappings between Japan titles and their translations.
    Returns dict of {normalized_jp_title: normalized_en_title}
    """
    mappings = {}

    # Get Japan-only games from No-Intro
    japan_games = {}
    for game in nointro_games:
        if '(Japan)' in game and '(En' not in game and '[T-En' not in game:
            base = extract_base_title(game)
            normalized = normalize_title(base)
            if normalized:
                japan_games[normalized] = base

    # Get translations from T-En DAT
    translations = {}
    for game in ten_games:
        if '[T-En' in game:
            base = extract_base_title(game)
            normalized = normalize_title(base)
            if normalized:
                translations[normalized] = base

    # Find translations that have different English names
    for jp_norm, jp_title in japan_games.items():
        # Look for translations with same base but different display name
        for ten_norm, ten_title in translations.items():
            # Check if they might be related (partial match)
            jp_words = set(jp_norm.split())
            ten_words = set(ten_norm.split())

            # Skip if titles are identical
            if jp_norm == ten_norm:
                continue

            # Skip if no word overlap at all
            common = jp_words & ten_words
            if len(common) < 1:
                continue

            # Check if this is a translation of the same game
            # (translation title often includes translated subtitle)
            if len(common) >= 2 or (len(common) == 1 and len(jp_words) <= 3):
                # Potential match - record it
                if jp_norm not in mappings:
                    mappings[jp_norm] = ten_norm

    return mappings


def find_exact_duplicates(refined_dir: Path) -> dict:
    """
    Scan refined ROMs directory to find actual duplicates.
    Returns dict of {jp_title: [translations]}
    """
    if not refined_dir.exists():
        return {}

    duplicates = defaultdict(list)

    for system_dir in refined_dir.iterdir():
        if not system_dir.is_dir():
            continue

        roms = list(system_dir.glob('*.zip'))

        # Group by normalized base title
        by_title = defaultdict(list)
        for rom in roms:
            base = extract_base_title(rom.name)
            norm = normalize_title(base)
            by_title[norm].append(rom.name)

        # Find groups with both JP and translation
        for norm, rom_list in by_title.items():
            jp_roms = [r for r in rom_list if '(Japan)' in r and '[T-En' not in r]
            ten_roms = [r for r in rom_list if '[T-En' in r]

            if jp_roms and ten_roms:
                for jp in jp_roms:
                    duplicates[jp].extend(ten_roms)

    return duplicates


def main():
    dat_dir = Path('dat_files')

    # Systems to analyze
    systems = ['nes', 'snes', 'gba', 'genesis', 'gameboy', 'gameboy-color',
               'n64', 'psx', 'nds', 'psp']

    all_mappings = defaultdict(dict)

    for system in systems:
        nointro_dat = dat_dir / f'{system}.dat'
        ten_dat = dat_dir / f'{system}_t-en.dat'

        if not nointro_dat.exists():
            print(f"No No-Intro DAT for {system}")
            continue
        if not ten_dat.exists():
            print(f"No T-En DAT for {system}")
            continue

        print(f"\n=== {system.upper()} ===")

        nointro_games = parse_dat(nointro_dat)
        ten_games = parse_dat(ten_dat)

        print(f"No-Intro: {len(nointro_games)} games")
        print(f"T-En: {len(ten_games)} translations")

        # Find Japan-only games
        japan_only = [g for g in nointro_games
                      if '(Japan)' in g and '(En' not in g and '[T-En' not in g
                      and 'Rev' not in g]  # Skip revisions
        print(f"Japan-only: {len(japan_only)} games")

        # Find translations
        translations = [g for g in ten_games if '[T-En' in g]
        print(f"Translations: {len(translations)}")

        # Try to match them
        # Build lookup by extracting Japanese title from translation name
        # Format: "English Title (Japan) [T-En by ...]"
        for ten_game in translations:
            # Extract the English title from the translation
            ten_base = extract_base_title(ten_game)
            ten_norm = normalize_title(ten_base)

            # Look for matching Japan game
            for jp_game in japan_only:
                jp_base = extract_base_title(jp_game)
                jp_norm = normalize_title(jp_base)

                # Skip if already same
                if jp_norm == ten_norm:
                    continue

                # Check for partial match (some common words)
                jp_words = set(jp_norm.split())
                ten_words = set(ten_norm.split())
                common = jp_words & ten_words

                # Strong match: multiple common words
                if len(common) >= 2:
                    if jp_norm not in all_mappings[system]:
                        all_mappings[system][jp_norm] = ten_norm
                        print(f"  {jp_base}")
                        print(f"    -> {ten_base}")

    # Also scan the refined directory for actual duplicates
    refined_dir = Path('refined')
    if refined_dir.exists():
        print("\n\n=== ACTUAL DUPLICATES IN REFINED ===")
        for system_dir in refined_dir.iterdir():
            if not system_dir.is_dir():
                continue

            roms = list(system_dir.glob('*.zip'))

            # Find Japan ROMs that have [T-En] counterparts
            jp_roms = [r.name for r in roms if '(Japan)' in r.name and '[T-En' not in r.name]
            ten_roms = [r.name for r in roms if '[T-En' in r.name]

            for jp in jp_roms:
                jp_base = extract_base_title(jp)
                jp_norm = normalize_title(jp_base)

                for ten in ten_roms:
                    ten_base = extract_base_title(ten)
                    ten_norm = normalize_title(ten_base)

                    # Check word overlap
                    jp_words = set(jp_norm.split())
                    ten_words = set(ten_norm.split())
                    common = jp_words & ten_words

                    if len(common) >= 1 and jp_norm != ten_norm:
                        print(f"\nDUPLICATE in {system_dir.name}:")
                        print(f"  JP: {jp}")
                        print(f"  EN: {ten}")
                        print(f"  Common words: {common}")

                        # Add to mappings
                        all_mappings[system_dir.name][jp_norm] = ten_norm

    # Output mappings
    print("\n\n=== GENERATED MAPPINGS ===")
    output = {}
    for system, mappings in all_mappings.items():
        if mappings:
            output[f"{system}_translations"] = mappings

    print(json.dumps(output, indent=2, ensure_ascii=False))

    # Save to file
    with open('generated_mappings.json', 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"\nSaved to generated_mappings.json")


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""
Update Title Mappings - Scan archives and DATs to suggest new title mappings.

This tool helps maintain title_mappings.json by:
1. Scanning No-Intro and Redump DAT files for game relationships
2. Scanning archive URLs (like Myrient) for ROM filenames
3. Identifying potential Japan <-> USA/Europe title pairs
4. Suggesting new mappings for review

Usage:
    python update_mappings.py --scan-dats                    # Scan local DAT files
    python update_mappings.py --scan-url URL                 # Scan archive URL
    python update_mappings.py --scan-myrient SYSTEM          # Scan Myrient for system
    python update_mappings.py --suggest                      # Show suggested mappings
    python update_mappings.py --merge                        # Merge suggestions into mappings
"""

import json
import re
import sys
import urllib.request
import urllib.error
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Set, Tuple, Optional


# Myrient base URLs
MYRIENT_NOINTO = "https://myrient.erista.me/files/No-Intro/"
MYRIENT_REDUMP = "https://myrient.erista.me/files/Redump/"
MYRIENT_T_EN = "https://myrient.erista.me/files/T-En%20Collection/"

# Common system name mappings for Myrient URLs
MYRIENT_SYSTEMS = {
    'nes': 'Nintendo%20-%20Nintendo%20Entertainment%20System%20(Headered)',
    'snes': 'Nintendo%20-%20Super%20Nintendo%20Entertainment%20System',
    'n64': 'Nintendo%20-%20Nintendo%2064',
    'gb': 'Nintendo%20-%20Game%20Boy',
    'gbc': 'Nintendo%20-%20Game%20Boy%20Color',
    'gba': 'Nintendo%20-%20Game%20Boy%20Advance',
    'nds': 'Nintendo%20-%20Nintendo%20DS%20(Decrypted)',
    'genesis': 'Sega%20-%20Mega%20Drive%20-%20Genesis',
    'sms': 'Sega%20-%20Master%20System%20-%20Mark%20III',
    'gg': 'Sega%20-%20Game%20Gear',
    'pce': 'NEC%20-%20PC%20Engine%20-%20TurboGrafx-16',
    'psx': 'Sony%20-%20PlayStation',  # Redump
    'ps2': 'Sony%20-%20PlayStation%202',  # Redump
    'saturn': 'Sega%20-%20Saturn',  # Redump
    'segacd': 'Sega%20-%20Mega-CD%20-%20Sega%20CD',  # Redump
}


def normalize_title_for_comparison(title: str) -> str:
    """Normalize a title for comparison purposes."""
    # Remove file extension
    title = re.sub(r'\.(zip|7z|rar|iso|cue|bin|chd)$', '', title, flags=re.IGNORECASE)

    # Extract base title (before region/tags)
    match = re.match(r'^(.+?)\s*[\(\[]', title)
    if match:
        title = match.group(1)

    # Lowercase and remove special characters
    title = title.lower()
    title = re.sub(r'[^\w\s]', ' ', title)
    title = re.sub(r'\s+', ' ', title).strip()

    # Convert roman numerals to arabic
    roman_map = {
        'viii': '8', 'vii': '7', 'vi': '6', 'iv': '4', 'v': '5',
        'iii': '3', 'ii': '2', 'i': '1', 'ix': '9', 'x': '10'
    }
    for roman, arabic in roman_map.items():
        title = re.sub(rf'\b{roman}\b', arabic, title)

    return title


def extract_region(filename: str) -> Optional[str]:
    """Extract region from filename."""
    regions = {
        'usa': ['USA', 'US', 'America'],
        'europe': ['Europe', 'EUR', 'EU'],
        'japan': ['Japan', 'JP', 'JPN'],
        'world': ['World'],
        'korea': ['Korea', 'KR'],
        'germany': ['Germany', 'DE'],
        'france': ['France', 'FR'],
        'spain': ['Spain', 'ES'],
        'italy': ['Italy', 'IT'],
    }

    for region, patterns in regions.items():
        for pattern in patterns:
            if re.search(rf'\({pattern}[,\)]', filename, re.IGNORECASE):
                return region
    return None


def fetch_url(url: str, timeout: int = 30) -> Optional[str]:
    """Fetch URL content."""
    try:
        request = urllib.request.Request(
            url,
            headers={'User-Agent': 'Mozilla/5.0 (compatible; Retro-Refiner/1.0)'}
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read().decode('utf-8', errors='replace')
    except Exception as e:
        print(f"  Error fetching {url}: {e}")
        return None


def parse_html_for_files(html: str) -> List[str]:
    """Extract filenames from HTML directory listing."""
    files = []

    # Look for href links to ROM files
    patterns = [
        r'href="([^"]+\.(?:zip|7z|rar|iso|cue|chd))"',
        r"href='([^']+\.(?:zip|7z|rar|iso|cue|chd))'",
    ]

    for pattern in patterns:
        matches = re.findall(pattern, html, re.IGNORECASE)
        for match in matches:
            # URL decode
            filename = urllib.request.unquote(match)
            # Get just the filename
            filename = filename.split('/')[-1].split('?')[0]
            if filename and not filename.startswith('.'):
                files.append(filename)

    return list(set(files))


def parse_dat_file(dat_path: Path) -> Dict[str, List[dict]]:
    """Parse a No-Intro or Redump DAT file."""
    games = defaultdict(list)

    if not dat_path.exists():
        return games

    content = dat_path.read_text(encoding='utf-8', errors='replace')

    # Try XML format first
    if content.strip().startswith('<?xml') or '<datafile' in content[:1000]:
        return parse_xml_dat(content)

    # Try ClrMamePro format
    return parse_clrmamepro_dat(content)


def parse_xml_dat(content: str) -> Dict[str, List[dict]]:
    """Parse XML format DAT file."""
    import xml.etree.ElementTree as ET
    games = defaultdict(list)

    try:
        root = ET.fromstring(content)
        for game in root.findall('.//game'):
            name = game.get('name', '')
            if not name:
                continue

            region = extract_region(name)
            normalized = normalize_title_for_comparison(name)

            games[normalized].append({
                'name': name,
                'region': region,
                'normalized': normalized
            })
    except ET.ParseError:
        pass

    return games


def parse_clrmamepro_dat(content: str) -> Dict[str, List[dict]]:
    """Parse ClrMamePro format DAT file."""
    games = defaultdict(list)

    # Match game entries
    game_pattern = re.compile(r'game\s*\(\s*name\s+"([^"]+)"', re.MULTILINE)

    for match in game_pattern.finditer(content):
        name = match.group(1)
        region = extract_region(name)
        normalized = normalize_title_for_comparison(name)

        games[normalized].append({
            'name': name,
            'region': region,
            'normalized': normalized
        })

    return games


def scan_archive_url(url: str) -> List[str]:
    """Scan an archive URL for ROM filenames."""
    print(f"Scanning: {url}")

    html = fetch_url(url)
    if not html:
        return []

    files = parse_html_for_files(html)
    print(f"  Found {len(files)} files")
    return files


def find_regional_pairs(games: Dict[str, List[dict]]) -> List[Tuple[str, str, str]]:
    """
    Find games that have both Japan and USA/Europe versions.
    Returns list of (japan_title, english_title, normalized_base) tuples.
    """
    pairs = []

    for normalized, entries in games.items():
        japan_entries = [e for e in entries if e['region'] == 'japan']
        english_entries = [e for e in entries if e['region'] in ('usa', 'europe', 'world')]

        if japan_entries and english_entries:
            # Found a game with both Japan and English versions
            japan_name = japan_entries[0]['name']
            english_name = english_entries[0]['name']

            # Only suggest if the names are actually different
            japan_normalized = normalize_title_for_comparison(japan_name)
            english_normalized = normalize_title_for_comparison(english_name)

            if japan_normalized != english_normalized:
                pairs.append((japan_normalized, english_normalized, normalized))

    return pairs


def scan_myrient_system(system: str, include_redump: bool = True) -> Dict[str, List[dict]]:
    """Scan Myrient for a specific system."""
    games = defaultdict(list)

    if system not in MYRIENT_SYSTEMS:
        print(f"Unknown system: {system}")
        print(f"Available: {', '.join(MYRIENT_SYSTEMS.keys())}")
        return games

    system_path = MYRIENT_SYSTEMS[system]

    # Determine if this is a Redump system (CD-based)
    redump_systems = {'psx', 'ps2', 'saturn', 'segacd'}

    if system in redump_systems and include_redump:
        url = MYRIENT_REDUMP + system_path + "/"
    else:
        url = MYRIENT_NOINTO + system_path + "/"

    files = scan_archive_url(url)

    for filename in files:
        region = extract_region(filename)
        normalized = normalize_title_for_comparison(filename)

        games[normalized].append({
            'name': filename,
            'region': region,
            'normalized': normalized
        })

    return games


def load_existing_mappings(path: Path = None) -> Dict[str, Dict[str, str]]:
    """Load existing title mappings."""
    if path is None:
        path = Path(__file__).parent.parent / 'data' / 'title_mappings.json'

    if not path.exists():
        return {}

    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def get_all_existing_mappings(mappings: Dict) -> Set[str]:
    """Get all source titles from existing mappings."""
    all_sources = set()
    for category, entries in mappings.items():
        if category.startswith('_'):
            continue
        if isinstance(entries, dict):
            all_sources.update(entries.keys())
    return all_sources


def suggest_new_mappings(games: Dict[str, List[dict]],
                         existing: Dict[str, Dict[str, str]]) -> List[Tuple[str, str]]:
    """Suggest new mappings that don't exist yet."""
    existing_sources = get_all_existing_mappings(existing)
    pairs = find_regional_pairs(games)

    suggestions = []
    for japan, english, _ in pairs:
        if japan not in existing_sources and japan != english:
            suggestions.append((japan, english))

    return suggestions


def scan_dat_directory(dat_dir: Path) -> Dict[str, List[dict]]:
    """Scan all DAT files in a directory."""
    all_games = defaultdict(list)

    dat_files = list(dat_dir.glob('*.dat')) + list(dat_dir.glob('*.xml'))

    for dat_file in dat_files:
        print(f"Parsing: {dat_file.name}")
        games = parse_dat_file(dat_file)

        for normalized, entries in games.items():
            all_games[normalized].extend(entries)

    return all_games


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description='Update title mappings from archives and DATs'
    )
    parser.add_argument('--scan-dats', metavar='DIR',
                        help='Scan DAT files in directory')
    parser.add_argument('--scan-url', metavar='URL',
                        help='Scan archive URL for ROMs')
    parser.add_argument('--scan-myrient', metavar='SYSTEM',
                        help='Scan Myrient for system (nes, snes, gba, etc.)')
    parser.add_argument('--include-redump', action='store_true', default=True,
                        help='Include Redump DATs for CD-based systems (default: True)')
    parser.add_argument('--suggest', action='store_true',
                        help='Show suggested new mappings')
    parser.add_argument('--output', metavar='FILE',
                        help='Output suggestions to file')
    parser.add_argument('--list-systems', action='store_true',
                        help='List available Myrient systems')

    args = parser.parse_args()

    if args.list_systems:
        print("Available Myrient systems:")
        for system in sorted(MYRIENT_SYSTEMS.keys()):
            print(f"  {system}")
        return

    games = defaultdict(list)

    if args.scan_dats:
        dat_dir = Path(args.scan_dats)
        if dat_dir.exists():
            games = scan_dat_directory(dat_dir)
        else:
            print(f"Directory not found: {dat_dir}")
            sys.exit(1)

    if args.scan_url:
        files = scan_archive_url(args.scan_url)
        for filename in files:
            region = extract_region(filename)
            normalized = normalize_title_for_comparison(filename)
            games[normalized].append({
                'name': filename,
                'region': region,
                'normalized': normalized
            })

    if args.scan_myrient:
        system_games = scan_myrient_system(args.scan_myrient, args.include_redump)
        for normalized, entries in system_games.items():
            games[normalized].extend(entries)

    if args.suggest or args.output:
        existing = load_existing_mappings()
        suggestions = suggest_new_mappings(games, existing)

        if suggestions:
            print(f"\n{len(suggestions)} suggested new mappings:")
            print("-" * 60)

            output_lines = []
            for japan, english in sorted(suggestions):
                line = f'"{japan}": "{english}"'
                output_lines.append(line)
                print(f"  {line},")

            if args.output:
                with open(args.output, 'w', encoding='utf-8') as f:
                    f.write('\n'.join(output_lines))
                print(f"\nSuggestions written to: {args.output}")
        else:
            print("\nNo new mappings suggested.")

    if not any([args.scan_dats, args.scan_url, args.scan_myrient]):
        parser.print_help()


if __name__ == '__main__':
    main()

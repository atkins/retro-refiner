#!/usr/bin/env python3
"""
Analyze refined ROMs to find duplicates and generate title mappings.
Focuses on Japan ROMs that have [T-En] translations.
"""

import re
import json
from pathlib import Path
from collections import defaultdict


def normalize_for_comparison(title: str) -> str:
    """Normalize title for comparison - very basic."""
    title = title.lower()
    title = re.sub(r'[^\w\s]', '', title)
    title = ' '.join(title.split())
    return title


def extract_base_title(filename: str) -> str:
    """Extract base title before region/tags."""
    # Remove extension
    title = re.sub(r'\.zip$', '', filename, flags=re.IGNORECASE)
    # Remove everything from (Japan) onwards
    title = re.sub(r'\s*\(Japan\).*$', '', title)
    # Remove everything from (USA) onwards
    title = re.sub(r'\s*\(USA\).*$', '', title)
    return title.strip()


def find_duplicates(rom_dir: Path):
    """Find Japan ROMs that have translation counterparts."""
    if not rom_dir.exists():
        return

    roms = list(rom_dir.glob('*.zip'))

    # Separate Japan untranslated and translations
    japan_roms = []
    translations = []

    for rom in roms:
        name = rom.name
        if '[T-En' in name:
            translations.append(name)
        elif '(Japan)' in name:
            japan_roms.append(name)

    # Build mapping of normalized base -> full name for translations
    trans_by_base = {}
    for t in translations:
        base = extract_base_title(t)
        norm = normalize_for_comparison(base)
        if norm not in trans_by_base:
            trans_by_base[norm] = []
        trans_by_base[norm].append(t)

    # Find duplicates
    duplicates = []

    for jp in japan_roms:
        jp_base = extract_base_title(jp)
        jp_norm = normalize_for_comparison(jp_base)

        # Look for translations with similar base
        for t_norm, t_names in trans_by_base.items():
            # Check various matching criteria
            matched = False

            # Exact match (same normalized base)
            if jp_norm == t_norm:
                matched = True

            # Check if JP title is prefix of translation title
            elif t_norm.startswith(jp_norm):
                matched = True

            # Check if translation title is prefix of JP title
            elif jp_norm.startswith(t_norm):
                matched = True

            # Check for significant word overlap (at least 2 words)
            else:
                jp_words = set(jp_norm.split())
                t_words = set(t_norm.split())
                common = jp_words & t_words

                # At least 2 common words and they make up most of shorter title
                if len(common) >= 2:
                    shorter_len = min(len(jp_words), len(t_words))
                    if len(common) >= shorter_len * 0.5:
                        matched = True

            if matched:
                for t_name in t_names:
                    duplicates.append({
                        'japan': jp,
                        'japan_base': jp_base,
                        'translation': t_name,
                        'translation_base': extract_base_title(t_name),
                    })

    return duplicates


def main():
    refined_dir = Path('refined')

    all_duplicates = []

    for system_dir in sorted(refined_dir.iterdir()):
        if not system_dir.is_dir():
            continue

        system = system_dir.name
        duplicates = find_duplicates(system_dir)

        if duplicates:
            print(f"\n=== {system.upper()} ({len(duplicates)} duplicates) ===")
            for d in duplicates:
                print(f"\n  JP: {d['japan']}")
                print(f"  EN: {d['translation']}")
                all_duplicates.append({**d, 'system': system})

    # Generate mappings
    print("\n\n" + "="*60)
    print("GENERATED TITLE MAPPINGS")
    print("="*60)

    # Group by category
    mappings = defaultdict(dict)

    for d in all_duplicates:
        jp_norm = normalize_for_comparison(d['japan_base'])
        en_norm = normalize_for_comparison(d['translation_base'])

        if jp_norm != en_norm:  # Only add if different
            category = f"{d['system']}_translations"
            mappings[category][jp_norm] = en_norm

    # Output as JSON
    output = dict(mappings)
    print(json.dumps(output, indent=2, ensure_ascii=False))

    # Save to file
    with open('duplicate_mappings.json', 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\nSaved {len(all_duplicates)} mappings to duplicate_mappings.json")


if __name__ == '__main__':
    main()

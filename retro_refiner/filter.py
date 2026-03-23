"""ROM filtering: parsing filenames, selecting best ROMs from groups.

Standalone implementations extracted from the monolith.  Console output is
replaced by optional ``on_progress`` callbacks and plain stderr for errors.
"""
import fnmatch
import os
import re
import shutil
from collections import defaultdict
from pathlib import Path
from typing import Callable, Dict, List, Optional

from retro_refiner.config import Config, DEFAULT_REGION_PRIORITY
from retro_refiner.dat import (
    RomInfo,
    normalize_title,
    normalize_title_for_dedupe,
    get_cached_crc,
    load_crc_cache,
    save_crc_cache,
)
from retro_refiner.models import ExcludedRom, FilterResult, FilterStats
from retro_refiner.network import format_size, get_filename_from_url


# =============================================================================
# Pre-compiled regex patterns used by parse_rom_filename()
# =============================================================================

_RE_EXTENSION = re.compile(
    r'\.(zip|7z|rar|sfc|smc|nes|n64|z64|v64|md|gen|bin|gb|gbc|gba|nds|gcm'
    r'|iso|cue|pce|col|a26|a52|a78|jag|lnx|st|int|gg|sms|sg|32x|vb|ws|wsc'
    r'|rom|mx1|mx2)$', re.IGNORECASE)
_RE_BETA = re.compile(r'\(Beta[^)]*\)')
_RE_PROTO = re.compile(r'\(Proto[^)]*\)')
_RE_MULTI_GAME = re.compile(r'\+ .+ \(')
_RE_NUMBERING = re.compile(r'\b(\d) & (\d)\b')
_RE_TRANSLATION = re.compile(r'\[T-En[^\]]*\]')
_RE_REGION = re.compile(r'\(([^)]+)\)')
_RE_ENGLISH_TAG = re.compile(r'\([^)]*\bEn\b[^)]*\)')
_RE_REVISION = re.compile(r'\(Rev\s*([A-Z0-9]+)\)')
_RE_VERSION = re.compile(r'\(v(\d+)\.(\d+)\)')
_RE_TITLE_VERSION = re.compile(r'\s+v(\d+(?:\.\d+)?)\s*$', re.IGNORECASE)
_RE_BRACKETS = re.compile(r'\[[^\]]+\]')
_RE_PARENS = re.compile(r'\s*\([^)]+\)')
_RE_WHITESPACE = re.compile(r'\s+')
_RE_YEAR = re.compile(r'\((\d{4})\)')
_RE_DISC = re.compile(
    r'\((?:Disc|Disk|Part)\s+(\d+)(?:\s+of\s+\d+)?\)', re.IGNORECASE)

# TOSEC naming convention patterns
_RE_TOSEC_DATE = re.compile(
    r'^\(\d{4}(?:-\d{2}(?:-\d{2})?)?\)$|^\(\d{2}xx\)$')
_RE_TOSEC_REVISION = re.compile(r'\s+r(\d+)\s*$')
_RE_TOSEC_BAD_FLAGS = re.compile(r'\[([bo!a]|cr[^\]]*)\]', re.IGNORECASE)
_TOSEC_REGION_MAP = {
    'US': 'USA', 'GB': 'Europe', 'EU': 'Europe', 'JP': 'Japan',
    'FR': 'France', 'DE': 'Germany', 'ES': 'Spain', 'IT': 'Italy',
    'AU': 'Australia', 'NL': 'Netherlands', 'SE': 'Sweden',
    'BR': 'Brazil', 'KR': 'Korea', 'CN': 'China', 'TW': 'Taiwan',
    'CA': 'Canada', 'PT': 'Portugal', 'NO': 'Norway', 'DK': 'Denmark',
    'FI': 'Finland',
}
_TOSEC_ENGLISH_REGIONS = {'US', 'GB', 'AU', 'CA'}

# =============================================================================
# Filter pattern lists
# =============================================================================

RERELEASE_PATTERNS = [re.compile(p) for p in [
    r'Virtual Console', r'GameCube\)', r'\(LodgeNet\)',
    r'\(Arcade\)', r'Sega Channel', r'Switch Online',
    r'Classic Mini', r'Retro-Bit', r'Evercade',
    r'Wii Virtual Console', r'Mega Drive Mini',
    r'Collection\)', r'\(NP\)',
    r'\(e-Reader\)', r'\(FamicomBox\)', r'Animal Crossing',
    r'Sonic Classic Collection', r'Sonic Mega Collection',
    r'Disney Classic Games', r'Castlevania Anniversary',
    r'Castlevania Advance Collection', r'Sega Smash Pack',
    r'Game no Kanzume', r'Sega Game Toshokan',
    r'SegaNet', r'Sega 3D Classics',
    r'Capcom Town', r'iam8bit',
    r'GameCube Edition',
    r'Genesis Mini', r'Mega Drive Mini',
    r'Contra Anniversary Collection', r'Konami Collector',
    r'Arcade Legends',
]]

COMPILATION_PATTERNS = [re.compile(p) for p in [
    r'\d+.in.1\b', r'\d+ Super Jogos', r'^\d+-Pak',
    r'Compilation',
    r'\+ .+ \+',
    r'Super Mario All-Stars',
    r'Double Pack', r'^2 Games in 1', r'^2 Games in One',
    r'^2.in.1 Game Pack', r'^Combo Pack', r'^2 Game Pack',
    r'Classics\)', r'Competition Cartridge',
    r'Twin Pack',
    r'Super Pack', r'^Double Game!',
    r'^Plato Courseware\b',
    r'^Tigercub\s+\d',
    r'^BCS\s+(Disk|Specialty Disk)\s+\d',
    r'^Modules\s+Disk\s+\d',
]]

_HACK_PATTERNS = [re.compile(p, re.IGNORECASE) for p in [
    r'\[Hack by',
    r'\[Add by',
    r'Edition\]',
    r'\[FastROM',
    r'\[Bugfix',
    r'patch\]',
    r'\[Retranslated\]',
    r'GBA Script',
]]


# =============================================================================
# ROM Filename Parsing
# =============================================================================

def parse_rom_filename(filename: str) -> RomInfo:
    """Parse a ROM filename and extract metadata."""

    # Remove file extension
    name = _RE_EXTENSION.sub('', filename)

    # Detect TOSEC naming
    is_tosec = False
    first_paren = _RE_REGION.search(name)
    if first_paren and _RE_TOSEC_DATE.match(f'({first_paren.group(1)})'):
        is_tosec = True

    is_bios = name.startswith('[BIOS]') or '(BIOS)' in name
    if name.startswith('_'):
        is_bios = True

    is_pirate = '(Pirate)' in name
    is_unlicensed = '(Unl)' in name

    is_beta = bool(_RE_BETA.search(name))
    is_demo = ('(Demo)' in name or '(demo' in name.lower()
               or '(Kiosk)' in name or 'Caravan' in name
               or 'Taikenban' in name
               or '(Test Program)' in name or '(Program)' in name
               or '(Tech Demo)' in name
               or '(SDK' in name or 'Diagnostic' in name
               or 'Development Card' in name
               or 'Atari PAM' in name or '(Trade Demo)' in name
               or 'Boot Disc' in name
               or 'Kensa' in name)
    is_promo = ('(Promo)' in name or '(Movie Promo)' in name
                or 'Present Campaign' in name
                or 'Senyou Cartridge' in name
                or 'Hot Mario Campaign' in name)
    is_sample = '(Sample)' in name
    is_proto = '(Proto)' in name or bool(_RE_PROTO.search(name))

    # TOSEC-specific flags
    tosec_cracked = False
    tosec_verified = False
    if is_tosec:
        name_lower = name.lower()
        if '(demo' in name_lower:
            is_demo = True
        for flag_match in _RE_TOSEC_BAD_FLAGS.finditer(name):
            flag = flag_match.group(1)
            flag_lower = flag.lower()
            if flag_lower in ('b', 'o', 'a'):
                is_beta = True
            elif flag_lower.startswith('cr'):
                tosec_cracked = True
            elif flag == '!':
                tosec_verified = True

    is_rerelease = any(p.search(name) for p in RERELEASE_PATTERNS)
    is_compilation = any(p.search(name) for p in COMPILATION_PATTERNS)

    if _RE_MULTI_GAME.search(name) and 'All-Stars' not in name:
        is_compilation = True
    if _RE_NUMBERING.search(name):
        is_compilation = True

    is_lock_on = '(Lock-on Combination)' in name or (
        'Sonic & Knuckles +' in name and 'Sonic' in name
    )

    is_translation = bool(_RE_TRANSLATION.search(name))

    if tosec_cracked:
        is_pirate = True
    if 'Cracked' in name and not any(
            x in name for x in ('Crack Down', 'Cracker')):
        is_pirate = True

    has_hacks = any(p.search(name) for p in _HACK_PATTERNS) or tosec_cracked

    # Extract region and language
    region = "Unknown"
    is_english = False
    revision = 0

    if is_tosec:
        paren_tokens = _RE_REGION.findall(name)
        tosec_region_code = None
        has_lang_tag = False

        for token in paren_tokens[2:]:
            token_upper = token.upper().strip()
            if token_upper in _TOSEC_REGION_MAP:
                tosec_region_code = token_upper
                region = _TOSEC_REGION_MAP[token_upper]
            if re.match(r'^[a-z]{2}(?:\s*-\s*[a-z]{2})*$', token.strip()):
                has_lang_tag = True
                if re.search(r'\ben\b', token.strip()):
                    is_english = True

        if (_RE_ENGLISH_TAG.search(name)
                or re.search(r'\(en\b', name, re.IGNORECASE)):
            is_english = True
        elif tosec_region_code in _TOSEC_ENGLISH_REGIONS:
            is_english = True
        elif not tosec_region_code and not has_lang_tag:
            is_english = True

        pre_paren = name[:name.index('(')] if '(' in name else name
        tosec_rev = _RE_TOSEC_REVISION.search(pre_paren)
        if tosec_rev:
            revision = int(tosec_rev.group(1))

        rev_match = _RE_REVISION.search(name)
        if rev_match:
            rev_str = rev_match.group(1)
            rev_val = (int(rev_str) if rev_str.isdigit()
                       else ord(rev_str[0].upper()) - ord('A') + 1)
            revision = max(revision, rev_val)

        if tosec_verified:
            revision += 1

    else:
        # No-Intro naming
        region_match = _RE_REGION.search(name)
        if region_match:
            region_str = region_match.group(1)
            nointro_regions = [
                'USA', 'World', 'Europe', 'Australia', 'England',
                'Japan', 'Korea',
                'Brazil', 'France', 'Germany', 'Spain', 'Italy', 'Asia',
                'Taiwan', 'Hong Kong', 'China']
            for reg in nointro_regions:
                if reg in region_str:
                    region = reg
                    break

        if _RE_ENGLISH_TAG.search(name):
            is_english = True
        if region in ['USA', 'World', 'Europe', 'Australia', 'England']:
            is_english = True
        if is_translation:
            is_english = True

        rev_match = _RE_REVISION.search(name)
        if rev_match:
            rev_str = rev_match.group(1)
            if rev_str.isdigit():
                revision = int(rev_str)
            else:
                revision = ord(rev_str[0].upper()) - ord('A') + 1

    # Version numbers (both No-Intro and TOSEC)
    ver_match = _RE_VERSION.search(name)
    if ver_match:
        revision = max(revision,
                       int(ver_match.group(1)) * 100
                       + int(ver_match.group(2)))

    # Disc number
    disc_match = _RE_DISC.search(name)
    disc_number = int(disc_match.group(1)) if disc_match else 0

    # Extract base title
    base_title = name
    base_title = _RE_BRACKETS.sub('', base_title)
    base_title = _RE_PARENS.sub('', base_title)
    tosec_rev_match = _RE_TOSEC_REVISION.search(base_title)
    if tosec_rev_match:
        revision = max(revision, int(tosec_rev_match.group(1)))
        base_title = base_title[:tosec_rev_match.start()]
    title_ver_match = _RE_TITLE_VERSION.search(base_title)
    if title_ver_match:
        ver_str = title_ver_match.group(1)
        base_title = base_title[:title_ver_match.start()]
        if '.' in ver_str:
            parts = ver_str.split('.')
            ver_num = int(parts[0]) * 100 + int(parts[1])
        else:
            ver_num = int(ver_str) * 100
        revision = max(revision, ver_num)
    base_title = base_title.strip()
    base_title = _RE_WHITESPACE.sub(' ', base_title)

    homebrew_indicators = ['(Aftermarket)', '(Homebrew)', 'Homebrew']
    is_homebrew = any(ind in name for ind in homebrew_indicators)

    # Year
    year = 0
    if is_tosec and first_paren:
        date_str = first_paren.group(1)
        if len(date_str) >= 4 and date_str[:4].isdigit():
            potential_year = int(date_str[:4])
            if 1970 <= potential_year <= 2030:
                year = potential_year
    year_match = _RE_YEAR.search(name)
    if year_match:
        potential_year = int(year_match.group(1))
        if 1970 <= potential_year <= 2030:
            year = potential_year

    return RomInfo(
        filename=filename,
        base_title=base_title,
        region=region,
        revision=revision,
        is_english=is_english,
        is_translation=is_translation,
        is_beta=is_beta,
        is_demo=is_demo,
        is_promo=is_promo,
        is_sample=is_sample,
        is_proto=is_proto,
        is_bios=is_bios,
        is_pirate=is_pirate,
        is_unlicensed=is_unlicensed,
        is_homebrew=is_homebrew,
        is_rerelease=is_rerelease,
        is_compilation=is_compilation,
        is_lock_on=is_lock_on,
        has_hacks=has_hacks,
        year=year,
        disc_number=disc_number,
    )


# =============================================================================
# Best ROM Selection
# =============================================================================

def select_best_rom(roms: List[RomInfo],
                    region_priority: List[str] = None,
                    verbose: bool = False) -> Optional[RomInfo]:
    """Select the best ROM from a group of ROMs for the same game.

    Priority order:
    1. English versions (USA/Europe/World)
    2. English translations of foreign games
    3. Foreign versions (Japan, etc.) if no English option exists
    """
    _ = verbose  # Reserved for future callback-based logging
    if not roms:
        return None

    if region_priority is None:
        region_priority = DEFAULT_REGION_PRIORITY

    # Filter out universally unwanted ROMs
    base_filtered = []
    for rom in roms:
        if rom.is_bios or rom.is_pirate or rom.is_homebrew or rom.is_unlicensed:
            continue
        if rom.is_beta or rom.is_demo or rom.is_promo or rom.is_sample:
            continue
        if rom.is_rerelease:
            continue
        if rom.is_compilation:
            continue
        if rom.is_lock_on:
            continue
        base_filtered.append(rom)

    if not base_filtered:
        return None

    # Check if a non-English region is explicitly prioritised higher than
    # all English regions.  When the user deliberately puts e.g. Japan first,
    # we should honour that instead of unconditionally preferring English.
    english_regions = {'USA', 'World', 'Europe', 'Australia', 'England'}
    _uses_custom_foreign = False
    if region_priority != DEFAULT_REGION_PRIORITY:
        # Find the highest-priority region that appears in the candidate ROMs
        first_in_list = next(
            (r for r in region_priority
             if any(rom.region == r for rom in base_filtered)), None)
        if first_in_list and first_in_list not in english_regions:
            _uses_custom_foreign = True

    # Separate into English and non-English pools
    # Skip this separation when the user's custom priority puts a
    # non-English region first — let region_priority decide instead.
    if _uses_custom_foreign:
        candidates = base_filtered
    else:
        english_roms = [r for r in base_filtered if r.is_english]
        foreign_roms = [r for r in base_filtered if not r.is_english]
        candidates = english_roms if english_roms else foreign_roms

    if not candidates:
        return None

    # Separate prototypes from regular releases
    protos = [r for r in candidates if r.is_proto]
    regular = [r for r in candidates if not r.is_proto]
    candidates = regular if regular else protos

    # Prefer official English over translations over untranslated
    # (skip when custom foreign priority is active — let sort handle it)
    if not _uses_custom_foreign:
        non_trans = [r for r in candidates if not r.is_translation]
        translations = [r for r in candidates if r.is_translation]

        english_non_trans = [
            r for r in non_trans if r.region in english_regions]

        if english_non_trans:
            non_hacked = [r for r in english_non_trans if not r.has_hacks]
            candidates = non_hacked if non_hacked else english_non_trans
        elif translations:
            pure_trans = [r for r in translations if not r.has_hacks]
            candidates = pure_trans if pure_trans else translations
        elif non_trans:
            non_hacked = [r for r in non_trans if not r.has_hacks]
            candidates = non_hacked if non_hacked else non_trans

    # Sort by region priority, revision, hacks
    def sort_key(rom: RomInfo):
        priority_dict = {
            reg: idx for idx, reg in enumerate(region_priority)}
        return (
            priority_dict.get(rom.region, 99),
            -rom.revision,
            1 if rom.has_hacks else 0,
        )

    candidates.sort(key=sort_key)
    return candidates[0] if candidates else None


def _collect_sibling_discs(best: RomInfo,
                           group: List[RomInfo]) -> List[RomInfo]:
    """Given a selected ROM, find all discs of the same game matching
    its region/revision."""
    if best.disc_number == 0:
        return [best]
    siblings = [r for r in group
                if r.disc_number > 0
                and r.region == best.region
                and r.revision == best.revision
                and r.is_translation == best.is_translation]
    siblings.sort(key=lambda r: r.disc_number)
    return siblings if siblings else [best]


# =============================================================================
# Pattern matching helper
# =============================================================================

def matches_patterns(name: str, patterns: List[str]) -> bool:
    """Check if a filename matches any of the glob patterns."""
    name_lower = name.lower()
    return any(fnmatch.fnmatch(name_lower, pat.lower()) for pat in patterns)


# =============================================================================
# Network ROM filtering (standalone)
# =============================================================================

def filter_network_roms(system, urls, config, url_sizes=None,
                        dat_entries=None, on_progress=None):
    # type: (str, List[str], Config, Dict[str, int], dict, Callable) -> FilterResult
    """Filter network ROM URLs for a console system.

    Standalone implementation -- does not depend on the monolith.

    Args:
        system: System code.
        urls: List of ROM URLs.
        config: Configuration object.
        url_sizes: Optional dict of URL -> file size.
        dat_entries: Optional pre-loaded DAT entries dict.
        on_progress: Optional callback for progress updates.

    Returns:
        FilterResult with selected/excluded URLs and statistics.
    """
    _ = on_progress

    if not urls:
        return FilterResult(system=system)

    sel = config.selection
    region_priority = sel.region_priority or DEFAULT_REGION_PRIORITY
    keep_regions = (sel.keep_regions.split(',')
                    if sel.keep_regions else None)
    no_filter = sel.all_roms
    if url_sizes is None:
        url_sizes = {}

    # Build filename -> DAT name lookup for better title matching
    dat_name_lookup: Dict[str, str] = {}
    if dat_entries:
        for _, entry in dat_entries.items():
            rom_base = Path(entry.rom_name).stem.lower()
            dat_name_lookup[rom_base] = entry.name

    # Parse all ROMs from URLs
    all_roms: List[RomInfo] = []
    url_map: Dict[str, str] = {}
    size_map: Dict[str, int] = {}
    total_source_size = 0
    breakdown: Dict[str, int] = defaultdict(int)
    excluded_list: List[ExcludedRom] = []

    for url in urls:
        filename = get_filename_from_url(url)

        if not no_filter:
            if (sel.include_patterns
                    and not matches_patterns(filename, sel.include_patterns)):
                breakdown['include pattern'] += 1
                excluded_list.append(ExcludedRom(
                    filename=filename, reason='include pattern',
                    size=url_sizes.get(url, 0)))
                continue
            if (sel.exclude_patterns
                    and matches_patterns(filename, sel.exclude_patterns)):
                breakdown['exclude pattern'] += 1
                excluded_list.append(ExcludedRom(
                    filename=filename, reason='exclude pattern',
                    size=url_sizes.get(url, 0)))
                continue

        rom_info = parse_rom_filename(filename)

        if not no_filter:
            if rom_info.is_proto and sel.exclude_protos:
                breakdown['prototype'] += 1
                excluded_list.append(ExcludedRom(
                    filename=filename, reason='prototype',
                    size=url_sizes.get(url, 0)))
                continue
            if rom_info.is_beta and not sel.include_betas:
                breakdown['beta'] += 1
                excluded_list.append(ExcludedRom(
                    filename=filename, reason='beta',
                    size=url_sizes.get(url, 0)))
                continue
            if rom_info.is_unlicensed and not sel.include_unlicensed:
                breakdown['unlicensed'] += 1
                excluded_list.append(ExcludedRom(
                    filename=filename, reason='unlicensed',
                    size=url_sizes.get(url, 0)))
                continue

            if rom_info.year > 0:
                if sel.year_from and rom_info.year < sel.year_from:
                    breakdown['year range'] += 1
                    excluded_list.append(ExcludedRom(
                        filename=filename, reason='year range',
                        size=url_sizes.get(url, 0)))
                    continue
                if sel.year_to and rom_info.year > sel.year_to:
                    breakdown['year range'] += 1
                    excluded_list.append(ExcludedRom(
                        filename=filename, reason='year range',
                        size=url_sizes.get(url, 0)))
                    continue

        all_roms.append(rom_info)
        url_map[filename] = url
        file_size = url_sizes.get(url, 0)
        size_map[filename] = file_size
        total_source_size += file_size

    if no_filter:
        selected_urls = [url_map[rom.filename]
                         for rom in all_roms if rom.filename in url_map]
    elif not sel.best_version:
        # Individual filters applied above, but no 1G1R grouping
        selected_urls = [url_map[rom.filename]
                         for rom in all_roms if rom.filename in url_map]
        if sel.english_only:
            english_set = {rom.filename for rom in all_roms if rom.is_english}
            selected_urls = [u for u in selected_urls
                             if get_filename_from_url(u) in english_set]
    else:
        # Group by normalized title
        grouped: Dict[str, List[RomInfo]] = defaultdict(list)
        for rom in all_roms:
            rom_base = Path(rom.filename).stem.lower()
            if rom_base in dat_name_lookup:
                dat_name = dat_name_lookup[rom_base]
                dat_rom_info = parse_rom_filename(dat_name + '.zip')
                normalized = normalize_title(dat_rom_info.base_title)
            else:
                normalized = normalize_title(rom.base_title)
            grouped[normalized].append(rom)

        selected_urls = []
        selected_roms_list: List[RomInfo] = []
        for _title, roms in grouped.items():
            if keep_regions:
                seen_regions: set = set()
                for reg in keep_regions:
                    for rom in sorted(roms, key=lambda r: (
                            r.is_translation, r.has_hacks, -r.revision)):
                        if rom.region == reg and reg not in seen_regions:
                            if rom.filename in url_map:
                                for sibling in _collect_sibling_discs(
                                        rom, roms):
                                    if sibling.filename in url_map:
                                        selected_urls.append(
                                            url_map[sibling.filename])
                                        selected_roms_list.append(sibling)
                                seen_regions.add(reg)
                            break
                if not seen_regions:
                    best = select_best_rom(roms, region_priority)
                    if best and best.filename in url_map:
                        for sibling in _collect_sibling_discs(best, roms):
                            if sibling.filename in url_map:
                                selected_urls.append(
                                    url_map[sibling.filename])
                                selected_roms_list.append(sibling)
            else:
                best = select_best_rom(roms, region_priority)
                if best and best.filename in url_map:
                    for sibling in _collect_sibling_discs(best, roms):
                        if sibling.filename in url_map:
                            selected_urls.append(url_map[sibling.filename])
                            selected_roms_list.append(sibling)

        # Apply english-only filter
        if sel.english_only:
            english_pairs = [(u, r) for u, r in zip(
                selected_urls, selected_roms_list) if r.is_english]
            if english_pairs:
                selected_urls = [p[0] for p in english_pairs]
            else:
                selected_urls = []

    # Track post-selection exclusions (1G1R duplicates, english-only)
    selected_url_set = set(selected_urls)
    for rom in all_roms:
        url = url_map.get(rom.filename)
        if url and url not in selected_url_set:
            if sel.english_only and not rom.is_english:
                reason = 'non-english'
            else:
                reason = 'duplicate version'
            breakdown[reason] += 1
            excluded_list.append(ExcludedRom(
                filename=rom.filename, reason=reason,
                size=size_map.get(rom.filename, 0)))

    # Count DAT matches
    dat_matched = sum(1 for rom in all_roms
                      if Path(rom.filename).stem.lower() in dat_name_lookup)

    selected_size = sum(
        size_map.get(get_filename_from_url(u), 0) for u in selected_urls)

    stats = FilterStats(
        source_count=len(urls),
        selected_count=len(selected_urls),
        excluded_count=len(urls) - len(selected_urls),
        source_size=total_source_size,
        selected_size=selected_size,
        dat_matched=dat_matched,
        filter_breakdown=dict(breakdown),
    )

    result = FilterResult(
        system=system, selected=selected_urls,
        excluded=excluded_list[:500], stats=stats)
    result.size_info = {
        'source_size': total_source_size,
        'selected_size': selected_size,
    }
    return result


# =============================================================================
# File-size helper
# =============================================================================

def get_file_size(filepath: Path) -> int:
    """Get the size of a file in bytes, returning 0 on error."""
    try:
        return filepath.stat().st_size
    except (OSError, IOError):
        return 0


# =============================================================================
# Local ROM filtering (filter_roms_from_files)
# =============================================================================

def filter_roms_from_files(rom_files: list, dest_dir: str, system: str,
                           dry_run: bool = False,
                           dat_entries: Dict[str, 'DatRomEntry'] = None,
                           include_patterns: List[str] = None,
                           exclude_patterns: List[str] = None,
                           exclude_protos: bool = False,
                           include_betas: bool = False,
                           include_unlicensed: bool = False,
                           region_priority: List[str] = None,
                           keep_regions: List[str] = None,
                           flat_output: bool = False,
                           transfer_mode: str = 'move',
                           year_from: int = None,
                           year_to: int = None,
                           verbose: bool = False,
                           top_n: int = None,
                           include_unrated: bool = False,
                           ratings: dict = None,
                           no_filter: bool = False,
                           best_version: bool = False,
                           english_only: bool = False,
                           download_crc_index: dict = None,
                           exclude_titles: set = None,
                           no_verify: bool = False,
                           no_cache: bool = False,
                           log_dir: str = None):
    """Filter ROMs from a list of file paths.

    If dat_entries is provided, uses DAT metadata to enhance/override
    filename parsing.

    Returns:
        (selected_roms, size_info_dict) where size_info_dict has keys
        'source_size', 'selected_size', and 'rom_sizes'.
    """
    if flat_output:
        dest_path = Path(dest_dir)
    else:
        dest_path = Path(dest_dir) / system

    if region_priority is None:
        region_priority = DEFAULT_REGION_PRIORITY

    crc_to_dat = dat_entries or {}
    dat_matched = 0

    crc_cache_path = dest_path / '_crc_cache.json'
    crc_cache = (load_crc_cache(crc_cache_path)
                 if crc_to_dat and not no_cache else {})

    all_roms = []
    file_map = {}
    size_map = {}
    filtered_by_pattern = 0
    total_source_size = 0

    for filepath in rom_files:
        filename = filepath.name

        if not no_filter:
            if (include_patterns
                    and not matches_patterns(filename, include_patterns)):
                filtered_by_pattern += 1
                continue
            if (exclude_patterns
                    and matches_patterns(filename, exclude_patterns)):
                filtered_by_pattern += 1
                continue

        rom_info = parse_rom_filename(filename)

        if not no_filter:
            if rom_info.is_proto and exclude_protos:
                continue
            if rom_info.is_beta and not include_betas:
                continue
            if rom_info.is_unlicensed and not include_unlicensed:
                continue

            if rom_info.year > 0:
                if year_from and rom_info.year < year_from:
                    continue
                if year_to and rom_info.year > year_to:
                    continue

        all_roms.append(rom_info)
        file_map[filename] = filepath
        file_size = get_file_size(filepath)
        size_map[filename] = file_size
        total_source_size += file_size

    skipped_games = []

    if no_filter:
        selected_roms = all_roms
        grouped = {rom.base_title: [rom] for rom in all_roms}
    elif not best_version:
        # Individual filters applied above, but no 1G1R grouping
        selected_roms = list(all_roms)
        grouped = {rom.base_title: [rom] for rom in all_roms}
        if english_only:
            selected_roms = [r for r in selected_roms if r.is_english]
    else:
        grouped = defaultdict(list)
        for rom in all_roms:
            normalized = normalize_title(rom.base_title)
            grouped[normalized].append(rom)

        if exclude_titles:
            for title in list(grouped.keys()):
                sample_rom = grouped[title][0]
                dedupe_key = normalize_title_for_dedupe(
                    sample_rom.base_title)
                if dedupe_key in exclude_titles:
                    del grouped[title]

        selected_roms = []

        for title, roms in grouped.items():
            if keep_regions:
                for region in keep_regions:
                    region_roms = [r for r in roms
                                   if r.region.lower() == region.lower()]
                    if region_roms:
                        best = select_best_rom(region_roms, region_priority,
                                               verbose=verbose)
                        if best:
                            selected_roms.extend(
                                _collect_sibling_discs(best, roms))
                if not any(r in selected_roms for r in roms):
                    best = select_best_rom(roms, region_priority,
                                           verbose=verbose)
                    if best:
                        selected_roms.extend(
                            _collect_sibling_discs(best, roms))
            else:
                best = select_best_rom(roms, region_priority,
                                       verbose=verbose)
                if best:
                    selected_roms.extend(
                        _collect_sibling_discs(best, roms))
                else:
                    sample = roms[0].filename if roms else "unknown"
                    skipped_games.append((title, sample))

        if english_only:
            selected_roms = [r for r in selected_roms if r.is_english]

        # Post-selection DAT enrichment
        if crc_to_dat and not no_verify:
            for rom in selected_roms:
                filepath = file_map.get(rom.filename)
                if not filepath:
                    continue
                crc = get_cached_crc(filepath, crc_cache,
                                     download_crc_index)
                if crc and crc in crc_to_dat:
                    dat_entry = crc_to_dat[crc]
                    if dat_entry.region != 'Unknown':
                        rom.region = dat_entry.region
                    dat_matched += 1
            if not no_cache:
                save_crc_cache(crc_cache_path, crc_cache)

        # Apply top-N filter
        if top_n and ratings:
            from retro_refiner.ratings import apply_top_n_filter  # pylint: disable=import-outside-toplevel
            system_ratings = ratings.get(system, {})
            selected_roms = apply_top_n_filter(
                selected_roms, system_ratings, top_n, include_unrated)

    selected_size = sum(size_map.get(rom.filename, 0)
                        for rom in selected_roms)

    if dry_run:
        return selected_roms, {
            'source_size': total_source_size,
            'selected_size': selected_size,
            'rom_sizes': size_map,
        }

    # Transfer
    dest_path.mkdir(parents=True, exist_ok=True)

    for rom in selected_roms:
        src = file_map.get(rom.filename)
        if src and src.exists():
            dst = dest_path / rom.filename
            _transfer_file(src, dst, transfer_mode)

    # Write selection log
    if log_dir:
        log_dir_path = Path(log_dir)
        log_dir_path.mkdir(parents=True, exist_ok=True)
        log_path = log_dir_path / f"{system}_selection_log.txt"
        with open(log_path, 'w', encoding='utf-8') as f:
            f.write(f"ROM Selection Log for {system.upper()}\n")
            f.write("=" * 60 + "\n\n")
            f.write(f"Total ROMs scanned: {len(all_roms)}\n")
            f.write(f"Unique games found: {len(grouped)}\n")
            f.write(f"ROMs selected: {len(selected_roms)}\n\n")
            f.write(f"Source size: {format_size(total_source_size)}\n")
            f.write(f"Selected size: {format_size(selected_size)}\n\n")
            f.write("SELECTED ROMS:\n")
            f.write("-" * 60 + "\n")
            for rom in sorted(selected_roms,
                              key=lambda r: r.base_title.lower()):
                f.write(f"{rom.filename}\n")
                f.write(f"  Title: {rom.base_title}\n")
                f.write(f"  Region: {rom.region}, "
                        f"Rev: {rom.revision}\n\n")

    return selected_roms, {
        'source_size': total_source_size,
        'selected_size': selected_size,
        'rom_sizes': size_map,
    }


def _transfer_file(src: Path, dst: Path, mode: str = 'copy'):
    """Transfer a single file using the specified mode."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if mode == 'link':
        if dst.exists() or dst.is_symlink():
            dst.unlink()
        try:
            dst.symlink_to(src.resolve())
        except OSError:
            shutil.copy2(src, dst)
    elif mode == 'hardlink':
        if dst.exists():
            dst.unlink()
        try:
            os.link(src, dst)
        except OSError:
            shutil.copy2(src, dst)
    elif mode == 'move':
        shutil.move(str(src), str(dst))
    else:
        shutil.copy2(src, dst)

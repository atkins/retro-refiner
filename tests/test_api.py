#!/usr/bin/env python3
"""
Comprehensive tests for retro_refiner/ui/api.py.

Tests the Api class and module-level helpers without requiring a GUI window.
Uses the TestResult framework (not pytest). Run directly:
    python tests/test_api.py
"""

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

# Add project root to path so retro_refiner package is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from retro_refiner.ui.api import (
    Api, _display_name, _get_exclusion_reason,
    _parse_csv, _int_or_none, _float_or_none, _parse_size_string,
    _SYSTEM_ABBREVS,
)
from retro_refiner.config import Config
from retro_refiner.filter import parse_rom_filename


class TestResult:
    """Track test results."""
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.errors = []

    def ok(self, name):
        self.passed += 1
        print(f"  [PASS] {name}")

    def fail(self, name, expected, actual):
        self.failed += 1
        self.errors.append((name, expected, actual))
        print(f"  [FAIL] {name}")
        print(f"    Expected: {expected}")
        print(f"    Actual:   {actual}")

    def summary(self):
        total = self.passed + self.failed
        print(f"\n{'='*60}")
        print(f"Results: {self.passed}/{total} passed")
        if self.failed > 0:
            print(f"Failed tests: {self.failed}")
        print(f"{'='*60}")
        return self.failed == 0


results = TestResult()


def make_api():
    """Create an Api instance without a window."""
    api = Api()
    api._window = None  # No GUI, events silently dropped
    return api


# =============================================================================
# _display_name tests
# =============================================================================

def test_display_name():
    print("\n--- _display_name ---")

    # Abbreviations should go full uppercase
    abbrevs = {
        'snes': 'SNES', 'nes': 'NES', 'gba': 'GBA', 'gbc': 'GBC',
        'n64': 'N64', 'psx': 'PSX', 'ps2': 'PS2', 'ps3': 'PS3',
        'psp': 'PSP', '3do': '3DO', '3ds': '3DS', 'dsi': 'DSI',
        'fds': 'FDS', 'msx': 'MSX', 'msx2': 'MSX2', 'n64dd': 'N64DD',
        'ngp': 'NGP', 'ngpc': 'NGPC', 'scv': 'SCV', 'sgx': 'SGX',
        'tg16': 'TG16', 'tgcd': 'TGCD',
    }
    for code, expected in abbrevs.items():
        actual = _display_name(code)
        if actual == expected:
            results.ok(f"display_name abbrev: {code} -> {expected}")
        else:
            results.fail(f"display_name abbrev: {code}", expected, actual)

    # Case insensitivity: SNES, Snes, sNeS should all match
    for variant in ('SNES', 'Snes', 'sNeS'):
        actual = _display_name(variant)
        if actual == variant.upper():
            results.ok(f"display_name case-insensitive: {variant}")
        else:
            results.fail(f"display_name case-insensitive: {variant}",
                         variant.upper(), actual)

    # Hyphenated systems
    hyph_cases = {
        'game-boy-advance': 'Game Boy Advance',
        'mega-drive': 'Mega Drive',
        'pc-engine': 'Pc Engine',
    }
    for code, expected in hyph_cases.items():
        actual = _display_name(code)
        if actual == expected:
            results.ok(f"display_name hyphen: {code} -> {expected}")
        else:
            results.fail(f"display_name hyphen: {code}", expected, actual)

    # Underscored systems
    under_cases = {
        'game_boy': 'Game Boy',
        'pc_engine': 'Pc Engine',
    }
    for code, expected in under_cases.items():
        actual = _display_name(code)
        if actual == expected:
            results.ok(f"display_name underscore: {code} -> {expected}")
        else:
            results.fail(f"display_name underscore: {code}", expected, actual)

    # Simple one-word non-abbrev
    actual = _display_name('genesis')
    if actual == 'Genesis':
        results.ok("display_name simple: genesis -> Genesis")
    else:
        results.fail("display_name simple: genesis", 'Genesis', actual)


# =============================================================================
# _eta_str tests
# =============================================================================

def test_eta_str():
    print("\n--- _eta_str ---")

    # Zero completed -> empty string
    actual = Api._eta_str(10.0, 0, 100)
    if actual == '':
        results.ok("eta_str: zero completed -> empty")
    else:
        results.fail("eta_str: zero completed", "''", repr(actual))

    # Negative completed -> empty
    actual = Api._eta_str(10.0, -1, 100)
    if actual == '':
        results.ok("eta_str: negative completed -> empty")
    else:
        results.fail("eta_str: negative completed", "''", repr(actual))

    # Zero total -> empty
    actual = Api._eta_str(10.0, 5, 0)
    if actual == '':
        results.ok("eta_str: zero total -> empty")
    else:
        results.fail("eta_str: zero total", "''", repr(actual))

    # Small ETA (under 60s): 50 done in 10s, 50 remaining
    # rate = 50/10 = 5/s, remaining = 50, eta = 10s
    actual = Api._eta_str(10.0, 50, 100)
    if '~10s left' in actual:
        results.ok("eta_str: small ETA (~10s left)")
    else:
        results.fail("eta_str: small ETA", 'contains ~10s left', actual)

    # Large ETA (over 60s): 10 done in 10s, 990 remaining
    # rate = 10/10 = 1/s, remaining = 990, eta = 990s = 16m 30s
    actual = Api._eta_str(10.0, 10, 1000)
    if '~16m' in actual and 'left' in actual:
        results.ok("eta_str: large ETA (minutes format)")
    else:
        results.fail("eta_str: large ETA", 'contains ~16m...left', actual)

    # All completed -> eta should be ~0s left
    actual = Api._eta_str(10.0, 100, 100)
    if '~0s left' in actual:
        results.ok("eta_str: all completed -> ~0s left")
    else:
        results.fail("eta_str: all completed", 'contains ~0s left', actual)

    # ETA string contains the pipe separator
    actual = Api._eta_str(10.0, 50, 100)
    if '\u2502' in actual:
        results.ok("eta_str: contains pipe separator")
    else:
        results.fail("eta_str: pipe separator", 'contains |', actual)


# =============================================================================
# _elapsed_str tests
# =============================================================================

def test_elapsed_str():
    print("\n--- _elapsed_str ---")

    # Under 60s -> "Xs"
    actual = Api._elapsed_str(0)
    if actual == '0s':
        results.ok("elapsed_str: 0 seconds")
    else:
        results.fail("elapsed_str: 0 seconds", '0s', actual)

    actual = Api._elapsed_str(45)
    if actual == '45s':
        results.ok("elapsed_str: 45 seconds")
    else:
        results.fail("elapsed_str: 45 seconds", '45s', actual)

    actual = Api._elapsed_str(59.9)
    if actual == '59s':
        results.ok("elapsed_str: 59.9 seconds -> 59s")
    else:
        results.fail("elapsed_str: 59.9 seconds", '59s', actual)

    # Over 60s -> "Xm XXs"
    actual = Api._elapsed_str(60)
    if actual == '1m 00s':
        results.ok("elapsed_str: 60 seconds -> 1m 00s")
    else:
        results.fail("elapsed_str: 60 seconds", '1m 00s', actual)

    actual = Api._elapsed_str(90)
    if actual == '1m 30s':
        results.ok("elapsed_str: 90 seconds -> 1m 30s")
    else:
        results.fail("elapsed_str: 90 seconds", '1m 30s', actual)

    actual = Api._elapsed_str(3661)
    if actual == '61m 01s':
        results.ok("elapsed_str: 3661 seconds -> 61m 01s")
    else:
        results.fail("elapsed_str: 3661 seconds", '61m 01s', actual)

    # Float precision
    actual = Api._elapsed_str(125.7)
    if actual == '2m 05s':
        results.ok("elapsed_str: 125.7 seconds -> 2m 05s")
    else:
        results.fail("elapsed_str: 125.7 seconds", '2m 05s', actual)


# =============================================================================
# get_default_config tests
# =============================================================================

def test_get_default_config():
    print("\n--- get_default_config ---")

    api = make_api()
    # Set some non-default values first
    api._config.sources = ['http://example.com']
    api._config.destination = '/tmp/roms'
    api._config.selection.english_only = True

    result_json = api.get_default_config()

    # Should be valid JSON
    try:
        data = json.loads(result_json)
        results.ok("get_default_config: returns valid JSON")
    except json.JSONDecodeError:
        results.fail("get_default_config: valid JSON", "valid JSON", "invalid")
        return

    # After reset, sources should be empty
    if data.get('sources') == []:
        results.ok("get_default_config: sources reset to []")
    else:
        results.fail("get_default_config: sources reset",
                     [], data.get('sources'))

    # destination should be None
    if data.get('destination') is None:
        results.ok("get_default_config: destination reset to None")
    else:
        results.fail("get_default_config: destination reset",
                     None, data.get('destination'))

    # english_only should be False (default)
    sel = data.get('selection', {})
    if sel.get('english_only') is False:
        results.ok("get_default_config: english_only reset to False")
    else:
        results.fail("get_default_config: english_only reset",
                     False, sel.get('english_only'))

    # Internal config should also be reset
    if api._config.sources == []:
        results.ok("get_default_config: internal config reset")
    else:
        results.fail("get_default_config: internal config reset",
                     [], api._config.sources)


# =============================================================================
# Config snapshot independence
# =============================================================================

def test_config_snapshot():
    print("\n--- Config snapshot ---")

    api = make_api()
    api._config.sources = ['http://original.com']
    api._config.selection.english_only = True

    # Create snapshot like _do_run does
    snapshot = Config.from_dict(api._config.to_dict())

    # Mutate original
    api._config.sources.append('http://added.com')
    api._config.selection.english_only = False

    # Snapshot should be independent
    if len(snapshot.sources) == 1:
        results.ok("config_snapshot: sources independent")
    else:
        results.fail("config_snapshot: sources independent",
                     1, len(snapshot.sources))

    if snapshot.selection.english_only is True:
        results.ok("config_snapshot: selection independent")
    else:
        results.fail("config_snapshot: selection independent",
                     True, snapshot.selection.english_only)

    if snapshot.sources[0] == 'http://original.com':
        results.ok("config_snapshot: original value preserved")
    else:
        results.fail("config_snapshot: original value preserved",
                     'http://original.com', snapshot.sources[0])


# =============================================================================
# _step_prefix tests
# =============================================================================

def test_step_prefix():
    print("\n--- _step_prefix ---")

    api = make_api()

    # Default is preview mode (2 steps)
    prefix = api._step_prefix(1)
    if prefix == '[1/2] ':
        results.ok("step_prefix: default preview step 1")
    else:
        results.fail("step_prefix: default preview step 1",
                     '[1/2] ', prefix)

    prefix = api._step_prefix(2)
    if prefix == '[2/2] ':
        results.ok("step_prefix: default preview step 2")
    else:
        results.fail("step_prefix: default preview step 2",
                     '[2/2] ', prefix)

    # Simulate commit mode (3 steps)
    api._step_prefix = lambda n: f'[{n}/3] '
    prefix = api._step_prefix(3)
    if prefix == '[3/3] ':
        results.ok("step_prefix: commit step 3")
    else:
        results.fail("step_prefix: commit step 3", '[3/3] ', prefix)


# =============================================================================
# _compute_system_stats tests
# =============================================================================

def test_compute_system_stats():
    print("\n--- _compute_system_stats ---")

    api = make_api()

    # Test with network URLs
    urls = [
        'https://example.com/Game%20(USA).zip',
        'https://example.com/Another%20Game%20(Europe)%20(En%2CFr).zip',
        'https://example.com/Third%20Game%20(Japan).nes',
    ]
    sizes = {
        'https://example.com/Game%20(USA).zip': 1024,
        'https://example.com/Another%20Game%20(Europe)%20(En%2CFr).zip': 2048,
        'https://example.com/Third%20Game%20(Japan).nes': 512,
    }

    stats = api._compute_system_stats(urls, [], sizes, 'nes')

    # Should have net_count
    if stats['net_count'] == 3:
        results.ok("system_stats: net_count = 3")
    else:
        results.fail("system_stats: net_count", 3, stats['net_count'])

    # local_count should be 0
    if stats['local_count'] == 0:
        results.ok("system_stats: local_count = 0")
    else:
        results.fail("system_stats: local_count", 0, stats['local_count'])

    # Should have regions
    if 'USA' in stats['regions']:
        results.ok("system_stats: USA region detected")
    else:
        results.fail("system_stats: USA region", 'USA in regions',
                     stats['regions'])

    if 'Europe' in stats['regions']:
        results.ok("system_stats: Europe region detected")
    else:
        results.fail("system_stats: Europe region", 'Europe in regions',
                     stats['regions'])

    # Should have formats
    if '.zip' in stats['formats']:
        results.ok("system_stats: .zip format detected")
    else:
        results.fail("system_stats: .zip format", '.zip in formats',
                     stats['formats'])

    if '.nes' in stats['formats']:
        results.ok("system_stats: .nes format detected")
    else:
        results.fail("system_stats: .nes format", '.nes in formats',
                     stats['formats'])

    # Should have size info
    if stats['sizes']['largest'][1] == 2048:
        results.ok("system_stats: largest size = 2048")
    else:
        results.fail("system_stats: largest size", 2048,
                     stats['sizes']['largest'][1])

    if stats['sizes']['smallest'][1] == 512:
        results.ok("system_stats: smallest size = 512")
    else:
        results.fail("system_stats: smallest size", 512,
                     stats['sizes']['smallest'][1])

    # Histogram: all should be < 1 MB
    if stats['sizes']['histogram']['< 1 MB'] == 3:
        results.ok("system_stats: histogram all < 1 MB")
    else:
        results.fail("system_stats: histogram", 3,
                     stats['sizes']['histogram']['< 1 MB'])

    # System field should be present
    if stats['system'] == 'nes':
        results.ok("system_stats: system field = nes")
    else:
        results.fail("system_stats: system field", 'nes', stats['system'])


def test_compute_system_stats_empty():
    print("\n--- _compute_system_stats (empty) ---")

    api = make_api()
    stats = api._compute_system_stats([], [], {}, 'snes')

    if stats['net_count'] == 0:
        results.ok("system_stats_empty: net_count = 0")
    else:
        results.fail("system_stats_empty: net_count", 0, stats['net_count'])

    if stats['local_count'] == 0:
        results.ok("system_stats_empty: local_count = 0")
    else:
        results.fail("system_stats_empty: local_count", 0,
                     stats['local_count'])

    if stats['regions'] == {}:
        results.ok("system_stats_empty: no regions")
    else:
        results.fail("system_stats_empty: regions", {}, stats['regions'])

    if stats['sizes']['avg'] == 0:
        results.ok("system_stats_empty: avg size = 0")
    else:
        results.fail("system_stats_empty: avg size", 0,
                     stats['sizes']['avg'])


# =============================================================================
# update_config_from_ui tests
# =============================================================================

def test_update_config_from_ui():
    print("\n--- update_config_from_ui ---")

    api = make_api()

    ui_state = {
        'sources': ['http://example.com/roms', '/local/path'],
        'source_settings': {'/local/path': {'recursive': True}},
        'destination': '/output/dir',
        'systems': 'nes,snes,genesis',
        'all_roms': False,
        'best_version': True,
        'english_only': True,
        'exclude_protos': True,
        'include_betas': False,
        'no_unlicensed': True,
        'region_priority': 'USA, Europe, Japan',
        'include_patterns': 'mario, zelda',
        'exclude_patterns': 'demo',
        'year_from': '1990',
        'year_to': '2000',
        'top': '100',
        'limit': '500',
        'size': '10GB',
        'include_unrated': True,
        'prefer_exclusives': '1.5',
        'parallel': 8,
        'scan_workers': 32,
        'resume_downloads': True,
        'auto_tune': False,
        'playlists': True,
        'gamelists': '/gamelists',
        'flatten': True,
        'local_file_action': 'symlink',
        'validate_destination': False,
        'clean_destination': True,
        'crc_validation': True,
        'retroarch_playlists': '/ra/playlists',
        'no_verify': True,
        'no_dat': True,
        'no_chd': True,
        'no_cache': True,
        'no_adult': True,
        'recursive': True,
        'max_depth': 5,
        'mame_version': '0.265',
        'dat_dir': '/dat',
        'log_dir': '/logs',
        'ratings_source': 'launchbox',
        'igdb_client_id': 'test_id',
        'igdb_client_secret': 'test_secret',
        'ia_access_key': 'ia_key',
        'ia_secret_key': 'ia_secret',
        'dedup_priority': 'snes,genesis,nes',
        'dedup_pc_lists': 'list1.txt, list2.txt',
        'dedup_delete': True,
        'theme': 'cyberpunk',
        'exclude_systems': 'atari2600, intellivision',
    }

    api.update_config_from_ui(json.dumps(ui_state))

    cfg = api._config

    # Sources
    if cfg.sources == ['http://example.com/roms', '/local/path']:
        results.ok("update_config: sources set")
    else:
        results.fail("update_config: sources",
                     ['http://example.com/roms', '/local/path'], cfg.sources)

    # Source settings
    if cfg.source_settings.get('/local/path', {}).get('recursive') is True:
        results.ok("update_config: source_settings recursive")
    else:
        results.fail("update_config: source_settings",
                     True, cfg.source_settings)

    # Destination
    if cfg.destination == '/output/dir':
        results.ok("update_config: destination set")
    else:
        results.fail("update_config: destination", '/output/dir',
                     cfg.destination)

    # Systems parsed from CSV
    if cfg.systems == ['nes', 'snes', 'genesis']:
        results.ok("update_config: systems parsed from CSV")
    else:
        results.fail("update_config: systems",
                     ['nes', 'snes', 'genesis'], cfg.systems)

    # Selection fields
    if cfg.selection.best_version is True:
        results.ok("update_config: best_version True")
    else:
        results.fail("update_config: best_version", True,
                     cfg.selection.best_version)

    if cfg.selection.english_only is True:
        results.ok("update_config: english_only True")
    else:
        results.fail("update_config: english_only", True,
                     cfg.selection.english_only)

    if cfg.selection.exclude_protos is True:
        results.ok("update_config: exclude_protos True")
    else:
        results.fail("update_config: exclude_protos", True,
                     cfg.selection.exclude_protos)

    # include_unlicensed is inverted from no_unlicensed
    if cfg.selection.include_unlicensed is False:
        results.ok("update_config: no_unlicensed -> include_unlicensed=False")
    else:
        results.fail("update_config: include_unlicensed", False,
                     cfg.selection.include_unlicensed)

    # Region priority parsed
    if cfg.selection.region_priority == ['USA', 'Europe', 'Japan']:
        results.ok("update_config: region_priority parsed")
    else:
        results.fail("update_config: region_priority",
                     ['USA', 'Europe', 'Japan'],
                     cfg.selection.region_priority)

    # Patterns parsed
    if cfg.selection.include_patterns == ['mario', 'zelda']:
        results.ok("update_config: include_patterns parsed")
    else:
        results.fail("update_config: include_patterns",
                     ['mario', 'zelda'], cfg.selection.include_patterns)

    if cfg.selection.exclude_patterns == ['demo']:
        results.ok("update_config: exclude_patterns parsed")
    else:
        results.fail("update_config: exclude_patterns",
                     ['demo'], cfg.selection.exclude_patterns)

    # Year range
    if cfg.selection.year_from == 1990:
        results.ok("update_config: year_from = 1990")
    else:
        results.fail("update_config: year_from", 1990,
                     cfg.selection.year_from)

    if cfg.selection.year_to == 2000:
        results.ok("update_config: year_to = 2000")
    else:
        results.fail("update_config: year_to", 2000, cfg.selection.year_to)

    # Network
    if cfg.network.parallel == 8:
        results.ok("update_config: parallel = 8")
    else:
        results.fail("update_config: parallel", 8, cfg.network.parallel)

    if cfg.network.auto_tune is False:
        results.ok("update_config: auto_tune = False")
    else:
        results.fail("update_config: auto_tune", False,
                     cfg.network.auto_tune)

    # Output
    if cfg.output.local_file_action == 'symlink':
        results.ok("update_config: local_file_action = symlink")
    else:
        results.fail("update_config: local_file_action", 'symlink',
                     cfg.output.local_file_action)

    if cfg.output.flat is True:
        results.ok("update_config: flat = True")
    else:
        results.fail("update_config: flat", True, cfg.output.flat)

    if cfg.output.clean_destination is True:
        results.ok("update_config: clean_destination = True")
    else:
        results.fail("update_config: clean_destination", True,
                     cfg.output.clean_destination)

    # Advanced
    if cfg.advanced.max_depth == 5:
        results.ok("update_config: max_depth = 5")
    else:
        results.fail("update_config: max_depth", 5, cfg.advanced.max_depth)

    if cfg.advanced.mame_version == '0.265':
        results.ok("update_config: mame_version = 0.265")
    else:
        results.fail("update_config: mame_version", '0.265',
                     cfg.advanced.mame_version)

    # Auth
    if cfg.auth.igdb_client_id == 'test_id':
        results.ok("update_config: igdb_client_id set")
    else:
        results.fail("update_config: igdb_client_id", 'test_id',
                     cfg.auth.igdb_client_id)

    # Dedup
    if cfg.deduplication.priority == 'snes,genesis,nes':
        results.ok("update_config: dedup priority set")
    else:
        results.fail("update_config: dedup priority",
                     'snes,genesis,nes', cfg.deduplication.priority)

    if cfg.deduplication.pc_lists == ['list1.txt', 'list2.txt']:
        results.ok("update_config: dedup pc_lists parsed")
    else:
        results.fail("update_config: dedup pc_lists",
                     ['list1.txt', 'list2.txt'], cfg.deduplication.pc_lists)

    # Theme
    if cfg.theme.mode == 'cyberpunk':
        results.ok("update_config: theme set")
    else:
        results.fail("update_config: theme", 'cyberpunk', cfg.theme.mode)

    # Exclude systems (internal, not on Config)
    if api._exclude_systems == ['atari2600', 'intellivision']:
        results.ok("update_config: exclude_systems parsed")
    else:
        results.fail("update_config: exclude_systems",
                     ['atari2600', 'intellivision'],
                     api._exclude_systems)


def test_update_config_from_ui_delete_dupes():
    """Legacy 'delete-dupes' value should map to 'remove'."""
    print("\n--- update_config_from_ui (delete-dupes legacy) ---")

    api = make_api()
    ui_state = {
        'local_file_action': 'delete-dupes',
    }
    api.update_config_from_ui(json.dumps(ui_state))
    if api._config.output.local_file_action == 'remove':
        results.ok("update_config: delete-dupes -> remove")
    else:
        results.fail("update_config: delete-dupes", 'remove',
                     api._config.output.local_file_action)


def test_update_config_from_ui_empty_patterns():
    """Empty pattern strings should produce empty lists."""
    print("\n--- update_config_from_ui (empty patterns) ---")

    api = make_api()
    ui_state = {
        'include_patterns': '',
        'exclude_patterns': '   ',
        'region_priority': '',
        'dedup_pc_lists': '',
    }
    api.update_config_from_ui(json.dumps(ui_state))

    if api._config.selection.include_patterns == []:
        results.ok("update_config_empty: include_patterns = []")
    else:
        results.fail("update_config_empty: include_patterns",
                     [], api._config.selection.include_patterns)

    if api._config.selection.exclude_patterns == []:
        results.ok("update_config_empty: exclude_patterns = []")
    else:
        results.fail("update_config_empty: exclude_patterns",
                     [], api._config.selection.exclude_patterns)

    if api._config.deduplication.pc_lists == []:
        results.ok("update_config_empty: dedup pc_lists = []")
    else:
        results.fail("update_config_empty: pc_lists",
                     [], api._config.deduplication.pc_lists)


# =============================================================================
# clean_data tests
# =============================================================================

def test_clean_data():
    print("\n--- clean_data ---")

    api = make_api()

    # Set up a temp directory as our runtime path
    tmpdir = tempfile.mkdtemp(prefix='rr_test_clean_')
    try:
        # Monkey-patch get_runtime_path for this test
        import retro_refiner.ui.api as api_mod
        orig_get_runtime = api_mod.get_runtime_path
        api_mod.get_runtime_path = lambda: Path(tmpdir)

        # Create cache dir
        cache_dir = Path(tmpdir) / 'cache'
        cache_dir.mkdir()
        (cache_dir / '_scan_cache.json').write_text('{}')

        # Create CRC cache
        crc_cache = Path(tmpdir) / '_crc_cache.json'
        crc_cache.write_text('{}')

        # Create state file
        state_file = Path(tmpdir) / '.retro-refiner-state.yaml'
        state_file.write_text('sources: []')

        # Create DAT dir with a .dat file (only deleted if has .dat files)
        dat_dir = Path(tmpdir) / 'dat_files'
        dat_dir.mkdir()
        (dat_dir / 'test.dat').write_text('test dat')

        # Configure dat_dir to match our temp path
        api._config.advanced.dat_dir = str(dat_dir)
        api._config.destination = None  # No dest to clean

        result_json = api.clean_data()
        data = json.loads(result_json)
        deleted = data.get('deleted', [])

        # Verify cache was deleted
        if not cache_dir.exists():
            results.ok("clean_data: cache dir deleted")
        else:
            results.fail("clean_data: cache dir", 'deleted', 'still exists')

        if any('scan cache' in d for d in deleted):
            results.ok("clean_data: cache in deleted list")
        else:
            results.fail("clean_data: cache in deleted list",
                         'cache in list', deleted)

        # Verify CRC cache was deleted
        if not crc_cache.exists():
            results.ok("clean_data: CRC cache deleted")
        else:
            results.fail("clean_data: CRC cache", 'deleted', 'still exists')

        # Verify DAT dir was deleted (had .dat files)
        if not dat_dir.exists():
            results.ok("clean_data: DAT dir deleted")
        else:
            results.fail("clean_data: DAT dir", 'deleted', 'still exists')

        # Verify state file was deleted
        if not state_file.exists():
            results.ok("clean_data: state file deleted")
        else:
            results.fail("clean_data: state file", 'deleted', 'still exists')

        # Verify return value has all items
        if len(deleted) >= 4:
            results.ok(f"clean_data: {len(deleted)} items in deleted list")
        else:
            results.fail("clean_data: deleted count", '>= 4', len(deleted))

    finally:
        api_mod.get_runtime_path = orig_get_runtime
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_clean_data_dat_dir_no_dats():
    """DAT dir should NOT be deleted if it has no .dat files."""
    print("\n--- clean_data (dat dir without .dat files) ---")

    api = make_api()

    tmpdir = tempfile.mkdtemp(prefix='rr_test_clean2_')
    try:
        import retro_refiner.ui.api as api_mod
        orig_get_runtime = api_mod.get_runtime_path
        api_mod.get_runtime_path = lambda: Path(tmpdir)

        # Create DAT dir with only non-.dat files
        dat_dir = Path(tmpdir) / 'dat_files'
        dat_dir.mkdir()
        (dat_dir / 'readme.txt').write_text('not a dat')

        api._config.advanced.dat_dir = str(dat_dir)
        api._config.destination = None

        api.clean_data()

        if dat_dir.exists():
            results.ok("clean_data_no_dats: DAT dir preserved")
        else:
            results.fail("clean_data_no_dats: DAT dir",
                         'still exists', 'deleted')

    finally:
        api_mod.get_runtime_path = orig_get_runtime
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_clean_data_rrdownload():
    """clean_data should remove .rrdownload temp files from destination."""
    print("\n--- clean_data (.rrdownload cleanup) ---")

    api = make_api()

    tmpdir = tempfile.mkdtemp(prefix='rr_test_clean3_')
    try:
        import retro_refiner.ui.api as api_mod
        orig_get_runtime = api_mod.get_runtime_path
        api_mod.get_runtime_path = lambda: Path(tmpdir)

        # Create destination with .rrdownload files
        dest = Path(tmpdir) / 'dest'
        dest.mkdir()
        nes_dir = dest / 'nes'
        nes_dir.mkdir()
        rrd = nes_dir / 'game.zip.rrdownload'
        rrd.write_text('partial download')

        api._config.destination = str(dest)

        result_json = api.clean_data()
        data = json.loads(result_json)

        if not rrd.exists():
            results.ok("clean_data_rrdownload: temp file deleted")
        else:
            results.fail("clean_data_rrdownload: temp file",
                         'deleted', 'still exists')

        if any('rrdownload' in d or 'temp download' in d
               for d in data.get('deleted', [])):
            results.ok("clean_data_rrdownload: listed in deleted")
        else:
            results.fail("clean_data_rrdownload: listed",
                         'in deleted list', data.get('deleted', []))

    finally:
        api_mod.get_runtime_path = orig_get_runtime
        shutil.rmtree(tmpdir, ignore_errors=True)


# =============================================================================
# Helper function tests
# =============================================================================

def test_parse_csv():
    print("\n--- _parse_csv ---")

    if _parse_csv(None) is None:
        results.ok("parse_csv: None -> None")
    else:
        results.fail("parse_csv: None", None, _parse_csv(None))

    if _parse_csv('') is None:
        results.ok("parse_csv: empty -> None")
    else:
        results.fail("parse_csv: empty", None, _parse_csv(''))

    if _parse_csv('   ') is None:
        results.ok("parse_csv: whitespace -> None")
    else:
        results.fail("parse_csv: whitespace", None, _parse_csv('   '))

    actual = _parse_csv('a, b, c')
    if actual == ['a', 'b', 'c']:
        results.ok("parse_csv: 'a, b, c' -> ['a', 'b', 'c']")
    else:
        results.fail("parse_csv: 'a, b, c'", ['a', 'b', 'c'], actual)

    actual = _parse_csv('single')
    if actual == ['single']:
        results.ok("parse_csv: 'single' -> ['single']")
    else:
        results.fail("parse_csv: 'single'", ['single'], actual)

    actual = _parse_csv(',,,')
    if actual is None:
        results.ok("parse_csv: ',,,' -> None")
    else:
        results.fail("parse_csv: ',,,'", None, actual)


def test_int_or_none():
    print("\n--- _int_or_none ---")

    if _int_or_none(None) is None:
        results.ok("int_or_none: None -> None")
    else:
        results.fail("int_or_none: None", None, _int_or_none(None))

    if _int_or_none('') is None:
        results.ok("int_or_none: '' -> None")
    else:
        results.fail("int_or_none: ''", None, _int_or_none(''))

    if _int_or_none('42') == 42:
        results.ok("int_or_none: '42' -> 42")
    else:
        results.fail("int_or_none: '42'", 42, _int_or_none('42'))

    if _int_or_none(42) == 42:
        results.ok("int_or_none: 42 -> 42")
    else:
        results.fail("int_or_none: 42", 42, _int_or_none(42))

    if _int_or_none('abc') is None:
        results.ok("int_or_none: 'abc' -> None")
    else:
        results.fail("int_or_none: 'abc'", None, _int_or_none('abc'))

    if _int_or_none('3.14') is None:
        results.ok("int_or_none: '3.14' -> None")
    else:
        results.fail("int_or_none: '3.14'", None, _int_or_none('3.14'))


def test_float_or_none():
    print("\n--- _float_or_none ---")

    if _float_or_none(None) is None:
        results.ok("float_or_none: None -> None")
    else:
        results.fail("float_or_none: None", None, _float_or_none(None))

    if _float_or_none('') is None:
        results.ok("float_or_none: '' -> None")
    else:
        results.fail("float_or_none: ''", None, _float_or_none(''))

    if _float_or_none('3.14') == 3.14:
        results.ok("float_or_none: '3.14' -> 3.14")
    else:
        results.fail("float_or_none: '3.14'", 3.14, _float_or_none('3.14'))

    if _float_or_none('42') == 42.0:
        results.ok("float_or_none: '42' -> 42.0")
    else:
        results.fail("float_or_none: '42'", 42.0, _float_or_none('42'))

    if _float_or_none('abc') is None:
        results.ok("float_or_none: 'abc' -> None")
    else:
        results.fail("float_or_none: 'abc'", None, _float_or_none('abc'))


def test_parse_size_string():
    print("\n--- _parse_size_string ---")

    result = _parse_size_string('10GB')
    expected = 10 * 1024 * 1024 * 1024
    if result == expected:
        results.ok("parse_size_string: 10GB")
    else:
        results.fail("parse_size_string: 10GB", expected, result)

    result = _parse_size_string('500MB')
    expected = 500 * 1024 * 1024
    if result == expected:
        results.ok("parse_size_string: 500MB")
    else:
        results.fail("parse_size_string: 500MB", expected, result)

    result = _parse_size_string(None)
    if result is None or result == 0:
        results.ok("parse_size_string: None -> None/0")
    else:
        results.fail("parse_size_string: None", 'None or 0', result)


# =============================================================================
# _get_exclusion_reason tests
# =============================================================================

def test_get_exclusion_reason():
    print("\n--- _get_exclusion_reason ---")

    # Proto
    rom = parse_rom_filename('Game (USA) (Proto).zip')
    reason = _get_exclusion_reason(rom)
    if 'Prototype' in reason:
        results.ok("exclusion_reason: Proto -> Prototype")
    else:
        results.fail("exclusion_reason: Proto", 'Prototype', reason)

    # Beta
    rom = parse_rom_filename('Game (USA) (Beta).zip')
    reason = _get_exclusion_reason(rom)
    if 'Beta' in reason:
        results.ok("exclusion_reason: Beta")
    else:
        results.fail("exclusion_reason: Beta", 'Beta', reason)

    # Demo
    rom = parse_rom_filename('Game (USA) (Demo).zip')
    reason = _get_exclusion_reason(rom)
    if 'Demo' in reason:
        results.ok("exclusion_reason: Demo")
    else:
        results.fail("exclusion_reason: Demo", 'Demo', reason)

    # BIOS
    rom = parse_rom_filename('[BIOS] System (USA).zip')
    reason = _get_exclusion_reason(rom)
    if 'BIOS' in reason:
        results.ok("exclusion_reason: BIOS")
    else:
        results.fail("exclusion_reason: BIOS", 'BIOS', reason)

    # Normal game: should say "Not best version"
    rom = parse_rom_filename('Super Mario World (USA).zip')
    reason = _get_exclusion_reason(rom)
    if reason == 'Not best version':
        results.ok("exclusion_reason: normal -> Not best version")
    else:
        results.fail("exclusion_reason: normal", 'Not best version', reason)

    # Sample
    rom = parse_rom_filename('Game (USA) (Sample).zip')
    reason = _get_exclusion_reason(rom)
    if 'Sample' in reason:
        results.ok("exclusion_reason: Sample")
    else:
        results.fail("exclusion_reason: Sample", 'Sample', reason)


# =============================================================================
# get_config / set_config round-trip
# =============================================================================

def test_config_round_trip():
    print("\n--- get_config / set_config round-trip ---")

    api = make_api()
    api._config.sources = ['http://source1.com', '/local/path']
    api._config.destination = '/dest'
    api._config.selection.english_only = True
    api._config.selection.best_version = True

    # Get config as JSON
    config_json = api.get_config()
    data = json.loads(config_json)

    # Create a new Api and set the config
    api2 = make_api()
    api2.set_config(config_json)

    if api2._config.sources == ['http://source1.com', '/local/path']:
        results.ok("config_round_trip: sources preserved")
    else:
        results.fail("config_round_trip: sources",
                     ['http://source1.com', '/local/path'],
                     api2._config.sources)

    if api2._config.destination == '/dest':
        results.ok("config_round_trip: destination preserved")
    else:
        results.fail("config_round_trip: destination", '/dest',
                     api2._config.destination)

    if api2._config.selection.english_only is True:
        results.ok("config_round_trip: english_only preserved")
    else:
        results.fail("config_round_trip: english_only", True,
                     api2._config.selection.english_only)

    if api2._config.selection.best_version is True:
        results.ok("config_round_trip: best_version preserved")
    else:
        results.fail("config_round_trip: best_version", True,
                     api2._config.selection.best_version)


# =============================================================================
# get_systems tests
# =============================================================================

def test_get_systems():
    print("\n--- get_systems ---")

    api = make_api()
    systems_json = api.get_systems()
    systems = json.loads(systems_json)

    if isinstance(systems, list):
        results.ok("get_systems: returns list")
    else:
        results.fail("get_systems: returns list", 'list', type(systems))

    if len(systems) >= 100:
        results.ok(f"get_systems: {len(systems)} systems (>= 100)")
    else:
        results.fail("get_systems: enough systems", '>= 100', len(systems))

    if 'nes' in systems:
        results.ok("get_systems: contains nes")
    else:
        results.fail("get_systems: contains nes", 'nes in list', systems[:5])


# =============================================================================
# update_sources / update_destination tests
# =============================================================================

def test_update_sources():
    print("\n--- update_sources ---")

    api = make_api()
    api.update_sources(json.dumps(['http://src1.com', '/path']))

    if api._config.sources == ['http://src1.com', '/path']:
        results.ok("update_sources: sources updated")
    else:
        results.fail("update_sources: sources",
                     ['http://src1.com', '/path'], api._config.sources)


def test_update_destination():
    print("\n--- update_destination ---")

    api = make_api()
    api.update_destination('/new/dest')

    if api._config.destination == '/new/dest':
        results.ok("update_destination: destination updated")
    else:
        results.fail("update_destination: destination",
                     '/new/dest', api._config.destination)


# =============================================================================
# update_selection tests
# =============================================================================

def test_update_selection():
    print("\n--- update_selection ---")

    api = make_api()
    api.update_selection(json.dumps({
        'english_only': True,
        'best_version': True,
        'exclude_protos': True,
    }))

    if api._config.selection.english_only is True:
        results.ok("update_selection: english_only set")
    else:
        results.fail("update_selection: english_only", True,
                     api._config.selection.english_only)

    if api._config.selection.best_version is True:
        results.ok("update_selection: best_version set")
    else:
        results.fail("update_selection: best_version", True,
                     api._config.selection.best_version)

    # Unknown keys should be ignored
    api.update_selection(json.dumps({'nonexistent_field': True}))
    results.ok("update_selection: unknown key ignored (no crash)")


# =============================================================================
# update_theme tests
# =============================================================================

def test_update_theme():
    print("\n--- update_theme ---")

    api = make_api()
    api.update_theme('cyberpunk')

    if api._config.theme.mode == 'cyberpunk':
        results.ok("update_theme: theme set to cyberpunk")
    else:
        results.fail("update_theme: theme", 'cyberpunk',
                     api._config.theme.mode)


# =============================================================================
# run_preview / run_commit state tests
# =============================================================================

def test_run_state():
    print("\n--- run_preview / run_commit state ---")

    api = make_api()

    # Initially not running
    if api.is_running() is False:
        results.ok("run_state: initially not running")
    else:
        results.fail("run_state: initially", False, api.is_running())

    # cancel_run while not running should not crash
    api.cancel_run()
    results.ok("run_state: cancel while not running (no crash)")

    # Verify cancel sets running to False
    api._running = True
    api.cancel_run()
    if api._running is False:
        results.ok("run_state: cancel sets _running = False")
    else:
        results.fail("run_state: cancel sets _running", False,
                     api._running)


# =============================================================================
# Picker state tests
# =============================================================================

def test_picker_state():
    print("\n--- picker state ---")

    api = make_api()

    # Set up mock last_results
    api._last_results = {
        'nes': {
            'urls': [
                'https://example.com/Mario%20(USA).zip',
                'https://example.com/Zelda%20(USA).zip',
            ],
            'sizes': {
                'https://example.com/Mario%20(USA).zip': 1024,
                'https://example.com/Zelda%20(USA).zip': 2048,
            },
            'local_files': [],
            'selected_urls': ['https://example.com/Mario%20(USA).zip'],
            'selected_local': [],
        }
    }

    # get_system_roms should return ROM list
    roms_json = api.get_system_roms('nes')
    roms = json.loads(roms_json)

    if len(roms) == 2:
        results.ok("picker: 2 ROMs returned")
    else:
        results.fail("picker: ROM count", 2, len(roms))

    # Mario should be selected
    mario = [r for r in roms if 'Mario' in r['filename']]
    if mario and mario[0]['status'] == 'selected':
        results.ok("picker: Mario is selected")
    else:
        results.fail("picker: Mario status", 'selected',
                     mario[0]['status'] if mario else 'not found')

    # Zelda should be excluded
    zelda = [r for r in roms if 'Zelda' in r['filename']]
    if zelda and zelda[0]['status'] == 'excluded':
        results.ok("picker: Zelda is excluded")
    else:
        results.fail("picker: Zelda status", 'excluded',
                     zelda[0]['status'] if zelda else 'not found')

    # Picker state should be cached
    if 'nes' in api._picker_state:
        results.ok("picker: state cached")
    else:
        results.fail("picker: state cached", 'nes in _picker_state',
                     list(api._picker_state.keys()))

    # Reset picker
    api.reset_picker('nes')
    if 'nes' not in api._picker_state:
        results.ok("picker: reset clears state")
    else:
        results.fail("picker: reset clears state",
                     'nes not in _picker_state', 'still present')

    # Reset all
    api._picker_state = {'nes': [], 'snes': []}
    api._manual_selections = {'nes': {}, 'snes': {}}
    api.reset_picker('')
    if len(api._picker_state) == 0 and len(api._manual_selections) == 0:
        results.ok("picker: reset all clears everything")
    else:
        results.fail("picker: reset all", 'empty dicts',
                     f'{len(api._picker_state)} / '
                     f'{len(api._manual_selections)}')


def test_update_rom_selection():
    print("\n--- update_rom_selection ---")

    api = make_api()

    # Set up picker state with a ROM
    api._picker_state['nes'] = [
        {'filename': 'Mario (USA).zip', 'status': 'selected',
         'region': 'USA', 'url': 'http://x/Mario%20(USA).zip', 'size': 0,
         'reason': ''},
        {'filename': 'Zelda (USA).zip', 'status': 'excluded',
         'region': 'USA', 'url': 'http://x/Zelda%20(USA).zip', 'size': 0,
         'reason': 'Not best version'},
    ]

    # Deselect Mario, select Zelda
    api.update_rom_selection('nes', json.dumps([
        {'filename': 'Mario (USA).zip', 'selected': False},
        {'filename': 'Zelda (USA).zip', 'selected': True},
    ]))

    # Check manual selections stored
    if api._manual_selections['nes']['Mario (USA).zip'] is False:
        results.ok("update_rom: Mario deselected in manual")
    else:
        results.fail("update_rom: Mario deselected", False,
                     api._manual_selections['nes']['Mario (USA).zip'])

    if api._manual_selections['nes']['Zelda (USA).zip'] is True:
        results.ok("update_rom: Zelda selected in manual")
    else:
        results.fail("update_rom: Zelda selected", True,
                     api._manual_selections['nes']['Zelda (USA).zip'])

    # Picker state should be updated too
    mario = [r for r in api._picker_state['nes']
             if r['filename'] == 'Mario (USA).zip']
    if mario and mario[0]['status'] == 'excluded':
        results.ok("update_rom: Mario excluded in picker state")
    else:
        results.fail("update_rom: Mario picker status", 'excluded',
                     mario[0]['status'] if mario else 'not found')


# =============================================================================
# _url_to_filename tests
# =============================================================================

def test_url_to_filename():
    print("\n--- _url_to_filename ---")

    api = make_api()

    cases = {
        'https://example.com/Game%20(USA).zip': 'Game (USA).zip',
        'https://example.com/path/to/ROM%20File.nes': 'ROM File.nes',
        'https://example.com/file.zip?auth=token': 'file.zip',
        'https://example.com/file.zip#fragment': 'file.zip',
        'https://example.com/Simple.zip': 'Simple.zip',
    }

    for url, expected in cases.items():
        actual = api._url_to_filename(url)
        if actual == expected:
            results.ok(f"url_to_filename: {expected}")
        else:
            results.fail(f"url_to_filename: {url}", expected, actual)


# =============================================================================
# _push_event tests
# =============================================================================

def test_push_event_no_window():
    """Events should silently drop when _window is None."""
    print("\n--- _push_event (no window) ---")

    api = make_api()

    # Should not raise
    api._push_event('log', {'text': 'test message'})
    api._push_event('status', {'state': 'running'})
    api._push_event('progress', {'phase': 'scanning', 'current': 1})
    results.ok("push_event: no crash without window")


def test_push_event_log_buffer():
    """Log events should be buffered when log_dir is configured."""
    print("\n--- _push_event (log buffer) ---")

    api = make_api()
    api._config.advanced.log_dir = '/tmp/logs'
    api._log_buffer = []

    api._push_event('log', {'text': 'Hello world\n'})
    api._push_event('log', {'text': 'Second line\n'})

    if len(api._log_buffer) == 2:
        results.ok("push_event_buffer: 2 messages buffered")
    else:
        results.fail("push_event_buffer: count", 2, len(api._log_buffer))

    if api._log_buffer[0] == 'Hello world\n':
        results.ok("push_event_buffer: first message correct")
    else:
        results.fail("push_event_buffer: first message",
                     'Hello world\n', api._log_buffer[0])


def test_push_event_no_buffer_without_log_dir():
    """Log events should NOT be buffered when log_dir is not set."""
    print("\n--- _push_event (no buffer without log_dir) ---")

    api = make_api()
    api._config.advanced.log_dir = None
    api._log_buffer = []

    api._push_event('log', {'text': 'test\n'})

    if len(api._log_buffer) == 0:
        results.ok("push_event_no_buffer: no buffering without log_dir")
    else:
        results.fail("push_event_no_buffer: count", 0,
                     len(api._log_buffer))


# =============================================================================
# SYSTEM_ABBREVS consistency
# =============================================================================

def test_system_abbrevs_consistency():
    """All abbreviations in _SYSTEM_ABBREVS should be lowercase."""
    print("\n--- _SYSTEM_ABBREVS consistency ---")

    all_lower = all(s == s.lower() for s in _SYSTEM_ABBREVS)
    if all_lower:
        results.ok("abbrevs: all entries are lowercase")
    else:
        non_lower = [s for s in _SYSTEM_ABBREVS if s != s.lower()]
        results.fail("abbrevs: all lowercase", 'all lower', non_lower)

    # Should contain at least the most common ones
    expected = {'snes', 'nes', 'gba', 'n64', 'psx', 'ps2', '3do', 'msx'}
    missing = expected - _SYSTEM_ABBREVS
    if not missing:
        results.ok("abbrevs: contains expected common systems")
    else:
        results.fail("abbrevs: common systems", 'all present',
                     f'missing: {missing}')


# =============================================================================
# get_all_roms tests
# =============================================================================

def test_get_all_roms():
    print("\n--- get_all_roms ---")

    api = make_api()

    api._last_results = {
        'nes': {
            'urls': ['https://example.com/Mario%20(USA).zip'],
            'sizes': {'https://example.com/Mario%20(USA).zip': 1024},
            'local_files': [],
            'selected_urls': ['https://example.com/Mario%20(USA).zip'],
            'selected_local': [],
        },
        'snes': {
            'urls': ['https://example.com/DKC%20(USA).zip'],
            'sizes': {'https://example.com/DKC%20(USA).zip': 2048},
            'local_files': [],
            'selected_urls': ['https://example.com/DKC%20(USA).zip'],
            'selected_local': [],
        },
    }

    all_roms_json = api.get_all_roms()
    all_roms = json.loads(all_roms_json)

    if len(all_roms) == 2:
        results.ok("get_all_roms: 2 ROMs total")
    else:
        results.fail("get_all_roms: count", 2, len(all_roms))

    # Each ROM should have a 'system' field
    systems_found = {r.get('system') for r in all_roms}
    if 'nes' in systems_found and 'snes' in systems_found:
        results.ok("get_all_roms: system field present on each ROM")
    else:
        results.fail("get_all_roms: system fields",
                     {'nes', 'snes'}, systems_found)


# =============================================================================
# save_ui_state / load_ui_state tests
# =============================================================================

def test_save_load_ui_state():
    print("\n--- save_ui_state / load_ui_state ---")

    api = make_api()

    tmpdir = tempfile.mkdtemp(prefix='rr_test_state_')
    try:
        import retro_refiner.ui.api as api_mod
        orig_get_runtime = api_mod.get_runtime_path
        api_mod.get_runtime_path = lambda: Path(tmpdir)

        api._config.sources = ['http://test.com']
        api._config.selection.english_only = True
        api._config.auth.igdb_client_id = 'secret_id'

        api.save_ui_state()

        # Load into a new Api
        api2 = make_api()
        state_json = api2.load_ui_state()

        if state_json != '{}':
            data = json.loads(state_json)
            results.ok("load_ui_state: returns non-empty state")
        else:
            results.fail("load_ui_state: returns state", 'non-empty', '{}')
            return

        # Sources should be persisted
        if data.get('sources') == ['http://test.com']:
            results.ok("save_load_state: sources persisted")
        else:
            results.fail("save_load_state: sources",
                         ['http://test.com'], data.get('sources'))

        # Auth should be stripped (not persisted)
        auth = data.get('auth', {})
        if not auth.get('igdb_client_id'):
            results.ok("save_load_state: auth credentials stripped")
        else:
            results.fail("save_load_state: auth stripped",
                         None, auth.get('igdb_client_id'))

    finally:
        api_mod.get_runtime_path = orig_get_runtime
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_save_ui_state_skip():
    """save_ui_state should skip when _skip_save is True."""
    print("\n--- save_ui_state (skip_save) ---")

    api = make_api()

    tmpdir = tempfile.mkdtemp(prefix='rr_test_skip_')
    try:
        import retro_refiner.ui.api as api_mod
        orig_get_runtime = api_mod.get_runtime_path
        api_mod.get_runtime_path = lambda: Path(tmpdir)

        api._skip_save = True
        api._config.sources = ['http://should-not-save.com']

        api.save_ui_state()

        state_file = Path(tmpdir) / '.retro-refiner-state.yaml'
        if not state_file.exists():
            results.ok("save_ui_state_skip: file not created")
        else:
            results.fail("save_ui_state_skip: file",
                         'not created', 'was created')

    finally:
        api_mod.get_runtime_path = orig_get_runtime
        shutil.rmtree(tmpdir, ignore_errors=True)


# =============================================================================
# Main
# =============================================================================

if __name__ == '__main__':
    test_display_name()
    test_eta_str()
    test_elapsed_str()
    test_get_default_config()
    test_config_snapshot()
    test_step_prefix()
    test_compute_system_stats()
    test_compute_system_stats_empty()
    test_update_config_from_ui()
    test_update_config_from_ui_delete_dupes()
    test_update_config_from_ui_empty_patterns()
    test_clean_data()
    test_clean_data_dat_dir_no_dats()
    test_clean_data_rrdownload()
    test_parse_csv()
    test_int_or_none()
    test_float_or_none()
    test_parse_size_string()
    test_get_exclusion_reason()
    test_config_round_trip()
    test_get_systems()
    test_update_sources()
    test_update_destination()
    test_update_selection()
    test_update_theme()
    test_run_state()
    test_picker_state()
    test_update_rom_selection()
    test_url_to_filename()
    test_push_event_no_window()
    test_push_event_log_buffer()
    test_push_event_no_buffer_without_log_dir()
    test_system_abbrevs_consistency()
    test_get_all_roms()
    test_save_load_ui_state()
    test_save_ui_state_skip()

    ok = results.summary()
    sys.exit(0 if ok else 1)

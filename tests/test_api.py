#!/usr/bin/env python3
"""
Comprehensive tests for retro_refiner/ui/api.py.

Tests the Api class and module-level helpers without requiring a GUI window.
"""

import json
import shutil
from pathlib import Path

import pytest

from retro_refiner.ui.api import (
    Api, _display_name, _get_exclusion_reason,
    _parse_csv, _int_or_none, _float_or_none, _parse_size_string,
    _SYSTEM_ABBREVS,
)
from retro_refiner.config import Config
from retro_refiner.filter import parse_rom_filename


@pytest.fixture
def api():
    from retro_refiner.ui.api import Api
    a = Api()
    a._window = None
    return a


# =============================================================================
# _display_name tests
# =============================================================================

class TestDisplayName:
    ABBREVS = {
        'snes': 'SNES', 'nes': 'NES', 'gba': 'GBA', 'gbc': 'GBC',
        'n64': 'N64', 'psx': 'PSX', 'ps2': 'PS2', 'ps3': 'PS3',
        'psp': 'PSP', '3do': '3DO', '3ds': '3DS', 'dsi': 'DSI',
        'fds': 'FDS', 'msx': 'MSX', 'msx2': 'MSX2', 'n64dd': 'N64DD',
        'ngp': 'NGP', 'ngpc': 'NGPC', 'scv': 'SCV', 'sgx': 'SGX',
        'tg16': 'TG16', 'tgcd': 'TGCD',
    }

    @pytest.mark.parametrize("code,expected", list(ABBREVS.items()))
    def test_abbreviations(self, code, expected):
        assert _display_name(code) == expected

    @pytest.mark.parametrize("variant", ["SNES", "Snes", "sNeS"])
    def test_case_insensitive(self, variant):
        assert _display_name(variant) == variant.upper()

    @pytest.mark.parametrize("code,expected", [
        ("game-boy-advance", "Game Boy Advance"),
        ("mega-drive", "Mega Drive"),
        ("pc-engine", "Pc Engine"),
    ])
    def test_hyphenated(self, code, expected):
        assert _display_name(code) == expected

    @pytest.mark.parametrize("code,expected", [
        ("game_boy", "Game Boy"),
        ("pc_engine", "Pc Engine"),
    ])
    def test_underscored(self, code, expected):
        assert _display_name(code) == expected

    def test_simple_word(self):
        assert _display_name("genesis") == "Genesis"


# =============================================================================
# _eta_str tests
# =============================================================================

class TestEtaStr:
    def test_zero_completed(self):
        assert Api._eta_str(10.0, 0, 100) == ''

    def test_negative_completed(self):
        assert Api._eta_str(10.0, -1, 100) == ''

    def test_zero_total(self):
        assert Api._eta_str(10.0, 5, 0) == ''

    def test_small_eta(self):
        actual = Api._eta_str(10.0, 50, 100)
        assert '~10s left' in actual

    def test_large_eta(self):
        actual = Api._eta_str(10.0, 10, 1000)
        assert '~16m' in actual
        assert 'left' in actual

    def test_all_completed(self):
        assert '~0s left' in Api._eta_str(10.0, 100, 100)

    def test_pipe_separator(self):
        assert '\u2502' in Api._eta_str(10.0, 50, 100)


# =============================================================================
# _elapsed_str tests
# =============================================================================

@pytest.mark.parametrize("seconds,expected", [
    (0, '0s'),
    (45, '45s'),
    (59.9, '59s'),
    (60, '1m 00s'),
    (90, '1m 30s'),
    (3661, '61m 01s'),
    (125.7, '2m 05s'),
])
def test_elapsed_str(seconds, expected):
    assert Api._elapsed_str(seconds) == expected


# =============================================================================
# get_default_config tests
# =============================================================================

def test_get_default_config(api):
    api._config.sources = ['http://example.com']
    api._config.destination = '/tmp/roms'
    api._config.selection.english_only = True

    result_json = api.get_default_config()
    data = json.loads(result_json)

    assert data.get('sources') == []
    assert data.get('destination') is None
    assert data.get('selection', {}).get('english_only') is False
    assert api._config.sources == []


# =============================================================================
# Config snapshot independence
# =============================================================================

def test_config_snapshot(api):
    api._config.sources = ['http://original.com']
    api._config.selection.english_only = True

    snapshot = Config.from_dict(api._config.to_dict())

    api._config.sources.append('http://added.com')
    api._config.selection.english_only = False

    assert len(snapshot.sources) == 1
    assert snapshot.selection.english_only is True
    assert snapshot.sources[0] == 'http://original.com'


# =============================================================================
# _step_prefix tests
# =============================================================================

def test_step_prefix_preview(api):
    assert api._step_prefix(1) == '[1/2] '
    assert api._step_prefix(2) == '[2/2] '


def test_step_prefix_commit(api):
    api._step_prefix = lambda n: f'[{n}/3] '
    assert api._step_prefix(3) == '[3/3] '


# =============================================================================
# _compute_system_stats tests
# =============================================================================

def test_compute_system_stats(api):
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

    assert stats['net_count'] == 3
    assert stats['local_count'] == 0
    assert 'USA' in stats['regions']
    assert 'Europe' in stats['regions']
    assert '.zip' in stats['formats']
    assert '.nes' in stats['formats']
    assert stats['sizes']['largest'][1] == 2048
    assert stats['sizes']['smallest'][1] == 512
    assert stats['sizes']['histogram']['< 1 MB'] == 3
    assert stats['system'] == 'nes'


def test_compute_system_stats_empty(api):
    stats = api._compute_system_stats([], [], {}, 'snes')
    assert stats['net_count'] == 0
    assert stats['local_count'] == 0
    assert stats['regions'] == {}
    assert stats['sizes']['avg'] == 0


# =============================================================================
# update_config_from_ui tests
# =============================================================================

def test_update_config_from_ui(api):
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

    assert cfg.sources == ['http://example.com/roms', '/local/path']
    assert cfg.source_settings.get('/local/path', {}).get('recursive') is True
    assert cfg.destination == '/output/dir'
    assert cfg.systems == ['nes', 'snes', 'genesis']
    assert cfg.selection.best_version is True
    assert cfg.selection.english_only is True
    assert cfg.selection.exclude_protos is True
    assert cfg.selection.include_unlicensed is False
    assert cfg.selection.region_priority == ['USA', 'Europe', 'Japan']
    assert cfg.selection.include_patterns == ['mario', 'zelda']
    assert cfg.selection.exclude_patterns == ['demo']
    assert cfg.selection.year_from == 1990
    assert cfg.selection.year_to == 2000
    assert cfg.network.parallel == 8
    assert cfg.output.local_file_action == 'symlink'
    assert cfg.output.flat is True
    assert cfg.output.clean_destination is True
    assert cfg.advanced.max_depth == 5
    assert cfg.advanced.mame_version == '0.265'
    assert cfg.auth.igdb_client_id == 'test_id'
    assert cfg.deduplication.priority == 'snes,genesis,nes'
    assert cfg.deduplication.pc_lists == ['list1.txt', 'list2.txt']
    assert cfg.theme.mode == 'cyberpunk'
    assert api._exclude_systems == ['atari2600', 'intellivision']


def test_update_config_from_ui_delete_dupes(api):
    api.update_config_from_ui(json.dumps({'local_file_action': 'delete-dupes'}))
    assert api._config.output.local_file_action == 'remove'


def test_update_config_from_ui_empty_patterns(api):
    ui_state = {
        'include_patterns': '',
        'exclude_patterns': '   ',
        'region_priority': '',
        'dedup_pc_lists': '',
    }
    api.update_config_from_ui(json.dumps(ui_state))

    assert api._config.selection.include_patterns == []
    assert api._config.selection.exclude_patterns == []
    assert api._config.deduplication.pc_lists == []


# =============================================================================
# clean_data tests
# =============================================================================

def test_clean_data(api, tmp_path):
    import retro_refiner.ui.api as api_mod
    orig_get_runtime = api_mod.get_runtime_path

    try:
        api_mod.get_runtime_path = lambda: tmp_path

        cache_dir = tmp_path / 'cache'
        cache_dir.mkdir()
        (cache_dir / '_scan_cache.json').write_text('{}')

        (tmp_path / '_crc_cache.json').write_text('{}')
        (tmp_path / '.retro-refiner-state.yaml').write_text('sources: []')

        dat_dir = tmp_path / 'dat_files'
        dat_dir.mkdir()
        (dat_dir / 'test.dat').write_text('test dat')

        api._config.advanced.dat_dir = str(dat_dir)
        api._config.destination = None

        result_json = api.clean_data()
        data = json.loads(result_json)
        deleted = data.get('deleted', [])

        assert not cache_dir.exists()
        assert any('scan cache' in d for d in deleted)
        assert not (tmp_path / '_crc_cache.json').exists()
        assert not dat_dir.exists()
        assert not (tmp_path / '.retro-refiner-state.yaml').exists()
        assert len(deleted) >= 4
    finally:
        api_mod.get_runtime_path = orig_get_runtime


def test_clean_data_dat_dir_no_dats(api, tmp_path):
    import retro_refiner.ui.api as api_mod
    orig_get_runtime = api_mod.get_runtime_path

    try:
        api_mod.get_runtime_path = lambda: tmp_path

        dat_dir = tmp_path / 'dat_files'
        dat_dir.mkdir()
        (dat_dir / 'readme.txt').write_text('not a dat')

        api._config.advanced.dat_dir = str(dat_dir)
        api._config.destination = None

        api.clean_data()
        assert dat_dir.exists()
    finally:
        api_mod.get_runtime_path = orig_get_runtime


def test_clean_data_rrdownload(api, tmp_path):
    import retro_refiner.ui.api as api_mod
    orig_get_runtime = api_mod.get_runtime_path

    try:
        api_mod.get_runtime_path = lambda: tmp_path

        dest = tmp_path / 'dest'
        dest.mkdir()
        nes_dir = dest / 'nes'
        nes_dir.mkdir()
        rrd = nes_dir / 'game.zip.rrdownload'
        rrd.write_text('partial download')

        api._config.destination = str(dest)

        result_json = api.clean_data()
        data = json.loads(result_json)

        assert not rrd.exists()
        assert any('rrdownload' in d or 'temp download' in d
                    for d in data.get('deleted', []))
    finally:
        api_mod.get_runtime_path = orig_get_runtime


# =============================================================================
# Helper function tests
# =============================================================================

@pytest.mark.parametrize("input_val,expected", [
    (None, None),
    ('', None),
    ('   ', None),
    ('a, b, c', ['a', 'b', 'c']),
    ('single', ['single']),
    (',,,', None),
])
def test_parse_csv(input_val, expected):
    assert _parse_csv(input_val) == expected


@pytest.mark.parametrize("input_val,expected", [
    (None, None),
    ('', None),
    ('42', 42),
    (42, 42),
    ('abc', None),
    ('3.14', None),
])
def test_int_or_none(input_val, expected):
    assert _int_or_none(input_val) == expected


@pytest.mark.parametrize("input_val,expected", [
    (None, None),
    ('', None),
    ('3.14', 3.14),
    ('42', 42.0),
    ('abc', None),
])
def test_float_or_none(input_val, expected):
    assert _float_or_none(input_val) == expected


def test_parse_size_string_api():
    assert _parse_size_string('10GB') == 10 * 1024 * 1024 * 1024
    assert _parse_size_string('500MB') == 500 * 1024 * 1024
    result = _parse_size_string(None)
    assert result is None or result == 0


# =============================================================================
# _get_exclusion_reason tests
# =============================================================================

@pytest.mark.parametrize("filename,expected_substr", [
    ('Game (USA) (Proto).zip', 'Prototype'),
    ('Game (USA) (Beta).zip', 'Beta'),
    ('Game (USA) (Demo).zip', 'Demo'),
    ('[BIOS] System (USA).zip', 'BIOS'),
    ('Game (USA) (Sample).zip', 'Sample'),
])
def test_get_exclusion_reason_special(filename, expected_substr):
    rom = parse_rom_filename(filename)
    reason = _get_exclusion_reason(rom)
    assert expected_substr in reason


def test_get_exclusion_reason_normal():
    rom = parse_rom_filename('Super Mario World (USA).zip')
    assert _get_exclusion_reason(rom) == 'Not best version'


# =============================================================================
# get_config / set_config round-trip
# =============================================================================

def test_config_round_trip(api):
    api._config.sources = ['http://source1.com', '/local/path']
    api._config.destination = '/dest'
    api._config.selection.english_only = True
    api._config.selection.best_version = True

    config_json = api.get_config()

    api2 = Api()
    api2._window = None
    api2.set_config(config_json)

    assert api2._config.sources == ['http://source1.com', '/local/path']
    assert api2._config.destination == '/dest'
    assert api2._config.selection.english_only is True
    assert api2._config.selection.best_version is True


# =============================================================================
# get_systems tests
# =============================================================================

def test_get_systems(api):
    systems = json.loads(api.get_systems())
    assert isinstance(systems, list)
    assert len(systems) >= 100
    assert 'nes' in systems


# =============================================================================
# update_sources / update_destination tests
# =============================================================================

def test_update_sources(api):
    api.update_sources(json.dumps(['http://src1.com', '/path']))
    assert api._config.sources == ['http://src1.com', '/path']


def test_update_destination(api):
    api.update_destination('/new/dest')
    assert api._config.destination == '/new/dest'


# =============================================================================
# update_selection tests
# =============================================================================

def test_update_selection(api):
    api.update_selection(json.dumps({
        'english_only': True,
        'best_version': True,
        'exclude_protos': True,
    }))

    assert api._config.selection.english_only is True
    assert api._config.selection.best_version is True


def test_update_selection_unknown_key(api):
    # Should not crash
    api.update_selection(json.dumps({'nonexistent_field': True}))


# =============================================================================
# update_theme tests
# =============================================================================

def test_update_theme(api):
    api.update_theme('cyberpunk')
    assert api._config.theme.mode == 'cyberpunk'


# =============================================================================
# run_preview / run_commit state tests
# =============================================================================

def test_run_state_initially_not_running(api):
    assert api.is_running() is False


def test_run_state_cancel_while_not_running(api):
    api.cancel_run()  # should not crash


def test_run_state_cancel_sets_running_false(api):
    api._running = True
    api.cancel_run()
    assert api._running is False


# =============================================================================
# Picker state tests
# =============================================================================

def test_picker_state(api):
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

    roms = json.loads(api.get_system_roms('nes'))
    assert len(roms) == 2

    mario = [r for r in roms if 'Mario' in r['filename']]
    assert mario and mario[0]['status'] == 'selected'

    zelda = [r for r in roms if 'Zelda' in r['filename']]
    assert zelda and zelda[0]['status'] == 'excluded'

    assert 'nes' in api._picker_state

    api.reset_picker('nes')
    assert 'nes' not in api._picker_state

    # Reset all
    api._picker_state = {'nes': [], 'snes': []}
    api._manual_selections = {'nes': {}, 'snes': {}}
    api.reset_picker('')
    assert len(api._picker_state) == 0
    assert len(api._manual_selections) == 0


# =============================================================================
# update_rom_selection tests
# =============================================================================

def test_update_rom_selection(api):
    api._picker_state['nes'] = [
        {'filename': 'Mario (USA).zip', 'status': 'selected',
         'region': 'USA', 'url': 'http://x/Mario%20(USA).zip', 'size': 0,
         'reason': ''},
        {'filename': 'Zelda (USA).zip', 'status': 'excluded',
         'region': 'USA', 'url': 'http://x/Zelda%20(USA).zip', 'size': 0,
         'reason': 'Not best version'},
    ]

    api.update_rom_selection('nes', json.dumps([
        {'filename': 'Mario (USA).zip', 'selected': False},
        {'filename': 'Zelda (USA).zip', 'selected': True},
    ]))

    assert api._manual_selections['nes']['Mario (USA).zip'] is False
    assert api._manual_selections['nes']['Zelda (USA).zip'] is True

    mario = [r for r in api._picker_state['nes']
             if r['filename'] == 'Mario (USA).zip']
    assert mario and mario[0]['status'] == 'excluded'


# =============================================================================
# _url_to_filename tests
# =============================================================================

@pytest.mark.parametrize("url,expected", [
    ('https://example.com/Game%20(USA).zip', 'Game (USA).zip'),
    ('https://example.com/path/to/ROM%20File.nes', 'ROM File.nes'),
    ('https://example.com/file.zip?auth=token', 'file.zip'),
    ('https://example.com/file.zip#fragment', 'file.zip'),
    ('https://example.com/Simple.zip', 'Simple.zip'),
])
def test_url_to_filename(api, url, expected):
    assert api._url_to_filename(url) == expected


# =============================================================================
# _push_event tests
# =============================================================================

def test_push_event_no_window(api):
    # Should not raise
    api._push_event('log', {'text': 'test message'})
    api._push_event('status', {'state': 'running'})
    api._push_event('progress', {'phase': 'scanning', 'current': 1})


def test_push_event_log_buffer(api):
    api._config.advanced.log_dir = '/tmp/logs'
    api._log_buffer = []

    api._push_event('log', {'text': 'Hello world\n'})
    api._push_event('log', {'text': 'Second line\n'})

    assert len(api._log_buffer) == 2
    assert api._log_buffer[0] == 'Hello world\n'


def test_push_event_no_buffer_without_log_dir(api):
    api._config.advanced.log_dir = None
    api._log_buffer = []

    api._push_event('log', {'text': 'test\n'})
    assert len(api._log_buffer) == 0


# =============================================================================
# SYSTEM_ABBREVS consistency
# =============================================================================

def test_system_abbrevs_all_lowercase():
    assert all(s == s.lower() for s in _SYSTEM_ABBREVS)


def test_system_abbrevs_contains_common():
    expected = {'snes', 'nes', 'gba', 'n64', 'psx', 'ps2', '3do', 'msx'}
    assert not (expected - _SYSTEM_ABBREVS)


# =============================================================================
# get_all_roms tests
# =============================================================================

def test_get_all_roms(api):
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

    all_roms = json.loads(api.get_all_roms())
    assert len(all_roms) == 2
    systems_found = {r.get('system') for r in all_roms}
    assert 'nes' in systems_found and 'snes' in systems_found


# =============================================================================
# save_ui_state / load_ui_state tests
# =============================================================================

def test_save_load_ui_state(api, tmp_path):
    import retro_refiner.ui.api as api_mod
    orig_get_runtime = api_mod.get_runtime_path

    try:
        api_mod.get_runtime_path = lambda: tmp_path

        api._config.sources = ['http://test.com']
        api._config.selection.english_only = True
        api._config.auth.igdb_client_id = 'secret_id'

        api.save_ui_state()

        api2 = Api()
        api2._window = None
        state_json = api2.load_ui_state()

        assert state_json != '{}'
        data = json.loads(state_json)

        assert data.get('sources') == ['http://test.com']

        # Auth should be stripped
        auth = data.get('auth', {})
        assert not auth.get('igdb_client_id')
    finally:
        api_mod.get_runtime_path = orig_get_runtime


def test_save_ui_state_skip(api, tmp_path):
    import retro_refiner.ui.api as api_mod
    orig_get_runtime = api_mod.get_runtime_path

    try:
        api_mod.get_runtime_path = lambda: tmp_path

        api._skip_save = True
        api._config.sources = ['http://should-not-save.com']

        api.save_ui_state()

        state_file = tmp_path / '.retro-refiner-state.yaml'
        assert not state_file.exists()
    finally:
        api_mod.get_runtime_path = orig_get_runtime

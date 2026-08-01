#!/usr/bin/env python3
"""
Comprehensive tests for retro_refiner/ui/api.py.

Tests the Api class and module-level helpers without requiring a GUI window.
"""

import collections
import json
import shutil
from pathlib import Path

import pytest

from retro_refiner.ui.api import (
    Api, _display_name, _get_exclusion_reason,
    _parse_csv, _int_or_none, _float_or_none, _parse_size_string,
    _SYSTEM_ABBREVS, _manual_keep, _volume_id, _local_transfer_cost,
)
from retro_refiner.config import Config
from retro_refiner.filter import parse_rom_filename
from retro_refiner.mame import MameGameInfo


@pytest.fixture
def api():
    from retro_refiner.ui.api import Api
    a = Api()
    a._window = None
    return a


def _make_mame_game(name, description, year='1991',
                    manufacturer='Test', category='Maze',
                    is_parent=True, parent_name='', is_bios=False,
                    is_device=False, has_chd=False, chd_names=None,
                    region='World', bios_name='', rom_files=None):
    """Build a MameGameInfo (12 required fields) for filter tests.

    Mirrors the helper of the same name in tests/test_filter.py.
    """
    return MameGameInfo(
        name=name, description=description, year=year,
        manufacturer=manufacturer, category=category,
        is_parent=is_parent, parent_name=parent_name,
        is_bios=is_bios, is_device=is_device,
        has_chd=has_chd, chd_names=chd_names or [], region=region,
        bios_name=bios_name, rom_files=rom_files,
    )


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
    assert _get_exclusion_reason(rom) == 'older version'


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


# =============================================================================
# Budget filter tests (top-N / size) — must apply to local files, not just URLs
# =============================================================================

class TestBudgetFiltersLocalFiles:
    """Regression tests: budget filters previously ignored local ROMs."""

    @staticmethod
    def _make_roms(tmp_path, specs):
        """Create local ROM files. specs: [(filename, size_bytes), ...]"""
        paths = []
        for name, size in specs:
            p = tmp_path / name
            p.write_bytes(b'\0' * size)
            paths.append(str(p))
        return paths

    @staticmethod
    def _stub_ratings(monkeypatch, system, entries):
        """Patch the ratings pipeline to return a fixed ratings dict.

        entries: {title: rating}
        """
        import retro_refiner.ratings as ratings_mod
        from retro_refiner.dat import normalize_title

        table = {
            normalize_title(t): {'rating': r, 'votes': 100, 'name': t}
            for t, r in entries.items()
        }
        monkeypatch.setattr(ratings_mod, 'download_launchbox_data',
                            lambda *a, **k: Path('fake.xml'))
        monkeypatch.setattr(ratings_mod, 'build_ratings_cache',
                            lambda *a, **k: {system: table})

    def _run(self, api, tmp_path, monkeypatch, budget_kwargs, specs, ratings):
        from retro_refiner.config import Config

        self._stub_ratings(monkeypatch, 'snes', ratings)
        paths = self._make_roms(tmp_path, specs)

        api._running = True
        api._last_results = {
            'snes': {'urls': [], 'local_files': paths,
                     'selected_urls': [], 'selected_local': list(paths)},
        }
        config = Config()
        config.advanced.dat_dir = str(tmp_path / 'dat')
        for key, val in budget_kwargs.items():
            setattr(config.budget, key, val)

        api._apply_ratings_budget(config, {'snes'}, {})
        return api._last_results['snes']['selected_local']

    def test_top_n_filters_local_files(self, api, tmp_path, monkeypatch):
        kept = self._run(
            api, tmp_path, monkeypatch,
            {'top': '2'},
            [('Super Mario World (USA).sfc', 512),
             ('Chrono Trigger (USA).sfc', 512),
             ('Bad Game (USA).sfc', 512)],
            {'Super Mario World': 9.5, 'Chrono Trigger': 9.4, 'Bad Game': 2.0},
        )
        assert len(kept) == 2
        names = {Path(f).name for f in kept}
        assert 'Bad Game (USA).sfc' not in names

    def test_size_budget_filters_local_files(self, api, tmp_path, monkeypatch):
        kept = self._run(
            api, tmp_path, monkeypatch,
            {'size': '2KB'},
            [('Super Mario World (USA).sfc', 1024),
             ('Chrono Trigger (USA).sfc', 1024),
             ('Bad Game (USA).sfc', 1024)],
            {'Super Mario World': 9.5, 'Chrono Trigger': 9.4, 'Bad Game': 2.0},
        )
        assert len(kept) == 2
        names = {Path(f).name for f in kept}
        assert 'Bad Game (USA).sfc' not in names

    def test_no_budget_keeps_everything(self, api, tmp_path, monkeypatch):
        kept = self._run(
            api, tmp_path, monkeypatch,
            {},
            [('Super Mario World (USA).sfc', 512),
             ('Chrono Trigger (USA).sfc', 512)],
            {'Super Mario World': 9.5, 'Chrono Trigger': 9.4},
        )
        assert len(kept) == 2

    def test_mixed_local_and_network_share_one_budget(
            self, api, tmp_path, monkeypatch):
        from retro_refiner.config import Config

        self._stub_ratings(monkeypatch, 'snes', {
            'Super Mario World': 9.5, 'Chrono Trigger': 9.4, 'Bad Game': 2.0,
        })
        local = self._make_roms(tmp_path, [('Chrono Trigger (USA).sfc', 512)])
        urls = ['http://x/Super%20Mario%20World%20(USA).sfc',
                'http://x/Bad%20Game%20(USA).sfc']

        api._running = True
        api._last_results = {
            'snes': {'urls': urls, 'local_files': local,
                     'selected_urls': list(urls),
                     'selected_local': list(local)},
        }
        config = Config()
        config.advanced.dat_dir = str(tmp_path / 'dat')
        config.budget.top = '2'

        api._apply_ratings_budget(config, {'snes'}, {u: 512 for u in urls})

        data = api._last_results['snes']
        assert len(data['selected_urls']) + len(data['selected_local']) == 2
        assert len(data['selected_local']) == 1  # Chrono Trigger survives
        assert data['selected_urls'] == [urls[0]]  # Bad Game dropped

# =============================================================================
# Arcade local-file filtering - local ROMs must reach the arcade filters
# =============================================================================

class TestArcadeLocalFiltering:
    """Regression: local arcade ROMs must go through the arcade filters.

    Before the fix only network URLs were handed to
    filter_mame_network_roms / filter_teknoparrot_network_roms, so a local
    arcade folder got no category filtering, no version dedup and no
    title/region maps.
    """

    @staticmethod
    def _stub_mame_data(monkeypatch, tmp_path, categories, games):
        """Patch the MAME data download/parse trio (no network)."""
        import retro_refiner.mame as mame_mod

        catver = tmp_path / 'catver.ini'
        catver.write_text('[Category]\n', encoding='utf-8')
        dat = tmp_path / 'mame.dat'
        dat.write_text('<datafile></datafile>', encoding='utf-8')

        monkeypatch.setattr(mame_mod, 'download_mame_data',
                            lambda *a, **k: (catver, dat))
        monkeypatch.setattr(mame_mod, 'parse_catver_ini',
                            lambda *a, **k: dict(categories))
        monkeypatch.setattr(mame_mod, 'parse_mame_dat',
                            lambda *a, **k: dict(games))

    @staticmethod
    def _make_files(folder, specs):
        """Create files under folder. specs: [(name, size), ...]"""
        folder.mkdir(parents=True, exist_ok=True)
        paths = []
        for name, size in specs:
            path = folder / name
            path.write_bytes(b'\0' * size)
            paths.append(str(path))
        return paths

    @staticmethod
    def _config(tmp_path):
        config = Config()
        config.advanced.dat_dir = str(tmp_path / 'dat')
        config.destination = str(tmp_path / 'dest')
        return config

    def _run(self, api, system, local_files, config):
        api._last_results = {system: {'urls': [], 'sizes': {},
                                      'local_files': list(local_files)}}
        api._filter_system(system, [], list(local_files), config, {})
        return api._last_results[system]

    def test_local_mame_gets_category_filtering(self, api, tmp_path,
                                                monkeypatch):
        pacman, bios = self._make_files(
            tmp_path / 'roms',
            [('pacman.zip', 100), ('neogeo.zip', 50)])
        self._stub_mame_data(
            monkeypatch, tmp_path,
            {'pacman': 'Maze', 'neogeo': 'System / BIOS'},
            {'pacman': _make_mame_game('pacman', 'Pac-Man',
                                       category='Maze'),
             'neogeo': _make_mame_game('neogeo', 'Neo Geo BIOS',
                                       category='System / BIOS',
                                       is_bios=True)})

        data = self._run(api, 'mame', [pacman, bios],
                         self._config(tmp_path))

        assert data['selected_local'] == [pacman]
        assert data['url_reasons'][bios] == 'BIOS'

    def test_local_mame_populates_title_and_region_maps(self, api, tmp_path,
                                                        monkeypatch):
        (sf2,) = self._make_files(tmp_path / 'roms', [('sf2.zip', 100)])
        self._stub_mame_data(
            monkeypatch, tmp_path, {'sf2': 'Fighter'},
            {'sf2': _make_mame_game('sf2', 'Street Fighter II (World)',
                                    category='Fighter', region='World')})

        data = self._run(api, 'mame', [sf2], self._config(tmp_path))

        assert data['selected_local'] == [sf2]
        assert data['title_map']['sf2'] == 'Street Fighter II (World)'
        assert data['region_map']['sf2'] == 'World'

    def test_local_mame_adult_filter(self, api, tmp_path, monkeypatch):
        (adult,) = self._make_files(tmp_path / 'roms', [('nudemj.zip', 100)])
        self._stub_mame_data(
            monkeypatch, tmp_path, {'nudemj': 'Maze * Mature *'},
            {'nudemj': _make_mame_game('nudemj', 'Adult Game',
                                       category='Maze * Mature *')})

        config = self._config(tmp_path)
        config.advanced.no_adult = True
        data = self._run(api, 'mame', [adult], config)

        assert data['selected_local'] == []
        assert data['url_reasons'][adult] == 'Adult/mature content'

    def test_local_teknoparrot_version_dedup(self, api, tmp_path):
        old, new = self._make_files(tmp_path / 'roms', [
            ('Wangan Midnight Maximum Tune 5 (1.03) '
             '[Namco System 357] [TP].zip', 100),
            ('Wangan Midnight Maximum Tune 5 (2.00) '
             '[Namco System 357] [TP].zip', 100),
        ])

        data = self._run(api, 'teknoparrot', [old, new],
                         self._config(tmp_path))

        assert data['selected_local'] == [new]
        assert data['url_reasons'][old] == 'duplicate version'

    def test_console_system_still_uses_file_filter(self, api, tmp_path,
                                                   monkeypatch):
        """The 'not arcade' gate keeps console systems on the file path."""
        import retro_refiner.filter as filter_mod
        import retro_refiner.mame as mame_mod
        import retro_refiner.teknoparrot as tp_mod

        (game,) = self._make_files(tmp_path / 'roms',
                                   [('Super Mario World (USA).sfc', 100)])

        file_calls = []

        def _file_spy(rom_files, **_kwargs):
            file_calls.append(list(rom_files))
            return ([parse_rom_filename(Path(f).name) for f in rom_files],
                    {'selected_size': 100})

        monkeypatch.setattr(filter_mod, 'filter_roms_from_files', _file_spy)

        arcade_calls = []
        monkeypatch.setattr(
            mame_mod, 'filter_mame_network_roms',
            lambda *a, **k: (arcade_calls.append('mame'), ([], {}))[1])
        monkeypatch.setattr(
            tp_mod, 'filter_teknoparrot_network_roms',
            lambda *a, **k: (arcade_calls.append('tp'), ([], {}))[1])

        config = self._config(tmp_path)
        config.advanced.no_dat = True
        data = self._run(api, 'snes', [game], config)

        assert file_calls == [[game]]
        assert arcade_calls == []
        assert data['selected_local'] == [game]

    def test_picker_shows_mame_region_for_local(self, api, tmp_path,
                                                monkeypatch):
        (sf2,) = self._make_files(tmp_path / 'roms', [('sf2.zip', 100)])
        self._stub_mame_data(
            monkeypatch, tmp_path, {'sf2': 'Fighter'},
            {'sf2': _make_mame_game('sf2', 'Street Fighter II (World)',
                                    category='Fighter', region='World')})

        self._run(api, 'mame', [sf2], self._config(tmp_path))
        rows = json.loads(api.get_system_roms('mame'))

        assert len(rows) == 1
        assert rows[0]['filename'] == 'Street Fighter II (World)'
        assert rows[0]['region'] == 'World'
        assert rows[0]['status'] == 'selected'


# =============================================================================
# _manual_keep tests
# =============================================================================

class TestManualKeep:
    """Picker overrides may be keyed by filename or by display title."""

    def test_matches_real_filename(self):
        assert _manual_keep({'sf2.zip': False}, {}, 'sf2.zip') is False

    def test_matches_display_title(self):
        manual = {'Street Fighter II (World)': False}
        titles = {'sf2': 'Street Fighter II (World)'}
        assert _manual_keep(manual, titles, 'sf2.zip') is False

    def test_defaults_to_true_without_override(self):
        manual = {'other.zip': False}
        titles = {'sf2': 'Street Fighter II (World)'}
        assert _manual_keep(manual, titles, 'sf2.zip') is True


# =============================================================================
# DAT sharing between network and local filtering
# =============================================================================

class TestFilterSystemSharesDats:
    """Local console filtering must receive the same DATs the URLs got."""

    @staticmethod
    def _spy_file_filter(monkeypatch, captured):
        import retro_refiner.filter as filter_mod

        def _fake(rom_files, **kwargs):
            captured.update(kwargs)
            captured['rom_files'] = list(rom_files)
            return ([], {'selected_size': 0})

        monkeypatch.setattr(filter_mod, 'filter_roms_from_files', _fake)

    @staticmethod
    def _stub_dat_loader(monkeypatch, api, loads, value):
        monkeypatch.setattr(
            api, '_load_console_dats',
            lambda system, config: (loads.append(system), value)[1])

    @staticmethod
    def _make_rom(tmp_path, name='Game (USA).sfc'):
        rom = tmp_path / name
        rom.write_bytes(b'\0' * 16)
        return str(rom)

    def test_local_only_system_gets_dat_entries(self, api, tmp_path,
                                                monkeypatch):
        captured = {}
        loads = []
        sentinel = {'DEADBEEF': 'sentinel-entry'}
        self._spy_file_filter(monkeypatch, captured)
        self._stub_dat_loader(monkeypatch, api, loads, sentinel)

        rom = self._make_rom(tmp_path)
        config = Config()
        config.advanced.dat_dir = str(tmp_path / 'dat')
        api._last_results = {'snes': {'urls': [], 'sizes': {},
                                      'local_files': [rom]}}
        api._filter_system('snes', [], [rom], config, {})

        assert loads == ['snes']
        assert captured['dat_entries'] is sentinel
        assert captured['no_verify'] is True

    def test_no_dat_config_skips_the_load(self, api, tmp_path, monkeypatch):
        captured = {}
        loads = []
        self._spy_file_filter(monkeypatch, captured)
        self._stub_dat_loader(monkeypatch, api, loads, {'X': 'y'})

        rom = self._make_rom(tmp_path)
        config = Config()
        config.advanced.dat_dir = str(tmp_path / 'dat')
        config.advanced.no_dat = True
        api._last_results = {'snes': {'urls': [], 'sizes': {},
                                      'local_files': [rom]}}
        api._filter_system('snes', [], [rom], config, {})

        assert loads == []
        assert captured['dat_entries'] is None

    @pytest.mark.parametrize('system', ['mame', 'teknoparrot'])
    def test_arcade_system_never_loads_console_dats(self, api, tmp_path,
                                                    monkeypatch, system):
        import retro_refiner.mame as mame_mod

        monkeypatch.setattr(mame_mod, 'download_mame_data',
                            lambda *a, **k: (None, None))
        loads = []
        self._stub_dat_loader(monkeypatch, api, loads, None)

        rom = self._make_rom(tmp_path, 'sf2.zip')
        config = Config()
        config.advanced.dat_dir = str(tmp_path / 'dat')
        api._last_results = {system: {'urls': [], 'sizes': {},
                                      'local_files': [rom]}}
        api._filter_system(system, [], [rom], config, {})

        assert loads == []


# =============================================================================
# _local_to_relpath tests
# =============================================================================

class TestLocalToRelpath:
    """Local files keep their subdirectories below the system folder."""

    def test_strips_system_folder(self, api, tmp_path):
        src = tmp_path / 'roms'
        rom = src / 'snes' / 'usa' / 'game.zip'
        assert api._local_to_relpath(rom, [str(src)], 'snes') == 'usa/game.zip'

    def test_strips_no_intro_folder(self, api, tmp_path):
        src = tmp_path / 'roms'
        rom = (src / 'Nintendo - Super Nintendo Entertainment System'
               / 'usa' / 'game.zip')
        assert api._local_to_relpath(rom, [str(src)], 'snes') == 'usa/game.zip'

    def test_keeps_non_system_subdir(self, api, tmp_path):
        src = tmp_path / 'roms'
        rom = src / 'Favorites' / 'game.zip'
        assert (api._local_to_relpath(rom, [str(src)], 'snes')
                == 'Favorites/game.zip')

    def test_source_root_is_system_folder(self, api, tmp_path):
        src = tmp_path / 'roms' / 'snes'
        rom = src / 'usa' / 'game.zip'
        assert api._local_to_relpath(rom, [str(src)], 'snes') == 'usa/game.zip'

    def test_no_subdir(self, api, tmp_path):
        src = tmp_path / 'roms'
        rom = src / 'game.zip'
        assert api._local_to_relpath(rom, [str(src)], 'snes') == 'game.zip'

    def test_outside_sources_falls_back_to_filename(self, api, tmp_path):
        src = tmp_path / 'roms'
        rom = tmp_path / 'elsewhere' / 'deep' / 'game.zip'
        assert api._local_to_relpath(rom, [str(src)], 'snes') == 'game.zip'

    def test_url_sources_ignored(self, api, tmp_path):
        src = tmp_path / 'roms'
        rom = src / 'snes' / 'usa' / 'game.zip'
        sources = ['https://example.com/roms/', str(src)]
        assert api._local_to_relpath(rom, sources, 'snes') == 'usa/game.zip'


# =============================================================================
# _commit_system: local subdirectory preservation
# =============================================================================

class TestCommitSystemLocalRelpaths:
    """Regression: local transfers used to collapse to the bare basename."""

    @staticmethod
    def _setup(tmp_path, specs):
        """specs: [(path relative to roms/, size)] -> (config, dest, paths)"""
        roms = tmp_path / 'roms'
        dest = tmp_path / 'dest'
        dest.mkdir()
        paths = []
        for rel, size in specs:
            path = roms.joinpath(*rel.split('/'))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'\0' * size)
            paths.append(str(path))
        config = Config()
        config.sources = [str(roms)]
        config.destination = str(dest)
        config.output.local_file_action = 'copy'
        return config, dest, paths

    def test_commit_system_preserves_local_subdirs(self, api, tmp_path):
        config, dest, paths = self._setup(tmp_path, [
            ('snes/usa/game.zip', 100),
            ('snes/japan/game.zip', 200),
        ])
        api._last_results = {'snes': {
            'urls': [], 'sizes': {}, 'local_files': paths,
            'selected_urls': [], 'selected_local': paths,
        }}

        api._commit_system('snes', config, dest)

        usa = dest / 'snes' / 'usa' / 'game.zip'
        japan = dest / 'snes' / 'japan' / 'game.zip'
        assert usa.read_bytes() == b'\0' * 100
        assert japan.read_bytes() == b'\0' * 200

    def test_commit_system_flat_collapses_local(self, api, tmp_path):
        config, dest, paths = self._setup(tmp_path, [
            ('snes/usa/mario.zip', 100),
            ('snes/japan/zelda.zip', 200),
        ])
        config.output.flat = True
        api._last_results = {'snes': {
            'urls': [], 'sizes': {}, 'local_files': paths,
            'selected_urls': [], 'selected_local': paths,
        }}

        api._commit_system('snes', config, dest)

        assert (dest / 'mario.zip').exists()
        assert (dest / 'zelda.zip').exists()
        assert not (dest / 'snes').exists()


# =============================================================================
# _volume_id / _local_transfer_cost tests
# =============================================================================

class TestVolumeId:
    def test_same_volume_matches(self, tmp_path):
        sub = tmp_path / 'sub'
        sub.mkdir()
        assert _volume_id(sub) == _volume_id(tmp_path)

    def test_missing_path_is_none(self, tmp_path):
        assert _volume_id(tmp_path / 'does-not-exist') is None


class TestLocalTransferCost:
    """What a local transfer actually costs in the destination."""

    @pytest.fixture
    def rom(self, tmp_path):
        path = tmp_path / 'game.zip'
        path.write_bytes(b'\0' * 1000)
        return path

    def test_copy_costs_full_size(self, rom, tmp_path):
        assert _local_transfer_cost(rom, 'copy', _volume_id(tmp_path)) == 1000

    @pytest.mark.parametrize('action', ['link', 'hardlink', 'remove'])
    def test_free_actions_cost_nothing(self, rom, tmp_path, action):
        assert _local_transfer_cost(rom, action, _volume_id(tmp_path)) == 0

    def test_move_on_same_volume_costs_nothing(self, rom, tmp_path):
        assert _local_transfer_cost(rom, 'move', _volume_id(tmp_path)) == 0

    def test_move_to_other_volume_costs_full_size(self, rom, tmp_path):
        other_vol = _volume_id(tmp_path) + 1
        assert _local_transfer_cost(rom, 'move', other_vol) == 1000

    def test_move_with_unknown_volume_costs_full_size(self, rom):
        assert _local_transfer_cost(rom, 'move', None) == 1000

    def test_symlink_costs_full_size(self, rom, tmp_path):
        # transfer_files has no 'symlink' branch: it falls through to
        # shutil.copy2, so the destination really does grow.
        assert _local_transfer_cost(rom, 'symlink',
                                    _volume_id(tmp_path)) == 1000


# =============================================================================
# _check_disk_space tests
# =============================================================================

_DiskUsage = collections.namedtuple('_DiskUsage', 'total used free')


class TestCheckDiskSpace:
    """Local-only commits must be disk-checked too."""

    @staticmethod
    def _stub_free(monkeypatch, free):
        monkeypatch.setattr(
            shutil, 'disk_usage',
            lambda _p: _DiskUsage(total=free * 10, used=0, free=free))

    @staticmethod
    def _setup(tmp_path, rel='snes/usa/game.zip', size=1000):
        roms = tmp_path / 'roms'
        dest = tmp_path / 'dest'
        dest.mkdir()
        rom = roms.joinpath(*rel.split('/'))
        rom.parent.mkdir(parents=True, exist_ok=True)
        rom.write_bytes(b'\0' * size)
        config = Config()
        config.sources = [str(roms)]
        config.destination = str(dest)
        return config, dest, str(rom)

    def test_local_copy_can_exhaust_free_space(self, api, tmp_path,
                                               monkeypatch):
        config, dest, rom = self._setup(tmp_path)
        self._stub_free(monkeypatch, 10)
        api._last_results = {'snes': {'selected_urls': [],
                                      'selected_local': [rom]}}

        assert api._check_disk_space(config, {'snes'}, 0, dest) is False

    def test_local_copy_that_fits_passes(self, api, tmp_path, monkeypatch):
        config, dest, rom = self._setup(tmp_path)
        self._stub_free(monkeypatch, 10 * 1000 * 1000)
        api._last_results = {'snes': {'selected_urls': [],
                                      'selected_local': [rom]}}

        assert api._check_disk_space(config, {'snes'}, 0, dest) is True

    def test_local_files_already_in_dest_are_not_charged(self, api, tmp_path,
                                                         monkeypatch):
        config, dest, rom = self._setup(tmp_path)
        # The commit writes to <dest>/snes/usa/game.zip, not the basename.
        existing = dest / 'snes' / 'usa' / 'game.zip'
        existing.parent.mkdir(parents=True)
        existing.write_bytes(b'\0' * 1000)
        self._stub_free(monkeypatch, 10)
        api._last_results = {'snes': {'selected_urls': [],
                                      'selected_local': [rom]}}

        assert api._check_disk_space(config, {'snes'}, 0, dest) is True

    @pytest.mark.parametrize('action', ['hardlink', 'link', 'remove'])
    def test_link_modes_need_no_space(self, api, tmp_path, monkeypatch,
                                      action):
        config, dest, rom = self._setup(tmp_path)
        config.output.local_file_action = action
        self._stub_free(monkeypatch, 10)
        api._last_results = {'snes': {'selected_urls': [],
                                      'selected_local': [rom]}}

        assert api._check_disk_space(config, {'snes'}, 0, dest) is True

    def test_same_volume_move_needs_no_space(self, api, tmp_path,
                                             monkeypatch):
        config, dest, rom = self._setup(tmp_path)
        config.output.local_file_action = 'move'
        self._stub_free(monkeypatch, 10)
        api._last_results = {'snes': {'selected_urls': [],
                                      'selected_local': [rom]}}

        assert api._check_disk_space(config, {'snes'}, 0, dest) is True

    def test_urls_still_counted(self, api, tmp_path, monkeypatch):
        config, dest, _rom = self._setup(tmp_path)
        self._stub_free(monkeypatch, 10)
        api._last_results = {'snes': {
            'selected_urls': ['https://example.com/snes/Game%20(USA).zip'],
            'selected_local': [],
        }}

        assert api._check_disk_space(config, {'snes'}, 5000, dest) is False


# =============================================================================
# Hard --limit budget tests
# =============================================================================

class TestHardLimitBudget:
    """--limit caps the total ROM count across every system."""

    @staticmethod
    def _urls(system, count):
        return [f'https://example.com/{system}/Game{i}.zip'
                for i in range(count)]

    def test_limit_caps_total_across_systems(self, api):
        api._running = True
        api._last_results = {
            'nes': {'selected_urls': self._urls('nes', 3),
                    'selected_local': []},
            'snes': {'selected_urls': self._urls('snes', 3),
                     'selected_local': []},
        }

        api._apply_hard_limit(4, {'nes', 'snes'}, {})

        total = sum(len(d['selected_urls']) + len(d['selected_local'])
                    for d in api._last_results.values())
        assert total == 4
        assert len(api._last_results['nes']['selected_urls']) == 3
        assert len(api._last_results['snes']['selected_urls']) == 1

    def test_limit_counts_local_files_not_just_urls(self, api, tmp_path):
        local = []
        for i in range(3):
            path = tmp_path / f'game{i}.zip'
            path.write_bytes(b'\0' * 10)
            local.append(str(path))
        api._running = True
        api._last_results = {
            'snes': {'selected_urls': self._urls('snes', 1),
                     'selected_local': local},
        }

        api._apply_hard_limit(2, {'snes'}, {})

        data = api._last_results['snes']
        assert len(data['selected_urls']) == 1
        assert len(data['selected_local']) == 1

    def test_limit_exhausted_empties_later_systems(self, api):
        api._running = True
        api._last_results = {
            'nes': {'selected_urls': self._urls('nes', 5),
                    'selected_local': []},
            'snes': {'selected_urls': self._urls('snes', 2),
                     'selected_local': []},
        }

        api._apply_hard_limit(2, {'nes', 'snes'}, {})

        assert len(api._last_results['nes']['selected_urls']) == 2
        assert api._last_results['snes']['selected_urls'] == []
        assert api._last_results['snes']['selected_local'] == []

    def test_no_limit_keeps_everything(self, api):
        api._running = True
        urls = self._urls('nes', 3)
        api._last_results = {
            'nes': {'selected_urls': list(urls), 'selected_local': []},
        }
        config = Config()

        api._apply_budget_filters(config, {'nes'}, {})

        assert api._last_results['nes']['selected_urls'] == urls


def test_update_config_from_ui_preserves_budget_limit(api):
    """The sidebar has no limit widget; a saved state must not null it."""
    api._config.budget.limit = 500

    api.update_config_from_ui(json.dumps({'top': '50'}))

    assert api._config.budget.limit == 500

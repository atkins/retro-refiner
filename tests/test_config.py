"""Tests for retro_refiner.config module."""
import json
from pathlib import Path

import pytest

from retro_refiner.config import (
    parse_yaml,
    Config, SelectionConfig, BudgetConfig, NetworkConfig, OutputConfig,
    AdvancedConfig, ThemeConfig, AuthConfig, DeduplicationConfig,
    DEFAULT_REGION_PRIORITY,
    load_config, save_config,
)


# =============================================================================
# YAML Parser Tests
# =============================================================================

def test_yaml_key_value_pairs():
    data = parse_yaml("name: hello\ncount: 42")
    assert data.get('name') == 'hello'
    assert data.get('count') == 42


def test_yaml_booleans():
    data = parse_yaml("a: true\nb: false\nc: yes\nd: no\ne: on\nf: off")
    expected = {'a': True, 'b': False, 'c': True, 'd': False,
                'e': True, 'f': False}
    for k, v in expected.items():
        assert data.get(k) == v, f"expected {k}={v}, got {data.get(k)}"


def test_yaml_null_values():
    data = parse_yaml("a: null\nb: ~")
    assert data.get('a') is None
    assert data.get('b') is None


def test_yaml_quoted_strings():
    data = parse_yaml('a: "hello world"\nb: \'single\'')
    assert data.get('a') == 'hello world'
    assert data.get('b') == 'single'


def test_yaml_lists():
    data = parse_yaml("items:\n  - one\n  - two\n  - three")
    assert data.get('items') == ['one', 'two', 'three']


def test_yaml_comments():
    data = parse_yaml("# full line comment\nname: hello  # inline comment")
    assert data == {'name': 'hello'}


def test_yaml_hash_in_quoted_string():
    data = parse_yaml('color: "#e94560"')
    assert data.get('color') == '#e94560'


def test_yaml_floats():
    data = parse_yaml("val: 3.14")
    assert isinstance(data.get('val'), float)
    assert abs(data['val'] - 3.14) < 0.001


def test_yaml_empty_content():
    assert parse_yaml("") == {}


def test_yaml_empty_value_becomes_empty_list():
    data = parse_yaml("items:\nother: val")
    assert data.get('items') is None  # pyyaml: empty key = None
    assert data.get('other') == 'val'


def test_yaml_list_with_integers():
    data = parse_yaml("nums:\n  - 1\n  - 2\n  - 3")
    assert data.get('nums') == [1, 2, 3]


def test_yaml_multiple_lists():
    data = parse_yaml("a:\n  - x\nb:\n  - y")
    assert data.get('a') == ['x']
    assert data.get('b') == ['y']


# =============================================================================
# Config Defaults Tests
# =============================================================================

class TestConfigDefaults:
    """Test that Config defaults are correct."""

    def test_sources_default(self):
        assert Config().sources == []

    def test_destination_default(self):
        assert Config().destination is None

    def test_systems_default(self):
        assert Config().systems is None

    def test_english_only_default(self):
        assert Config().selection.english_only is False

    def test_region_priority_default(self):
        assert Config().selection.region_priority == DEFAULT_REGION_PRIORITY

    def test_include_patterns_default(self):
        assert Config().selection.include_patterns == []

    def test_budget_top_limit_default(self):
        cfg = Config()
        assert cfg.budget.top is None
        assert cfg.budget.limit is None

    def test_include_unrated_default(self):
        assert Config().budget.include_unrated is False

    def test_parallel_default(self):
        assert Config().network.parallel == 4

    def test_scan_workers_default(self):
        assert Config().network.scan_workers == 16

    def test_local_file_action_default(self):
        assert Config().output.local_file_action == 'copy'

    def test_flat_default(self):
        assert Config().output.flat is False

    def test_max_depth_default(self):
        assert Config().advanced.max_depth == 3

    def test_ratings_source_default(self):
        assert Config().advanced.ratings_source == 'combined'

    def test_theme_defaults(self):
        cfg = Config()
        assert cfg.theme.mode == 'midnight-terminal'
        assert cfg.theme.accent == '#e94560'

    def test_auth_defaults(self):
        cfg = Config()
        assert cfg.auth.ia_access_key is None
        assert cfg.auth.igdb_client_id is None

    def test_dedup_defaults(self):
        cfg = Config()
        assert cfg.deduplication.priority is None
        assert cfg.deduplication.pc_lists == []


# =============================================================================
# Config.from_dict Tests
# =============================================================================

def test_from_dict_sets_selection_fields():
    cfg = Config.from_dict({
        'selection': {'english_only': True, 'verbose': True}
    })
    assert cfg.selection.english_only is True
    assert cfg.selection.verbose is True


def test_from_dict_unset_fields_keep_defaults():
    cfg = Config.from_dict({
        'selection': {'english_only': True, 'verbose': True}
    })
    assert cfg.selection.exclude_protos is False


def test_from_dict_top_level_fields():
    cfg = Config.from_dict({
        'sources': ['/path/a', '/path/b'],
        'destination': '/out',
        'systems': ['nes', 'snes'],
    })
    assert cfg.sources == ['/path/a', '/path/b']
    assert cfg.destination == '/out'
    assert cfg.systems == ['nes', 'snes']


def test_from_dict_ignores_unknown_keys():
    cfg = Config.from_dict({'unknown_key': 'value'})
    assert cfg.sources == []


def test_from_dict_ignores_unknown_section_keys():
    cfg = Config.from_dict({
        'selection': {'english_only': True, 'bogus_field': 42}
    })
    assert cfg.selection.english_only is True


def test_from_dict_multiple_sections():
    cfg = Config.from_dict({
        'budget': {'top': '50%', 'limit': 100},
        'network': {'parallel': 8},
        'theme': {'mode': 'light'},
    })
    assert cfg.budget.top == '50%'
    assert cfg.budget.limit == 100
    assert cfg.network.parallel == 8
    assert cfg.theme.mode == 'light'


def test_from_dict_empty_dict():
    cfg = Config.from_dict({})
    assert cfg.sources == []
    assert cfg.destination is None


# =============================================================================
# Config.to_dict Tests
# =============================================================================

def test_to_dict_returns_dict():
    assert isinstance(Config().to_dict(), dict)


def test_to_dict_sources():
    assert Config().to_dict().get('sources') == []


def test_to_dict_selection_is_dict():
    assert isinstance(Config().to_dict().get('selection'), dict)


def test_to_dict_selection_english_only():
    assert Config().to_dict().get('selection', {}).get('english_only') is False


def test_to_dict_preserves_custom_top_level():
    cfg = Config(sources=['/a'], destination='/b')
    data = cfg.to_dict()
    assert data['sources'] == ['/a']
    assert data['destination'] == '/b'


def test_to_dict_preserves_custom_section():
    cfg = Config()
    cfg.selection.english_only = True
    data = cfg.to_dict()
    assert data['selection']['english_only'] is True


# =============================================================================
# Round-trip Tests
# =============================================================================

def test_default_config_round_trip():
    cfg1 = Config()
    cfg2 = Config.from_dict(cfg1.to_dict())
    assert cfg1.to_dict() == cfg2.to_dict()


def test_custom_config_round_trip():
    cfg1 = Config(
        sources=['/rom1', '/rom2'],
        destination='/dest',
        systems=['nes', 'snes'],
    )
    cfg1.selection.english_only = True
    cfg1.selection.region_priority = ['Japan', 'USA']
    cfg1.budget.top = '25%'
    cfg1.network.parallel = 8
    cfg1.theme.mode = 'light'
    cfg1.auth.igdb_client_id = 'myid'
    cfg1.deduplication.pc_lists = ['list1.xml', 'list2.xml']

    cfg2 = Config.from_dict(cfg1.to_dict())
    assert cfg1.to_dict() == cfg2.to_dict()


# =============================================================================
# File I/O Tests
# =============================================================================

def test_save_config_creates_file(tmp_path):
    cfg = Config(sources=['/path/a'], destination='/out')
    cfg.selection.english_only = True
    cfg.budget.limit = 50
    cfg.theme.accent = '#ff0000'

    yaml_path = tmp_path / 'config.yaml'
    save_config(cfg, yaml_path)
    assert yaml_path.exists()


def test_load_config_reads_top_level(tmp_path):
    cfg = Config(sources=['/path/a'], destination='/out')
    yaml_path = tmp_path / 'config.yaml'
    save_config(cfg, yaml_path)

    loaded = load_config(yaml_path)
    assert loaded.sources == ['/path/a']
    assert loaded.destination == '/out'


def test_load_config_reads_section_values(tmp_path):
    cfg = Config()
    cfg.selection.english_only = True
    yaml_path = tmp_path / 'config.yaml'
    save_config(cfg, yaml_path)

    loaded = load_config(yaml_path)
    assert loaded.selection.english_only is True


def test_load_config_reads_budget_limit(tmp_path):
    cfg = Config()
    cfg.budget.limit = 50
    yaml_path = tmp_path / 'config.yaml'
    save_config(cfg, yaml_path)

    loaded = load_config(yaml_path)
    assert loaded.budget.limit == 50


def test_load_config_missing_file_returns_defaults():
    cfg = load_config(Path("/nonexistent/path/config_file.yaml"))
    assert cfg.sources == []
    assert cfg.destination is None


def test_load_config_json_file(tmp_path):
    json_path = tmp_path / 'config.json'
    data = {
        'sources': ['/json/path'],
        'selection': {'verbose': True},
        'network': {'parallel': 16},
    }
    json_path.write_text(json.dumps(data), encoding='utf-8')

    cfg = load_config(json_path)
    assert cfg.sources == ['/json/path']
    assert cfg.selection.verbose is True
    assert cfg.network.parallel == 16


def test_load_config_bad_content_returns_config(tmp_path):
    bad_path = tmp_path / 'bad.yaml'
    bad_path.write_text('just a bare string with no colon', encoding='utf-8')
    cfg = load_config(bad_path)
    assert isinstance(cfg, Config)


# =============================================================================
# Backward Compatibility Tests
# =============================================================================

def test_load_config_ignores_removed_genres_field(tmp_path):
    """selection.genres was removed as dead config, but existing state files and
    jobs/*.yaml still carry the key — from_dict must keep ignoring unknown keys."""
    yaml_path = tmp_path / 'legacy.yaml'
    yaml_path.write_text(
        'selection:\n'
        '  english_only: true\n'
        '  genres: null\n',
        encoding='utf-8',
    )

    cfg = load_config(yaml_path)
    assert cfg.selection.english_only is True
    assert not hasattr(cfg.selection, 'genres')

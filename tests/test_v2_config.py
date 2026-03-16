"""Tests for retro_refiner.config module."""
import json
import sys
import tempfile
from pathlib import Path

# Ensure project root is on sys.path so retro_refiner package is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from retro_refiner.config import (
    parse_yaml, _parse_yaml_value, _dump_yaml_value,
    Config, SelectionConfig, BudgetConfig, NetworkConfig, OutputConfig,
    AdvancedConfig, ThemeConfig, AuthConfig, DeduperConfig,
    DEFAULT_REGION_PRIORITY,
    load_config, save_config,
)


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


# =============================================================================
# YAML Parser Tests
# =============================================================================

def test_yaml_parser():
    """Test YAML parsing."""
    print("\n" + "="*60)
    print("YAML PARSER TESTS")
    print("="*60)

    # key-value pairs
    data = parse_yaml("name: hello\ncount: 42")
    if data.get('name') == 'hello' and data.get('count') == 42:
        results.ok("yaml key-value pairs")
    else:
        results.fail("yaml key-value pairs", "{'name': 'hello', 'count': 42}",
                     repr(data))

    # booleans
    data = parse_yaml("a: true\nb: false\nc: yes\nd: no\ne: on\nf: off")
    expected = {'a': True, 'b': False, 'c': True, 'd': False,
                'e': True, 'f': False}
    if all(data.get(k) == v for k, v in expected.items()):
        results.ok("yaml booleans")
    else:
        results.fail("yaml booleans", repr(expected), repr(data))

    # null values
    data = parse_yaml("a: null\nb: ~")
    if data.get('a') is None and data.get('b') is None:
        results.ok("yaml null values")
    else:
        results.fail("yaml null values", "both None", repr(data))

    # quoted strings
    data = parse_yaml('a: "hello world"\nb: \'single\'')
    if data.get('a') == 'hello world' and data.get('b') == 'single':
        results.ok("yaml quoted strings")
    else:
        results.fail("yaml quoted strings",
                     "{'a': 'hello world', 'b': 'single'}", repr(data))

    # lists
    data = parse_yaml("items:\n  - one\n  - two\n  - three")
    if data.get('items') == ['one', 'two', 'three']:
        results.ok("yaml lists")
    else:
        results.fail("yaml lists", "['one', 'two', 'three']",
                     repr(data.get('items')))

    # comments
    data = parse_yaml("# full line comment\nname: hello  # inline comment")
    if data == {'name': 'hello'}:
        results.ok("yaml comments")
    else:
        results.fail("yaml comments", "{'name': 'hello'}", repr(data))

    # hash in quoted string preserved
    data = parse_yaml('color: "#e94560"')
    if data.get('color') == '#e94560':
        results.ok("yaml hash in quoted string preserved")
    else:
        results.fail("yaml hash in quoted string preserved",
                     "'#e94560'", repr(data.get('color')))

    # floats
    data = parse_yaml("val: 3.14")
    if isinstance(data.get('val'), float) and abs(data['val'] - 3.14) < 0.001:
        results.ok("yaml floats")
    else:
        results.fail("yaml floats", "3.14", repr(data.get('val')))

    # empty content
    data = parse_yaml("")
    if data == {}:
        results.ok("yaml empty content")
    else:
        results.fail("yaml empty content", "{}", repr(data))

    # empty value starts a list
    data = parse_yaml("items:\nother: val")
    if data.get('items') == [] and data.get('other') == 'val':
        results.ok("yaml empty value becomes empty list if no items follow")
    else:
        results.fail("yaml empty value becomes empty list",
                     "{'items': [], 'other': 'val'}", repr(data))

    # list with typed values
    data = parse_yaml("nums:\n  - 1\n  - 2\n  - 3")
    if data.get('nums') == [1, 2, 3]:
        results.ok("yaml list with integers")
    else:
        results.fail("yaml list with integers", "[1, 2, 3]",
                     repr(data.get('nums')))

    # multiple lists
    data = parse_yaml("a:\n  - x\nb:\n  - y")
    if data.get('a') == ['x'] and data.get('b') == ['y']:
        results.ok("yaml multiple lists")
    else:
        results.fail("yaml multiple lists",
                     "{'a': ['x'], 'b': ['y']}", repr(data))


# =============================================================================
# _parse_yaml_value Tests
# =============================================================================

def test_parse_yaml_value():
    """Test individual value parsing."""
    print("\n" + "="*60)
    print("YAML VALUE PARSER TESTS")
    print("="*60)

    if _parse_yaml_value('') is None:
        results.ok("parse_yaml_value empty string")
    else:
        results.fail("parse_yaml_value empty string", "None",
                     repr(_parse_yaml_value('')))

    if _parse_yaml_value('42') == 42:
        results.ok("parse_yaml_value integer")
    else:
        results.fail("parse_yaml_value integer", "42",
                     repr(_parse_yaml_value('42')))

    if _parse_yaml_value('hello') == 'hello':
        results.ok("parse_yaml_value plain string")
    else:
        results.fail("parse_yaml_value plain string", "'hello'",
                     repr(_parse_yaml_value('hello')))


# =============================================================================
# _dump_yaml_value Tests
# =============================================================================

def test_dump_yaml_value():
    """Test YAML value serialization."""
    print("\n" + "="*60)
    print("YAML VALUE DUMP TESTS")
    print("="*60)

    if _dump_yaml_value(None) == 'null':
        results.ok("dump None -> null")
    else:
        results.fail("dump None -> null", "'null'",
                     repr(_dump_yaml_value(None)))

    if _dump_yaml_value(True) == 'true':
        results.ok("dump True -> true")
    else:
        results.fail("dump True -> true", "'true'",
                     repr(_dump_yaml_value(True)))

    if _dump_yaml_value(False) == 'false':
        results.ok("dump False -> false")
    else:
        results.fail("dump False -> false", "'false'",
                     repr(_dump_yaml_value(False)))

    if _dump_yaml_value(42) == '42':
        results.ok("dump int")
    else:
        results.fail("dump int", "'42'", repr(_dump_yaml_value(42)))

    if _dump_yaml_value(3.14) == '3.14':
        results.ok("dump float")
    else:
        results.fail("dump float", "'3.14'", repr(_dump_yaml_value(3.14)))

    if _dump_yaml_value('hello') == 'hello':
        results.ok("dump plain string unquoted")
    else:
        results.fail("dump plain string unquoted", "'hello'",
                     repr(_dump_yaml_value('hello')))

    # Strings that need quoting
    if _dump_yaml_value('true') == '"true"':
        results.ok("dump bool-like string gets quoted")
    else:
        results.fail("dump bool-like string gets quoted", "'\"true\"'",
                     repr(_dump_yaml_value('true')))

    if _dump_yaml_value('#e94560') == '"#e94560"':
        results.ok("dump string with hash gets quoted")
    else:
        results.fail("dump string with hash gets quoted", "'\"#e94560\"'",
                     repr(_dump_yaml_value('#e94560')))

    if _dump_yaml_value('key: val') == '"key: val"':
        results.ok("dump string with colon gets quoted")
    else:
        results.fail("dump string with colon gets quoted", "'\"key: val\"'",
                     repr(_dump_yaml_value('key: val')))

    if _dump_yaml_value('') == '""':
        results.ok("dump empty string gets quoted")
    else:
        results.fail("dump empty string gets quoted", "'\"\"'",
                     repr(_dump_yaml_value('')))


# =============================================================================
# Config Defaults Tests
# =============================================================================

def test_config_defaults():
    """Test that Config defaults are correct."""
    print("\n" + "="*60)
    print("CONFIG DEFAULTS TESTS")
    print("="*60)

    cfg = Config()

    # Top-level
    if cfg.sources == []:
        results.ok("default sources is empty list")
    else:
        results.fail("default sources", "[]", repr(cfg.sources))

    if cfg.destination is None:
        results.ok("default destination is None")
    else:
        results.fail("default destination", "None", repr(cfg.destination))

    if cfg.systems is None:
        results.ok("default systems is None")
    else:
        results.fail("default systems", "None", repr(cfg.systems))

    # Selection
    if cfg.selection.english_only is False:
        results.ok("default english_only is False")
    else:
        results.fail("default english_only", "False",
                     repr(cfg.selection.english_only))

    if cfg.selection.region_priority == DEFAULT_REGION_PRIORITY:
        results.ok("default region_priority matches DEFAULT_REGION_PRIORITY")
    else:
        results.fail("default region_priority",
                     repr(DEFAULT_REGION_PRIORITY),
                     repr(cfg.selection.region_priority))

    if cfg.selection.include_patterns == []:
        results.ok("default include_patterns is empty list")
    else:
        results.fail("default include_patterns", "[]",
                     repr(cfg.selection.include_patterns))

    # Budget
    if cfg.budget.top is None and cfg.budget.limit is None:
        results.ok("default budget top/limit are None")
    else:
        results.fail("default budget", "None/None",
                     f"{cfg.budget.top}/{cfg.budget.limit}")

    if cfg.budget.include_unrated is False:
        results.ok("default include_unrated is False")
    else:
        results.fail("default include_unrated", "False",
                     repr(cfg.budget.include_unrated))

    # Network
    if cfg.network.parallel == 4:
        results.ok("default parallel is 4")
    else:
        results.fail("default parallel", "4", repr(cfg.network.parallel))

    if cfg.network.auto_tune is True:
        results.ok("default auto_tune is True")
    else:
        results.fail("default auto_tune", "True",
                     repr(cfg.network.auto_tune))

    if cfg.network.scan_workers == 16:
        results.ok("default scan_workers is 16")
    else:
        results.fail("default scan_workers", "16",
                     repr(cfg.network.scan_workers))

    # Output
    if cfg.output.transfer_mode == 'move':
        results.ok("default transfer_mode is 'move'")
    else:
        results.fail("default transfer_mode", "'move'",
                     repr(cfg.output.transfer_mode))

    if cfg.output.flat is False:
        results.ok("default flat is False")
    else:
        results.fail("default flat", "False", repr(cfg.output.flat))

    # Advanced
    if cfg.advanced.max_depth == 3:
        results.ok("default max_depth is 3")
    else:
        results.fail("default max_depth", "3", repr(cfg.advanced.max_depth))

    if cfg.advanced.ratings_source == 'combined':
        results.ok("default ratings_source is 'combined'")
    else:
        results.fail("default ratings_source", "'combined'",
                     repr(cfg.advanced.ratings_source))

    # Theme
    if cfg.theme.mode == 'dark' and cfg.theme.accent == '#e94560':
        results.ok("default theme mode=dark accent=#e94560")
    else:
        results.fail("default theme", "dark/#e94560",
                     f"{cfg.theme.mode}/{cfg.theme.accent}")

    # Auth
    if (cfg.auth.ia_access_key is None and cfg.auth.igdb_client_id is None):
        results.ok("default auth keys are None")
    else:
        results.fail("default auth", "all None", repr(cfg.auth))

    # Dedup
    if cfg.dedup.priority is None and cfg.dedup.pc_lists == []:
        results.ok("default dedup priority=None pc_lists=[]")
    else:
        results.fail("default dedup", "None/[]",
                     f"{cfg.dedup.priority}/{cfg.dedup.pc_lists}")


# =============================================================================
# Config.from_dict Tests
# =============================================================================

def test_config_from_dict():
    """Test Config.from_dict with partial dicts."""
    print("\n" + "="*60)
    print("CONFIG FROM_DICT TESTS")
    print("="*60)

    # Partial selection config
    cfg = Config.from_dict({
        'selection': {'english_only': True, 'verbose': True}
    })
    if cfg.selection.english_only is True and cfg.selection.verbose is True:
        results.ok("from_dict sets specified selection fields")
    else:
        results.fail("from_dict selection fields",
                     "english_only=True, verbose=True",
                     f"{cfg.selection.english_only}, {cfg.selection.verbose}")

    # Unset fields keep defaults
    if cfg.selection.exclude_protos is False:
        results.ok("from_dict unset fields keep defaults")
    else:
        results.fail("from_dict unset fields", "False",
                     repr(cfg.selection.exclude_protos))

    # Top-level fields
    cfg = Config.from_dict({
        'sources': ['/path/a', '/path/b'],
        'destination': '/out',
        'systems': ['nes', 'snes'],
    })
    if (cfg.sources == ['/path/a', '/path/b']
            and cfg.destination == '/out'
            and cfg.systems == ['nes', 'snes']):
        results.ok("from_dict top-level fields")
    else:
        results.fail("from_dict top-level fields",
                     "sources/dest/systems set",
                     f"{cfg.sources}/{cfg.destination}/{cfg.systems}")

    # Unknown keys ignored
    cfg = Config.from_dict({'unknown_key': 'value'})
    if cfg.sources == []:
        results.ok("from_dict ignores unknown keys")
    else:
        results.fail("from_dict unknown keys", "[]", repr(cfg.sources))

    # Unknown section keys ignored
    cfg = Config.from_dict({
        'selection': {'english_only': True, 'bogus_field': 42}
    })
    if cfg.selection.english_only is True:
        results.ok("from_dict ignores unknown section keys")
    else:
        results.fail("from_dict unknown section keys", "True",
                     repr(cfg.selection.english_only))

    # Multiple sections
    cfg = Config.from_dict({
        'budget': {'top': '50%', 'limit': 100},
        'network': {'parallel': 8},
        'theme': {'mode': 'light'},
    })
    if (cfg.budget.top == '50%' and cfg.budget.limit == 100
            and cfg.network.parallel == 8
            and cfg.theme.mode == 'light'):
        results.ok("from_dict multiple sections")
    else:
        results.fail("from_dict multiple sections",
                     "top=50% limit=100 parallel=8 mode=light",
                     f"{cfg.budget.top}/{cfg.budget.limit}/"
                     f"{cfg.network.parallel}/{cfg.theme.mode}")

    # Empty dict
    cfg = Config.from_dict({})
    if cfg.sources == [] and cfg.destination is None:
        results.ok("from_dict empty dict gives defaults")
    else:
        results.fail("from_dict empty dict", "defaults",
                     f"{cfg.sources}/{cfg.destination}")


# =============================================================================
# Config.to_dict Tests
# =============================================================================

def test_config_to_dict():
    """Test Config.to_dict."""
    print("\n" + "="*60)
    print("CONFIG TO_DICT TESTS")
    print("="*60)

    cfg = Config()
    data = cfg.to_dict()

    if isinstance(data, dict):
        results.ok("to_dict returns dict")
    else:
        results.fail("to_dict returns dict", "dict", type(data).__name__)

    if data.get('sources') == []:
        results.ok("to_dict sources is []")
    else:
        results.fail("to_dict sources", "[]", repr(data.get('sources')))

    if isinstance(data.get('selection'), dict):
        results.ok("to_dict selection is dict")
    else:
        results.fail("to_dict selection is dict", "dict",
                     type(data.get('selection')).__name__)

    sel = data.get('selection', {})
    if sel.get('english_only') is False:
        results.ok("to_dict selection.english_only is False")
    else:
        results.fail("to_dict selection.english_only", "False",
                     repr(sel.get('english_only')))

    # Custom values
    cfg = Config(sources=['/a'], destination='/b')
    cfg.selection.english_only = True
    data = cfg.to_dict()
    if data['sources'] == ['/a'] and data['destination'] == '/b':
        results.ok("to_dict preserves custom top-level values")
    else:
        results.fail("to_dict custom values",
                     "sources=['/a'] dest='/b'",
                     f"{data['sources']}/{data['destination']}")

    if data['selection']['english_only'] is True:
        results.ok("to_dict preserves custom section values")
    else:
        results.fail("to_dict custom section values", "True",
                     repr(data['selection']['english_only']))


# =============================================================================
# Round-trip Tests
# =============================================================================

def test_round_trip():
    """Test Config -> dict -> Config round-trip."""
    print("\n" + "="*60)
    print("ROUND-TRIP TESTS")
    print("="*60)

    # Default config round-trip
    cfg1 = Config()
    data = cfg1.to_dict()
    cfg2 = Config.from_dict(data)
    if cfg1.to_dict() == cfg2.to_dict():
        results.ok("default config round-trip")
    else:
        results.fail("default config round-trip",
                     "equal dicts", "dicts differ")

    # Custom config round-trip
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
    cfg1.dedup.pc_lists = ['list1.xml', 'list2.xml']

    data = cfg1.to_dict()
    cfg2 = Config.from_dict(data)
    d1 = cfg1.to_dict()
    d2 = cfg2.to_dict()
    if d1 == d2:
        results.ok("custom config round-trip")
    else:
        # Find first difference
        for k in d1:
            if d1[k] != d2.get(k):
                results.fail("custom config round-trip",
                             f"{k}={d1[k]}", f"{k}={d2.get(k)}")
                break
        else:
            results.fail("custom config round-trip", "equal", "differ")


# =============================================================================
# File I/O Tests
# =============================================================================

def test_file_io():
    """Test save_config + load_config round-trip."""
    print("\n" + "="*60)
    print("FILE I/O TESTS")
    print("="*60)

    # save + load round-trip
    cfg1 = Config(
        sources=['/path/a'],
        destination='/out',
    )
    cfg1.selection.english_only = True
    cfg1.budget.limit = 50
    cfg1.theme.accent = '#ff0000'

    with tempfile.TemporaryDirectory() as tmpdir:
        yaml_path = Path(tmpdir) / 'config.yaml'
        save_config(cfg1, yaml_path)

        # Verify file was created
        if yaml_path.exists():
            results.ok("save_config creates file")
        else:
            results.fail("save_config creates file", "file exists",
                         "file missing")

        cfg2 = load_config(yaml_path)
        if cfg2.sources == ['/path/a'] and cfg2.destination == '/out':
            results.ok("load_config reads top-level values")
        else:
            results.fail("load_config top-level",
                         "sources=['/path/a'] dest='/out'",
                         f"{cfg2.sources}/{cfg2.destination}")

        if cfg2.selection.english_only is True:
            results.ok("load_config reads section values")
        else:
            results.fail("load_config section values", "True",
                         repr(cfg2.selection.english_only))

        if cfg2.budget.limit == 50:
            results.ok("load_config reads budget.limit")
        else:
            results.fail("load_config budget.limit", "50",
                         repr(cfg2.budget.limit))

    # load_config on missing file
    missing = Path(tempfile.gettempdir()) / 'nonexistent_config_file.yaml'
    cfg = load_config(missing)
    if cfg.sources == [] and cfg.destination is None:
        results.ok("load_config on missing file returns defaults")
    else:
        results.fail("load_config missing file", "defaults",
                     f"{cfg.sources}/{cfg.destination}")

    # load_config on JSON file
    with tempfile.TemporaryDirectory() as tmpdir:
        json_path = Path(tmpdir) / 'config.json'
        data = {
            'sources': ['/json/path'],
            'selection': {'verbose': True},
            'network': {'parallel': 16},
        }
        json_path.write_text(json.dumps(data), encoding='utf-8')

        cfg = load_config(json_path)
        if (cfg.sources == ['/json/path']
                and cfg.selection.verbose is True
                and cfg.network.parallel == 16):
            results.ok("load_config on JSON file")
        else:
            results.fail("load_config JSON", "sources/verbose/parallel",
                         f"{cfg.sources}/{cfg.selection.verbose}/"
                         f"{cfg.network.parallel}")

    # load_config on broken YAML
    with tempfile.TemporaryDirectory() as tmpdir:
        bad_path = Path(tmpdir) / 'bad.yaml'
        # Our simple parser won't crash on bad YAML, it just produces
        # empty/partial results which from_dict handles gracefully.
        # Test with a truly unreadable scenario (binary content that
        # still decodes as utf-8 but produces no useful keys).
        bad_path.write_text('just a bare string with no colon',
                            encoding='utf-8')
        cfg = load_config(bad_path)
        if isinstance(cfg, Config):
            results.ok("load_config on bad content returns Config")
        else:
            results.fail("load_config bad content", "Config instance",
                         type(cfg).__name__)


# =============================================================================
# Main
# =============================================================================

if __name__ == '__main__':
    test_yaml_parser()
    test_parse_yaml_value()
    test_dump_yaml_value()
    test_config_defaults()
    test_config_from_dict()
    test_config_to_dict()
    test_round_trip()
    test_file_io()
    success = results.summary()
    sys.exit(0 if success else 1)

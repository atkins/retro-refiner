# Sub-project 1: Package Scaffold + Config + Systems

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create the `retro_refiner/` Python package with config and systems modules extracted from the monolith, with tests proving they work independently.

**Architecture:** New `retro_refiner/` package alongside the existing files (no removal yet). Config module owns YAML parsing and the v2 config format. Systems module loads `data/systems.json` and provides lookup dictionaries. Both modules are pure logic with no Console/print dependencies.

**Tech Stack:** Python 3.8+ stdlib only (no new deps in this sub-project)

**Spec:** `docs/superpowers/specs/2026-03-16-retro-refiner-v2-design.md`

---

## File Structure

```
retro_refiner/
    __init__.py          # Package init, version
    config.py            # YAML parsing, Config dataclass, load/save
    systems.py           # System data loading, SystemData class with all lookups
    paths.py             # _get_base_path / _get_runtime_path helpers

tests/
    test_v2_config.py    # Config module tests
    test_v2_systems.py   # Systems module tests
```

---

## Chunk 1: Package Scaffold + Paths

### Task 1: Create package directory and __init__.py

**Files:**
- Create: `retro_refiner/__init__.py`

- [ ] **Step 1: Create the package with version**

```python
# retro_refiner/__init__.py
"""Retro-Refiner: Refine your ROM collection down to the essentials."""

__version__ = "dev"
```

- [ ] **Step 2: Verify the package imports**

Run: `python -c "import retro_refiner; print(retro_refiner.__version__)"`
Expected: `dev`

- [ ] **Step 3: Commit**

```bash
git add retro_refiner/__init__.py
git commit -m "feat(v2): create retro_refiner package scaffold"
```

### Task 2: Extract path helpers

**Files:**
- Create: `retro_refiner/paths.py`
- Reference: `retro-refiner.py:139-155` (current `_get_base_path` and `_get_runtime_path`)

- [ ] **Step 1: Write the failing test**

Create `tests/test_v2_paths.py`:

```python
"""Tests for retro_refiner.paths module."""
from pathlib import Path
from retro_refiner.paths import get_base_path, get_runtime_path


def test_get_base_path_returns_path():
    result = get_base_path()
    assert isinstance(result, Path)
    assert result.exists()


def test_get_runtime_path_returns_path():
    result = get_runtime_path()
    assert isinstance(result, Path)
    assert result.exists()


def test_base_path_contains_data_dir():
    """Base path should point to directory containing data/systems.json."""
    base = get_base_path()
    assert (base / 'data' / 'systems.json').exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_v2_paths.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'retro_refiner.paths'`

- [ ] **Step 3: Write minimal implementation**

Create `retro_refiner/paths.py`:

```python
"""Path resolution helpers for bundled data and writable runtime files.

In development: both paths resolve to the project root directory.
In PyInstaller builds: base_path is sys._MEIPASS (read-only bundled data),
runtime_path is the directory containing the executable (writable).
"""
import sys
from pathlib import Path


def get_base_path() -> Path:
    """Get path to bundled read-only data (data/*.json).

    Returns sys._MEIPASS in PyInstaller builds, otherwise the project root.
    """
    if getattr(sys, '_MEIPASS', None):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent


def get_runtime_path() -> Path:
    """Get path for writable runtime files (dat_files/, cache/, logs).

    Returns the executable's directory in PyInstaller builds,
    otherwise the project root.
    """
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_v2_paths.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add retro_refiner/paths.py tests/test_v2_paths.py
git commit -m "feat(v2): extract path helpers into retro_refiner.paths"
```

---

## Chunk 2: Systems Module

### Task 3: Extract systems data loading

**Files:**
- Create: `retro_refiner/systems.py`
- Create: `tests/test_v2_systems.py`
- Reference: `retro-refiner.py:518-652` (current `load_system_data` and globals)

The current code uses module-level globals (KNOWN_SYSTEMS, EXTENSION_TO_SYSTEM, etc.). The v2 version returns a `SystemData` dataclass — no globals, no side effects.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_v2_systems.py`:

```python
"""Tests for retro_refiner.systems module."""
from retro_refiner.systems import load_system_data, SystemData


def test_load_returns_system_data():
    data = load_system_data()
    assert isinstance(data, SystemData)


def test_known_systems_populated():
    data = load_system_data()
    assert len(data.known_systems) > 100  # 144 systems expected
    assert 'nes' in data.known_systems
    assert 'snes' in data.known_systems
    assert 'mame' in data.known_systems


def test_extension_to_system():
    data = load_system_data()
    assert data.extension_to_system.get('.nes') == 'nes'
    assert data.extension_to_system.get('.sfc') == 'snes'
    assert data.extension_to_system.get('.md') == 'genesis'


def test_folder_aliases():
    data = load_system_data()
    assert data.folder_aliases.get('super nintendo') == 'snes'
    assert data.folder_aliases.get('megadrive') == 'genesis'


def test_dat_systems():
    data = load_system_data()
    assert 'nes' in data.libretro_dat_systems
    assert 'psx' in data.redump_dat_systems


def test_launchbox_platform_map():
    data = load_system_data()
    assert len(data.launchbox_platform_map) > 0


def test_reverse_mappings():
    data = load_system_data()
    # DAT name -> system reverse lookup
    assert len(data.dat_name_to_system) > 0
    # System -> LaunchBox reverse lookup
    assert len(data.system_to_launchbox) > 0


def test_sorted_lists_for_detection():
    data = load_system_data()
    # Sorted longest-first for greedy matching
    assert len(data.sorted_dat_names) > 0
    if len(data.sorted_dat_names) >= 2:
        assert len(data.sorted_dat_names[0][0]) >= len(data.sorted_dat_names[1][0])


def test_caching():
    """Second call should return same object (cached)."""
    data1 = load_system_data()
    data2 = load_system_data()
    assert data1 is data2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_v2_systems.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write implementation**

Create `retro_refiner/systems.py`:

```python
"""System definitions loaded from data/systems.json.

Provides SystemData with all lookup dictionaries needed for system detection,
DAT file mapping, and platform identification. No globals — callers receive
a dataclass instance.
"""
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from retro_refiner.paths import get_base_path


@dataclass
class SystemData:
    """All system lookup data loaded from systems.json."""
    known_systems: List[str]
    extension_to_system: Dict[str, str]
    folder_aliases: Dict[str, str]
    libretro_dat_systems: Dict[str, str]
    additional_dat_systems: Dict[str, list]
    redump_dat_systems: Dict[str, str]
    ten_dat_systems: Dict[str, str]
    launchbox_platform_map: Dict[str, str]
    igdb_platform_map: Dict[str, int]
    dat_name_to_system: Dict[str, str]
    system_to_launchbox: Dict[str, str]
    sorted_dat_names: List[Tuple[str, str]]
    sorted_aliases: List[Tuple[str, str]]


_cache: Optional[SystemData] = None


def load_system_data(systems_json_path: Path = None) -> SystemData:
    """Load system definitions from data/systems.json.

    Returns a SystemData instance with all lookup dictionaries.
    Results are cached — subsequent calls return the same object.

    Args:
        systems_json_path: Override path to systems.json (for testing).
                           Defaults to data/systems.json relative to base path.
    """
    global _cache
    if _cache is not None:
        return _cache

    if systems_json_path is None:
        systems_json_path = get_base_path() / 'data' / 'systems.json'

    with open(systems_json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    systems = data.get('systems', {})

    known = list(systems.keys())
    ext_map: Dict[str, str] = {}
    alias_map: Dict[str, str] = {}
    dat_map: Dict[str, str] = {}
    additional_map: Dict[str, list] = {}
    redump_map: Dict[str, str] = {}
    ten_map: Dict[str, str] = {}
    lb_map: Dict[str, str] = {}
    igdb_map: Dict[str, int] = {}

    for system_code, info in systems.items():
        for ext in info.get('extensions', []):
            ext_map[ext] = system_code

        for alias in info.get('folder_aliases', []):
            alias_map[alias] = system_code

        dat_name = info.get('dat_name')
        if dat_name:
            dat_map[system_code] = dat_name

        additional = info.get('additional_dat_names')
        if additional:
            additional_map[system_code] = additional

        redump_name = info.get('redump_dat_name')
        if redump_name:
            redump_map[system_code] = redump_name

        ten_prefix = info.get('ten_dat_prefix')
        if ten_prefix:
            ten_map[system_code] = ten_prefix

        for lb_name in info.get('launchbox_platforms', []):
            lb_map[lb_name] = system_code

        igdb_id = info.get('igdb_id')
        if igdb_id is not None:
            igdb_map[system_code] = igdb_id

    # Reverse mappings
    dat_name_to_sys = {v.lower(): k for k, v in dat_map.items()}
    dat_name_to_sys.update({v.lower(): k for k, v in redump_map.items()})

    sys_to_lb: Dict[str, str] = {}
    for lb_name, sys_code in lb_map.items():
        if sys_code not in sys_to_lb:
            sys_to_lb[sys_code] = lb_name

    # Pre-sorted lists for detect_system_from_path (longest first)
    sorted_dats = sorted(dat_name_to_sys.items(), key=lambda x: len(x[0]), reverse=True)
    sorted_als = sorted(alias_map.items(), key=lambda x: len(x[0]), reverse=True)

    _cache = SystemData(
        known_systems=known,
        extension_to_system=ext_map,
        folder_aliases=alias_map,
        libretro_dat_systems=dat_map,
        additional_dat_systems=additional_map,
        redump_dat_systems=redump_map,
        ten_dat_systems=ten_map,
        launchbox_platform_map=lb_map,
        igdb_platform_map=igdb_map,
        dat_name_to_system=dat_name_to_sys,
        system_to_launchbox=sys_to_lb,
        sorted_dat_names=sorted_dats,
        sorted_aliases=sorted_als,
    )
    return _cache


def reset_cache():
    """Clear the cached SystemData (for testing)."""
    global _cache
    _cache = None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_v2_systems.py -v`
Expected: All passed

- [ ] **Step 5: Commit**

```bash
git add retro_refiner/systems.py tests/test_v2_systems.py
git commit -m "feat(v2): extract systems module with SystemData dataclass"
```

---

## Chunk 3: Config Module

### Task 4: Extract YAML parser and config dataclass

**Files:**
- Create: `retro_refiner/config.py`
- Create: `tests/test_v2_config.py`
- Reference: `retro-refiner.py:656-754` (parse_simple_yaml, _parse_yaml_value)
- Reference: `retro-refiner.py:4061-4160` (load_config, apply_config_to_args)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_v2_config.py`:

```python
"""Tests for retro_refiner.config module."""
import json
import tempfile
from pathlib import Path
from retro_refiner.config import parse_yaml, Config, load_config, save_config


# --- YAML parser tests ---

def test_parse_yaml_key_value():
    result = parse_yaml("name: hello\ncount: 42")
    assert result['name'] == 'hello'
    assert result['count'] == 42


def test_parse_yaml_booleans():
    result = parse_yaml("a: true\nb: false\nc: yes\nd: no")
    assert result['a'] is True
    assert result['b'] is False
    assert result['c'] is True
    assert result['d'] is False


def test_parse_yaml_null():
    result = parse_yaml("a: null\nb: ~")
    assert result['a'] is None
    assert result['b'] is None


def test_parse_yaml_quoted_strings():
    result = parse_yaml('name: "hello world"\npath: \'C:/roms\'')
    assert result['name'] == 'hello world'
    assert result['path'] == 'C:/roms'


def test_parse_yaml_lists():
    result = parse_yaml("items:\n  - one\n  - two\n  - three")
    assert result['items'] == ['one', 'two', 'three']


def test_parse_yaml_comments():
    result = parse_yaml("name: hello  # a comment\n# full line comment\ncount: 5")
    assert result['name'] == 'hello'
    assert result['count'] == 5


def test_parse_yaml_floats():
    result = parse_yaml("score: 3.14")
    assert result['score'] == 3.14


def test_parse_yaml_empty():
    result = parse_yaml("")
    assert result == {}


# --- Config dataclass tests ---

def test_config_defaults():
    config = Config()
    assert config.sources == []
    assert config.destination is None
    assert config.selection.english_only is False
    assert config.selection.region_priority == [
        'USA', 'World', 'Europe', 'Australia', 'England', 'Spain',
        'France', 'Germany', 'Italy', 'Netherlands', 'Sweden',
        'Asia', 'Japan', 'Korea', 'China', 'Taiwan', 'Brazil'
    ]
    assert config.network.auto_tune is True
    assert config.network.scan_workers == 16
    assert config.output.transfer_mode == 'move'
    assert config.theme.mode == 'dark'
    assert config.theme.accent == '#e94560'


def test_config_from_dict():
    config = Config.from_dict({
        'sources': ['https://example.com/roms/'],
        'destination': '/tmp/roms',
        'selection': {'english_only': True},
        'output': {'transfer_mode': 'copy'},
    })
    assert config.sources == ['https://example.com/roms/']
    assert config.destination == '/tmp/roms'
    assert config.selection.english_only is True
    assert config.output.transfer_mode == 'copy'
    # Unset fields keep defaults
    assert config.network.auto_tune is True


def test_config_to_dict():
    config = Config()
    config.sources = ['https://example.com/roms/']
    d = config.to_dict()
    assert d['sources'] == ['https://example.com/roms/']
    assert d['selection']['english_only'] is False


def test_config_round_trip():
    """Config -> dict -> Config should preserve all values."""
    original = Config()
    original.sources = ['https://example.com/']
    original.selection.english_only = True
    original.theme.accent = '#ff0000'

    restored = Config.from_dict(original.to_dict())
    assert restored.sources == original.sources
    assert restored.selection.english_only is True
    assert restored.theme.accent == '#ff0000'


# --- File I/O tests ---

def test_save_and_load_yaml():
    config = Config()
    config.sources = ['https://example.com/']
    config.selection.english_only = True

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'config.yaml'
        save_config(config, path)
        assert path.exists()

        loaded = load_config(path)
        assert loaded.sources == ['https://example.com/']
        assert loaded.selection.english_only is True


def test_load_config_missing_file():
    loaded = load_config(Path('/nonexistent/config.yaml'))
    assert isinstance(loaded, Config)  # Returns defaults


def test_load_json_config():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'config.json'
        path.write_text(json.dumps({
            'sources': ['/local/roms'],
            'selection': {'english_only': True},
        }))
        loaded = load_config(path)
        assert loaded.sources == ['/local/roms']
        assert loaded.selection.english_only is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_v2_config.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write implementation**

Create `retro_refiner/config.py`:

```python
"""Configuration management for Retro-Refiner.

Provides:
- parse_yaml(): Built-in YAML parser (no external dependency)
- Config dataclass: Structured configuration with nested sections
- load_config() / save_config(): File I/O for YAML and JSON configs
"""
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


# --- YAML Parser (no external dependency) ---

def parse_yaml(content: str) -> dict:
    """Parse a simple YAML subset: key-value pairs, lists, comments.

    Supports: strings, booleans, integers, floats, lists, null.
    Does NOT support: nested objects, anchors, multi-line strings.
    """
    result = {}
    current_key = None
    current_list = None

    for line in content.split('\n'):
        # Remove inline comments (preserve # in quoted strings)
        if '#' in line:
            in_quote = False
            quote_char = None
            for i, char in enumerate(line):
                if char in ('"', "'") and (i == 0 or line[i - 1] != '\\'):
                    if not in_quote:
                        in_quote = True
                        quote_char = char
                    elif char == quote_char:
                        in_quote = False
                elif char == '#' and not in_quote:
                    line = line[:i]
                    break

        stripped = line.rstrip()
        if not stripped:
            continue

        # List item (- value)
        if stripped.lstrip().startswith('- '):
            if current_key and current_list is not None:
                item = stripped.lstrip()[2:].strip()
                current_list.append(_parse_yaml_value(item))
            continue

        # Close open list if line is not indented
        if not line.startswith(' ') and not line.startswith('\t'):
            if current_key and current_list is not None:
                result[current_key] = current_list
                current_list = None
                current_key = None

        # Key: value pair
        if ':' in stripped:
            colon_idx = stripped.index(':')
            key = stripped[:colon_idx].strip()
            value_part = stripped[colon_idx + 1:].strip()

            if not key:
                continue

            if value_part == '':
                current_key = key
                current_list = []
            else:
                result[key] = _parse_yaml_value(value_part)
                current_key = None
                current_list = None

    # Close any remaining open list
    if current_key and current_list is not None:
        result[current_key] = current_list

    return result


def _parse_yaml_value(value: str):
    """Parse a YAML value into a Python type."""
    if not value:
        return None

    # Remove quotes
    if (value.startswith('"') and value.endswith('"')) or \
       (value.startswith("'") and value.endswith("'")):
        return value[1:-1]

    # Booleans
    if value.lower() in ('true', 'yes', 'on'):
        return True
    if value.lower() in ('false', 'no', 'off'):
        return False

    # Null
    if value.lower() in ('null', '~', ''):
        return None

    # Numbers
    try:
        if '.' in value:
            return float(value)
        return int(value)
    except ValueError:
        pass

    return value


def _dump_yaml_value(value) -> str:
    """Serialize a Python value to YAML string."""
    if value is None:
        return 'null'
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, str):
        if any(c in value for c in ':#{}[],"\'') or value in ('true', 'false', 'null', '~'):
            return f'"{value}"'
        return value
    return str(value)


# --- Config Dataclass ---

DEFAULT_REGION_PRIORITY = [
    'USA', 'World', 'Europe', 'Australia', 'England', 'Spain',
    'France', 'Germany', 'Italy', 'Netherlands', 'Sweden',
    'Asia', 'Japan', 'Korea', 'China', 'Taiwan', 'Brazil',
]


@dataclass
class SelectionConfig:
    english_only: bool = False
    exclude_protos: bool = False
    include_betas: bool = False
    include_unlicensed: bool = False
    region_priority: List[str] = field(default_factory=lambda: list(DEFAULT_REGION_PRIORITY))
    keep_regions: Optional[str] = None
    include_patterns: List[str] = field(default_factory=list)
    exclude_patterns: List[str] = field(default_factory=list)
    all_roms: bool = False
    verbose: bool = False
    genres: Optional[str] = None
    year_from: Optional[int] = None
    year_to: Optional[int] = None


@dataclass
class BudgetConfig:
    top: Optional[str] = None
    limit: Optional[int] = None
    size: Optional[str] = None
    include_unrated: bool = False
    prefer_exclusives: Optional[float] = None


@dataclass
class NetworkConfig:
    parallel: int = 4
    connections: Optional[int] = None
    auto_tune: bool = True
    scan_workers: int = 16
    resume_downloads: bool = False


@dataclass
class OutputConfig:
    transfer_mode: str = 'move'
    flat: bool = False
    playlists: bool = False
    gamelist: bool = False
    retroarch_playlists: Optional[str] = None
    prefer_source: Optional[str] = None
    print_roms: bool = False


@dataclass
class AdvancedConfig:
    no_verify: bool = False
    no_cache: bool = False
    no_dat: bool = False
    no_chd: bool = False
    no_adult: bool = False
    mame_version: Optional[str] = None
    recursive: bool = False
    max_depth: int = 3
    cache_dir: Optional[str] = None
    dat_dir: Optional[str] = None
    log_dir: Optional[str] = None
    tp_include_platforms: Optional[str] = None
    tp_exclude_platforms: Optional[str] = None
    tp_all_versions: bool = False
    ratings_source: str = 'combined'


@dataclass
class ThemeConfig:
    mode: str = 'dark'
    accent: str = '#e94560'


@dataclass
class AuthConfig:
    ia_access_key: Optional[str] = None
    ia_secret_key: Optional[str] = None
    igdb_client_id: Optional[str] = None
    igdb_client_secret: Optional[str] = None


@dataclass
class DeduperConfig:
    priority: Optional[str] = None
    pc_lists: List[str] = field(default_factory=list)
    delete: bool = False


@dataclass
class Config:
    """Top-level configuration for Retro-Refiner."""
    sources: List[str] = field(default_factory=list)
    destination: Optional[str] = None
    systems: Optional[List[str]] = None
    selection: SelectionConfig = field(default_factory=SelectionConfig)
    budget: BudgetConfig = field(default_factory=BudgetConfig)
    network: NetworkConfig = field(default_factory=NetworkConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    advanced: AdvancedConfig = field(default_factory=AdvancedConfig)
    theme: ThemeConfig = field(default_factory=ThemeConfig)
    auth: AuthConfig = field(default_factory=AuthConfig)
    dedup: DeduperConfig = field(default_factory=DeduperConfig)

    @classmethod
    def from_dict(cls, d: dict) -> 'Config':
        """Create Config from a flat or nested dictionary."""
        c = cls()
        if 'sources' in d:
            c.sources = d['sources'] if isinstance(d['sources'], list) else [d['sources']]
        if 'destination' in d:
            c.destination = d['destination']
        if 'systems' in d:
            c.systems = d['systems']

        # Nested sections
        for section_name, section_cls in [
            ('selection', SelectionConfig),
            ('budget', BudgetConfig),
            ('network', NetworkConfig),
            ('output', OutputConfig),
            ('advanced', AdvancedConfig),
            ('theme', ThemeConfig),
            ('auth', AuthConfig),
            ('dedup', DeduperConfig),
        ]:
            section_dict = d.get(section_name, {})
            if isinstance(section_dict, dict):
                section = getattr(c, section_name)
                for key, value in section_dict.items():
                    if hasattr(section, key):
                        setattr(section, key, value)
        return c

    def to_dict(self) -> dict:
        """Serialize Config to a nested dictionary."""
        from dataclasses import asdict
        return asdict(self)


# --- File I/O ---

def load_config(path: Path) -> Config:
    """Load configuration from a YAML or JSON file.

    Returns default Config if file doesn't exist or can't be parsed.
    """
    if not path.exists():
        return Config()

    try:
        content = path.read_text(encoding='utf-8')
    except IOError:
        return Config()

    if path.suffix.lower() in ('.yaml', '.yml'):
        try:
            raw = parse_yaml(content)
        except Exception:
            return Config()
    elif path.suffix.lower() == '.json':
        try:
            raw = json.loads(content)
        except (json.JSONDecodeError, ValueError):
            return Config()
    else:
        # Try YAML then JSON
        try:
            raw = parse_yaml(content)
        except Exception:
            try:
                raw = json.loads(content)
            except Exception:
                return Config()

    return Config.from_dict(raw) if raw else Config()


def save_config(config: Config, path: Path):
    """Save configuration to a YAML file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    d = config.to_dict()
    lines = ['# Retro-Refiner Configuration\n']

    # Top-level simple fields
    if d.get('sources'):
        lines.append('sources:')
        for src in d['sources']:
            lines.append(f'  - "{src}"')
    if d.get('destination'):
        lines.append(f'destination: "{d["destination"]}"')
    if d.get('systems'):
        lines.append('systems:')
        for sys_name in d['systems']:
            lines.append(f'  - {sys_name}')

    # Nested sections
    for section_name in ('selection', 'budget', 'network', 'output', 'advanced', 'theme', 'auth', 'dedup'):
        section = d.get(section_name, {})
        # Skip sections that are all defaults
        non_none = {k: v for k, v in section.items() if v is not None}
        if not non_none:
            continue
        lines.append(f'\n{section_name}:')
        for key, value in section.items():
            if isinstance(value, list):
                if value:
                    lines.append(f'  {key}:')
                    for item in value:
                        lines.append(f'    - {_dump_yaml_value(item)}')
            else:
                lines.append(f'  {key}: {_dump_yaml_value(value)}')

    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_v2_config.py -v`
Expected: All passed

- [ ] **Step 5: Run existing tests to verify nothing is broken**

Run: `python tests/test_selection.py 2>&1 | tail -3`
Expected: `Results: 300/300 passed`

- [ ] **Step 6: Commit**

```bash
git add retro_refiner/config.py tests/test_v2_config.py
git commit -m "feat(v2): extract config module with Config dataclass and YAML parser"
```

---

## Chunk 4: Integration Verification

### Task 5: Verify all modules work together

**Files:**
- Create: `tests/test_v2_integration.py`

- [ ] **Step 1: Write integration test**

Create `tests/test_v2_integration.py`:

```python
"""Integration tests: verify v2 modules work together."""
from pathlib import Path
from retro_refiner import __version__
from retro_refiner.paths import get_base_path, get_runtime_path
from retro_refiner.systems import load_system_data, reset_cache
from retro_refiner.config import Config, load_config, save_config
import tempfile


def test_version_exists():
    assert __version__ == "dev"


def test_systems_uses_paths():
    """SystemData loads from the path provided by paths module."""
    reset_cache()
    data = load_system_data()
    assert len(data.known_systems) > 100


def test_config_round_trip_to_disk():
    """Config saves to YAML and loads back identically."""
    config = Config()
    config.sources = ['https://myrient.erista.me/files/Redump/Sega%20-%20Saturn/']
    config.selection.english_only = True
    config.selection.region_priority = ['USA', 'Japan']
    config.output.transfer_mode = 'move'
    config.theme.accent = '#00ff00'

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'test.yaml'
        save_config(config, path)
        loaded = load_config(path)

        assert loaded.sources == config.sources
        assert loaded.selection.english_only is True
        assert loaded.selection.region_priority == ['USA', 'Japan']
        assert loaded.output.transfer_mode == 'move'
        assert loaded.theme.accent == '#00ff00'


def test_old_tests_still_pass():
    """Marker: run the old test suite to confirm no regressions."""
    # This is a reminder — run manually:
    # python tests/test_selection.py
    pass
```

- [ ] **Step 2: Run all v2 tests**

Run: `python -m pytest tests/test_v2_*.py -v`
Expected: All passed

- [ ] **Step 3: Run old tests to confirm no regressions**

Run: `python tests/test_selection.py 2>&1 | tail -3`
Expected: `Results: 300/300 passed`

- [ ] **Step 4: Run pylint on new modules**

Run: `python -m pylint retro_refiner/ --disable=C0114,C0115,C0116`
Expected: 10.00/10 (disable missing-docstring for dataclass fields)

- [ ] **Step 5: Commit**

```bash
git add tests/test_v2_integration.py
git commit -m "test(v2): add integration tests for scaffold modules"
```

---

## Summary

After completing this sub-project, we have:

- `retro_refiner/` package with `__init__.py`, `paths.py`, `systems.py`, `config.py`
- `SystemData` dataclass replacing module-level globals
- `Config` dataclass with nested sections matching the v2 config format
- Built-in YAML parser (extracted from monolith)
- Full test coverage for all new modules
- Old tests still passing (no regressions)
- All work on the `v2-rewrite` branch

**Next sub-project:** Extract scanner, filter, dat, and network modules from the monolith.

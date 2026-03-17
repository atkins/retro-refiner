"""Configuration dataclass and YAML parser for Retro-Refiner."""

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional


# =============================================================================
# YAML Parser
# =============================================================================

def _parse_yaml_value(value: str):
    """Parse a YAML value into Python type."""
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

    # Plain string
    return value


def _strip_comment(line: str) -> str:
    """Remove inline comments while preserving # inside quoted strings."""
    if '#' not in line:
        return line
    in_quote = False
    quote_char = None
    for i, char in enumerate(line):
        if char in ('"', "'") and (i == 0 or line[i-1] != '\\'):
            if not in_quote:
                in_quote = True
                quote_char = char
            elif char == quote_char:
                in_quote = False
        elif char == '#' and not in_quote:
            return line[:i]
    return line


def _indent_level(line: str) -> int:
    """Return the number of leading whitespace characters."""
    return len(line) - len(line.lstrip())


def parse_yaml(content: str) -> dict:
    """
    Parse a simple YAML subset: key-value pairs, lists, comments,
    and one level of nesting (sections with indented key-value pairs
    that may themselves contain lists).
    Does NOT support: deeply nested objects, anchors, multi-line strings.
    """
    result = {}
    # section_key is the top-level key whose value is being built as a
    # dict or list.  sub_key is the key within a section dict that is
    # currently accumulating list items.
    section_key = None
    section_value = None   # list | dict | None
    sub_key = None         # key inside section_value awaiting list items
    sub_list = None        # the list being built for sub_key

    def _flush_sub():
        """Flush any pending sub-list into section_value[sub_key]."""
        nonlocal sub_key, sub_list
        if sub_key is not None and sub_list is not None \
                and isinstance(section_value, dict):
            section_value[sub_key] = sub_list
        sub_key = None
        sub_list = None

    def _flush_section():
        """Flush the current section into result."""
        nonlocal section_key, section_value
        _flush_sub()
        if section_key is not None and section_value is not None:
            result[section_key] = section_value
        section_key = None
        section_value = None

    for line in content.split('\n'):
        line = _strip_comment(line)
        stripped = line.rstrip()
        if not stripped:
            continue

        indent = _indent_level(line)
        lstripped = stripped.lstrip()

        # --- List item -----------------------------------------------
        if lstripped.startswith('- '):
            item = lstripped[2:].strip()
            if section_key is not None:
                if sub_key is not None and sub_list is not None:
                    # List item for a sub-key inside a section dict
                    sub_list.append(_parse_yaml_value(item))
                elif isinstance(section_value, list):
                    # Top-level list under section_key
                    section_value.append(_parse_yaml_value(item))
            continue

        # --- Non-indented line: close section ------------------------
        if indent == 0:
            _flush_section()

        # --- Key: value pair -----------------------------------------
        if ':' in stripped:
            colon_idx = stripped.index(':')
            key = stripped[:colon_idx].strip()
            value_part = stripped[colon_idx + 1:].strip()
            if not key:
                continue

            if indent > 0 and section_key is not None:
                # Inside a section
                if isinstance(section_value, list) and not section_value:
                    # First indented key: section is a mapping, not a list
                    section_value = {}
                if isinstance(section_value, dict):
                    _flush_sub()
                    if value_part == '':
                        # Sub-key that may start a list
                        sub_key = key
                        sub_list = []
                    else:
                        section_value[key] = _parse_yaml_value(value_part)
                continue

            # Top-level key
            if value_part == '':
                section_key = key
                section_value = []
            else:
                result[key] = _parse_yaml_value(value_part)

    _flush_section()
    return result


def _dump_yaml_value(value) -> str:
    """Serialize a Python value to a YAML string."""
    if value is None:
        return 'null'
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        # Quote strings that contain special characters
        needs_quoting = False
        if not value:
            needs_quoting = True
        elif value.lower() in ('true', 'false', 'yes', 'no', 'on', 'off',
                                'null', '~'):
            needs_quoting = True
        elif '#' in value or ':' in value or value != value.strip():
            needs_quoting = True
        else:
            try:
                float(value)
                needs_quoting = True
            except ValueError:
                pass
        if needs_quoting:
            escaped = value.replace('"', '\\"')
            return f'"{escaped}"'
        return value
    return str(value)


# =============================================================================
# Default Region Priority
# =============================================================================

DEFAULT_REGION_PRIORITY = [
    'USA', 'World', 'Europe', 'Australia', 'England', 'Spain',
    'France', 'Germany', 'Italy', 'Netherlands', 'Sweden',
    'Asia', 'Japan', 'Korea', 'China', 'Taiwan', 'Brazil',
]


# =============================================================================
# Config Dataclasses
# =============================================================================

@dataclass
class SelectionConfig:
    """ROM selection filtering options."""
    english_only: bool = False
    exclude_protos: bool = False
    include_betas: bool = False
    include_unlicensed: bool = False
    region_priority: List[str] = field(
        default_factory=lambda: list(DEFAULT_REGION_PRIORITY))
    keep_regions: Optional[str] = None
    include_patterns: List[str] = field(default_factory=list)
    exclude_patterns: List[str] = field(default_factory=list)
    all_roms: bool = False
    best_version: bool = False
    verbose: bool = False
    genres: Optional[str] = None
    year_from: Optional[int] = None
    year_to: Optional[int] = None


@dataclass
class BudgetConfig:
    """Budget / top-N filtering options."""
    top: Optional[str] = None
    limit: Optional[int] = None
    size: Optional[str] = None
    include_unrated: bool = False
    prefer_exclusives: Optional[float] = None


@dataclass
class NetworkConfig:
    """Network download options."""
    parallel: int = 4
    connections: Optional[int] = None
    auto_tune: bool = True
    scan_workers: int = 16
    resume_downloads: bool = False


@dataclass
class OutputConfig:
    """Output and transfer options."""
    transfer_mode: str = 'move'
    flat: bool = False
    playlists: bool = False
    gamelist: bool = False
    retroarch_playlists: Optional[str] = None
    prefer_source: Optional[str] = None
    print_roms: bool = False


@dataclass
class AdvancedConfig:
    """Advanced options."""
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
    """Theme options."""
    mode: str = 'dark'
    accent: str = '#e94560'


@dataclass
class AuthConfig:
    """Authentication credentials."""
    ia_access_key: Optional[str] = None
    ia_secret_key: Optional[str] = None
    igdb_client_id: Optional[str] = None
    igdb_client_secret: Optional[str] = None


@dataclass
class DeduplicationConfig:
    """Deduplication options."""
    priority: Optional[str] = None
    pc_lists: List[str] = field(default_factory=list)
    delete: bool = False


@dataclass
class Config:
    """Top-level configuration."""
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
    deduplication: DeduplicationConfig = field(
        default_factory=DeduplicationConfig)

    # Map of section name -> dataclass type for from_dict
    SECTION_TYPES = {
        'selection': SelectionConfig,
        'budget': BudgetConfig,
        'network': NetworkConfig,
        'output': OutputConfig,
        'advanced': AdvancedConfig,
        'theme': ThemeConfig,
        'auth': AuthConfig,
        'deduplication': DeduplicationConfig,
    }

    @classmethod
    def from_dict(cls, data: dict) -> 'Config':
        """Create a Config from a nested dict, applying values to matching
        fields. Unknown keys are ignored. Missing keys keep defaults."""
        kwargs = {}
        # Accept legacy 'dedup' key as alias for 'deduplication'
        if 'dedup' in data and 'deduplication' not in data:
            data['deduplication'] = data.pop('dedup')
        for key, value in data.items():
            if key in cls.SECTION_TYPES and isinstance(value, dict):
                section_cls = cls.SECTION_TYPES[key]
                # Only pass keys that are valid fields
                valid = {k: v for k, v in value.items()
                         if k in {f.name for f in
                                  section_cls.__dataclass_fields__.values()}}
                kwargs[key] = section_cls(**valid)
            elif key in ('sources', 'destination', 'systems'):
                kwargs[key] = value
        return cls(**kwargs)

    def to_dict(self) -> dict:
        """Serialize to a nested dict."""
        return asdict(self)


# =============================================================================
# File I/O
# =============================================================================

def load_config(path: Path) -> Config:
    """Load a Config from a YAML or JSON file.

    Returns a default Config if the file is missing or cannot be parsed.
    """
    if not path.exists():
        return Config()

    try:
        text = path.read_text(encoding='utf-8')
    except OSError:
        return Config()

    try:
        if path.suffix.lower() == '.json':
            data = json.loads(text)
        else:
            data = parse_yaml(text)
    except (json.JSONDecodeError, ValueError):
        return Config()

    if not isinstance(data, dict):
        return Config()

    return Config.from_dict(data)


def _write_yaml_section(lines: list, section_name: str, section_dict: dict,
                         comment: str = ''):
    """Write a YAML section with optional comment header."""
    if comment:
        lines.append(f'# {comment}')
    lines.append(f'{section_name}:')
    for key, value in section_dict.items():
        if isinstance(value, list):
            lines.append(f'  {key}:')
            for item in value:
                lines.append(f'    - {_dump_yaml_value(item)}')
        else:
            lines.append(f'  {key}: {_dump_yaml_value(value)}')
    lines.append('')


def save_config(config: Config, path: Path) -> None:
    """Save a Config to a YAML file with section comments."""
    data = config.to_dict()
    lines = ['# Retro-Refiner configuration', '']

    # Top-level scalar fields
    top_keys = ('sources', 'destination', 'systems')
    for key in top_keys:
        value = data.get(key)
        if isinstance(value, list):
            lines.append(f'{key}:')
            for item in value:
                lines.append(f'  - {_dump_yaml_value(item)}')
        else:
            lines.append(f'{key}: {_dump_yaml_value(value)}')
    lines.append('')

    section_comments = {
        'selection': 'ROM selection',
        'budget': 'Budget / top-N filtering',
        'network': 'Network options',
        'output': 'Output and transfer',
        'advanced': 'Advanced options',
        'theme': 'Theme',
        'auth': 'Authentication',
        'deduplication': 'Deduplication',
    }

    for section_name in Config.SECTION_TYPES:
        section_data = data.get(section_name, {})
        comment = section_comments.get(section_name, '')
        _write_yaml_section(lines, section_name, section_data, comment)

    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')


# =============================================================================
# Legacy compatibility shim
# =============================================================================

def apply_config_to_args(args, config: dict):
    """Apply config dict settings to an argparse Namespace.

    CLI args take precedence: only applies config values when the
    corresponding arg is None, False, or an empty list.

    This is a compatibility shim for tests that used the monolith's
    apply_config_to_args.  New code should use Config.from_dict() instead.
    """
    config_map = {
        'source': 'source', 'dest': 'dest', 'systems': 'systems',
        'region_priority': 'region_priority', 'keep_regions': 'keep_regions',
        'include': 'include', 'exclude': 'exclude',
        'exclude_protos': 'exclude_protos',
        'include_betas': 'include_betas',
        'include_unlicensed': 'include_unlicensed',
        'english_only': 'english_only', 'genres': 'genres',
        'year_from': 'year_from', 'year_to': 'year_to',
        'flat': 'flat', 'link': 'link', 'hardlink': 'hardlink',
        'move': 'move', 'playlists': 'playlists', 'gamelist': 'gamelist',
        'retroarch_playlists': 'retroarch_playlists',
        'prefer_source': 'prefer_source', 'no_verify': 'no_verify',
        'no_cache': 'no_cache', 'no_dat': 'no_dat',
        'update_dats': 'update_dats', 'no_chd': 'no_chd',
        'no_adult': 'no_adult', 'verbose': 'verbose',
        'mame_version': 'mame_version', 'dat_dir': 'dat_dir',
        'cache_dir': 'cache_dir', 'log_dir': 'log_dir', 'yes': 'yes',
        'tp_include_platforms': 'tp_include_platforms',
        'tp_exclude_platforms': 'tp_exclude_platforms',
        'tp_all_versions': 'tp_all_versions',
        'parallel': 'parallel', 'connections': 'connections',
        'scan_workers': 'scan_workers',
        'recursive': 'recursive', 'max_depth': 'max_depth',
        'top': 'top', 'include_unrated': 'include_unrated',
        'limit': 'limit', 'size': 'size', 'all': 'all',
        'prefer_exclusives': 'prefer_exclusives',
        'dedupe_priority': 'dedupe_priority',
        'dedupe_pc_lists': 'dedupe_pc_lists',
        'dedupe_delete': 'dedupe_delete',
        'igdb_client_id': 'igdb_client_id',
        'igdb_client_secret': 'igdb_client_secret',
        'ratings_source': 'ratings_source',
    }

    for config_key, arg_name in config_map.items():
        if config_key in config:
            current_value = getattr(args, arg_name, None)
            if current_value is None or current_value is False \
                    or current_value == []:
                value = config[config_key]
                if config_key in ('top', 'size') and value is not None:
                    value = str(value)
                setattr(args, arg_name, value)

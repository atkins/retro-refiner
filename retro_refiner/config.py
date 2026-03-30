"""Configuration dataclass and YAML parser for Retro-Refiner."""

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional

import yaml


def parse_yaml(content: str) -> dict:
    """Parse YAML content into a dict using PyYAML."""
    try:
        result = yaml.safe_load(content)
    except yaml.YAMLError:
        # Windows backslashes in double-quoted strings cause YAML escape
        # errors (e.g. \U interpreted as unicode escape).  Replace only
        # unescaped backslashes (not already doubled) so we don't corrupt
        # intentional escape sequences.
        import re  # pylint: disable=import-outside-toplevel
        escaped = re.sub(r'(?<!\\)\\(?!\\)', r'\\\\', content)
        result = yaml.safe_load(escaped)
    return result if isinstance(result, dict) else {}




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
    scan_workers: int = 16


@dataclass
class OutputConfig:
    """Output and transfer options."""
    local_file_action: str = 'copy'
    flat: bool = False
    playlists: bool = False
    gamelist: Optional[str] = None
    retroarch_playlists: Optional[str] = None
    prefer_source: Optional[str] = None
    print_roms: bool = False
    validate_destination: bool = True
    clean_destination: bool = False
    crc_validation: bool = False


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
    tp_include_platforms: Optional[str] = None
    tp_exclude_platforms: Optional[str] = None
    tp_all_versions: bool = False
    ratings_source: str = 'combined'


@dataclass
class ThemeConfig:
    """Theme options."""
    mode: str = 'midnight-terminal'
    accent: str = '#e94560'


@dataclass
class AuthConfig:
    """Authentication credentials."""
    ia_access_key: Optional[str] = None
    ia_secret_key: Optional[str] = None
    igdb_client_id: Optional[str] = None
    igdb_client_secret: Optional[str] = None


@dataclass
class WindowConfig:
    """Window geometry and UI state (saved/restored automatically)."""
    x: Optional[int] = None
    y: Optional[int] = None
    width: int = 1200
    height: int = 800
    section_states: Dict[str, bool] = field(default_factory=dict)


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
    source_settings: Dict[str, dict] = field(default_factory=dict)
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
    window: WindowConfig = field(default_factory=WindowConfig)

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
        'window': WindowConfig,
    }

    @classmethod
    def from_dict(cls, data: dict) -> 'Config':
        """Create a Config from a nested dict, applying values to matching
        fields. Unknown keys are ignored. Missing keys keep defaults."""
        kwargs = {}
        for key, value in data.items():
            if key in cls.SECTION_TYPES and isinstance(value, dict):
                section_cls = cls.SECTION_TYPES[key]
                valid = {k: v for k, v in value.items()
                         if k in {f.name for f in
                                  section_cls.__dataclass_fields__.values()}}
                kwargs[key] = section_cls(**valid)
            elif key in ('sources', 'source_settings', 'destination', 'systems'):
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


def save_config(config: Config, path: Path) -> None:
    """Save a Config to a YAML file."""
    data = config.to_dict()
    content = '# Retro-Refiner configuration\n\n'
    content += yaml.dump(data, default_flow_style=False, sort_keys=False,
                         allow_unicode=True)
    path.write_text(content, encoding='utf-8')

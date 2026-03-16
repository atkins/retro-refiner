"""Structured result types for the v2 API.

These replace the monolith's print-based output with data objects
that the UI can render directly.
"""
from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class ProgressEvent:
    """Progress update from a long-running operation."""
    phase: str           # "fetching", "scanning", "filtering", "downloading", "complete"
    message: str = ""
    current: int = 0
    total: int = 0
    system: str = ""


@dataclass
class ExcludedRom:
    """A ROM that was filtered out, with the reason."""
    filename: str
    reason: str
    size: int = 0
    region: str = ""


@dataclass
class FilterStats:
    """Statistics from a filtering operation."""
    source_count: int = 0
    selected_count: int = 0
    excluded_count: int = 0
    source_size: int = 0
    selected_size: int = 0
    dat_matched: int = 0
    filter_breakdown: Dict[str, int] = field(default_factory=dict)


@dataclass
class FilterResult:
    """Result of filtering ROMs for one system."""
    system: str
    selected: list = field(default_factory=list)
    excluded: List[ExcludedRom] = field(default_factory=list)
    stats: FilterStats = field(default_factory=FilterStats)
    size_info: Dict[str, int] = field(default_factory=dict)


@dataclass
class ScanResult:
    """Result of scanning a network source."""
    url_dict: Dict[str, List[str]] = field(default_factory=dict)
    url_sizes: Dict[str, int] = field(default_factory=dict)


@dataclass
class SystemScanInfo:
    """Info about one system discovered during scanning."""
    system: str
    file_count: int
    total_size: int
    source_type: str  # "local" or "network"

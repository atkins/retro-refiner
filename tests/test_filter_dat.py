#!/usr/bin/env python3
"""Comprehensive tests for filter.py and dat.py coverage gaps.

Covers:
- filter_roms_from_files() — local file filtering with all options
- _collect_sibling_discs() — multi-disc edge cases
- matches_patterns() — glob pattern matching
- select_best_rom() — edge cases with region priorities
- filter_network_roms() — filter_breakdown / ExcludedRom population
- parse_logiqx_xml_dat() — complex XML with multiple ROMs per game
- parse_clrmamepro_dat() — complex multi-game input
- load_all_system_dats() — merging multiple DAT files
- CRC cache round-trip (load_crc_cache / save_crc_cache / get_cached_crc)
- calculate_crc32_from_zip() — CRC of first file inside a ZIP
- detect_dat_region() — additional edge cases
- Title mapping edge cases
- normalize_title() — accent stripping, edge cases
"""

import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from retro_refiner.filter import (  # pylint: disable=wrong-import-position
    select_best_rom,
    matches_patterns,
    filter_network_roms,
    filter_roms_from_files,
    _collect_sibling_discs,
    get_file_size,
)
from retro_refiner.dat import (  # pylint: disable=wrong-import-position
    RomInfo,
    DatRomEntry,
    normalize_title,
    normalize_title_for_dedupe,
    parse_dat_file,
    parse_logiqx_xml_dat,
    parse_clrmamepro_dat,
    load_all_system_dats,
    load_crc_cache,
    save_crc_cache,
    get_cached_crc,
    calculate_crc32,
    calculate_crc32_from_zip,
    detect_dat_region,
    load_title_mappings,
    reset_title_mappings_cache,
)
from retro_refiner.config import Config, SelectionConfig  # pylint: disable=wrong-import-position


# =============================================================================
# Helpers
# =============================================================================

def _make_rom_info(filename, base_title, region="USA", **kwargs):
    """Helper to build a RomInfo with sensible defaults."""
    defaults = dict(
        revision=0, is_english=True, is_translation=False,
        is_beta=False, is_demo=False, is_promo=False, is_sample=False,
        is_proto=False, is_bios=False, is_pirate=False, is_unlicensed=False,
        is_homebrew=False, is_rerelease=False, is_compilation=False,
        is_lock_on=False,
    )
    defaults.update(kwargs)
    return RomInfo(filename=filename, base_title=base_title,
                   region=region, **defaults)


def _make_local_roms(tmp_path, filenames, content=b'\x00' * 100):
    """Create dummy ROM files and return list of Path objects."""
    paths = []
    for fn in filenames:
        p = tmp_path / fn
        p.write_bytes(content)
        paths.append(p)
    return paths


def _make_zip_rom(tmp_path, zip_name, inner_name, inner_content):
    """Create a real .zip file containing a single file."""
    zip_path = tmp_path / zip_name
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(inner_name, inner_content)
    return zip_path


# =============================================================================
# filter_roms_from_files — Basic Filtering
# =============================================================================

class TestFilterRomsFromFilesBasic:
    """Basic filter_roms_from_files behavior."""

    def test_dry_run_returns_selected_and_sizes(self, tmp_path):
        roms = _make_local_roms(tmp_path, [
            "Mario (USA).zip", "Zelda (USA).zip",
        ])
        selected, info = filter_roms_from_files(
            roms, str(tmp_path / "dest"), "nes",
            dry_run=True, best_version=True,
        )
        assert len(selected) == 2
        assert "source_size" in info
        assert "selected_size" in info
        assert "rom_sizes" in info

    def test_dry_run_does_not_create_dest(self, tmp_path):
        roms = _make_local_roms(tmp_path, ["Mario (USA).zip"])
        dest = tmp_path / "dest_no_create"
        filter_roms_from_files(
            roms, str(dest), "nes", dry_run=True, best_version=True,
        )
        assert not dest.exists()

    def test_non_dry_run_creates_dest_and_copies(self, tmp_path):
        rom_dir = tmp_path / "roms"
        rom_dir.mkdir()
        roms = _make_local_roms(rom_dir, ["Mario (USA).zip"])
        dest = tmp_path / "dest"
        filter_roms_from_files(
            roms, str(dest), "nes", dry_run=False,
            best_version=True, transfer_mode='copy',
        )
        assert (dest / "nes" / "Mario (USA).zip").exists()

    def test_flat_output_no_system_subdir(self, tmp_path):
        rom_dir = tmp_path / "roms"
        rom_dir.mkdir()
        roms = _make_local_roms(rom_dir, ["Mario (USA).zip"])
        dest = tmp_path / "dest"
        filter_roms_from_files(
            roms, str(dest), "nes", dry_run=False,
            best_version=True, flat_output=True, transfer_mode='copy',
        )
        assert (dest / "Mario (USA).zip").exists()
        assert not (dest / "nes").exists()

    def test_empty_rom_list(self, tmp_path):
        selected, info = filter_roms_from_files(
            [], str(tmp_path / "dest"), "nes",
            dry_run=True, best_version=True,
        )
        assert len(selected) == 0
        assert info["source_size"] == 0


# =============================================================================
# filter_roms_from_files — 1G1R Selection
# =============================================================================

class TestFilterRomsFromFiles1G1R:
    """1G1R best-version selection from local files."""

    def test_selects_usa_over_japan(self, tmp_path):
        roms = _make_local_roms(tmp_path, [
            "Mario (USA).zip", "Mario (Japan).zip",
        ])
        selected, _ = filter_roms_from_files(
            roms, str(tmp_path / "dest"), "nes",
            dry_run=True, best_version=True,
        )
        names = {r.filename for r in selected}
        assert "Mario (USA).zip" in names
        assert "Mario (Japan).zip" not in names

    def test_selects_highest_revision(self, tmp_path):
        roms = _make_local_roms(tmp_path, [
            "Mario (USA).zip", "Mario (USA) (Rev 1).zip",
        ])
        selected, _ = filter_roms_from_files(
            roms, str(tmp_path / "dest"), "nes",
            dry_run=True, best_version=True,
        )
        names = {r.filename for r in selected}
        assert "Mario (USA) (Rev 1).zip" in names
        assert len(names) == 1

    def test_groups_normalize_title(self, tmp_path):
        roms = _make_local_roms(tmp_path, [
            "Super Mario Bros (USA).zip",
            "Super Mario Bros (Europe).zip",
        ])
        selected, _ = filter_roms_from_files(
            roms, str(tmp_path / "dest"), "nes",
            dry_run=True, best_version=True,
        )
        assert len(selected) == 1
        assert selected[0].region == "USA"

    def test_different_games_both_selected(self, tmp_path):
        roms = _make_local_roms(tmp_path, [
            "Mario (USA).zip", "Zelda (USA).zip",
        ])
        selected, _ = filter_roms_from_files(
            roms, str(tmp_path / "dest"), "nes",
            dry_run=True, best_version=True,
        )
        assert len(selected) == 2


# =============================================================================
# filter_roms_from_files — English-Only
# =============================================================================

class TestFilterRomsFromFilesEnglish:
    """English-only filtering on local files."""

    def test_english_only_keeps_usa(self, tmp_path):
        roms = _make_local_roms(tmp_path, [
            "Mario (USA).zip", "Game (Japan).zip",
        ])
        selected, _ = filter_roms_from_files(
            roms, str(tmp_path / "dest"), "nes",
            dry_run=True, best_version=True, english_only=True,
        )
        names = {r.filename for r in selected}
        assert "Mario (USA).zip" in names
        assert "Game (Japan).zip" not in names

    def test_english_only_keeps_europe(self, tmp_path):
        roms = _make_local_roms(tmp_path, [
            "Zelda (Europe).zip", "Jeu (Japan).zip",
        ])
        selected, _ = filter_roms_from_files(
            roms, str(tmp_path / "dest"), "nes",
            dry_run=True, best_version=True, english_only=True,
        )
        names = {r.filename for r in selected}
        assert "Zelda (Europe).zip" in names

    def test_english_only_keeps_translation(self, tmp_path):
        roms = _make_local_roms(tmp_path, [
            "Seiken (Japan) [T-En by Team].zip",
        ])
        selected, _ = filter_roms_from_files(
            roms, str(tmp_path / "dest"), "nes",
            dry_run=True, best_version=True, english_only=True,
        )
        assert len(selected) == 1

    def test_english_only_false_keeps_japan(self, tmp_path):
        roms = _make_local_roms(tmp_path, [
            "Game (Japan).zip",
        ])
        selected, _ = filter_roms_from_files(
            roms, str(tmp_path / "dest"), "nes",
            dry_run=True, best_version=True, english_only=False,
        )
        assert len(selected) == 1


# =============================================================================
# filter_roms_from_files — Pattern Include/Exclude
# =============================================================================

class TestFilterRomsFromFilesPatterns:
    """Pattern include/exclude on local files."""

    def test_include_pattern_filters(self, tmp_path):
        roms = _make_local_roms(tmp_path, [
            "Mario (USA).zip", "Zelda (USA).zip",
            "Metroid (USA).zip",
        ])
        selected, _ = filter_roms_from_files(
            roms, str(tmp_path / "dest"), "nes",
            dry_run=True, best_version=True,
            include_patterns=["*mario*"],
        )
        assert len(selected) == 1
        assert selected[0].filename == "Mario (USA).zip"

    def test_exclude_pattern_filters(self, tmp_path):
        roms = _make_local_roms(tmp_path, [
            "Mario (USA).zip", "Zelda (USA).zip",
        ])
        selected, _ = filter_roms_from_files(
            roms, str(tmp_path / "dest"), "nes",
            dry_run=True, best_version=True,
            exclude_patterns=["*zelda*"],
        )
        names = {r.filename for r in selected}
        assert "Mario (USA).zip" in names
        assert "Zelda (USA).zip" not in names

    def test_include_and_exclude_combined(self, tmp_path):
        roms = _make_local_roms(tmp_path, [
            "Mario Bros (USA).zip",
            "Mario Kart (USA).zip",
            "Zelda (USA).zip",
        ])
        selected, _ = filter_roms_from_files(
            roms, str(tmp_path / "dest"), "nes",
            dry_run=True, best_version=True,
            include_patterns=["*mario*"],
            exclude_patterns=["*kart*"],
        )
        assert len(selected) == 1
        assert selected[0].filename == "Mario Bros (USA).zip"

    def test_no_filter_ignores_patterns(self, tmp_path):
        roms = _make_local_roms(tmp_path, [
            "Mario (USA).zip", "Zelda (USA).zip",
        ])
        selected, _ = filter_roms_from_files(
            roms, str(tmp_path / "dest"), "nes",
            dry_run=True, no_filter=True,
            include_patterns=["*mario*"],
        )
        assert len(selected) == 2


# =============================================================================
# filter_roms_from_files — Proto/Beta/Unlicensed Exclusion
# =============================================================================

class TestFilterRomsFromFilesExclusions:
    """Prototype, beta, unlicensed exclusion on local files."""

    def test_exclude_protos(self, tmp_path):
        roms = _make_local_roms(tmp_path, [
            "Mario (USA).zip", "Secret Game (USA) (Proto).zip",
        ])
        selected, _ = filter_roms_from_files(
            roms, str(tmp_path / "dest"), "nes",
            dry_run=True, best_version=True, exclude_protos=True,
        )
        names = {r.filename for r in selected}
        assert "Secret Game (USA) (Proto).zip" not in names
        assert "Mario (USA).zip" in names

    def test_include_protos_when_not_excluded(self, tmp_path):
        roms = _make_local_roms(tmp_path, [
            "Secret Game (USA) (Proto).zip",
        ])
        selected, _ = filter_roms_from_files(
            roms, str(tmp_path / "dest"), "nes",
            dry_run=True, best_version=True, exclude_protos=False,
        )
        assert len(selected) == 1

    def test_exclude_betas_default(self, tmp_path):
        roms = _make_local_roms(tmp_path, [
            "Mario (USA).zip", "Beta Game (USA) (Beta).zip",
        ])
        selected, _ = filter_roms_from_files(
            roms, str(tmp_path / "dest"), "nes",
            dry_run=True, best_version=True, include_betas=False,
        )
        names = {r.filename for r in selected}
        assert "Beta Game (USA) (Beta).zip" not in names

    def test_include_betas(self, tmp_path):
        """include_betas lets betas pass pre-filtering; they appear
        in the candidate pool.  With best_version=False (no 1G1R
        grouping), the beta survives in the output."""
        roms = _make_local_roms(tmp_path, [
            "Beta Game (USA) (Beta).zip",
        ])
        selected, _ = filter_roms_from_files(
            roms, str(tmp_path / "dest"), "nes",
            dry_run=True, best_version=False, include_betas=True,
        )
        assert len(selected) == 1

    def test_exclude_unlicensed_default(self, tmp_path):
        roms = _make_local_roms(tmp_path, [
            "Mario (USA).zip", "Pirate Game (USA) (Unl).zip",
        ])
        selected, _ = filter_roms_from_files(
            roms, str(tmp_path / "dest"), "nes",
            dry_run=True, best_version=True, include_unlicensed=False,
        )
        names = {r.filename for r in selected}
        assert "Pirate Game (USA) (Unl).zip" not in names

    def test_include_unlicensed(self, tmp_path):
        """include_unlicensed lets unlicensed ROMs pass pre-filtering;
        they appear in the candidate pool.  With best_version=False
        (no 1G1R grouping), the unlicensed ROM survives."""
        roms = _make_local_roms(tmp_path, [
            "Pirate Game (USA) (Unl).zip",
        ])
        selected, _ = filter_roms_from_files(
            roms, str(tmp_path / "dest"), "nes",
            dry_run=True, best_version=False, include_unlicensed=True,
        )
        assert len(selected) == 1

    def test_year_range_from(self, tmp_path):
        roms = _make_local_roms(tmp_path, [
            "Old Game (1985)(Publisher).zip",
            "New Game (1995)(Publisher).zip",
        ])
        selected, _ = filter_roms_from_files(
            roms, str(tmp_path / "dest"), "nes",
            dry_run=True, best_version=True, year_from=1990,
        )
        # Only the 1995 game should survive year filter
        years = [r.year for r in selected if r.year > 0]
        assert all(y >= 1990 for y in years)

    def test_year_range_to(self, tmp_path):
        roms = _make_local_roms(tmp_path, [
            "Old Game (1985)(Publisher).zip",
            "New Game (1995)(Publisher).zip",
        ])
        selected, _ = filter_roms_from_files(
            roms, str(tmp_path / "dest"), "nes",
            dry_run=True, best_version=True, year_to=1990,
        )
        years = [r.year for r in selected if r.year > 0]
        assert all(y <= 1990 for y in years)


# =============================================================================
# filter_roms_from_files — no_filter / best_version modes
# =============================================================================

class TestFilterRomsFromFilesModes:
    """Test no_filter and best_version interaction."""

    def test_no_filter_keeps_all(self, tmp_path):
        roms = _make_local_roms(tmp_path, [
            "Mario (USA).zip", "Mario (Japan).zip",
            "Beta Game (Beta).zip", "Proto (Proto).zip",
        ])
        selected, _ = filter_roms_from_files(
            roms, str(tmp_path / "dest"), "nes",
            dry_run=True, no_filter=True,
        )
        assert len(selected) == 4

    def test_best_version_false_no_grouping(self, tmp_path):
        """Without best_version, duplicates are kept (no 1G1R)."""
        roms = _make_local_roms(tmp_path, [
            "Mario (USA).zip", "Mario (Europe).zip",
        ])
        selected, _ = filter_roms_from_files(
            roms, str(tmp_path / "dest"), "nes",
            dry_run=True, best_version=False,
        )
        assert len(selected) == 2

    def test_best_version_true_groups(self, tmp_path):
        """With best_version, only best per title kept."""
        roms = _make_local_roms(tmp_path, [
            "Mario (USA).zip", "Mario (Europe).zip",
        ])
        selected, _ = filter_roms_from_files(
            roms, str(tmp_path / "dest"), "nes",
            dry_run=True, best_version=True,
        )
        assert len(selected) == 1

    def test_best_version_false_still_filters_betas(self, tmp_path):
        """Individual filters still apply even without grouping."""
        roms = _make_local_roms(tmp_path, [
            "Mario (USA).zip", "Beta Game (Beta).zip",
        ])
        selected, _ = filter_roms_from_files(
            roms, str(tmp_path / "dest"), "nes",
            dry_run=True, best_version=False, include_betas=False,
        )
        names = {r.filename for r in selected}
        assert "Beta Game (Beta).zip" not in names
        assert "Mario (USA).zip" in names

    def test_best_version_false_english_only(self, tmp_path):
        """English-only applies even without 1G1R."""
        roms = _make_local_roms(tmp_path, [
            "Mario (USA).zip", "Game (Japan).zip",
        ])
        selected, _ = filter_roms_from_files(
            roms, str(tmp_path / "dest"), "nes",
            dry_run=True, best_version=False, english_only=True,
        )
        assert len(selected) == 1
        assert selected[0].filename == "Mario (USA).zip"


# =============================================================================
# filter_roms_from_files — Size Tracking
# =============================================================================

class TestFilterRomsFromFilesSizes:
    """Size info tracking in filter_roms_from_files."""

    def test_source_size_sums_all_files(self, tmp_path):
        p1 = tmp_path / "Mario (USA).zip"
        p1.write_bytes(b'\x00' * 200)
        p2 = tmp_path / "Zelda (USA).zip"
        p2.write_bytes(b'\x00' * 300)
        _, info = filter_roms_from_files(
            [p1, p2], str(tmp_path / "dest"), "nes",
            dry_run=True, best_version=True,
        )
        assert info["source_size"] == 500

    def test_selected_size_only_selected(self, tmp_path):
        p1 = tmp_path / "Mario (USA).zip"
        p1.write_bytes(b'\x00' * 200)
        p2 = tmp_path / "Mario (Japan).zip"
        p2.write_bytes(b'\x00' * 300)
        selected, info = filter_roms_from_files(
            [p1, p2], str(tmp_path / "dest"), "nes",
            dry_run=True, best_version=True,
        )
        assert len(selected) == 1
        assert info["selected_size"] == 200  # USA version

    def test_rom_sizes_dict_populated(self, tmp_path):
        p1 = tmp_path / "Mario (USA).zip"
        p1.write_bytes(b'\x00' * 150)
        _, info = filter_roms_from_files(
            [p1], str(tmp_path / "dest"), "nes",
            dry_run=True, best_version=True,
        )
        assert "Mario (USA).zip" in info["rom_sizes"]
        assert info["rom_sizes"]["Mario (USA).zip"] == 150


# =============================================================================
# filter_roms_from_files — exclude_titles (cross-system dedup)
# =============================================================================

class TestFilterRomsFromFilesExcludeTitles:
    """Test exclude_titles parameter for cross-system dedup."""

    def test_exclude_titles_removes_matching(self, tmp_path):
        roms = _make_local_roms(tmp_path, [
            "Mario (USA).zip", "Zelda (USA).zip",
        ])
        mario_key = normalize_title_for_dedupe("Mario")
        selected, _ = filter_roms_from_files(
            roms, str(tmp_path / "dest"), "nes",
            dry_run=True, best_version=True,
            exclude_titles={mario_key},
        )
        names = {r.filename for r in selected}
        assert "Mario (USA).zip" not in names
        assert "Zelda (USA).zip" in names

    def test_exclude_titles_empty_set_keeps_all(self, tmp_path):
        roms = _make_local_roms(tmp_path, [
            "Mario (USA).zip", "Zelda (USA).zip",
        ])
        selected, _ = filter_roms_from_files(
            roms, str(tmp_path / "dest"), "nes",
            dry_run=True, best_version=True,
            exclude_titles=set(),
        )
        assert len(selected) == 2


# =============================================================================
# filter_roms_from_files — keep_regions
# =============================================================================

class TestFilterRomsFromFilesKeepRegions:
    """Test keep_regions parameter."""

    def test_keep_regions_selects_matching(self, tmp_path):
        roms = _make_local_roms(tmp_path, [
            "Mario (USA).zip", "Mario (Europe).zip",
            "Mario (Japan).zip",
        ])
        selected, _ = filter_roms_from_files(
            roms, str(tmp_path / "dest"), "nes",
            dry_run=True, best_version=True,
            keep_regions=["USA", "Europe"],
        )
        regions = {r.region for r in selected}
        assert "USA" in regions
        assert "Europe" in regions

    def test_keep_regions_fallback_when_no_match(self, tmp_path):
        roms = _make_local_roms(tmp_path, [
            "Mario (Japan).zip",
        ])
        selected, _ = filter_roms_from_files(
            roms, str(tmp_path / "dest"), "nes",
            dry_run=True, best_version=True,
            keep_regions=["USA"],
        )
        # Should fall back to best ROM since no USA match
        assert len(selected) == 1


# =============================================================================
# filter_network_roms — filter_breakdown + ExcludedRom
# =============================================================================

class TestFilterNetworkRomsBreakdown:
    """Test filter_breakdown and ExcludedRom population."""

    def test_breakdown_tracks_beta_exclusions(self):
        urls = [
            "https://example.com/roms/Mario (USA).zip",
            "https://example.com/roms/Game (Beta).zip",
        ]
        config = Config(selection=SelectionConfig(
            best_version=True, include_betas=False,
        ))
        result = filter_network_roms("nes", urls, config)
        assert result.stats.filter_breakdown.get("beta", 0) == 1

    def test_breakdown_tracks_prototype_exclusions(self):
        urls = [
            "https://example.com/roms/Mario (USA).zip",
            "https://example.com/roms/Proto (Proto).zip",
        ]
        config = Config(selection=SelectionConfig(
            best_version=True, exclude_protos=True,
        ))
        result = filter_network_roms("nes", urls, config)
        assert result.stats.filter_breakdown.get("prototype", 0) == 1

    def test_breakdown_tracks_unlicensed_exclusions(self):
        urls = [
            "https://example.com/roms/Mario (USA).zip",
            "https://example.com/roms/Pirate (Unl).zip",
        ]
        config = Config(selection=SelectionConfig(
            best_version=True, include_unlicensed=False,
        ))
        result = filter_network_roms("nes", urls, config)
        assert result.stats.filter_breakdown.get("unlicensed", 0) == 1

    def test_breakdown_tracks_include_pattern(self):
        urls = [
            "https://example.com/roms/Mario (USA).zip",
            "https://example.com/roms/Zelda (USA).zip",
        ]
        config = Config(selection=SelectionConfig(
            best_version=True, include_patterns=["*mario*"],
        ))
        result = filter_network_roms("nes", urls, config)
        assert result.stats.filter_breakdown.get("include pattern", 0) == 1

    def test_breakdown_tracks_exclude_pattern(self):
        urls = [
            "https://example.com/roms/Mario (USA).zip",
            "https://example.com/roms/Zelda (USA).zip",
        ]
        config = Config(selection=SelectionConfig(
            best_version=True, exclude_patterns=["*zelda*"],
        ))
        result = filter_network_roms("nes", urls, config)
        assert result.stats.filter_breakdown.get("exclude pattern", 0) == 1

    def test_breakdown_tracks_duplicate_version(self):
        urls = [
            "https://example.com/roms/Mario (USA).zip",
            "https://example.com/roms/Mario (Europe).zip",
        ]
        config = Config(selection=SelectionConfig(best_version=True))
        result = filter_network_roms("nes", urls, config)
        assert result.stats.filter_breakdown.get("duplicate version", 0) == 1

    def test_breakdown_tracks_non_english(self):
        urls = [
            "https://example.com/roms/Mario (USA).zip",
            "https://example.com/roms/Game (Japan).zip",
        ]
        config = Config(selection=SelectionConfig(
            best_version=True, english_only=True,
        ))
        result = filter_network_roms("nes", urls, config)
        assert result.stats.filter_breakdown.get("non-english", 0) >= 1

    def test_excluded_list_populated(self):
        urls = [
            "https://example.com/roms/Mario (USA).zip",
            "https://example.com/roms/Beta (Beta).zip",
        ]
        config = Config(selection=SelectionConfig(
            best_version=True, include_betas=False,
        ))
        result = filter_network_roms("nes", urls, config)
        assert len(result.excluded) > 0
        beta_excluded = [e for e in result.excluded if e.reason == "beta"]
        assert len(beta_excluded) == 1
        assert "Beta" in beta_excluded[0].filename

    def test_excluded_has_size_info(self):
        urls = [
            "https://example.com/roms/Mario (USA).zip",
            "https://example.com/roms/Beta (Beta).zip",
        ]
        url_sizes = {
            "https://example.com/roms/Beta (Beta).zip": 5000,
        }
        config = Config(selection=SelectionConfig(
            best_version=True, include_betas=False,
        ))
        result = filter_network_roms("nes", urls, config,
                                     url_sizes=url_sizes)
        beta_excluded = [e for e in result.excluded if e.reason == "beta"]
        assert beta_excluded[0].size == 5000

    def test_stats_counts_correct(self):
        urls = [
            "https://example.com/roms/Mario (USA).zip",
            "https://example.com/roms/Zelda (USA).zip",
            "https://example.com/roms/Beta (Beta).zip",
        ]
        config = Config(selection=SelectionConfig(
            best_version=True, include_betas=False,
        ))
        result = filter_network_roms("nes", urls, config)
        assert result.stats.source_count == 3
        assert result.stats.selected_count == 2
        assert result.stats.excluded_count == 1

    def test_empty_urls_returns_empty_result(self):
        config = Config(selection=SelectionConfig(best_version=True))
        result = filter_network_roms("nes", [], config)
        assert result.selected == []
        assert result.stats.source_count == 0

    def test_year_range_exclusion_in_breakdown(self):
        urls = [
            "https://example.com/roms/Old Game (1985)(Publisher).zip",
            "https://example.com/roms/New Game (1995)(Publisher).zip",
        ]
        config = Config(selection=SelectionConfig(
            best_version=True, year_from=1990,
        ))
        result = filter_network_roms("nes", urls, config)
        assert result.stats.filter_breakdown.get("year range", 0) >= 1


# =============================================================================
# _collect_sibling_discs — Edge Cases
# =============================================================================

class TestCollectSiblingDiscsEdge:
    """Edge cases for _collect_sibling_discs."""

    def test_mismatched_region_not_collected(self):
        disc1_usa = _make_rom_info(
            "Game (USA) (Disc 1).bin", "Game", "USA", disc_number=1)
        disc2_jp = _make_rom_info(
            "Game (Japan) (Disc 2).bin", "Game", "Japan", disc_number=2)
        siblings = _collect_sibling_discs(disc1_usa, [disc1_usa, disc2_jp])
        assert len(siblings) == 1
        assert siblings[0].region == "USA"

    def test_mismatched_revision_not_collected(self):
        disc1_r0 = _make_rom_info(
            "Game (USA) (Disc 1).bin", "Game", "USA",
            disc_number=1, revision=0)
        disc2_r1 = _make_rom_info(
            "Game (USA) (Disc 2).bin", "Game", "USA",
            disc_number=2, revision=1)
        siblings = _collect_sibling_discs(disc1_r0, [disc1_r0, disc2_r1])
        assert len(siblings) == 1

    def test_translation_mismatch_not_collected(self):
        disc1 = _make_rom_info(
            "Game (USA) (Disc 1).bin", "Game", "USA",
            disc_number=1, is_translation=False)
        disc2_trans = _make_rom_info(
            "Game (USA) (Disc 2) [T-En].bin", "Game", "USA",
            disc_number=2, is_translation=True)
        siblings = _collect_sibling_discs(disc1, [disc1, disc2_trans])
        assert len(siblings) == 1

    def test_four_disc_game(self):
        discs = [
            _make_rom_info(
                f"Game (USA) (Disc {i}).bin", "Game", "USA", disc_number=i)
            for i in range(1, 5)
        ]
        siblings = _collect_sibling_discs(discs[0], discs)
        assert len(siblings) == 4
        assert [s.disc_number for s in siblings] == [1, 2, 3, 4]


# =============================================================================
# matches_patterns
# =============================================================================

class TestMatchesPatterns:
    """Test glob pattern matching helper."""

    def test_simple_star_pattern(self):
        assert matches_patterns("Mario Bros.zip", ["*mario*"])

    def test_case_insensitive(self):
        assert matches_patterns("MARIO.zip", ["*mario*"])

    def test_no_match(self):
        assert not matches_patterns("Zelda.zip", ["*mario*"])

    def test_multiple_patterns_any_match(self):
        assert matches_patterns("Zelda.zip", ["*mario*", "*zelda*"])

    def test_extension_pattern(self):
        assert matches_patterns("game.sfc", ["*.sfc"])
        assert not matches_patterns("game.nes", ["*.sfc"])

    def test_question_mark_wildcard(self):
        assert matches_patterns("Game1.zip", ["Game?.zip"])
        assert not matches_patterns("Game12.zip", ["Game?.zip"])

    def test_empty_patterns_no_match(self):
        assert not matches_patterns("anything.zip", [])


# =============================================================================
# select_best_rom — Edge Cases
# =============================================================================

class TestSelectBestRomEdge:
    """Edge cases in select_best_rom."""

    def test_prefers_non_hacked_over_hacked(self):
        clean = _make_rom_info("Game (USA).zip", "Game", "USA")
        hacked = _make_rom_info(
            "Game (USA) [Hack by X].zip", "Game", "USA", has_hacks=True)
        best = select_best_rom([clean, hacked])
        assert best.filename == "Game (USA).zip"

    def test_custom_priority_japan_first(self):
        usa = _make_rom_info("Game (USA).zip", "Game", "USA")
        japan = _make_rom_info(
            "Game (Japan).zip", "Game", "Japan", is_english=False)
        best = select_best_rom(
            [usa, japan],
            region_priority=["Japan", "USA", "Europe"],
        )
        assert best.region == "Japan"

    def test_all_bios_returns_none(self):
        bios = _make_rom_info("BIOS (USA).zip", "BIOS", "USA", is_bios=True)
        assert select_best_rom([bios]) is None

    def test_all_compilations_returns_none(self):
        comp = _make_rom_info(
            "2 in 1 Pack.zip", "2 in 1 Pack", "USA", is_compilation=True)
        assert select_best_rom([comp]) is None

    def test_all_rereleases_returns_none(self):
        rerel = _make_rom_info(
            "Game Virtual Console.zip", "Game", "USA", is_rerelease=True)
        assert select_best_rom([rerel]) is None

    def test_proto_only_group_selects_proto(self):
        """When only protos exist after filtering, select the best proto."""
        proto = _make_rom_info(
            "Game (USA) (Proto).zip", "Game", "USA", is_proto=True)
        best = select_best_rom([proto])
        assert best is not None
        assert best.is_proto

    def test_translation_fallback_when_no_english(self):
        """When no official English, prefer translation over foreign."""
        foreign = _make_rom_info(
            "Game (Japan).zip", "Game", "Japan", is_english=False)
        translation = _make_rom_info(
            "Game (Japan) [T-En].zip", "Game", "Japan",
            is_english=True, is_translation=True)
        best = select_best_rom([foreign, translation])
        assert best.is_translation

    def test_world_region_preferred_over_europe(self):
        europe = _make_rom_info("Game (Europe).zip", "Game", "Europe")
        world = _make_rom_info("Game (World).zip", "Game", "World")
        best = select_best_rom([europe, world])
        assert best.region == "World"

    def test_lock_on_filtered_out(self):
        normal = _make_rom_info("Game (USA).zip", "Game", "USA")
        lockon = _make_rom_info(
            "Sonic & Knuckles + Game (USA).zip", "Game", "USA",
            is_lock_on=True)
        best = select_best_rom([normal, lockon])
        assert best.filename == "Game (USA).zip"

    def test_homebrew_filtered_out(self):
        normal = _make_rom_info("Game (USA).zip", "Game", "USA")
        homebrew = _make_rom_info(
            "Game (Homebrew).zip", "Game", "USA", is_homebrew=True)
        best = select_best_rom([normal, homebrew])
        assert not best.is_homebrew


# =============================================================================
# get_file_size
# =============================================================================

class TestGetFileSize:
    """Test get_file_size helper."""

    def test_returns_correct_size(self, tmp_path):
        f = tmp_path / "test.bin"
        f.write_bytes(b'\x00' * 42)
        assert get_file_size(f) == 42

    def test_nonexistent_returns_zero(self, tmp_path):
        assert get_file_size(tmp_path / "nonexistent.bin") == 0


# =============================================================================
# parse_logiqx_xml_dat — Complex XML
# =============================================================================

class TestParseLogiqxXmlDat:
    """Test Logiqx XML DAT parsing with complex inputs."""

    def test_multiple_roms_per_game(self, tmp_path):
        dat = '''<?xml version="1.0"?>
<datafile>
<game name="Multi ROM Game (USA)">
<rom name="rom1.bin" size="1024" crc="AAAA1111"/>
<rom name="rom2.bin" size="2048" crc="BBBB2222"/>
</game>
</datafile>'''
        p = tmp_path / "multi.dat"
        p.write_text(dat, encoding="utf-8")
        entries = parse_logiqx_xml_dat(p)
        assert len(entries) == 2
        assert "aaaa1111" in entries
        assert "bbbb2222" in entries

    def test_machine_tag(self, tmp_path):
        dat = '''<?xml version="1.0"?>
<datafile>
<machine name="Arcade Game (World)">
<rom name="arcade.bin" size="512" crc="CCCC3333"/>
</machine>
</datafile>'''
        p = tmp_path / "machine.dat"
        p.write_text(dat, encoding="utf-8")
        entries = parse_logiqx_xml_dat(p)
        assert "cccc3333" in entries
        assert entries["cccc3333"].region == "World"

    def test_md5_and_sha1_parsed(self, tmp_path):
        dat = '''<?xml version="1.0"?>
<datafile>
<game name="Hash Game (USA)">
<rom name="hash.bin" size="100" crc="11112222"
     md5="AABBCCDD11223344AABBCCDD11223344"
     sha1="AABB11223344556677889900AABBCCDDEEFF0011"/>
</game>
</datafile>'''
        p = tmp_path / "hash.dat"
        p.write_text(dat, encoding="utf-8")
        entries = parse_logiqx_xml_dat(p)
        entry = entries["11112222"]
        assert entry.md5 == "aabbccdd11223344aabbccdd11223344"
        assert entry.sha1 != ""

    def test_region_detection_from_game_name(self, tmp_path):
        dat = '''<?xml version="1.0"?>
<datafile>
<game name="Euro Game (Europe)">
<rom name="euro.bin" size="100" crc="EEFF0011"/>
</game>
<game name="JP Game (Japan)">
<rom name="jp.bin" size="100" crc="EEFF0022"/>
</game>
</datafile>'''
        p = tmp_path / "regions.dat"
        p.write_text(dat, encoding="utf-8")
        entries = parse_logiqx_xml_dat(p)
        assert entries["eeff0011"].region == "Europe"
        assert entries["eeff0022"].region == "Japan"

    def test_rom_without_crc_skipped(self, tmp_path):
        dat = '''<?xml version="1.0"?>
<datafile>
<game name="No CRC Game (USA)">
<rom name="nocrc.bin" size="100"/>
</game>
<game name="With CRC (USA)">
<rom name="withcrc.bin" size="100" crc="DEADBEEF"/>
</game>
</datafile>'''
        p = tmp_path / "nocrc.dat"
        p.write_text(dat, encoding="utf-8")
        entries = parse_logiqx_xml_dat(p)
        assert len(entries) == 1
        assert "deadbeef" in entries

    def test_empty_dat(self, tmp_path):
        dat = '''<?xml version="1.0"?>
<datafile>
</datafile>'''
        p = tmp_path / "empty.dat"
        p.write_text(dat, encoding="utf-8")
        entries = parse_logiqx_xml_dat(p)
        assert len(entries) == 0

    def test_size_zero_when_missing(self, tmp_path):
        dat = '''<?xml version="1.0"?>
<datafile>
<game name="No Size (USA)">
<rom name="nosize.bin" crc="AABB0011"/>
</game>
</datafile>'''
        p = tmp_path / "nosize.dat"
        p.write_text(dat, encoding="utf-8")
        entries = parse_logiqx_xml_dat(p)
        assert entries["aabb0011"].size == 0


# =============================================================================
# parse_clrmamepro_dat — Complex Input
# =============================================================================

class TestParseClrMameProDat:
    """Test ClrMamePro DAT parsing with complex inputs."""

    def test_multiple_games(self, tmp_path):
        dat = (
            'clrmamepro (\n'
            '\tname "Multi Test"\n'
            ')\n\n'
            'game ( name "Game One (USA)"\n'
            '\trom ( name "game1.zip" size 1024 crc AAAA1111 )\n'
            ')\n\n'
            'game ( name "Game Two (Japan)"\n'
            '\trom ( name "game2.zip" size 2048 crc BBBB2222 )\n'
            ')\n'
        )
        p = tmp_path / "multi.dat"
        p.write_text(dat, encoding="utf-8")
        entries = parse_clrmamepro_dat(p)
        assert len(entries) == 2
        assert entries["aaaa1111"].region == "USA"
        assert entries["bbbb2222"].region == "Japan"

    def test_multiple_roms_per_game(self, tmp_path):
        dat = (
            'game ( name "Multi ROM (USA)"\n'
            '\trom ( name "rom1.bin" size 100 crc 11110000 )\n'
            '\trom ( name "rom2.bin" size 200 crc 22220000 )\n'
            ')\n'
        )
        p = tmp_path / "multrom.dat"
        p.write_text(dat, encoding="utf-8")
        entries = parse_clrmamepro_dat(p)
        assert len(entries) == 2

    def test_md5_and_sha1_parsed(self, tmp_path):
        dat = (
            'game ( name "Hash Game (USA)"\n'
            '\trom ( name "hash.bin" size 100 crc 33330000'
            ' md5 aabbccdd11223344 sha1 aabb112233445566 )\n'
            ')\n'
        )
        p = tmp_path / "hash.dat"
        p.write_text(dat, encoding="utf-8")
        entries = parse_clrmamepro_dat(p)
        assert entries["33330000"].md5 == "aabbccdd11223344"

    def test_rom_without_crc_skipped(self, tmp_path):
        dat = (
            'game ( name "No CRC (USA)"\n'
            '\trom ( name "nocrc.bin" size 100 )\n'
            ')\n'
            'game ( name "Has CRC (USA)"\n'
            '\trom ( name "hascrc.bin" size 100 crc FFEE0011 )\n'
            ')\n'
        )
        p = tmp_path / "nocrc.dat"
        p.write_text(dat, encoding="utf-8")
        entries = parse_clrmamepro_dat(p)
        assert len(entries) == 1
        assert "ffee0011" in entries

    def test_empty_dat(self, tmp_path):
        dat = 'clrmamepro (\n\tname "Empty"\n)\n'
        p = tmp_path / "empty.dat"
        p.write_text(dat, encoding="utf-8")
        entries = parse_clrmamepro_dat(p)
        assert len(entries) == 0


# =============================================================================
# parse_dat_file — Auto-detection
# =============================================================================

class TestParseDatFileAutoDetect:
    """Test auto-detection of DAT format."""

    def test_detects_xml_format(self, tmp_path):
        dat = '''<?xml version="1.0"?>
<datafile>
<game name="XML Game (USA)">
<rom name="xml.zip" size="100" crc="12345678"/>
</game>
</datafile>'''
        p = tmp_path / "test.dat"
        p.write_text(dat, encoding="utf-8")
        entries = parse_dat_file(p)
        assert "12345678" in entries

    def test_detects_clrmamepro_format(self, tmp_path):
        dat = (
            'clrmamepro (\n'
            '\tname "Test"\n)\n'
            'game ( name "CMP Game (USA)"\n'
            '\trom ( name "cmp.zip" size 100 crc ABCDEF01 )\n)\n'
        )
        p = tmp_path / "test.dat"
        p.write_text(dat, encoding="utf-8")
        entries = parse_dat_file(p)
        assert "abcdef01" in entries


# =============================================================================
# load_all_system_dats
# =============================================================================

class TestLoadAllSystemDats:
    """Test loading and merging multiple DAT files for a system."""

    def test_primary_dat_only(self, tmp_path):
        dat = '''<?xml version="1.0"?>
<datafile>
<game name="Game A (USA)">
<rom name="a.zip" size="100" crc="AAAA0001"/>
</game>
</datafile>'''
        (tmp_path / "nes.dat").write_text(dat, encoding="utf-8")
        entries = load_all_system_dats("nes", tmp_path)
        assert len(entries) == 1
        assert "aaaa0001" in entries

    def test_primary_plus_extra(self, tmp_path):
        primary = '''<?xml version="1.0"?>
<datafile>
<game name="Game A (USA)">
<rom name="a.zip" size="100" crc="AAAA0001"/>
</game>
</datafile>'''
        extra = '''<?xml version="1.0"?>
<datafile>
<game name="Game B (USA)">
<rom name="b.zip" size="200" crc="BBBB0002"/>
</game>
</datafile>'''
        (tmp_path / "nes.dat").write_text(primary, encoding="utf-8")
        (tmp_path / "nes_extra1.dat").write_text(extra, encoding="utf-8")
        entries = load_all_system_dats("nes", tmp_path)
        assert len(entries) == 2
        assert "aaaa0001" in entries
        assert "bbbb0002" in entries

    def test_multiple_extras_merged(self, tmp_path):
        primary = '''<?xml version="1.0"?>
<datafile>
<game name="A (USA)"><rom name="a.zip" size="100" crc="AA000001"/></game>
</datafile>'''
        extra1 = '''<?xml version="1.0"?>
<datafile>
<game name="B (USA)"><rom name="b.zip" size="100" crc="BB000002"/></game>
</datafile>'''
        extra2 = '''<?xml version="1.0"?>
<datafile>
<game name="C (USA)"><rom name="c.zip" size="100" crc="CC000003"/></game>
</datafile>'''
        (tmp_path / "snes.dat").write_text(primary, encoding="utf-8")
        (tmp_path / "snes_extra1.dat").write_text(extra1, encoding="utf-8")
        (tmp_path / "snes_extra2.dat").write_text(extra2, encoding="utf-8")
        entries = load_all_system_dats("snes", tmp_path)
        assert len(entries) == 3

    def test_no_dats_returns_empty(self, tmp_path):
        entries = load_all_system_dats("nonexistent", tmp_path)
        assert len(entries) == 0

    def test_extra_without_primary(self, tmp_path):
        extra = '''<?xml version="1.0"?>
<datafile>
<game name="B (USA)"><rom name="b.zip" size="200" crc="BBBB0002"/></game>
</datafile>'''
        (tmp_path / "gba_extra1.dat").write_text(extra, encoding="utf-8")
        entries = load_all_system_dats("gba", tmp_path)
        assert len(entries) == 1


# =============================================================================
# CRC Cache Round-Trip
# =============================================================================

class TestCrcCache:
    """Test load_crc_cache / save_crc_cache / get_cached_crc."""

    def test_save_and_load_roundtrip(self, tmp_path):
        cache_path = tmp_path / "cache.json"
        cache = {
            "/path/to/rom.zip": {
                "crc": "abcd1234",
                "mtime": 1000.0,
                "size": 500,
            }
        }
        save_crc_cache(cache_path, cache)
        loaded = load_crc_cache(cache_path)
        assert loaded["/path/to/rom.zip"]["crc"] == "abcd1234"

    def test_load_nonexistent_returns_empty(self, tmp_path):
        loaded = load_crc_cache(tmp_path / "nonexistent.json")
        assert loaded == {}

    def test_load_corrupt_json_returns_empty(self, tmp_path):
        cache_path = tmp_path / "corrupt.json"
        cache_path.write_text("{bad json", encoding="utf-8")
        loaded = load_crc_cache(cache_path)
        assert loaded == {}

    def test_get_cached_crc_calculates_and_caches(self, tmp_path):
        f = tmp_path / "testrom.bin"
        f.write_bytes(b"Hello CRC test")
        cache = {}
        crc = get_cached_crc(f, cache)
        assert crc is not None
        assert len(crc) == 8
        # Should be cached now
        key = str(f)
        assert key in cache
        assert cache[key]["crc"] == crc

    def test_get_cached_crc_returns_cached(self, tmp_path):
        f = tmp_path / "cached.bin"
        f.write_bytes(b"data")
        stat = f.stat()
        cache = {
            str(f): {
                "crc": "cafebabe",
                "mtime": stat.st_mtime,
                "size": stat.st_size,
            }
        }
        crc = get_cached_crc(f, cache)
        assert crc == "cafebabe"

    def test_get_cached_crc_invalidates_on_mtime_change(self, tmp_path):
        f = tmp_path / "changing.bin"
        f.write_bytes(b"original")
        stat = f.stat()
        cache = {
            str(f): {
                "crc": "oldcrc00",
                "mtime": stat.st_mtime - 100,  # stale mtime
                "size": stat.st_size,
            }
        }
        crc = get_cached_crc(f, cache)
        assert crc != "oldcrc00"

    def test_get_cached_crc_invalidates_on_size_change(self, tmp_path):
        f = tmp_path / "resized.bin"
        f.write_bytes(b"data")
        stat = f.stat()
        cache = {
            str(f): {
                "crc": "oldcrc00",
                "mtime": stat.st_mtime,
                "size": stat.st_size + 999,  # wrong size
            }
        }
        crc = get_cached_crc(f, cache)
        assert crc != "oldcrc00"

    def test_get_cached_crc_zip_file(self, tmp_path):
        zip_path = _make_zip_rom(
            tmp_path, "game.zip", "game.bin", b"zip content data")
        cache = {}
        crc = get_cached_crc(zip_path, cache)
        assert crc is not None
        assert len(crc) == 8

    def test_get_cached_crc_with_download_index(self, tmp_path):
        f = tmp_path / "indexed.bin"
        f.write_bytes(b"indexed data")
        stat = f.stat()
        download_index = {
            str(f): {
                "crc": "indexcrc1",
                "mtime": stat.st_mtime,
                "size": stat.st_size,
            }
        }
        cache = {}
        crc = get_cached_crc(f, cache, download_crc_index=download_index)
        assert crc == "indexcrc1"
        # Should also be copied into the main cache
        assert cache[str(f)]["crc"] == "indexcrc1"

    def test_save_creates_parent_dirs(self, tmp_path):
        cache_path = tmp_path / "sub" / "dir" / "cache.json"
        save_crc_cache(cache_path, {"key": "val"})
        assert cache_path.exists()


# =============================================================================
# calculate_crc32_from_zip
# =============================================================================

class TestCalculateCrc32FromZip:
    """Test CRC32 calculation from first file inside a ZIP."""

    def test_basic_zip(self, tmp_path):
        zip_path = _make_zip_rom(
            tmp_path, "test.zip", "rom.bin", b"ROM content")
        crc = calculate_crc32_from_zip(zip_path)
        assert crc is not None
        assert len(crc) == 8

    def test_matches_direct_crc(self, tmp_path):
        content = b"Some ROM data for CRC comparison"
        # Calculate CRC directly
        raw_file = tmp_path / "raw.bin"
        raw_file.write_bytes(content)
        direct_crc = calculate_crc32(raw_file)
        # Calculate CRC from inside ZIP
        zip_path = _make_zip_rom(
            tmp_path, "test.zip", "rom.bin", content)
        zip_crc = calculate_crc32_from_zip(zip_path)
        assert zip_crc == direct_crc

    def test_skips_directory_entries(self, tmp_path):
        zip_path = tmp_path / "withdir.zip"
        with zipfile.ZipFile(zip_path, 'w') as zf:
            zf.mkdir("subdir")
            zf.writestr("subdir/rom.bin", b"nested rom content")
        crc = calculate_crc32_from_zip(zip_path)
        assert crc is not None

    def test_invalid_zip_returns_none(self, tmp_path):
        bad_zip = tmp_path / "notazip.zip"
        bad_zip.write_bytes(b"not a real zip file")
        crc = calculate_crc32_from_zip(bad_zip)
        assert crc is None

    def test_empty_zip_returns_none(self, tmp_path):
        zip_path = tmp_path / "empty.zip"
        with zipfile.ZipFile(zip_path, 'w'):
            pass  # empty ZIP
        crc = calculate_crc32_from_zip(zip_path)
        assert crc is None


# =============================================================================
# detect_dat_region — Additional Edge Cases
# =============================================================================

class TestDetectDatRegionEdge:
    """Additional edge cases for detect_dat_region."""

    def test_case_insensitive_usa(self):
        assert detect_dat_region("game (UsA)") == "USA"

    def test_case_insensitive_europe(self):
        assert detect_dat_region("game (EUROPE)") == "Europe"

    def test_us_shorthand(self):
        assert detect_dat_region("game (US)") == "USA"

    def test_eu_shorthand(self):
        assert detect_dat_region("game (EU)") == "Europe"

    def test_jp_shorthand(self):
        assert detect_dat_region("game (JP)") == "Japan"

    def test_au_shorthand(self):
        assert detect_dat_region("game (AU)") == "Australia"

    def test_multiple_regions_first_wins(self):
        # First match wins in the if-chain
        result = detect_dat_region("game (USA) (Japan)")
        assert result == "USA"

    def test_region_in_middle_of_name(self):
        assert detect_dat_region("Super Game (World) Edition") == "World"

    def test_no_region_returns_unknown(self):
        assert detect_dat_region("Game Without Region") == "Unknown"

    def test_empty_string(self):
        assert detect_dat_region("") == "Unknown"


# =============================================================================
# normalize_title — Edge Cases
# =============================================================================

class TestNormalizeTitleEdge:
    """Edge cases for normalize_title."""

    def test_accented_characters_stripped(self):
        result = normalize_title("Pokemon")
        assert result == "pokemon"

    def test_unicode_accents_normalized(self):
        # e-acute should be stripped
        result = normalize_title("Pok\u00e9mon")
        assert result == "pokemon"

    def test_multiple_spaces_collapsed(self):
        result = normalize_title("Super   Mario   Bros")
        assert result == "super mario bros"

    def test_leading_trailing_spaces_stripped(self):
        result = normalize_title("  Game  ")
        assert result == "game"

    def test_comma_the_pattern(self):
        result = normalize_title("Legend of Zelda, The")
        assert result == "legend of zelda"

    def test_roman_numeral_boundary(self):
        """Roman numerals only match word boundaries."""
        result = normalize_title("Ivanhoe")
        # Should NOT convert the "iv" in "ivanhoe"
        assert "4" not in result

    def test_dedupe_preserves_articles(self):
        normal = normalize_title("The Legend")
        dedupe = normalize_title_for_dedupe("The Legend")
        assert "the" not in normal
        assert dedupe.startswith("the")


# =============================================================================
# Title Mappings
# =============================================================================

class TestTitleMappings:
    """Test title mapping loading and caching."""

    def test_load_returns_dict(self):
        reset_title_mappings_cache()
        mappings = load_title_mappings()
        assert isinstance(mappings, dict)

    def test_cache_returns_same_object(self):
        reset_title_mappings_cache()
        m1 = load_title_mappings()
        m2 = load_title_mappings()
        assert m1 is m2

    def test_reset_clears_cache(self):
        reset_title_mappings_cache()
        m1 = load_title_mappings()
        reset_title_mappings_cache()
        m2 = load_title_mappings()
        assert m1 is not m2

    def test_mapping_applied_in_normalize(self):
        reset_title_mappings_cache()
        mappings = load_title_mappings()
        if mappings:
            source = next(iter(mappings))
            result = normalize_title(source)
            # After mapping, the result should be the target
            assert result == mappings[source]


# =============================================================================
# filter_roms_from_files — Transfer Modes
# =============================================================================

class TestFilterRomsFromFilesTransfer:
    """Test actual file transfer when dry_run=False."""

    def test_copy_mode(self, tmp_path):
        rom_dir = tmp_path / "roms"
        rom_dir.mkdir()
        roms = _make_local_roms(rom_dir, ["Mario (USA).zip"])
        dest = tmp_path / "dest"
        filter_roms_from_files(
            roms, str(dest), "nes", dry_run=False,
            best_version=True, transfer_mode='copy',
        )
        assert (dest / "nes" / "Mario (USA).zip").exists()
        assert roms[0].exists()  # source still exists

    def test_move_mode(self, tmp_path):
        rom_dir = tmp_path / "roms"
        rom_dir.mkdir()
        roms = _make_local_roms(rom_dir, ["Mario (USA).zip"])
        dest = tmp_path / "dest"
        filter_roms_from_files(
            roms, str(dest), "nes", dry_run=False,
            best_version=True, transfer_mode='move',
        )
        assert (dest / "nes" / "Mario (USA).zip").exists()
        assert not roms[0].exists()  # source moved


# =============================================================================
# filter_roms_from_files — Log Output
# =============================================================================

class TestFilterRomsFromFilesLog:
    """Test log file generation."""

    def test_log_dir_creates_selection_log(self, tmp_path):
        rom_dir = tmp_path / "roms"
        rom_dir.mkdir()
        log_dir = tmp_path / "logs"
        roms = _make_local_roms(rom_dir, [
            "Mario (USA).zip", "Zelda (USA).zip",
        ])
        dest = tmp_path / "dest"
        filter_roms_from_files(
            roms, str(dest), "nes", dry_run=False,
            best_version=True, transfer_mode='copy',
            log_dir=str(log_dir),
        )
        log_file = log_dir / "nes_selection_log.txt"
        assert log_file.exists()
        content = log_file.read_text(encoding="utf-8")
        assert "Mario" in content
        assert "Zelda" in content
        assert "ROMs selected:" in content


# =============================================================================
# filter_roms_from_files — with Real ZIP ROMs
# =============================================================================

class TestFilterRomsFromFilesWithZips:
    """Test with real .zip files containing dummy ROM content."""

    def test_basic_zip_filtering(self, tmp_path):
        zip1 = _make_zip_rom(
            tmp_path, "Mario (USA).zip", "mario.nes", b"NES ROM data")
        zip2 = _make_zip_rom(
            tmp_path, "Zelda (USA).zip", "zelda.nes", b"NES ROM data 2")
        selected, info = filter_roms_from_files(
            [zip1, zip2], str(tmp_path / "dest"), "nes",
            dry_run=True, best_version=True,
        )
        assert len(selected) == 2
        assert info["source_size"] > 0

    def test_zip_1g1r_selection(self, tmp_path):
        zip_usa = _make_zip_rom(
            tmp_path, "Mario (USA).zip", "mario.nes", b"USA data")
        zip_jp = _make_zip_rom(
            tmp_path, "Mario (Japan).zip", "mario.nes", b"JP data")
        selected, _ = filter_roms_from_files(
            [zip_usa, zip_jp], str(tmp_path / "dest"), "nes",
            dry_run=True, best_version=True,
        )
        assert len(selected) == 1
        assert selected[0].region == "USA"


# =============================================================================
# filter_network_roms — all_roms mode
# =============================================================================

class TestFilterNetworkRomsAllRoms:
    """Test all_roms (no_filter) mode in filter_network_roms."""

    def test_all_roms_keeps_everything(self):
        urls = [
            "https://example.com/roms/Mario (USA).zip",
            "https://example.com/roms/Beta (Beta).zip",
            "https://example.com/roms/Proto (Proto).zip",
            "https://example.com/roms/Mario (Japan).zip",
        ]
        config = Config(selection=SelectionConfig(all_roms=True))
        result = filter_network_roms("nes", urls, config)
        assert len(result.selected) == 4

    def test_all_roms_size_tracking(self):
        urls = [
            "https://example.com/roms/Mario (USA).zip",
            "https://example.com/roms/Zelda (USA).zip",
        ]
        url_sizes = {
            "https://example.com/roms/Mario (USA).zip": 1000,
            "https://example.com/roms/Zelda (USA).zip": 2000,
        }
        config = Config(selection=SelectionConfig(all_roms=True))
        result = filter_network_roms("nes", urls, config,
                                     url_sizes=url_sizes)
        assert result.stats.source_size == 3000
        assert result.stats.selected_size == 3000


# =============================================================================
# filter_network_roms — DAT entries integration
# =============================================================================

class TestFilterNetworkRomsDatEntries:
    """Test DAT entry integration in filter_network_roms."""

    def test_dat_matched_count(self):
        urls = [
            "https://example.com/roms/Mario (USA).zip",
        ]
        dat_entries = {
            "abcd1234": DatRomEntry(
                name="Mario (USA)", rom_name="Mario (USA).zip",
                size=1024, crc="abcd1234", md5="", sha1="",
                region="USA", is_parent=True, parent_name="",
            )
        }
        config = Config(selection=SelectionConfig(best_version=True))
        result = filter_network_roms("nes", urls, config,
                                     dat_entries=dat_entries)
        assert result.stats.dat_matched == 1

    def test_dat_title_used_for_grouping(self):
        urls = [
            "https://example.com/roms/Mario%20(USA).zip",
            "https://example.com/roms/Mario%20(Europe).zip",
        ]
        dat_entries = {
            "11111111": DatRomEntry(
                name="Super Mario (USA)",
                rom_name="Mario (USA).zip",
                size=1024, crc="11111111", md5="", sha1="",
                region="USA", is_parent=True, parent_name="",
            ),
            "22222222": DatRomEntry(
                name="Super Mario (Europe)",
                rom_name="Mario (Europe).zip",
                size=1024, crc="22222222", md5="", sha1="",
                region="Europe", is_parent=True, parent_name="",
            ),
        }
        config = Config(selection=SelectionConfig(best_version=True))
        result = filter_network_roms("nes", urls, config,
                                     dat_entries=dat_entries)
        # Both should group under the same DAT title
        assert len(result.selected) == 1

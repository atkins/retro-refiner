"""Comprehensive pytest tests for teknoparrot.py.

Covers: TeknoParrot DAT parsing, TP filtering pipeline, name normalization,
version parsing, region priority, and platform filtering.
"""
# pylint: disable=missing-function-docstring
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from retro_refiner.teknoparrot import (  # noqa: E402
    TeknoParrotGameInfo,
    parse_teknoparrot_filename,
    parse_teknoparrot_version,
    parse_teknoparrot_dat,
    normalize_teknoparrot_title,
    get_teknoparrot_region_priority,
    select_best_teknoparrot_version,
    should_include_teknoparrot_game,
    filter_teknoparrot_network_roms,
)


# =============================================================================
# Helpers
# =============================================================================

def _make_tp_game(filename, name='', base_title='', version='',
                  version_tuple=None, date='', year=0, region='World',
                  platform='Sega Lindbergh'):
    """Build a TeknoParrotGameInfo with sensible defaults."""
    return TeknoParrotGameInfo(
        filename=filename,
        name=name or filename.replace('.zip', ''),
        base_title=base_title or filename.replace('.zip', ''),
        description=name or filename.replace('.zip', ''),
        version=version,
        version_tuple=version_tuple or (0,),
        date=date,
        year=year,
        region=region,
        platform=platform,
        is_parent=True,
        parent_name='',
        has_chd=False,
        chd_names=[],
    )


# =============================================================================
# TeknoParrot: parse_teknoparrot_version
# =============================================================================

class TestParseTeknoParrotVersion:

    @pytest.mark.parametrize("version_str,expected", [
        ("1.30.01", (1, 30, 1)),
        ("2.30.00", (2, 30, 0)),
        ("Ver.2", (2,)),
        ("Ver 3.1", (3, 1)),
        ("Version 4", (4,)),
        ("Rev.6", (6,)),
        ("v1.0", (1, 0)),
        ("", (0,)),
        ("no_digits_here", (0,)),
    ])
    def test_version_parsing(self, version_str, expected):
        assert parse_teknoparrot_version(version_str) == expected


# =============================================================================
# TeknoParrot: parse_teknoparrot_filename
# =============================================================================

class TestParseTeknoParrotFilename:

    def test_basic_tp_filename(self):
        info = parse_teknoparrot_filename(
            "Initial D Arcade Stage 8 (2.30.01) (2014-11-20) "
            "[Sega RingEdge 2] [TP].zip")
        assert info is not None
        assert info.version == '2.30.01'
        assert info.version_tuple == (2, 30, 1)
        assert info.date == '2014-11-20'
        assert info.year == 2014
        assert info.platform == 'Sega RingEdge 2'

    def test_non_tp_file_returns_none(self):
        assert parse_teknoparrot_filename("normal_game.zip") is None

    def test_case_insensitive_tp_tag(self):
        info = parse_teknoparrot_filename(
            "Game [Sega Nu] [tp].zip")
        assert info is not None

    def test_export_region(self):
        info = parse_teknoparrot_filename(
            "Game Export [Sega Nu] [TP].zip")
        assert info is not None
        assert info.region == 'Export'

    def test_japan_region(self):
        info = parse_teknoparrot_filename(
            "Game Japan [Taito Type X2] [TP].zip")
        assert info is not None
        assert info.region == 'Japan'

    def test_usa_region(self):
        info = parse_teknoparrot_filename(
            "Game USA [Sega Lindbergh] [TP].zip")
        assert info is not None
        assert info.region == 'USA'

    def test_default_region_world(self):
        info = parse_teknoparrot_filename(
            "Cool Game [Sega Nu] [TP].zip")
        assert info is not None
        assert info.region == 'World'

    def test_platform_extraction(self):
        info = parse_teknoparrot_filename(
            "Virtua Fighter 5 [Sega Lindbergh] [TP].zip")
        assert info is not None
        assert info.platform == 'Sega Lindbergh'

    def test_version_ver_prefix(self):
        info = parse_teknoparrot_filename(
            "Game Ver.2 [Sega Nu] [TP].zip")
        assert info is not None
        assert info.version == '2'

    def test_revision_version(self):
        info = parse_teknoparrot_filename(
            "Game (Rev.6) [Sega Nu] [TP].zip")
        assert info is not None
        assert info.version == 'Rev.6'

    def test_no_version(self):
        info = parse_teknoparrot_filename(
            "Simple Game [Windows PC] [TP].zip")
        assert info is not None
        assert info.version == ''
        assert info.version_tuple == (0,)

    def test_extensions_stripped(self):
        for ext in ['.zip', '.7z', '.rar']:
            info = parse_teknoparrot_filename(
                f"Game [Sega Nu] [TP]{ext}")
            assert info is not None
            assert ext not in info.name

    def test_base_title_cleaned(self):
        info = parse_teknoparrot_filename(
            "Cool Game (1.0) (2020) [Sega Nu] [TP].zip")
        assert info is not None
        # Base title should not contain parenthesized items
        assert '(' not in info.base_title
        assert ')' not in info.base_title

    def test_en_region_tag(self):
        info = parse_teknoparrot_filename(
            "Game [En] [Sega Nu] [TP].zip")
        assert info is not None
        assert info.region == 'Export'


# =============================================================================
# TeknoParrot: normalize_teknoparrot_title
# =============================================================================

class TestNormalizeTeknoParrotTitle:

    @pytest.mark.parametrize("title,expected", [
        ("Initial D", "initial d"),
        ("Initial D Arcade Stage", "initial d"),
        ("Initial D Stage", "initial d"),
        ("Initial D Arcade", "initial d"),
        ("Game Ver.2", "game"),
        ("Game Ver 3.1", "game"),
        ("Game!!!", "game"),
        ("  Spaced  Out  ", "spaced out"),
    ])
    def test_normalization(self, title, expected):
        assert normalize_teknoparrot_title(title) == expected


# =============================================================================
# TeknoParrot: region priority / version selection
# =============================================================================

class TestTeknoParrotRegionPriority:

    @pytest.mark.parametrize("region,expected", [
        ('Export', 0), ('USA', 1), ('World', 2), ('Europe', 3),
        ('Asia', 4), ('Japan', 5), ('Korea', 6), ('Unknown', 10),
        ('Other', 10),
    ])
    def test_default_priorities(self, region, expected):
        assert get_teknoparrot_region_priority(region) == expected

    def test_custom_priority_list(self):
        priority = ['Japan', 'USA', 'Europe']
        assert get_teknoparrot_region_priority('Japan', priority) == 0
        assert get_teknoparrot_region_priority('USA', priority) == 1
        assert get_teknoparrot_region_priority('Europe', priority) == 2
        # Not in list => len + 1
        assert get_teknoparrot_region_priority('Korea', priority) == 4

    def test_custom_priority_case_insensitive(self):
        priority = ['japan', 'usa']
        assert get_teknoparrot_region_priority('JAPAN', priority) == 0
        assert get_teknoparrot_region_priority('Japan', priority) == 0


class TestSelectBestTeknoParrotVersion:

    def test_empty_list(self):
        assert select_best_teknoparrot_version([]) is None

    def test_single_game(self):
        game = _make_tp_game("Game [TP].zip")
        assert select_best_teknoparrot_version([game]) is game

    def test_higher_version_preferred(self):
        v1 = _make_tp_game("Game v1 [TP].zip", version='1.0',
                           version_tuple=(1, 0))
        v2 = _make_tp_game("Game v2 [TP].zip", version='2.0',
                           version_tuple=(2, 0))
        best = select_best_teknoparrot_version([v1, v2])
        assert best.version == '2.0'

    def test_newer_year_preferred(self):
        old = _make_tp_game("Game 2015 [TP].zip", year=2015)
        new = _make_tp_game("Game 2020 [TP].zip", year=2020)
        best = select_best_teknoparrot_version([old, new])
        assert best.year == 2020

    def test_region_tiebreaker(self):
        jp = _make_tp_game("Game JP [TP].zip", region='Japan')
        us = _make_tp_game("Game US [TP].zip", region='USA')
        best = select_best_teknoparrot_version([jp, us])
        assert best.region == 'USA'

    def test_version_trumps_region(self):
        jp_v2 = _make_tp_game("Game JP v2 [TP].zip", region='Japan',
                              version='2.0', version_tuple=(2, 0))
        us_v1 = _make_tp_game("Game US v1 [TP].zip", region='USA',
                              version='1.0', version_tuple=(1, 0))
        best = select_best_teknoparrot_version([jp_v2, us_v1])
        assert best.version == '2.0'

    def test_custom_region_priority(self):
        jp = _make_tp_game("Game JP [TP].zip", region='Japan')
        us = _make_tp_game("Game US [TP].zip", region='USA')
        best = select_best_teknoparrot_version(
            [jp, us], region_priority=['Japan', 'USA'])
        assert best.region == 'Japan'


# =============================================================================
# TeknoParrot: should_include_teknoparrot_game
# =============================================================================

class TestShouldIncludeTeknoParrotGame:

    def test_no_filter_includes_all(self):
        game = _make_tp_game("Game [TP].zip", platform='Sega Lindbergh')
        included, _ = should_include_teknoparrot_game(game)
        assert included is True

    def test_include_platform_match(self):
        game = _make_tp_game("Game [TP].zip", platform='Sega Lindbergh')
        included, _ = should_include_teknoparrot_game(
            game, include_platforms={'Sega Lindbergh'})
        assert included is True

    def test_include_platform_no_match(self):
        game = _make_tp_game("Game [TP].zip", platform='Custom HW')
        included, _ = should_include_teknoparrot_game(
            game, include_platforms={'Sega Lindbergh'})
        assert included is False

    def test_exclude_platform(self):
        game = _make_tp_game("Game [TP].zip", platform='Custom HW')
        included, reason = should_include_teknoparrot_game(
            game, exclude_platforms={'Custom HW'})
        assert included is False
        assert 'Excluded' in reason

    def test_include_platform_partial_match(self):
        """Platform matching uses substring."""
        game = _make_tp_game("Game [TP].zip", platform='Sega Lindbergh Blue')
        included, _ = should_include_teknoparrot_game(
            game, include_platforms={'Sega Lindbergh'})
        assert included is True

    def test_exclude_overrides_include(self):
        game = _make_tp_game("Game [TP].zip", platform='Sega Lindbergh')
        included, _ = should_include_teknoparrot_game(
            game, include_platforms={'Sega Lindbergh'},
            exclude_platforms={'Sega Lindbergh'})
        assert included is False


# =============================================================================
# TeknoParrot: parse_teknoparrot_dat
# =============================================================================

TP_DAT_XML = '''\
<?xml version="1.0" encoding="utf-8"?>
<datafile>
  <game name="initiald8">
    <description>Initial D Arcade Stage 8 (2.30.01) (2014) [Sega RingEdge 2] [TP]</description>
    <year>2014</year>
    <manufacturer>Sega</manufacturer>
  </game>
  <game name="vf5">
    <description>Virtua Fighter 5 [Sega Lindbergh] [TP]</description>
    <year>2006</year>
    <manufacturer>Sega</manufacturer>
  </game>
  <game name="chdgame">
    <description>CHD Game [Taito Type X2] [TP]</description>
    <year>2010</year>
    <manufacturer>Taito</manufacturer>
    <disk name="chdgame_disc"/>
  </game>
  <game name="nodesc">
    <year>2020</year>
  </game>
  <game name="">
    <description>Empty Name Game [TP]</description>
  </game>
</datafile>'''


class TestParseTeknoParrotDat:

    @pytest.fixture
    def tp_games(self, tmp_path):
        p = tmp_path / "teknoparrot.dat"
        p.write_text(TP_DAT_XML, encoding='utf-8')
        return parse_teknoparrot_dat(str(p))

    def test_games_parsed(self, tp_games):
        # Empty-name game should be skipped
        assert len(tp_games) == 4

    def test_game_with_tp_description(self, tp_games):
        game = tp_games['initiald8']
        assert game.version == '2.30.01'
        assert game.platform == 'Sega RingEdge 2'
        assert game.year == 2014

    def test_game_without_version(self, tp_games):
        game = tp_games['vf5']
        assert game.platform == 'Sega Lindbergh'
        assert game.version == ''

    def test_chd_detected(self, tp_games):
        game = tp_games['chdgame']
        assert game.has_chd is True
        assert 'chdgame_disc.chd' in game.chd_names

    def test_no_description_fallback(self, tp_games):
        game = tp_games['nodesc']
        # Should use name-based fallback when no [TP] in description
        assert game.name == 'nodesc'

    def test_name_overridden(self, tp_games):
        # parse_teknoparrot_dat sets info.name to the XML name attribute
        assert tp_games['initiald8'].name == 'initiald8'

    def test_invalid_xml(self, tmp_path):
        p = tmp_path / "bad.dat"
        p.write_text("<<<not valid xml>>>", encoding='utf-8')
        assert parse_teknoparrot_dat(str(p)) == {}

    def test_empty_file(self, tmp_path):
        p = tmp_path / "empty.dat"
        p.write_text("", encoding='utf-8')
        assert parse_teknoparrot_dat(str(p)) == {}


# =============================================================================
# TeknoParrot: filter_teknoparrot_network_roms
# =============================================================================

class TestFilterTeknoParrotNetworkRoms:

    @pytest.fixture
    def tp_urls(self):
        urls = [
            "http://roms.test/Initial%20D%20(1.0)%20(2012)%20[Sega%20RingEdge%202]%20[TP].zip",
            "http://roms.test/Initial%20D%20(2.0)%20(2014)%20[Sega%20RingEdge%202]%20[TP].zip",
            "http://roms.test/Virtua%20Fighter%205%20[Sega%20Lindbergh]%20[TP].zip",
            "http://roms.test/Some%20Racer%20Japan%20[Taito%20Type%20X2]%20[TP].zip",
            "http://roms.test/normal_game.zip",
        ]
        sizes = {u: 5000 for u in urls}
        return urls, sizes

    def test_basic_filtering(self, tp_urls):
        urls, sizes = tp_urls
        selected, info = filter_teknoparrot_network_roms(
            urls, url_sizes=sizes)
        assert len(selected) > 0
        assert info['source_size'] == 25000

    def test_version_dedup(self, tp_urls):
        """Two Initial D versions should be deduped to latest."""
        urls, sizes = tp_urls
        selected, _ = filter_teknoparrot_network_roms(
            urls, url_sizes=sizes)
        id_urls = [u for u in selected if 'Initial' in u]
        assert len(id_urls) == 1
        assert '2.0' in id_urls[0]

    def test_keep_all_versions(self, tp_urls):
        urls, sizes = tp_urls
        selected, _ = filter_teknoparrot_network_roms(
            urls, url_sizes=sizes, keep_all_versions=True)
        id_urls = [u for u in selected if 'Initial' in u]
        assert len(id_urls) == 2

    def test_no_filter_returns_all(self, tp_urls):
        urls, sizes = tp_urls
        selected, _ = filter_teknoparrot_network_roms(
            urls, url_sizes=sizes, no_filter=True)
        assert len(selected) == len(urls)

    def test_non_tp_files_excluded_in_filter_mode(self, tp_urls):
        urls, sizes = tp_urls
        selected, _ = filter_teknoparrot_network_roms(
            urls, url_sizes=sizes)
        non_tp = [u for u in selected if 'normal_game' in u]
        assert len(non_tp) == 0

    def test_non_tp_files_kept_in_no_filter(self, tp_urls):
        urls, sizes = tp_urls
        selected, _ = filter_teknoparrot_network_roms(
            urls, url_sizes=sizes, no_filter=True)
        non_tp = [u for u in selected if 'normal_game' in u]
        assert len(non_tp) == 1

    def test_english_only_excludes_japan(self, tp_urls):
        urls, sizes = tp_urls
        selected, _ = filter_teknoparrot_network_roms(
            urls, url_sizes=sizes, english_only=True)
        jp_urls = [u for u in selected if 'Japan' in u]
        assert len(jp_urls) == 0

    def test_include_patterns(self, tp_urls):
        urls, sizes = tp_urls
        selected, _ = filter_teknoparrot_network_roms(
            urls, url_sizes=sizes, include_patterns=['*Virtua*'])
        assert len(selected) == 1
        assert 'Virtua' in selected[0]

    def test_exclude_patterns(self, tp_urls):
        urls, sizes = tp_urls
        selected, _ = filter_teknoparrot_network_roms(
            urls, url_sizes=sizes, exclude_patterns=['*Virtua*'])
        vf_urls = [u for u in selected if 'Virtua' in u]
        assert len(vf_urls) == 0

    def test_platform_include(self, tp_urls):
        urls, sizes = tp_urls
        selected, _ = filter_teknoparrot_network_roms(
            urls, url_sizes=sizes,
            include_platforms={'Sega Lindbergh'})
        # Only VF5 on Lindbergh should pass
        assert len(selected) == 1
        assert 'Virtua' in selected[0]

    def test_platform_exclude(self, tp_urls):
        urls, sizes = tp_urls
        selected, _ = filter_teknoparrot_network_roms(
            urls, url_sizes=sizes,
            exclude_platforms={'Sega Lindbergh'})
        vf_urls = [u for u in selected if 'Virtua' in u]
        assert len(vf_urls) == 0

    def test_empty_urls(self):
        selected, info = filter_teknoparrot_network_roms([])
        assert selected == []
        assert info['source_size'] == 0
        assert info['selected_size'] == 0

    def test_size_info_tracking(self, tp_urls):
        urls, sizes = tp_urls
        _, info = filter_teknoparrot_network_roms(
            urls, url_sizes=sizes)
        assert info['selected_size'] <= info['source_size']
        assert info['selected_size'] > 0

    def test_region_priority_selection(self):
        """With custom region priority, JP should be preferred."""
        urls = [
            "http://roms.test/Cool%20Racer%20(Export)%20[Sega%20Nu]%20[TP].zip",
            "http://roms.test/Cool%20Racer%20(Japan)%20[Sega%20Nu]%20[TP].zip",
        ]
        sizes = {u: 1000 for u in urls}
        selected, _ = filter_teknoparrot_network_roms(
            urls, url_sizes=sizes,
            region_priority=['Japan', 'Export'])
        assert len(selected) == 1
        assert 'Japan' in selected[0]

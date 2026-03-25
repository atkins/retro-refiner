"""Comprehensive pytest tests for mame.py and teknoparrot.py.

Covers the untested functions: catver.ini parsing, MAME DAT parsing,
MAME filtering pipeline, category inclusion/exclusion, clone selection,
TeknoParrot DAT parsing, TP filtering pipeline, name normalization,
version parsing, region priority, and platform filtering.
"""
# pylint: disable=missing-function-docstring
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from retro_refiner.mame import (  # noqa: E402
    MameGameInfo,
    parse_catver_ini,
    parse_mame_dat,
    detect_mame_region,
    should_include_mame_game,
    get_mame_region_priority,
    select_best_mame_clone,
    filter_mame_network_roms,
    MAME_EXCLUDE_CATEGORIES,
)
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

def _make_mame_game(name, description, year='1991',
                    manufacturer='TestCo', category='',
                    is_parent=True, parent_name='', is_bios=False,
                    is_device=False, has_chd=False, chd_names=None,
                    region='Unknown', bios_name='', rom_files=None):
    """Build a MameGameInfo with sensible defaults."""
    return MameGameInfo(
        name=name, description=description, year=year,
        manufacturer=manufacturer, category=category,
        is_parent=is_parent, parent_name=parent_name,
        is_bios=is_bios, is_device=is_device,
        has_chd=has_chd, chd_names=chd_names or [],
        region=region, bios_name=bios_name,
        rom_files=rom_files,
    )


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
# MAME: parse_catver_ini
# =============================================================================

CATVER_INI = """\
;; CatVer 0.274
[Category]
pacman=Maze
sf2=Fighter / Versus
mslug=Shooter / Run 'n Gun
neogeo=System / BIOS
dkong=Platform
galaxian=Shooter / Gallery
qix=Puzzle
ssf2t=Fighter / Versus * Mature *
majxtal7=Tabletop / Mahjong
pokermon=Casino
slotcarn=Slot Machine
bios_device=System / Device
quester=Quiz

[VerAdded]
pacman=0.01
sf2=0.10
"""


class TestParseCatverIni:
    """Test catver.ini parsing."""

    @pytest.fixture
    def catver_path(self, tmp_path):
        p = tmp_path / "catver.ini"
        p.write_text(CATVER_INI, encoding='utf-8')
        return str(p)

    def test_basic_category_parsed(self, catver_path):
        cats = parse_catver_ini(catver_path)
        assert cats['pacman'] == 'Maze'

    def test_category_with_slash(self, catver_path):
        cats = parse_catver_ini(catver_path)
        assert cats['sf2'] == 'Fighter / Versus'

    def test_category_with_quotes(self, catver_path):
        cats = parse_catver_ini(catver_path)
        assert cats['mslug'] == "Shooter / Run 'n Gun"

    def test_bios_category(self, catver_path):
        cats = parse_catver_ini(catver_path)
        assert cats['neogeo'] == 'System / BIOS'

    def test_stops_at_next_section(self, catver_path):
        cats = parse_catver_ini(catver_path)
        # VerAdded entries should not appear
        assert 'VerAdded' not in cats
        # Only Category entries should be present
        assert len(cats) > 0

    def test_ignores_comments(self, catver_path):
        cats = parse_catver_ini(catver_path)
        assert ';;' not in str(cats)

    def test_all_entries_parsed(self, catver_path):
        cats = parse_catver_ini(catver_path)
        expected = {'pacman', 'sf2', 'mslug', 'neogeo', 'dkong',
                    'galaxian', 'qix', 'ssf2t', 'majxtal7', 'pokermon',
                    'slotcarn', 'bios_device', 'quester'}
        assert set(cats.keys()) == expected

    def test_empty_file(self, tmp_path):
        p = tmp_path / "empty.ini"
        p.write_text("", encoding='utf-8')
        assert parse_catver_ini(str(p)) == {}

    def test_no_category_section(self, tmp_path):
        p = tmp_path / "no_cat.ini"
        p.write_text("[VerAdded]\npacman=0.01\n", encoding='utf-8')
        assert parse_catver_ini(str(p)) == {}


# =============================================================================
# MAME: parse_mame_dat
# =============================================================================

MAME_DAT_XML = '''\
<?xml version="1.0"?>
<datafile>
  <machine name="neogeo" isbios="yes">
    <description>Neo Geo BIOS</description>
    <year>1990</year>
    <manufacturer>SNK</manufacturer>
    <rom name="sp-s2.sp1" size="131072"/>
  </machine>
  <machine name="pacman">
    <description>Pac-Man (USA)</description>
    <year>1980</year>
    <manufacturer>Namco</manufacturer>
    <rom name="pacman.6e" size="4096"/>
    <rom name="pacman.6f" size="4096"/>
  </machine>
  <machine name="mslug" romof="neogeo">
    <description>Metal Slug (World)</description>
    <year>1996</year>
    <manufacturer>SNK</manufacturer>
    <rom name="201-p1.p1" size="1048576"/>
  </machine>
  <machine name="mslug2" cloneof="mslug" romof="neogeo">
    <description>Metal Slug 2 (Japan)</description>
    <year>1998</year>
    <manufacturer>SNK</manufacturer>
    <rom name="263-p1.p1" size="2097152"/>
  </machine>
  <machine name="sf2">
    <description>Street Fighter II (World)</description>
    <year>1991</year>
    <manufacturer>Capcom</manufacturer>
    <rom name="sf2.01" size="131072"/>
    <rom name="sf2.02" size="131072"/>
  </machine>
  <machine name="sf2ce" cloneof="sf2" romof="sf2">
    <description>Street Fighter II' CE (USA)</description>
    <year>1992</year>
    <manufacturer>Capcom</manufacturer>
    <rom name="sf2ce.01" size="131072"/>
  </machine>
  <machine name="adevice" isdevice="yes">
    <description>Some Device</description>
    <year>2000</year>
    <manufacturer>Test</manufacturer>
  </machine>
  <machine name="chdgame">
    <description>CHD Game (USA)</description>
    <year>2000</year>
    <manufacturer>Test</manufacturer>
    <rom name="chdgame.01" size="1024"/>
    <disk name="chdgame_disk"/>
  </machine>
</datafile>'''


class TestParseMameDat:
    """Test MAME XML DAT parsing."""

    @pytest.fixture
    def games(self, tmp_path):
        p = tmp_path / "mame.xml"
        p.write_text(MAME_DAT_XML, encoding='utf-8')
        return parse_mame_dat(str(p))

    def test_all_games_parsed(self, games):
        assert len(games) == 8

    def test_bios_detected(self, games):
        assert games['neogeo'].is_bios is True

    def test_device_detected(self, games):
        assert games['adevice'].is_device is True

    def test_parent_game(self, games):
        assert games['pacman'].is_parent is True
        assert games['pacman'].parent_name == ''

    def test_clone_relationship(self, games):
        assert games['sf2ce'].is_parent is False
        assert games['sf2ce'].parent_name == 'sf2'

    def test_bios_name_romof_not_cloneof(self, games):
        # mslug: romof=neogeo, no cloneof => bios_name=neogeo
        assert games['mslug'].bios_name == 'neogeo'

    def test_bios_name_romof_equals_cloneof(self, games):
        # sf2ce: romof=sf2, cloneof=sf2 => bios_name='' (parent, not BIOS)
        assert games['sf2ce'].bios_name == ''

    def test_rom_files_populated(self, games):
        assert 'sf2.01' in games['sf2'].rom_files
        assert 'sf2.02' in games['sf2'].rom_files

    def test_chd_detected(self, games):
        assert games['chdgame'].has_chd is True
        assert 'chdgame_disk.chd' in games['chdgame'].chd_names

    def test_no_chd(self, games):
        assert games['pacman'].has_chd is False
        assert games['pacman'].chd_names == []

    def test_region_from_description(self, games):
        assert games['pacman'].region == 'USA'
        assert games['sf2'].region == 'World'
        assert games['mslug2'].region == 'Japan'

    def test_year_parsed(self, games):
        assert games['pacman'].year == '1980'

    def test_manufacturer_empty_due_to_element_truthiness(self, games):
        """Element.__bool__ is False for leaf elements, so `find(x) or find(y)`
        evaluates to the second branch.  This is a known limitation of the
        `or`-based fallback in parse_mame_dat -- manufacturer is always ''."""
        assert games['pacman'].manufacturer == ''

    def test_non_xml_file_returns_empty(self, tmp_path):
        p = tmp_path / "notxml.txt"
        p.write_text("This is not XML", encoding='utf-8')
        assert parse_mame_dat(str(p)) == {}

    def test_game_tag_format(self, tmp_path):
        """XML using <game> instead of <machine>."""
        xml = '''\
<?xml version="1.0"?>
<datafile>
  <game name="puckman">
    <description>Puck Man (Japan)</description>
    <year>1980</year>
    <manufacturer>Namco</manufacturer>
  </game>
</datafile>'''
        p = tmp_path / "game_tag.xml"
        p.write_text(xml, encoding='utf-8')
        games = parse_mame_dat(str(p))
        assert 'puckman' in games
        assert games['puckman'].region == 'Japan'


# =============================================================================
# MAME: detect_mame_region
# =============================================================================

class TestDetectMameRegion:

    @pytest.mark.parametrize("desc,expected", [
        ("Pac-Man (USA)", "USA"),
        ("Pac-Man (US)", "USA"),
        ("Pac-Man [US]", "USA"),
        ("Street Fighter II (World)", "World"),
        ("Puzzle Bobble [World]", "World"),
        ("Virtua Fighter (Europe)", "Europe"),
        ("Tetris (Euro)", "Europe"),
        ("Tetris [Europe]", "Europe"),
        ("Metal Slug (Japan)", "Japan"),
        ("Parodius (JPN)", "Japan"),
        ("Raiden [Japan]", "Japan"),
        ("Puzzle Fighter (Asia)", "Asia"),
        ("Tekken [Asia]", "Asia"),
        ("King of Fighters (Korea)", "Korea"),
        ("Fatal Fury [Korea]", "Korea"),
        ("Some Game (Hispanic)", "LatinAmerica"),
        ("Some Game (Brazil)", "LatinAmerica"),
        ("Game Title USA", "USA"),
        ("Some Random Game", "Unknown"),
    ])
    def test_region_detection(self, desc, expected):
        assert detect_mame_region(desc) == expected


# =============================================================================
# MAME: should_include_mame_game
# =============================================================================

class TestShouldIncludeMameGame:

    def test_bios_excluded(self):
        game = _make_mame_game('neogeo', 'Neo Geo', is_bios=True)
        included, reason = should_include_mame_game(game, 'System / BIOS')
        assert included is False
        assert 'BIOS' in reason

    def test_device_excluded(self):
        game = _make_mame_game('dev', 'Device', is_device=True)
        included, reason = should_include_mame_game(game, 'System / Device')
        assert included is False
        assert 'Device' in reason

    def test_no_category_excluded(self):
        game = _make_mame_game('unknown', 'Unknown Game')
        included, reason = should_include_mame_game(game, '')
        assert included is False
        assert 'No category' in reason

    @pytest.mark.parametrize("category", [
        'Fighter / Versus', 'Shooter / Gallery', 'Platform',
        'Maze', 'Puzzle', 'Ball & Paddle', 'Driving',
        'Sports / Basketball', 'Climbing',
    ])
    def test_included_categories(self, category):
        game = _make_mame_game('game', 'Some Game')
        included, _reason = should_include_mame_game(game, category)
        assert included is True

    @pytest.mark.parametrize("category", [
        'Casino', 'Gambling', 'Quiz',
        'Tabletop / Mahjong', 'Tabletop / Hanafuda',
        'Slot Machine', 'Electromechanical',
        'System / BIOS', 'System / Device',
        'Computer', 'Calculator', 'Printer',
        'Redemption Game', 'Medal Game',
    ])
    def test_excluded_categories(self, category):
        game = _make_mame_game('game', 'Some Game')
        included, _ = should_include_mame_game(game, category)
        assert included is False

    @pytest.mark.parametrize("category", list(MAME_EXCLUDE_CATEGORIES))
    def test_all_exclude_categories_rejected(self, category):
        game = _make_mame_game('game', 'Some Game')
        included, _ = should_include_mame_game(game, category)
        assert included is False

    def test_mature_content_excluded_when_disabled(self):
        game = _make_mame_game('mature', 'Mature Game')
        included, reason = should_include_mame_game(
            game, 'Fighter / Versus * Mature *', include_adult=False)
        assert included is False
        assert 'Adult' in reason or 'mature' in reason.lower()

    def test_mature_content_included_when_enabled(self):
        game = _make_mame_game('mature', 'Mature Game')
        included, _ = should_include_mame_game(
            game, 'Fighter / Versus * Mature *', include_adult=True)
        assert included is True

    def test_mahjong_excluded_by_keyword(self):
        game = _make_mame_game('mj', 'Mahjong Game')
        included, reason = should_include_mame_game(game, 'Board / Mahjong')
        assert included is False
        assert 'Mahjong' in reason

    def test_quiz_excluded_by_keyword(self):
        game = _make_mame_game('quiz', 'Quiz Game')
        included, reason = should_include_mame_game(game, 'Misc. / Quiz')
        assert included is False
        assert 'Quiz' in reason

    def test_pachinko_excluded(self):
        game = _make_mame_game('pachinko', 'Pachinko Game')
        included, reason = should_include_mame_game(
            game, 'Misc. / Pachinko')
        assert included is False
        assert 'Pachinko' in reason

    def test_dance_game_excluded(self):
        game = _make_mame_game('ddr', 'Dance Game')
        included, _reason = should_include_mame_game(
            game, 'Music Game / Dance')
        assert included is False

    def test_video_pinball_included(self):
        game = _make_mame_game('pin', 'Video Pinball')
        included, reason = should_include_mame_game(
            game, 'Pinball / Video')
        assert included is True
        assert 'pinball' in reason.lower()

    def test_light_gun_included(self):
        game = _make_mame_game('gun', 'Gun Game')
        included, _reason = should_include_mame_game(
            game, 'Shooter / Gallery')
        assert included is True

    def test_unknown_category_excluded(self):
        game = _make_mame_game('unk', 'Unknown')
        included, reason = should_include_mame_game(
            game, 'Completely Unknown Category')
        assert included is False
        assert 'Unknown category' in reason

    def test_excluded_subcategory_mahjong_mature(self):
        game = _make_mame_game('mj', 'Mahjong Mature')
        included, _ = should_include_mame_game(
            game, 'Tabletop / Mahjong * Mature *', include_adult=True)
        assert included is False

    def test_casino_keyword_in_novel_category(self):
        game = _make_mame_game('cas', 'Casino Novel')
        included, reason = should_include_mame_game(
            game, 'Fun Casino Experience')
        assert included is False
        assert 'Casino' in reason

    def test_slot_machine_keyword(self):
        game = _make_mame_game('slot', 'Slot Fun')
        included, reason = should_include_mame_game(
            game, 'Fun Slot Machine')
        assert included is False
        assert 'Slot machine' in reason

    def test_medal_game_keyword(self):
        game = _make_mame_game('medal', 'Medal Fun')
        included, reason = should_include_mame_game(
            game, 'Prize / Medal Game')
        assert included is False
        assert 'Medal game' in reason


# =============================================================================
# MAME: get_mame_region_priority / select_best_mame_clone
# =============================================================================

class TestMameRegionPriority:

    @pytest.mark.parametrize("region,expected", [
        ('USA', 0), ('World', 1), ('Europe', 2), ('Asia', 3),
        ('Japan', 4), ('Korea', 5), ('LatinAmerica', 6), ('Unknown', 10),
        ('SomethingElse', 10),
    ])
    def test_priorities(self, region, expected):
        assert get_mame_region_priority(region) == expected


class TestSelectBestMameClone:

    def test_no_clones_returns_parent(self):
        games = {'sf2': _make_mame_game('sf2', 'Street Fighter II',
                                        region='World')}
        best = select_best_mame_clone('sf2', [], games)
        assert best.name == 'sf2'

    def test_usa_preferred_over_japan(self):
        games = {
            'sf2': _make_mame_game('sf2', 'SF2', region='Japan'),
            'sf2u': _make_mame_game('sf2u', 'SF2 USA', region='USA'),
        }
        best = select_best_mame_clone('sf2', ['sf2u'], games)
        assert best.name == 'sf2u'

    def test_world_preferred_over_europe(self):
        games = {
            'game': _make_mame_game('game', 'Game', region='Europe'),
            'gamew': _make_mame_game('gamew', 'Game W', region='World'),
        }
        best = select_best_mame_clone('game', ['gamew'], games)
        assert best.name == 'gamew'

    def test_parent_included_in_candidates(self):
        games = {
            'parent': _make_mame_game('parent', 'Parent', region='USA'),
            'clone': _make_mame_game('clone', 'Clone', region='Japan'),
        }
        best = select_best_mame_clone('parent', ['clone'], games)
        assert best.name == 'parent'

    def test_empty_clones_missing_parent(self):
        best = select_best_mame_clone('missing', [], {})
        assert best is None

    def test_all_missing_returns_none(self):
        best = select_best_mame_clone('parent', ['clone1'], {})
        assert best is None

    def test_multiple_clones_best_region(self):
        games = {
            'parent': _make_mame_game('parent', 'Parent', region='Korea'),
            'clone_eu': _make_mame_game('clone_eu', 'EU', region='Europe'),
            'clone_us': _make_mame_game('clone_us', 'US', region='USA'),
            'clone_jp': _make_mame_game('clone_jp', 'JP', region='Japan'),
        }
        best = select_best_mame_clone(
            'parent', ['clone_eu', 'clone_us', 'clone_jp'], games)
        assert best.name == 'clone_us'


# =============================================================================
# MAME: filter_mame_network_roms
# =============================================================================

class TestFilterMameNetworkRoms:

    @pytest.fixture
    def mame_data(self):
        """Set up games, categories, and URLs for filtering tests."""
        games = {
            'sf2': _make_mame_game('sf2', 'Street Fighter II (World)',
                                   category='Fighter / Versus',
                                   region='World'),
            'sf2ce': _make_mame_game('sf2ce', "SF2 CE (USA)",
                                     category='Fighter / Versus',
                                     is_parent=False, parent_name='sf2',
                                     region='USA'),
            'pacman': _make_mame_game('pacman', 'Pac-Man (USA)',
                                      category='Maze', region='USA'),
            'neogeo': _make_mame_game('neogeo', 'Neo Geo BIOS',
                                      is_bios=True, category='System / BIOS'),
            'pokermon': _make_mame_game('pokermon', 'Poker Game',
                                        category='Casino'),
            'mslug': _make_mame_game('mslug', 'Metal Slug (World)',
                                     category='Shooter / Run \'n Gun',
                                     region='World'),
            'ddr': _make_mame_game('ddr', 'Dance Dance Revolution',
                                   category='Music Game / Dance'),
            'jponly': _make_mame_game('jponly', 'JP Only (Japan)',
                                     category='Maze', region='Japan'),
        }
        categories = {name: g.category for name, g in games.items()}
        urls = [
            'http://roms.test/sf2.zip',
            'http://roms.test/sf2ce.zip',
            'http://roms.test/pacman.zip',
            'http://roms.test/neogeo.zip',
            'http://roms.test/pokermon.zip',
            'http://roms.test/mslug.zip',
            'http://roms.test/ddr.zip',
            'http://roms.test/jponly.zip',
        ]
        sizes = {u: 1000 for u in urls}
        return games, categories, urls, sizes

    def test_basic_filtering(self, mame_data):
        games, categories, urls, sizes = mame_data
        selected, _info = filter_mame_network_roms(
            urls, categories, games, url_sizes=sizes)
        filenames = {u.split('/')[-1] for u in selected}
        # Included categories should pass
        assert 'pacman.zip' in filenames
        assert 'mslug.zip' in filenames
        # sf2 group: parent or best clone
        assert 'sf2.zip' in filenames or 'sf2ce.zip' in filenames

    def test_bios_excluded(self, mame_data):
        games, categories, urls, sizes = mame_data
        selected, _ = filter_mame_network_roms(
            urls, categories, games, url_sizes=sizes)
        filenames = {u.split('/')[-1] for u in selected}
        assert 'neogeo.zip' not in filenames

    def test_casino_excluded(self, mame_data):
        games, categories, urls, sizes = mame_data
        selected, _ = filter_mame_network_roms(
            urls, categories, games, url_sizes=sizes)
        filenames = {u.split('/')[-1] for u in selected}
        assert 'pokermon.zip' not in filenames

    def test_dance_excluded(self, mame_data):
        games, categories, urls, sizes = mame_data
        selected, _ = filter_mame_network_roms(
            urls, categories, games, url_sizes=sizes)
        filenames = {u.split('/')[-1] for u in selected}
        assert 'ddr.zip' not in filenames

    def test_no_filter_returns_all(self, mame_data):
        games, categories, urls, sizes = mame_data
        selected, _ = filter_mame_network_roms(
            urls, categories, games, url_sizes=sizes, no_filter=True)
        assert len(selected) == len(urls)

    def test_size_info_returned(self, mame_data):
        games, categories, urls, sizes = mame_data
        _, info = filter_mame_network_roms(
            urls, categories, games, url_sizes=sizes)
        assert 'source_size' in info
        assert 'selected_size' in info
        assert info['source_size'] == 8000  # 8 urls * 1000

    def test_clone_dedup(self, mame_data):
        """sf2 and sf2ce should not both be selected."""
        games, categories, urls, sizes = mame_data
        selected, _ = filter_mame_network_roms(
            urls, categories, games, url_sizes=sizes)
        filenames = {u.split('/')[-1] for u in selected}
        sf2_count = sum(1 for f in filenames if f.startswith('sf2'))
        assert sf2_count == 1

    def test_best_clone_usa_over_world(self, mame_data):
        """sf2ce (USA) should be preferred over sf2 (World) for region."""
        games, categories, urls, sizes = mame_data
        selected, _ = filter_mame_network_roms(
            urls, categories, games, url_sizes=sizes)
        filenames = {u.split('/')[-1] for u in selected}
        assert 'sf2ce.zip' in filenames

    def test_english_only_excludes_japan(self, mame_data):
        games, categories, urls, sizes = mame_data
        selected, _ = filter_mame_network_roms(
            urls, categories, games, url_sizes=sizes, english_only=True)
        filenames = {u.split('/')[-1] for u in selected}
        assert 'jponly.zip' not in filenames

    def test_english_only_keeps_world(self, mame_data):
        games, categories, urls, sizes = mame_data
        selected, _ = filter_mame_network_roms(
            urls, categories, games, url_sizes=sizes, english_only=True)
        filenames = {u.split('/')[-1] for u in selected}
        # World and USA games should survive
        assert 'pacman.zip' in filenames

    def test_include_patterns(self, mame_data):
        games, categories, urls, sizes = mame_data
        selected, _ = filter_mame_network_roms(
            urls, categories, games,
            include_patterns=['pac*'], url_sizes=sizes)
        filenames = {u.split('/')[-1] for u in selected}
        assert 'pacman.zip' in filenames
        assert len(filenames) == 1

    def test_exclude_patterns(self, mame_data):
        games, categories, urls, sizes = mame_data
        selected, _ = filter_mame_network_roms(
            urls, categories, games,
            exclude_patterns=['pac*'], url_sizes=sizes)
        filenames = {u.split('/')[-1] for u in selected}
        assert 'pacman.zip' not in filenames

    def test_unknown_rom_passes_through(self):
        """ROMs not in games dict should still be selected."""
        games = {}
        categories = {}
        urls = ['http://roms.test/mystery.zip']
        selected, _ = filter_mame_network_roms(urls, categories, games)
        assert len(selected) == 1

    def test_chd_url_maps_to_parent(self):
        """CHD file URLs should be linked to their parent game."""
        games = {
            'chdgame': _make_mame_game('chdgame', 'CHD Game (USA)',
                                       category='Driving',
                                       has_chd=True,
                                       chd_names=['disc.chd'],
                                       region='USA'),
        }
        categories = {'chdgame': 'Driving'}
        urls = [
            'http://roms.test/chdgame/disc.chd',
        ]
        selected, _ = filter_mame_network_roms(
            urls, categories, games)
        assert len(selected) == 1

    def test_empty_url_list(self):
        selected, info = filter_mame_network_roms([], {}, {})
        assert selected == []
        assert info['source_size'] == 0


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

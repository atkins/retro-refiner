"""Tests for retro_refiner v2 wrapper modules."""
import sys
from pathlib import Path

# Ensure project root is on sys.path so retro_refiner package is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


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
# Systems Module Tests
# =============================================================================

def test_systems():
    """Test that the systems module loads correctly."""
    print("\n" + "="*60)
    print("SYSTEMS MODULE TESTS")
    print("="*60)

    from retro_refiner.systems import load_system_data, SystemData

    sysdata = load_system_data()
    if isinstance(sysdata, SystemData):
        results.ok("load_system_data returns SystemData")
    else:
        results.fail("load_system_data returns SystemData",
                     "SystemData", type(sysdata).__name__)

    if len(sysdata.known_systems) > 100:
        results.ok(f"loaded {len(sysdata.known_systems)} known systems")
    else:
        results.fail("loaded many known systems",
                     ">100", str(len(sysdata.known_systems)))

    if '.sfc' in sysdata.extension_to_system:
        results.ok("extension_to_system has .sfc")
    else:
        results.fail("extension_to_system has .sfc",
                     ".sfc in map", "missing")

    if 'super-nintendo' in sysdata.folder_aliases:
        results.ok("folder_aliases has 'super-nintendo'")
    else:
        results.fail("folder_aliases has 'super-nintendo'",
                     "alias exists", "missing")


# =============================================================================
# Models Tests
# =============================================================================

def test_models():
    """Test dataclass construction for all model types."""
    print("\n" + "="*60)
    print("MODELS TESTS")
    print("="*60)

    from retro_refiner.models import (
        ProgressEvent, ExcludedRom, FilterStats, FilterResult,
        ScanResult, SystemScanInfo
    )

    # ProgressEvent
    evt = ProgressEvent(phase="scanning", message="test", current=5, total=10)
    if evt.phase == "scanning" and evt.current == 5 and evt.total == 10:
        results.ok("ProgressEvent constructs correctly")
    else:
        results.fail("ProgressEvent constructs correctly",
                     "phase=scanning, current=5, total=10",
                     f"phase={evt.phase}, current={evt.current}")

    # ProgressEvent defaults
    evt2 = ProgressEvent(phase="complete")
    if evt2.message == "" and evt2.current == 0 and evt2.system == "":
        results.ok("ProgressEvent defaults work")
    else:
        results.fail("ProgressEvent defaults work",
                     "empty defaults", repr(evt2))

    # ExcludedRom
    exc = ExcludedRom(filename="test.rom", reason="beta", size=1024)
    if exc.filename == "test.rom" and exc.reason == "beta":
        results.ok("ExcludedRom constructs correctly")
    else:
        results.fail("ExcludedRom constructs correctly",
                     "filename=test.rom", repr(exc))

    # FilterStats
    stats = FilterStats(source_count=100, selected_count=50)
    if stats.source_count == 100 and stats.filter_breakdown == {}:
        results.ok("FilterStats constructs correctly")
    else:
        results.fail("FilterStats constructs correctly",
                     "source_count=100", repr(stats))

    # FilterResult
    fr = FilterResult(system="snes")
    if fr.system == "snes" and fr.selected == [] and fr.excluded == []:
        results.ok("FilterResult constructs correctly")
    else:
        results.fail("FilterResult constructs correctly",
                     "system=snes, empty lists", repr(fr))

    # ScanResult
    sr = ScanResult()
    if sr.url_dict == {} and sr.url_sizes == {}:
        results.ok("ScanResult default construction")
    else:
        results.fail("ScanResult default construction",
                     "empty dicts", repr(sr))

    sr2 = ScanResult(url_dict={"snes": ["url1"]}, url_sizes={"url1": 1000})
    if sr2.url_dict["snes"] == ["url1"] and sr2.url_sizes["url1"] == 1000:
        results.ok("ScanResult with data")
    else:
        results.fail("ScanResult with data",
                     "populated dicts", repr(sr2))

    # SystemScanInfo
    info = SystemScanInfo(system="genesis", file_count=42,
                          total_size=1048576, source_type="local")
    if info.system == "genesis" and info.file_count == 42:
        results.ok("SystemScanInfo constructs correctly")
    else:
        results.fail("SystemScanInfo constructs correctly",
                     "system=genesis, count=42", repr(info))


# =============================================================================
# Network Module Tests
# =============================================================================

def test_network():
    """Test network wrapper functions."""
    print("\n" + "="*60)
    print("NETWORK MODULE TESTS")
    print("="*60)

    from retro_refiner.network import is_url, is_archive_org_url

    # is_url - URLs
    if is_url("https://example.com/roms"):
        results.ok("is_url True for https URL")
    else:
        results.fail("is_url True for https URL", "True", "False")

    if is_url("http://example.com/roms"):
        results.ok("is_url True for http URL")
    else:
        results.fail("is_url True for http URL", "True", "False")

    # is_url - local paths
    if not is_url("/home/user/roms"):
        results.ok("is_url False for Unix path")
    else:
        results.fail("is_url False for Unix path", "False", "True")

    if not is_url("C:\\Users\\roms"):
        results.ok("is_url False for Windows path")
    else:
        results.fail("is_url False for Windows path", "False", "True")

    # is_archive_org_url
    if is_archive_org_url("https://archive.org/download/something"):
        results.ok("is_archive_org_url True for archive.org")
    else:
        results.fail("is_archive_org_url True for archive.org", "True", "False")

    if not is_archive_org_url("https://example.com/roms"):
        results.ok("is_archive_org_url False for non-archive.org")
    else:
        results.fail("is_archive_org_url False for non-archive.org",
                     "False", "True")


# =============================================================================
# Scanner Module Tests
# =============================================================================

def test_scanner():
    """Test scanner wrapper functions."""
    print("\n" + "="*60)
    print("SCANNER MODULE TESTS")
    print("="*60)

    from retro_refiner.scanner import detect_system_from_path, get_system_scan_info
    from retro_refiner.models import SystemScanInfo

    # detect_system_from_path - MAME
    result = detect_system_from_path("/roms/MAME/")
    if result == "mame":
        results.ok("detect_system_from_path finds mame")
    else:
        results.fail("detect_system_from_path finds mame",
                     "mame", repr(result))

    # detect_system_from_path - SNES
    result = detect_system_from_path(
        "https://example.com/roms/Super Nintendo/")
    if result == "snes":
        results.ok("detect_system_from_path finds snes")
    else:
        results.fail("detect_system_from_path finds snes",
                     "snes", repr(result))

    # get_system_scan_info
    test_dict = {"snes": ["a.sfc", "b.sfc"], "genesis": ["c.md"]}
    info_list = get_system_scan_info(test_dict, source_type="network")
    if len(info_list) == 2:
        results.ok("get_system_scan_info returns correct count")
    else:
        results.fail("get_system_scan_info returns correct count",
                     "2", str(len(info_list)))

    # Check the items are SystemScanInfo
    if all(isinstance(i, SystemScanInfo) for i in info_list):
        results.ok("get_system_scan_info returns SystemScanInfo objects")
    else:
        results.fail("get_system_scan_info returns SystemScanInfo objects",
                     "all SystemScanInfo", repr(info_list))

    # Verify file counts
    info_by_system = {i.system: i for i in info_list}
    if info_by_system.get("snes") and info_by_system["snes"].file_count == 2:
        results.ok("get_system_scan_info snes has 2 files")
    else:
        results.fail("get_system_scan_info snes has 2 files",
                     "2", repr(info_by_system.get("snes")))


# =============================================================================
# DAT Module Tests
# =============================================================================

def test_dat():
    """Test DAT wrapper functions."""
    print("\n" + "="*60)
    print("DAT MODULE TESTS")
    print("="*60)

    from retro_refiner.filter import parse_rom_filename
    from retro_refiner.dat import normalize_title

    # parse_rom_filename
    info = parse_rom_filename("Super Mario World (USA).sfc")
    if info.base_title == "Super Mario World":
        results.ok("parse_rom_filename extracts base_title")
    else:
        results.fail("parse_rom_filename extracts base_title",
                     "Super Mario World", repr(info.base_title))

    if "USA" in info.region:
        results.ok("parse_rom_filename extracts region")
    else:
        results.fail("parse_rom_filename extracts region",
                     "USA in region", repr(info.region))

    # parse_rom_filename - beta
    info2 = parse_rom_filename("Test Game (USA) (Beta).zip")
    if info2.is_beta:
        results.ok("parse_rom_filename detects beta")
    else:
        results.fail("parse_rom_filename detects beta",
                     "is_beta=True", repr(info2.is_beta))

    # normalize_title
    norm = normalize_title("Super Mario World")
    if isinstance(norm, str) and len(norm) > 0:
        results.ok("normalize_title returns non-empty string")
    else:
        results.fail("normalize_title returns non-empty string",
                     "non-empty string", repr(norm))

    # normalize_title - case insensitive
    norm1 = normalize_title("ZELDA")
    norm2 = normalize_title("zelda")
    if norm1 == norm2:
        results.ok("normalize_title is case insensitive")
    else:
        results.fail("normalize_title is case insensitive",
                     f"{norm1} == {norm2}", f"{norm1} != {norm2}")


# =============================================================================
# Filter Module Tests
# =============================================================================

def test_filter():
    """Test filter wrapper functions."""
    print("\n" + "="*60)
    print("FILTER MODULE TESTS")
    print("="*60)

    from retro_refiner.filter import filter_console_roms, filter_network_roms
    from retro_refiner.config import Config
    from retro_refiner.models import FilterResult

    config = Config()

    # filter_console_roms returns FilterResult
    result = filter_console_roms("snes", [], config)
    if isinstance(result, FilterResult) and result.system == "snes":
        results.ok("filter_console_roms returns FilterResult")
    else:
        results.fail("filter_console_roms returns FilterResult",
                     "FilterResult(system=snes)", repr(result))

    # filter_network_roms returns FilterResult
    result2 = filter_network_roms("genesis", [], config)
    if isinstance(result2, FilterResult) and result2.system == "genesis":
        results.ok("filter_network_roms returns FilterResult")
    else:
        results.fail("filter_network_roms returns FilterResult",
                     "FilterResult(system=genesis)", repr(result2))


# =============================================================================
# MAME Module Tests
# =============================================================================

def test_mame():
    """Test MAME wrapper functions."""
    print("\n" + "="*60)
    print("MAME MODULE TESTS")
    print("="*60)

    from retro_refiner.mame import filter_mame_network
    from retro_refiner.config import Config
    from retro_refiner.models import FilterResult

    config = Config()
    result = filter_mame_network([], config)
    if isinstance(result, FilterResult) and result.system == "mame":
        results.ok("filter_mame_network returns FilterResult")
    else:
        results.fail("filter_mame_network returns FilterResult",
                     "FilterResult(system=mame)", repr(result))


# =============================================================================
# TeknoParrot Module Tests
# =============================================================================

def test_teknoparrot():
    """Test TeknoParrot wrapper functions."""
    print("\n" + "="*60)
    print("TEKNOPARROT MODULE TESTS")
    print("="*60)

    from retro_refiner.teknoparrot import filter_teknoparrot_network
    from retro_refiner.config import Config
    from retro_refiner.models import FilterResult

    config = Config()
    result = filter_teknoparrot_network([], config)
    if isinstance(result, FilterResult) and result.system == "teknoparrot":
        results.ok("filter_teknoparrot_network returns FilterResult")
    else:
        results.fail("filter_teknoparrot_network returns FilterResult",
                     "FilterResult(system=teknoparrot)", repr(result))


# =============================================================================
# Downloader Module Tests
# =============================================================================

def test_downloader():
    """Test downloader standalone functions."""
    print("\n" + "="*60)
    print("DOWNLOADER MODULE TESTS")
    print("="*60)

    from retro_refiner.downloader import (
        get_download_tool, calculate_autotune_settings,
        Aria2cRPC, DownloadUI,
        AUTOTUNE_SMALL, AUTOTUNE_MEDIUM, AUTOTUNE_LARGE,
    )

    tool = get_download_tool()
    if tool in ('aria2c', 'curl', None):
        results.ok(f"get_download_tool returns valid tool: {tool}")
    else:
        results.fail("get_download_tool returns valid tool",
                     "aria2c|curl|None", repr(tool))

    # calculate_autotune_settings
    result = calculate_autotune_settings([])
    if result == AUTOTUNE_MEDIUM:
        results.ok("autotune empty list returns MEDIUM")
    else:
        results.fail("autotune empty list returns MEDIUM",
                     repr(AUTOTUNE_MEDIUM), repr(result))

    result = calculate_autotune_settings([1024, 2048, 4096])
    if result == AUTOTUNE_SMALL:
        results.ok("autotune small files returns SMALL")
    else:
        results.fail("autotune small files returns SMALL",
                     repr(AUTOTUNE_SMALL), repr(result))

    result = calculate_autotune_settings([500_000_000, 600_000_000])
    if result == AUTOTUNE_LARGE:
        results.ok("autotune large files returns LARGE")
    else:
        results.fail("autotune large files returns LARGE",
                     repr(AUTOTUNE_LARGE), repr(result))

    # Aria2cRPC construction
    rpc = Aria2cRPC(port=6800, secret='test')
    if rpc.url == 'http://localhost:6800/jsonrpc':
        results.ok("Aria2cRPC constructs with correct URL")
    else:
        results.fail("Aria2cRPC constructs with correct URL",
                     "http://localhost:6800/jsonrpc", rpc.url)

    # DownloadUI construction (no actual downloads)
    ui = DownloadUI(
        system_name='snes',
        files=[('http://example.com/game.sfc', Path('/tmp/game.sfc'))],
        parallel=4, connections=2
    )
    if ui.system_name == 'snes' and len(ui.files) == 1:
        results.ok("DownloadUI constructs correctly")
    else:
        results.fail("DownloadUI constructs correctly",
                     "snes, 1 file", f"{ui.system_name}, {len(ui.files)}")

    if ui.files[0]['status'] == DownloadUI.STATUS_QUEUED:
        results.ok("DownloadUI files start as queued")
    else:
        results.fail("DownloadUI files start as queued",
                     "queued", ui.files[0]['status'])


# =============================================================================
# Transfer Module Tests
# =============================================================================

def test_transfer():
    """Test transfer file operations."""
    print("\n" + "="*60)
    print("TRANSFER MODULE TESTS")
    print("="*60)

    import tempfile
    from retro_refiner.transfer import transfer_files

    # Empty file list
    result = transfer_files([], Path("/tmp/test"))
    if isinstance(result, dict) and 'transferred' in result:
        results.ok("transfer_files returns result dict")
    else:
        results.fail("transfer_files returns result dict",
                     "dict with transferred key", repr(result))

    if result['transferred'] == 0 and result['errors'] == 0:
        results.ok("transfer_files empty list returns zeros")
    else:
        results.fail("transfer_files empty list returns zeros",
                     "all zeros", repr(result))

    # Actual file transfer
    with tempfile.TemporaryDirectory() as tmpdir:
        src_dir = Path(tmpdir) / 'src'
        dst_dir = Path(tmpdir) / 'dst'
        src_dir.mkdir()

        # Create test files
        test_file = src_dir / 'game.sfc'
        test_file.write_text('rom data')

        result = transfer_files([test_file], dst_dir, mode='copy',
                                system='snes')
        if result['transferred'] == 1:
            results.ok("transfer_files copies 1 file")
        else:
            results.fail("transfer_files copies 1 file",
                         "1", str(result['transferred']))

        expected = dst_dir / 'snes' / 'game.sfc'
        if expected.exists():
            results.ok("transfer_files creates system subdirectory")
        else:
            results.fail("transfer_files creates system subdirectory",
                         str(expected), "not found")

        # Duplicate transfer should skip
        result2 = transfer_files([test_file], dst_dir, mode='copy',
                                 system='snes')
        if result2['skipped'] == 1:
            results.ok("transfer_files skips existing files")
        else:
            results.fail("transfer_files skips existing files",
                         "1 skipped", repr(result2))

        # Flat mode
        flat_dir = Path(tmpdir) / 'flat'
        result3 = transfer_files([test_file], flat_dir, mode='copy',
                                 flat=True)
        if (flat_dir / 'game.sfc').exists():
            results.ok("transfer_files flat mode works")
        else:
            results.fail("transfer_files flat mode works",
                         "file in flat_dir", "not found")


# =============================================================================
# Import All Modules Test
# =============================================================================

def test_all_imports():
    """Verify all v2 modules import without error."""
    print("\n" + "="*60)
    print("MODULE IMPORT TESTS")
    print("="*60)

    modules_to_import = [
        'retro_refiner.models',
        'retro_refiner.paths',
        'retro_refiner.systems',
        'retro_refiner.network',
        'retro_refiner.scanner',
        'retro_refiner.dat',
        'retro_refiner.filter',
        'retro_refiner.mame',
        'retro_refiner.teknoparrot',
        'retro_refiner.downloader',
        'retro_refiner.transfer',
        'retro_refiner.config',
    ]

    import importlib
    for mod_name in modules_to_import:
        try:
            importlib.import_module(mod_name)
            results.ok(f"import {mod_name}")
        except Exception as exc:  # pylint: disable=broad-except
            results.fail(f"import {mod_name}",
                         "successful import", str(exc))


def test_scanner_local():
    """Test local source scanning."""
    print("\n" + "="*60)
    print("SCANNER LOCAL TESTS")
    print("="*60)

    import tempfile
    from retro_refiner.scanner import scan_local_sources

    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a system folder with ROM files
        snes_dir = Path(tmpdir) / 'snes'
        snes_dir.mkdir()
        (snes_dir / 'game1.sfc').write_text('rom1')
        (snes_dir / 'game2.sfc').write_text('rom2')
        (snes_dir / 'readme.txt').write_text('not a rom')

        result = scan_local_sources([Path(tmpdir)], recursive=True)
        if 'snes' in result:
            results.ok("scan_local_sources detects snes folder")
        else:
            results.fail("scan_local_sources detects snes folder",
                         "snes in result", repr(list(result.keys())))

        if 'snes' in result and len(result['snes']) == 2:
            results.ok("scan_local_sources finds 2 sfc files")
        else:
            count = len(result.get('snes', []))
            results.fail("scan_local_sources finds 2 sfc files",
                         "2", str(count))

    # Empty directory
    with tempfile.TemporaryDirectory() as tmpdir:
        result = scan_local_sources([Path(tmpdir)])
        if len(result) == 0:
            results.ok("scan_local_sources empty dir returns empty dict")
        else:
            results.fail("scan_local_sources empty dir returns empty dict",
                         "{}", repr(result))


if __name__ == '__main__':
    test_all_imports()
    test_systems()
    test_models()
    test_network()
    test_scanner()
    test_scanner_local()
    test_dat()
    test_filter()
    test_mame()
    test_teknoparrot()
    test_downloader()
    test_transfer()
    success = results.summary()
    sys.exit(0 if success else 1)

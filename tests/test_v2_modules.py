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
# Monolith Import Tests
# =============================================================================

def test_monolith_import():
    """Test that _monolith.get_module() imports retro-refiner.py."""
    print("\n" + "="*60)
    print("MONOLITH IMPORT TESTS")
    print("="*60)

    from retro_refiner._monolith import get_module
    mod = get_module()

    if mod is not None:
        results.ok("get_module returns non-None")
    else:
        results.fail("get_module returns non-None", "module", "None")

    # Verify it has expected attributes
    if hasattr(mod, 'parse_rom_filename'):
        results.ok("module has parse_rom_filename")
    else:
        results.fail("module has parse_rom_filename",
                     "attribute exists", "missing")

    if hasattr(mod, 'normalize_title'):
        results.ok("module has normalize_title")
    else:
        results.fail("module has normalize_title",
                     "attribute exists", "missing")

    if hasattr(mod, 'is_url'):
        results.ok("module has is_url")
    else:
        results.fail("module has is_url",
                     "attribute exists", "missing")

    # Calling get_module again returns cached instance
    mod2 = get_module()
    if mod is mod2:
        results.ok("get_module returns cached instance")
    else:
        results.fail("get_module returns cached instance",
                     "same object", "different object")


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

    from retro_refiner.dat import parse_rom_filename, normalize_title

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
    """Test downloader wrapper functions."""
    print("\n" + "="*60)
    print("DOWNLOADER MODULE TESTS")
    print("="*60)

    from retro_refiner.downloader import get_download_tool

    tool = get_download_tool()
    # Should be one of the known tools or None
    if tool in ('aria2c', 'curl', 'urllib', None):
        results.ok(f"get_download_tool returns valid tool: {tool}")
    else:
        results.fail("get_download_tool returns valid tool",
                     "aria2c|curl|urllib|None", repr(tool))


# =============================================================================
# Transfer Module Tests
# =============================================================================

def test_transfer():
    """Test transfer wrapper functions."""
    print("\n" + "="*60)
    print("TRANSFER MODULE TESTS")
    print("="*60)

    from retro_refiner.transfer import transfer_files

    result = transfer_files([], Path("/tmp/test"))
    if isinstance(result, dict) and 'transferred' in result:
        results.ok("transfer_files returns result dict")
    else:
        results.fail("transfer_files returns result dict",
                     "dict with transferred key", repr(result))

    if result['transferred'] == 0 and result['errors'] == 0:
        results.ok("transfer_files stub returns zeros")
    else:
        results.fail("transfer_files stub returns zeros",
                     "all zeros", repr(result))


# =============================================================================
# Import All Modules Test
# =============================================================================

def test_all_imports():
    """Verify all v2 modules import without error."""
    print("\n" + "="*60)
    print("MODULE IMPORT TESTS")
    print("="*60)

    modules_to_import = [
        'retro_refiner._monolith',
        'retro_refiner.models',
        'retro_refiner.network',
        'retro_refiner.scanner',
        'retro_refiner.dat',
        'retro_refiner.filter',
        'retro_refiner.mame',
        'retro_refiner.teknoparrot',
        'retro_refiner.downloader',
        'retro_refiner.transfer',
    ]

    import importlib
    for mod_name in modules_to_import:
        try:
            importlib.import_module(mod_name)
            results.ok(f"import {mod_name}")
        except Exception as exc:  # pylint: disable=broad-except
            results.fail(f"import {mod_name}",
                         "successful import", str(exc))


if __name__ == '__main__':
    test_all_imports()
    test_monolith_import()
    test_models()
    test_network()
    test_scanner()
    test_dat()
    test_filter()
    test_mame()
    test_teknoparrot()
    test_downloader()
    test_transfer()
    success = results.summary()
    sys.exit(0 if success else 1)

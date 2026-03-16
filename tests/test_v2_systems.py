"""Tests for retro_refiner.systems module."""
import sys
from pathlib import Path

# Ensure project root is on sys.path so retro_refiner package is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from retro_refiner.systems import load_system_data, reset_cache, SystemData


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
# SystemData Tests
# =============================================================================

def test_load_system_data():
    """Test retro_refiner.systems module."""
    print("\n" + "="*60)
    print("SYSTEM DATA TESTS")
    print("="*60)

    reset_cache()
    data = load_system_data()

    # Returns SystemData instance
    if isinstance(data, SystemData):
        results.ok("load_system_data returns SystemData instance")
    else:
        results.fail("load_system_data returns SystemData instance",
                     "SystemData", type(data).__name__)

    # known_systems has >100 entries
    count = len(data.known_systems)
    if count > 100:
        results.ok(f"known_systems has >100 entries ({count})")
    else:
        results.fail("known_systems has >100 entries",
                     ">100", count)

    # known_systems includes 'nes'
    if 'nes' in data.known_systems:
        results.ok("known_systems includes 'nes'")
    else:
        results.fail("known_systems includes 'nes'", "'nes' in list", "not found")

    # known_systems includes 'snes'
    if 'snes' in data.known_systems:
        results.ok("known_systems includes 'snes'")
    else:
        results.fail("known_systems includes 'snes'", "'snes' in list", "not found")

    # known_systems includes 'mame'
    if 'mame' in data.known_systems:
        results.ok("known_systems includes 'mame'")
    else:
        results.fail("known_systems includes 'mame'", "'mame' in list", "not found")

    # extension_to_system maps '.nes' -> 'nes'
    val = data.extension_to_system.get('.nes')
    if val == 'nes':
        results.ok("extension_to_system maps '.nes' -> 'nes'")
    else:
        results.fail("extension_to_system maps '.nes' -> 'nes'", "'nes'", repr(val))

    # extension_to_system maps '.sfc' -> 'snes'
    val = data.extension_to_system.get('.sfc')
    if val == 'snes':
        results.ok("extension_to_system maps '.sfc' -> 'snes'")
    else:
        results.fail("extension_to_system maps '.sfc' -> 'snes'", "'snes'", repr(val))

    # extension_to_system maps '.md' -> 'genesis'
    val = data.extension_to_system.get('.md')
    if val == 'genesis':
        results.ok("extension_to_system maps '.md' -> 'genesis'")
    else:
        results.fail("extension_to_system maps '.md' -> 'genesis'", "'genesis'", repr(val))

    # folder_aliases maps 'super-nintendo' -> 'snes'
    val = data.folder_aliases.get('super-nintendo')
    if val == 'snes':
        results.ok("folder_aliases maps 'super-nintendo' -> 'snes'")
    else:
        results.fail("folder_aliases maps 'super-nintendo' -> 'snes'", "'snes'", repr(val))

    # folder_aliases maps 'megadrive' -> 'genesis'
    val = data.folder_aliases.get('megadrive')
    if val == 'genesis':
        results.ok("folder_aliases maps 'megadrive' -> 'genesis'")
    else:
        results.fail("folder_aliases maps 'megadrive' -> 'genesis'", "'genesis'", repr(val))

    # libretro_dat_systems contains 'nes'
    if 'nes' in data.libretro_dat_systems:
        results.ok("libretro_dat_systems contains 'nes'")
    else:
        results.fail("libretro_dat_systems contains 'nes'", "'nes' key present", "not found")

    # redump_dat_systems contains 'psx'
    if 'psx' in data.redump_dat_systems:
        results.ok("redump_dat_systems contains 'psx'")
    else:
        results.fail("redump_dat_systems contains 'psx'", "'psx' key present", "not found")

    # launchbox_platform_map is populated
    if len(data.launchbox_platform_map) > 0:
        results.ok(f"launchbox_platform_map is populated ({len(data.launchbox_platform_map)} entries)")
    else:
        results.fail("launchbox_platform_map is populated", ">0 entries", "empty")

    # dat_name_to_system reverse lookup populated
    if len(data.dat_name_to_system) > 0:
        results.ok(f"dat_name_to_system reverse lookup populated ({len(data.dat_name_to_system)} entries)")
    else:
        results.fail("dat_name_to_system reverse lookup populated", ">0 entries", "empty")

    # system_to_launchbox reverse lookup populated
    if len(data.system_to_launchbox) > 0:
        results.ok(f"system_to_launchbox reverse lookup populated ({len(data.system_to_launchbox)} entries)")
    else:
        results.fail("system_to_launchbox reverse lookup populated", ">0 entries", "empty")

    # sorted_dat_names is sorted longest-first
    names = [k for k, _ in data.sorted_dat_names]
    if names == sorted(names, key=len, reverse=True):
        results.ok("sorted_dat_names is sorted longest-first")
    else:
        results.fail("sorted_dat_names is sorted longest-first",
                     "longest-first order", "not longest-first")

    # sorted_aliases is sorted longest-first
    aliases = [k for k, _ in data.sorted_aliases]
    if aliases == sorted(aliases, key=len, reverse=True):
        results.ok("sorted_aliases is sorted longest-first")
    else:
        results.fail("sorted_aliases is sorted longest-first",
                     "longest-first order", "not longest-first")


def test_caching():
    """Test that second call returns the same object."""
    print("\n" + "="*60)
    print("CACHING TESTS")
    print("="*60)

    reset_cache()
    first = load_system_data()
    second = load_system_data()

    if first is second:
        results.ok("second call returns same object (cached)")
    else:
        results.fail("second call returns same object (cached)",
                     "identical object (is)", "different objects")


def test_custom_path():
    """Test load_system_data with explicit path."""
    print("\n" + "="*60)
    print("CUSTOM PATH TESTS")
    print("="*60)

    project_root = Path(__file__).resolve().parent.parent
    systems_json = project_root / 'data' / 'systems.json'

    reset_cache()
    data = load_system_data(systems_json_path=systems_json)

    if isinstance(data, SystemData) and len(data.known_systems) > 100:
        results.ok("load_system_data with explicit path works")
    else:
        results.fail("load_system_data with explicit path works",
                     "SystemData with >100 systems", repr(data))


if __name__ == '__main__':
    test_load_system_data()
    test_caching()
    test_custom_path()
    success = results.summary()
    sys.exit(0 if success else 1)

"""Integration tests: verify v2 modules work together."""
import sys
import tempfile
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from tests.test_v2_paths import TestResult  # Reuse test framework


def run_tests():
    results = TestResult()

    print("\n" + "=" * 60)
    print("V2 INTEGRATION TESTS")
    print("=" * 60)

    # Test 1: Package version
    from retro_refiner import __version__
    if __version__ == "dev":
        results.ok("Package version exists")
    else:
        results.fail("Package version", "dev", __version__)

    # Test 2: Paths module
    from retro_refiner.paths import get_base_path, get_runtime_path
    base = get_base_path()
    runtime = get_runtime_path()
    if base.exists() and runtime.exists():
        results.ok("Paths module works")
    else:
        results.fail("Paths", "existing paths", f"base={base.exists()}, runtime={runtime.exists()}")

    # Test 3: Systems module uses paths
    from retro_refiner.systems import load_system_data, reset_cache
    reset_cache()
    data = load_system_data()
    if len(data.known_systems) > 100:
        results.ok(f"Systems loads via paths ({len(data.known_systems)} systems)")
    else:
        results.fail("Systems count", ">100", len(data.known_systems))

    # Test 4: Config round-trip to disk
    from retro_refiner.config import Config, save_config, load_config
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

        checks = [
            loaded.sources == config.sources,
            loaded.selection.english_only is True,
            loaded.selection.region_priority == ['USA', 'Japan'],
            loaded.output.transfer_mode == 'move',
            loaded.theme.accent == '#00ff00',
        ]
        if all(checks):
            results.ok("Config round-trip to disk preserves values")
        else:
            results.fail("Config round-trip", "all match", f"checks={checks}")

    # Test 5: All modules importable from package
    try:
        from retro_refiner import paths, systems, config  # noqa: F401
        results.ok("All modules importable from package")
    except ImportError as e:
        results.fail("Module imports", "success", str(e))

    print("\n" + "=" * 60)
    print(f"Results: {results.passed}/{results.passed + results.failed} passed")
    print("=" * 60)

    return results.failed == 0


if __name__ == '__main__':
    success = run_tests()
    sys.exit(0 if success else 1)

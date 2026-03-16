"""Tests for retro_refiner.paths module."""
import sys
from pathlib import Path

# Ensure project root is on sys.path so retro_refiner package is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from retro_refiner.paths import get_base_path, get_runtime_path


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
# Path Helper Tests
# =============================================================================

def test_path_helpers():
    """Test retro_refiner.paths module."""
    print("\n" + "="*60)
    print("PATH HELPER TESTS")
    print("="*60)

    # test_get_base_path_returns_path
    result = get_base_path()
    if isinstance(result, Path) and result.exists():
        results.ok("get_base_path returns existing Path")
    else:
        results.fail("get_base_path returns existing Path",
                     "Path that exists", repr(result))

    # test_get_runtime_path_returns_path
    result = get_runtime_path()
    if isinstance(result, Path) and result.exists():
        results.ok("get_runtime_path returns existing Path")
    else:
        results.fail("get_runtime_path returns existing Path",
                     "Path that exists", repr(result))

    # test_base_path_contains_data_dir
    base = get_base_path()
    systems_json = base / 'data' / 'systems.json'
    if systems_json.exists():
        results.ok("base_path contains data/systems.json")
    else:
        results.fail("base_path contains data/systems.json",
                     f"{systems_json} to exist",
                     f"base_path={base}, file not found")


if __name__ == '__main__':
    test_path_helpers()
    success = results.summary()
    sys.exit(0 if success else 1)

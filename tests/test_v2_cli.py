"""Tests for retro_refiner.cli module."""
import io
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

# Ensure project root is on sys.path so retro_refiner package is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from retro_refiner.cli import format_size, run_headless
from retro_refiner.config import Config, load_config, save_config


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
# format_size Tests
# =============================================================================

def test_format_size():
    """Test format_size() for all magnitude ranges."""
    print("\n" + "="*60)
    print("FORMAT_SIZE TESTS")
    print("="*60)

    # Bytes
    result = format_size(0)
    if result == "0 B":
        results.ok("format_size: 0 bytes")
    else:
        results.fail("format_size: 0 bytes", "0 B", result)

    result = format_size(512)
    if result == "512 B":
        results.ok("format_size: 512 bytes")
    else:
        results.fail("format_size: 512 bytes", "512 B", result)

    result = format_size(1023)
    if result == "1023 B":
        results.ok("format_size: 1023 bytes")
    else:
        results.fail("format_size: 1023 bytes", "1023 B", result)

    # Kilobytes
    result = format_size(1024)
    if result == "1.0 KB":
        results.ok("format_size: 1 KB")
    else:
        results.fail("format_size: 1 KB", "1.0 KB", result)

    result = format_size(1536)
    if result == "1.5 KB":
        results.ok("format_size: 1.5 KB")
    else:
        results.fail("format_size: 1.5 KB", "1.5 KB", result)

    result = format_size(1024 * 1024 - 1)
    expected = f"{(1024 * 1024 - 1) / 1024:.1f} KB"
    if result == expected:
        results.ok("format_size: just under 1 MB")
    else:
        results.fail("format_size: just under 1 MB", expected, result)

    # Megabytes
    result = format_size(1024 * 1024)
    if result == "1.0 MB":
        results.ok("format_size: 1 MB")
    else:
        results.fail("format_size: 1 MB", "1.0 MB", result)

    result = format_size(512 * 1024 * 1024)
    if result == "512.0 MB":
        results.ok("format_size: 512 MB")
    else:
        results.fail("format_size: 512 MB", "512.0 MB", result)

    # Gigabytes
    result = format_size(1024 * 1024 * 1024)
    if result == "1.00 GB":
        results.ok("format_size: 1 GB")
    else:
        results.fail("format_size: 1 GB", "1.00 GB", result)

    result = format_size(2 * 1024 * 1024 * 1024)
    if result == "2.00 GB":
        results.ok("format_size: 2 GB")
    else:
        results.fail("format_size: 2 GB", "2.00 GB", result)

    # Terabytes
    result = format_size(1024 * 1024 * 1024 * 1024)
    if result == "1.00 TB":
        results.ok("format_size: 1 TB")
    else:
        results.fail("format_size: 1 TB", "1.00 TB", result)

    result = format_size(3 * 1024 * 1024 * 1024 * 1024)
    if result == "3.00 TB":
        results.ok("format_size: 3 TB")
    else:
        results.fail("format_size: 3 TB", "3.00 TB", result)


# =============================================================================
# Config Round-Trip Tests
# =============================================================================

def test_config_round_trip():
    """Test that Config exports to YAML and loads back identically."""
    print("\n" + "="*60)
    print("CONFIG ROUND-TRIP TESTS")
    print("="*60)

    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = Path(tmpdir) / 'test_config.yaml'

        # Default config round-trip
        original = Config()
        save_config(original, config_path)
        loaded = load_config(config_path)

        if loaded.selection.english_only == original.selection.english_only:
            results.ok("round-trip: selection.english_only preserved")
        else:
            results.fail("round-trip: selection.english_only preserved",
                         original.selection.english_only,
                         loaded.selection.english_only)

        if loaded.network.scan_workers == original.network.scan_workers:
            results.ok("round-trip: network.scan_workers preserved")
        else:
            results.fail("round-trip: network.scan_workers preserved",
                         original.network.scan_workers,
                         loaded.network.scan_workers)

        if loaded.advanced.no_cache == original.advanced.no_cache:
            results.ok("round-trip: advanced.no_cache preserved")
        else:
            results.fail("round-trip: advanced.no_cache preserved",
                         original.advanced.no_cache,
                         loaded.advanced.no_cache)

        # Non-default values round-trip
        custom = Config()
        custom.sources = ['http://example.com/roms', '/path/to/local']
        custom.destination = '/path/to/dest'
        custom.selection.english_only = True
        custom.network.scan_workers = 8
        custom.advanced.no_cache = True

        save_config(custom, config_path)
        loaded_custom = load_config(config_path)

        if loaded_custom.sources == custom.sources:
            results.ok("round-trip: sources list preserved")
        else:
            results.fail("round-trip: sources list preserved",
                         custom.sources, loaded_custom.sources)

        if loaded_custom.destination == custom.destination:
            results.ok("round-trip: destination preserved")
        else:
            results.fail("round-trip: destination preserved",
                         custom.destination, loaded_custom.destination)

        if loaded_custom.selection.english_only is True:
            results.ok("round-trip: selection.english_only=True preserved")
        else:
            results.fail("round-trip: selection.english_only=True preserved",
                         True, loaded_custom.selection.english_only)

        if loaded_custom.network.scan_workers == 8:
            results.ok("round-trip: network.scan_workers=8 preserved")
        else:
            results.fail("round-trip: network.scan_workers=8 preserved",
                         8, loaded_custom.network.scan_workers)

        if loaded_custom.advanced.no_cache is True:
            results.ok("round-trip: advanced.no_cache=True preserved")
        else:
            results.fail("round-trip: advanced.no_cache=True preserved",
                         True, loaded_custom.advanced.no_cache)


# =============================================================================
# run_headless --export-config Tests
# =============================================================================

def test_export_config():
    """Test that --export-config prints valid YAML to stdout."""
    print("\n" + "="*60)
    print("EXPORT-CONFIG TESTS")
    print("="*60)

    captured = io.StringIO()
    with patch('sys.stdout', captured):
        run_headless(['--export-config'])

    output = captured.getvalue()

    # Should contain YAML markers
    if '# Retro-Refiner configuration' in output:
        results.ok("export-config: contains YAML header comment")
    else:
        results.fail("export-config: contains YAML header comment",
                     "'# Retro-Refiner configuration' in output",
                     repr(output[:200]))

    if 'selection:' in output:
        results.ok("export-config: contains 'selection:' section")
    else:
        results.fail("export-config: contains 'selection:' section",
                     "'selection:' in output", repr(output[:200]))

    if 'network:' in output:
        results.ok("export-config: contains 'network:' section")
    else:
        results.fail("export-config: contains 'network:' section",
                     "'network:' in output", repr(output[:200]))

    if 'advanced:' in output:
        results.ok("export-config: contains 'advanced:' section")
    else:
        results.fail("export-config: contains 'advanced:' section",
                     "'advanced:' in output", repr(output[:200]))

    # Output should be parseable as valid config YAML
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = Path(tmpdir) / 'exported.yaml'
        config_path.write_text(output, encoding='utf-8')
        loaded = load_config(config_path)

        if isinstance(loaded, Config):
            results.ok("export-config: output is valid Config YAML")
        else:
            results.fail("export-config: output is valid Config YAML",
                         "Config instance", type(loaded).__name__)


# =============================================================================
# run_headless Missing Config Tests
# =============================================================================

def test_missing_config():
    """Test that run_headless prints error and exits for missing config."""
    print("\n" + "="*60)
    print("MISSING CONFIG TESTS")
    print("="*60)

    captured_out = io.StringIO()
    exit_code = None

    with patch('sys.stdout', captured_out):
        try:
            run_headless(['--run', '/nonexistent/path/config.yaml'])
        except SystemExit as exc:
            exit_code = exc.code

    output = captured_out.getvalue()

    if exit_code == 1:
        results.ok("missing config: exits with code 1")
    else:
        results.fail("missing config: exits with code 1", 1, exit_code)

    if 'Error' in output or 'not found' in output:
        results.ok("missing config: prints error message")
    else:
        results.fail("missing config: prints error message",
                     "Error/not found in output", repr(output))


def test_no_args():
    """Test that run_headless prints usage when called with no relevant args."""
    print("\n" + "="*60)
    print("NO ARGS TESTS")
    print("="*60)

    captured_out = io.StringIO()
    exit_code = None

    with patch('sys.stdout', captured_out):
        try:
            run_headless([])
        except SystemExit as exc:
            exit_code = exc.code

    output = captured_out.getvalue()

    if exit_code == 1:
        results.ok("no args: exits with code 1")
    else:
        results.fail("no args: exits with code 1", 1, exit_code)

    if 'Usage' in output or 'usage' in output:
        results.ok("no args: prints usage message")
    else:
        results.fail("no args: prints usage message",
                     "Usage in output", repr(output))


# =============================================================================
# Package Export Tests
# =============================================================================

def test_package_exports():
    """Test that retro_refiner.__init__ exports key items."""
    print("\n" + "="*60)
    print("PACKAGE EXPORT TESTS")
    print("="*60)

    import retro_refiner  # pylint: disable=import-outside-toplevel

    if hasattr(retro_refiner, '__version__'):
        results.ok("package exports __version__")
    else:
        results.fail("package exports __version__", "attribute present", "missing")

    if hasattr(retro_refiner, 'Config'):
        results.ok("package exports Config")
    else:
        results.fail("package exports Config", "attribute present", "missing")

    if hasattr(retro_refiner, 'load_config'):
        results.ok("package exports load_config")
    else:
        results.fail("package exports load_config", "attribute present", "missing")

    if hasattr(retro_refiner, 'save_config'):
        results.ok("package exports save_config")
    else:
        results.fail("package exports save_config", "attribute present", "missing")

    if hasattr(retro_refiner, 'load_system_data'):
        results.ok("package exports load_system_data")
    else:
        results.fail("package exports load_system_data", "attribute present", "missing")

    if hasattr(retro_refiner, 'SystemData'):
        results.ok("package exports SystemData")
    else:
        results.fail("package exports SystemData", "attribute present", "missing")

    # Verify Config is the right type
    cfg = retro_refiner.Config()
    if isinstance(cfg, Config):
        results.ok("package Config is usable")
    else:
        results.fail("package Config is usable", "Config instance", type(cfg).__name__)


if __name__ == '__main__':
    test_format_size()
    test_config_round_trip()
    test_export_config()
    test_missing_config()
    test_no_args()
    test_package_exports()
    success = results.summary()
    sys.exit(0 if success else 1)

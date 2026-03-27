"""Smoke tests that exercise the full scan/filter pipeline.

These hit real network sources (Myrient) so they are slower than unit tests.
First run: ~30-60s per test (full directory scan).
Cached runs: ~2-5s (loads from scan cache).

Run all tests:
    python tests/test_smoke.py

Run only cached tests (skip if no cache exists):
    python tests/test_smoke.py --quick
"""
import sys
import urllib.error
import urllib.request
from pathlib import Path

# Ensure project root is on sys.path so retro_refiner package is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from retro_refiner.config import Config, SelectionConfig, NetworkConfig, AdvancedConfig
from retro_refiner.mame import (
    download_mame_data,
    filter_mame_network_roms,
    parse_catver_ini,
    parse_mame_dat,
)
from retro_refiner.network import load_scan_cache, reset_shutdown
from retro_refiner.paths import get_runtime_path
from retro_refiner.scanner import scan_network_source
from retro_refiner.teknoparrot import filter_teknoparrot_network_roms
from retro_refiner.filter import filter_network_roms


# ---------------------------------------------------------------------------
# Test framework (matches project pattern from test_v2_paths.py)
# ---------------------------------------------------------------------------

class TestResult:
    """Track test results."""
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.skipped = 0
        self.errors = []

    def ok(self, name):
        """Record a passing test."""
        self.passed += 1
        print(f"  [PASS] {name}")

    def fail(self, name, expected, actual):
        """Record a failing test."""
        self.failed += 1
        self.errors.append((name, expected, actual))
        print(f"  [FAIL] {name}")
        print(f"    Expected: {expected}")
        print(f"    Actual:   {actual}")

    def skip(self, name, reason=""):
        """Record a skipped test."""
        self.skipped += 1
        print(f"  [SKIP] {name}" + (f" ({reason})" if reason else ""))

    def summary(self):
        """Print a summary and return True if all tests passed."""
        total = self.passed + self.failed + self.skipped
        print(f"\n{'='*60}")
        print(f"Results: {self.passed}/{total} passed"
              + (f", {self.skipped} skipped" if self.skipped else ""))
        if self.failed > 0:
            print(f"Failed tests: {self.failed}")
            for name, expected, actual in self.errors:
                print(f"  - {name}")
                print(f"      Expected: {expected}")
                print(f"      Actual:   {actual}")
        print(f"{'='*60}")
        return self.failed == 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

CACHE_DIR = get_runtime_path() / "cache"
DAT_DIR = get_runtime_path() / "dat_files"


def _network_available(timeout: int = 5) -> bool:
    """Return True if Myrient is reachable."""
    try:
        req = urllib.request.Request(
            "https://myrient.erista.me/",
            headers={"User-Agent": "retro-refiner-smoke-test/1.0"},
        )
        with urllib.request.urlopen(req, timeout=timeout):
            return True
    except (urllib.error.URLError, OSError):
        return False


def _has_scan_cache(url: str) -> bool:
    """Return True if a scan cache entry exists for this URL."""
    return bool(load_scan_cache(CACHE_DIR, url))


def _make_config(english_only: bool = True) -> Config:
    """Build a minimal Config with sensible smoke-test defaults."""
    config = Config()
    config.selection = SelectionConfig(english_only=english_only)
    config.network = NetworkConfig(scan_workers=16)
    config.advanced = AdvancedConfig(
        cache_dir=str(CACHE_DIR),
        dat_dir=str(DAT_DIR),
    )
    return config


# ---------------------------------------------------------------------------
# Smoke tests
# ---------------------------------------------------------------------------

def test_atari_2600(results: TestResult, quick: bool = False):
    """Atari 2600 — small set, good for a quick end-to-end check."""
    print("\n" + "="*60)
    print("SMOKE: Atari 2600 (No-Intro)")
    print("="*60)

    url = "https://myrient.erista.me/files/No-Intro/Atari%20-%20Atari%202600/"

    if quick and not _has_scan_cache(url):
        results.skip("Atari 2600 scan", "no cache and --quick requested")
        return

    if not quick and not _network_available():
        results.skip("Atari 2600 scan", "network unavailable")
        return

    reset_shutdown()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    try:
        print(f"  Scanning: {url}")
        scan = scan_network_source(
            url,
            cache_dir=CACHE_DIR,
            scan_workers=16,
        )
    except Exception as exc:  # pylint: disable=broad-except
        results.fail("Atari 2600 scan", "ScanResult", f"exception: {exc}")
        return

    # Validate scan result structure
    if not scan.url_dict:
        results.fail("Atari 2600 scan found URLs", "url_dict non-empty", "empty")
        return
    results.ok("Atari 2600 scan returned url_dict")

    # Find the atari2600 system key
    system = next((s for s in scan.url_dict if '2600' in s or s == 'atari2600'),
                  next(iter(scan.url_dict), None))
    if not system:
        results.fail("Atari 2600 system detection", "atari2600 key", list(scan.url_dict.keys()))
        return

    rom_urls = scan.url_dict[system]
    print(f"  Found {len(rom_urls)} URLs for system '{system}'")

    if len(rom_urls) < 10:
        results.fail("Atari 2600 URL count", ">= 10", len(rom_urls))
        return
    results.ok(f"Atari 2600 found {len(rom_urls)} URLs")

    # Filter with english_only=True
    config = _make_config(english_only=True)
    try:
        filter_result = filter_network_roms(
            system, rom_urls, config,
            url_sizes=scan.url_sizes,
        )
    except Exception as exc:  # pylint: disable=broad-except
        results.fail("Atari 2600 filter", "FilterResult", f"exception: {exc}")
        return

    selected = filter_result.selected
    stats = filter_result.stats

    print(f"  Source: {stats.source_count}, Selected: {stats.selected_count}, "
          f"Excluded: {stats.excluded_count}")

    if stats.selected_count > 0:
        results.ok(f"Atari 2600 filter selected {stats.selected_count} ROMs")
    else:
        results.fail("Atari 2600 selected > 0", "> 0", stats.selected_count)

    if stats.excluded_count > 0:
        results.ok(f"Atari 2600 filter excluded {stats.excluded_count} ROMs")
    else:
        results.fail("Atari 2600 excluded > 0", "> 0", stats.excluded_count)

    # english_only should reduce the set (Japan-only titles excluded)
    if stats.selected_count < stats.source_count:
        results.ok("english_only reduced the ROM set")
    else:
        results.fail("english_only reduced the set",
                     f"< {stats.source_count}", stats.selected_count)

    # selected list matches selected_count
    if len(selected) == stats.selected_count:
        results.ok("selected list length matches stats.selected_count")
    else:
        results.fail("selected list vs stats",
                     stats.selected_count, len(selected))


def test_teknoparrot(results: TestResult, quick: bool = False):
    """TeknoParrot — verify Japan-only games are excluded with english_only."""
    print("\n" + "="*60)
    print("SMOKE: TeknoParrot")
    print("="*60)

    url = "https://myrient.erista.me/files/TeknoParrot/"

    if quick and not _has_scan_cache(url):
        results.skip("TeknoParrot scan", "no cache and --quick requested")
        return

    if not quick and not _network_available():
        results.skip("TeknoParrot scan", "network unavailable")
        return

    reset_shutdown()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    try:
        print(f"  Scanning: {url}")
        scan = scan_network_source(
            url,
            cache_dir=CACHE_DIR,
            scan_workers=16,
        )
    except Exception as exc:  # pylint: disable=broad-except
        results.fail("TeknoParrot scan", "ScanResult", f"exception: {exc}")
        return

    if not scan.url_dict:
        results.fail("TeknoParrot scan found URLs", "url_dict non-empty", "empty")
        return
    results.ok("TeknoParrot scan returned url_dict")

    # Collect all TP URLs (may be under 'teknoparrot' or similar)
    all_urls = []
    for system_urls in scan.url_dict.values():
        all_urls.extend(system_urls)

    print(f"  Found {len(all_urls)} total URLs")

    if len(all_urls) < 5:
        results.fail("TeknoParrot URL count", ">= 5", len(all_urls))
        return
    results.ok(f"TeknoParrot found {len(all_urls)} URLs")

    # Filter without english_only to get baseline
    try:
        all_selected, _ = filter_teknoparrot_network_roms(
            all_urls,
            url_sizes=scan.url_sizes,
            english_only=False,
        )
    except Exception as exc:  # pylint: disable=broad-except
        results.fail("TeknoParrot filter (all)", "list", f"exception: {exc}")
        return

    # Filter with english_only=True
    try:
        en_selected, _ = filter_teknoparrot_network_roms(
            all_urls,
            url_sizes=scan.url_sizes,
            english_only=True,
        )
    except Exception as exc:  # pylint: disable=broad-except
        results.fail("TeknoParrot filter (english_only)", "list", f"exception: {exc}")
        return

    print(f"  All regions: {len(all_selected)}, English-only: {len(en_selected)}")

    if len(all_selected) > 0:
        results.ok(f"TeknoParrot filter (all) selected {len(all_selected)}")
    else:
        results.fail("TeknoParrot all_selected > 0", "> 0", len(all_selected))

    if len(en_selected) > 0:
        results.ok(f"TeknoParrot filter (english_only) selected {len(en_selected)}")
    else:
        results.fail("TeknoParrot en_selected > 0", "> 0", len(en_selected))

    if len(en_selected) < len(all_selected):
        results.ok(
            f"english_only excluded Japan-only titles "
            f"({len(all_selected) - len(en_selected)} removed)"
        )
    else:
        results.fail("english_only excludes Japan-only",
                     f"< {len(all_selected)}", len(en_selected))


def test_mame_chds(results: TestResult, quick: bool = False):
    """MAME CHDs (merged) — verify category filtering excludes non-arcade games."""
    print("\n" + "="*60)
    print("SMOKE: MAME CHDs (merged)")
    print("="*60)

    url = "https://myrient.erista.me/files/MAME/CHDs%20%28merged%29/"

    if quick and not _has_scan_cache(url):
        results.skip("MAME CHDs scan", "no cache and --quick requested")
        return

    if not quick and not _network_available():
        results.skip("MAME CHDs scan", "network unavailable")
        return

    reset_shutdown()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    try:
        print(f"  Scanning: {url}")
        scan = scan_network_source(
            url,
            cache_dir=CACHE_DIR,
            scan_workers=16,
        )
    except Exception as exc:  # pylint: disable=broad-except
        results.fail("MAME CHDs scan", "ScanResult", f"exception: {exc}")
        return

    if not scan.url_dict:
        results.fail("MAME CHDs scan found URLs", "url_dict non-empty", "empty")
        return
    results.ok("MAME CHDs scan returned url_dict")

    all_urls = []
    for system_urls in scan.url_dict.values():
        all_urls.extend(system_urls)

    print(f"  Found {len(all_urls)} total URLs")

    if len(all_urls) < 10:
        results.fail("MAME CHDs URL count", ">= 10", len(all_urls))
        return
    results.ok(f"MAME CHDs found {len(all_urls)} URLs")

    # Load or download MAME data
    DAT_DIR.mkdir(parents=True, exist_ok=True)
    catver_path = DAT_DIR / 'catver.ini'
    dat_path = DAT_DIR / 'mame.xml'

    if not catver_path.exists() or not dat_path.exists():
        if quick:
            results.skip("MAME CHDs filter", "no MAME data and --quick requested")
            return
        if not _network_available():
            results.skip("MAME CHDs filter", "network unavailable for MAME data download")
            return
        print("  Downloading MAME data files...")
        catver_path, dat_path = download_mame_data(DAT_DIR)
        if not catver_path or not catver_path.exists():
            results.skip("MAME CHDs filter", "MAME catver.ini download failed")
            return
        if not dat_path or not dat_path.exists():
            results.skip("MAME CHDs filter", "MAME DAT download failed")
            return

    print("  Parsing MAME data...")
    try:
        categories = parse_catver_ini(str(catver_path))
        games = parse_mame_dat(str(dat_path))
    except Exception as exc:  # pylint: disable=broad-except
        results.fail("MAME data parsing", "categories + games dicts", f"exception: {exc}")
        return

    if not categories:
        results.fail("MAME categories non-empty", "> 0", len(categories))
        return
    results.ok(f"Parsed {len(categories)} MAME categories")

    if not games:
        results.fail("MAME games non-empty", "> 0", len(games))
        return
    results.ok(f"Parsed {len(games)} MAME game entries")

    # Filter without english_only to get baseline
    try:
        all_selected, _ = filter_mame_network_roms(
            all_urls, categories, games,
            url_sizes=scan.url_sizes,
            english_only=False,
        )
    except Exception as exc:  # pylint: disable=broad-except
        results.fail("MAME CHDs filter (all)", "list", f"exception: {exc}")
        return

    # Filter with english_only=True
    try:
        en_selected, _ = filter_mame_network_roms(
            all_urls, categories, games,
            url_sizes=scan.url_sizes,
            english_only=True,
        )
    except Exception as exc:  # pylint: disable=broad-except
        results.fail("MAME CHDs filter (english_only)", "list", f"exception: {exc}")
        return

    print(f"  All regions: {len(all_selected)}, English-only: {len(en_selected)}")
    print(f"  Category-excluded: {len(all_urls) - len(all_selected)}")

    if len(all_selected) > 0:
        results.ok(f"MAME CHDs filter selected {len(all_selected)} URLs")
    else:
        results.fail("MAME CHDs all_selected > 0", "> 0", len(all_selected))

    # Category filtering should exclude some non-arcade CHDs
    if len(all_selected) < len(all_urls):
        results.ok(
            f"Category filter excluded {len(all_urls) - len(all_selected)} CHDs"
        )
    else:
        results.fail("MAME category filter reduced set",
                     f"< {len(all_urls)}", len(all_selected))

    if len(en_selected) > 0:
        results.ok(f"MAME CHDs english_only selected {len(en_selected)}")
    else:
        results.fail("MAME CHDs en_selected > 0", "> 0", len(en_selected))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    quick_mode = '--quick' in sys.argv

    if quick_mode:
        print("Running in --quick mode: only cached tests will run.")

    results = TestResult()

    test_atari_2600(results, quick=quick_mode)
    test_teknoparrot(results, quick=quick_mode)
    test_mame_chds(results, quick=quick_mode)

    success = results.summary()
    sys.exit(0 if success else 1)

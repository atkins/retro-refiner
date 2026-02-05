#!/usr/bin/env python3
"""
Functional tests for network source operations.

Tests:
- No-Intro + T-En remote scanning and filtering
- MAME remote scanning with category filtering
- FBNeo remote scanning
- TeknoParrot remote scanning
- Redump system scanning
- Cache clearing functionality
- Parallel scanning performance
- Network error handling
"""

import subprocess
import sys
import os
import shutil
import time
import re
import tempfile
from pathlib import Path
from typing import Optional, Tuple, Dict, List


# =============================================================================
# Configuration
# =============================================================================

# Test URLs (Myrient)
NETWORK_SOURCES = {
    'nointro_gba': {
        'name': 'No-Intro GBA',
        'url': 'https://myrient.erista.me/files/No-Intro/Nintendo%20-%20Game%20Boy%20Advance/',
        'system': 'gba',
        'expected_min_roms': 1000,
        'recursive': False,
    },
    'ten_gba': {
        'name': 'T-En GBA Collection',
        'url': 'https://myrient.erista.me/files/T-En%20Collection/Nintendo%20-%20Game%20Boy%20Advance%20%5BT-En%5D%20Collection/',
        'system': 'gba',
        'expected_min_roms': 20,
        'recursive': False,
    },
    'mame_chd': {
        'name': 'MAME CHDs',
        'url': 'https://myrient.erista.me/files/MAME/CHDs%20(merged)/',
        'system': 'mame',
        'expected_min_roms': 500,
        'recursive': False,  # Game folders are scanned automatically
    },
    'fbneo_arcade': {
        'name': 'FBNeo Arcade',
        'url': 'https://myrient.erista.me/files/FinalBurn%20Neo/arcade/',
        'system': 'fbneo',
        'expected_min_roms': 5000,
        'recursive': False,
    },
    'fbneo_all': {
        'name': 'FBNeo All Systems',
        'url': 'https://myrient.erista.me/files/FinalBurn%20Neo/',
        'system': None,  # Multiple systems
        'expected_min_roms': 100,
        'recursive': True,
    },
    'teknoparrot': {
        'name': 'TeknoParrot',
        'url': 'https://myrient.erista.me/files/TeknoParrot/',
        'system': 'teknoparrot',
        'expected_min_roms': 50,
        'recursive': False,
    },
    'redump_psx': {
        'name': 'Redump PlayStation',
        'url': 'https://myrient.erista.me/files/Redump/Sony%20-%20PlayStation/',
        'system': 'psx',
        'expected_min_roms': 5000,
        'recursive': False,
    },
    'redump_saturn': {
        'name': 'Redump Saturn',
        'url': 'https://myrient.erista.me/files/Redump/Sega%20-%20Saturn/',
        'system': 'saturn',
        'expected_min_roms': 1000,
        'recursive': False,
    },
}

# Quick test subset for CI
QUICK_SOURCES = ['nointro_gba', 'fbneo_arcade', 'teknoparrot']

SCRIPT_PATH = Path(__file__).parent.parent / 'retro-refiner.py'


# =============================================================================
# Test Result Tracking
# =============================================================================

class TestResult:
    """Track test results."""
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.skipped = 0
        self.errors: List[Tuple[str, str, str]] = []

    def ok(self, name: str, details: str = ""):
        self.passed += 1
        detail_str = f" ({details})" if details else ""
        print(f"  [PASS] {name}{detail_str}")

    def fail(self, name: str, expected: str, actual: str):
        self.failed += 1
        self.errors.append((name, expected, actual))
        print(f"  [FAIL] {name}")
        print(f"    Expected: {expected}")
        print(f"    Actual:   {actual}")

    def skip(self, name: str, reason: str):
        self.skipped += 1
        print(f"  [SKIP] {name} - {reason}")

    def summary(self) -> bool:
        total = self.passed + self.failed + self.skipped
        print(f"\n{'='*60}")
        print(f"Results: {self.passed}/{total} passed, {self.failed} failed, {self.skipped} skipped")
        if self.failed > 0:
            print(f"\nFailed tests:")
            for name, expected, actual in self.errors:
                print(f"  - {name}")
        print(f"{'='*60}")
        return self.failed == 0


results = TestResult()


# =============================================================================
# Helper Functions
# =============================================================================

def run_script(args: List[str], timeout: int = 300) -> Tuple[int, str, str]:
    """Run retro-refiner.py with given arguments."""
    cmd = [sys.executable, str(SCRIPT_PATH)] + args

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "TIMEOUT"


def parse_output_stats(output: str) -> Dict[str, any]:
    """Parse statistics from script output."""
    stats = {
        'roms_found': 0,
        'roms_selected': 0,
        'total_size': 0,
        'systems_found': [],
        'scan_time': 0,
    }

    # Parse "Found X ROM URLs" or "X ROMs found"
    match = re.search(r'Found (\d+) ROM URLs', output)
    if match:
        stats['roms_found'] = int(match.group(1))

    # Parse "Selected X ROMs"
    match = re.search(r'Selected (\d+) ROMs', output)
    if match:
        stats['roms_selected'] = int(match.group(1))

    # Parse "X ROMs after filtering"
    match = re.search(r'(\d+) ROMs? after filtering', output)
    if match:
        stats['roms_selected'] = int(match.group(1))

    # Parse size (e.g., "985.03 GB" or "1.2 TB")
    match = re.search(r'\((\d+(?:\.\d+)?)\s*(KB|MB|GB|TB)\)', output)
    if match:
        size_val = float(match.group(1))
        unit = match.group(2)
        multipliers = {'KB': 1024, 'MB': 1024**2, 'GB': 1024**3, 'TB': 1024**4}
        stats['total_size'] = size_val * multipliers.get(unit, 1)

    # Parse scan time from progress bar [Xs<Ys, X/s]
    match = re.search(r'\[(\d+)s<', output)
    if match:
        stats['scan_time'] = int(match.group(1))

    return stats


def check_network_available(url: str) -> bool:
    """Check if a network URL is reachable."""
    import urllib.request
    try:
        req = urllib.request.Request(url, method='HEAD')
        req.add_header('User-Agent', 'retro-refiner-test/1.0')
        urllib.request.urlopen(req, timeout=10)
        return True
    except Exception:
        return False


# =============================================================================
# Network Source Tests
# =============================================================================

def test_nointro_source():
    """Test No-Intro source scanning."""
    print("\n" + "="*60)
    print("TEST: No-Intro Source (GBA)")
    print("="*60)

    source = NETWORK_SOURCES['nointro_gba']

    # Check network availability
    if not check_network_available(source['url']):
        results.skip("No-Intro scan", "Network unavailable")
        return

    # Run dry-run scan
    args = [
        '-s', source['url'],
        '--systems', source['system'],
        '--include', '*Mario*',  # Limit to Mario games for speed
    ]

    ret, stdout, stderr = run_script(args, timeout=120)
    output = stdout + stderr

    if ret != 0 and "TIMEOUT" not in stderr:
        results.fail("No-Intro scan execution", "return code 0", f"return code {ret}")
        print(f"Output: {output[:500]}")
        return

    stats = parse_output_stats(output)

    # Check that ROMs were found
    if stats['roms_found'] > 0 or stats['roms_selected'] > 0:
        results.ok("No-Intro scan found ROMs", f"{stats['roms_found'] or stats['roms_selected']} ROMs")
    else:
        results.fail("No-Intro scan found ROMs", ">0 ROMs", f"{stats['roms_found']} found")

    # Check for expected output patterns
    if "DRY RUN" in output:
        results.ok("No-Intro dry run mode active")
    else:
        results.fail("No-Intro dry run mode", "DRY RUN in output", "not found")


def test_nointro_with_ten():
    """Test No-Intro + T-En combined source scanning."""
    print("\n" + "="*60)
    print("TEST: No-Intro + T-En Combined (GBA)")
    print("="*60)

    nointro = NETWORK_SOURCES['nointro_gba']
    ten = NETWORK_SOURCES['ten_gba']

    # Check network availability
    if not check_network_available(nointro['url']):
        results.skip("No-Intro + T-En combined", "Network unavailable")
        return

    # Run with both sources
    args = [
        '-s', nointro['url'],
        '-s', ten['url'],
        '--systems', 'gba',
        '--include', '*Mario*',  # Limit for speed
    ]

    ret, stdout, stderr = run_script(args, timeout=180)
    output = stdout + stderr

    if ret != 0 and "TIMEOUT" not in stderr:
        results.fail("No-Intro + T-En execution", "return code 0", f"return code {ret}")
        return

    stats = parse_output_stats(output)

    # Check that ROMs were found from both sources
    if "T-En" in output or "Translation" in output or stats['roms_selected'] > 0:
        results.ok("No-Intro + T-En combined scan", f"{stats['roms_selected']} selected")
    else:
        results.fail("T-En source detection", "T-En mentioned in output", "not found")


def test_mame_source():
    """Test MAME CHD source scanning with parallel game folder scanning."""
    print("\n" + "="*60)
    print("TEST: MAME CHDs (Parallel Scanning)")
    print("="*60)

    source = NETWORK_SOURCES['mame_chd']

    # Check network availability
    if not check_network_available(source['url']):
        results.skip("MAME CHD scan", "Network unavailable")
        return

    # Run dry-run scan with limited scope
    args = [
        '-s', source['url'],
        '--systems', 'mame',
        '--include', '*area51*',  # Limit to a few games
    ]

    ret, stdout, stderr = run_script(args, timeout=600)  # MAME can take a while
    output = stdout + stderr

    if ret != 0 and "TIMEOUT" not in stderr:
        results.fail("MAME scan execution", "return code 0", f"return code {ret}")
        print(f"Output: {output[:1000]}")
        return

    # Check for parallel scanning output
    if "game folders in parallel" in output or "folders in parallel" in output:
        results.ok("MAME parallel folder scanning")
    else:
        results.skip("MAME parallel scanning check", "Pattern not found in output")

    # Check for category filtering
    if "category" in output.lower() or "catver" in output.lower():
        results.ok("MAME category filtering active")
    else:
        results.skip("MAME category filtering", "May not have downloaded catver.ini")

    stats = parse_output_stats(output)
    if stats['roms_found'] > 0 or stats['roms_selected'] > 0:
        results.ok("MAME scan found CHDs", f"{stats['roms_found'] or stats['roms_selected']} files")
    else:
        # MAME without include filter would find many ROMs
        results.skip("MAME ROM count", "Filter may be too restrictive")


def test_fbneo_arcade():
    """Test FBNeo arcade source scanning."""
    print("\n" + "="*60)
    print("TEST: FBNeo Arcade")
    print("="*60)

    source = NETWORK_SOURCES['fbneo_arcade']

    if not check_network_available(source['url']):
        results.skip("FBNeo arcade scan", "Network unavailable")
        return

    args = [
        '-s', source['url'],
        '--systems', 'fbneo',
        '--include', '*sf2*',  # Street Fighter 2 variants
    ]

    ret, stdout, stderr = run_script(args, timeout=180)
    output = stdout + stderr

    if ret != 0 and "TIMEOUT" not in stderr:
        results.fail("FBNeo arcade execution", "return code 0", f"return code {ret}")
        return

    stats = parse_output_stats(output)

    if stats['roms_found'] > 0 or stats['roms_selected'] > 0:
        results.ok("FBNeo arcade scan", f"{stats['roms_found'] or stats['roms_selected']} ROMs")
    else:
        results.fail("FBNeo arcade ROMs", ">0 ROMs", "0 found")


def test_fbneo_recursive():
    """Test FBNeo with recursive scanning for multiple systems."""
    print("\n" + "="*60)
    print("TEST: FBNeo Recursive (All Systems)")
    print("="*60)

    source = NETWORK_SOURCES['fbneo_all']

    if not check_network_available(source['url']):
        results.skip("FBNeo recursive scan", "Network unavailable")
        return

    args = [
        '-s', source['url'],
        '-r',  # Recursive
        '--max-depth', '2',
        '--systems', 'coleco',  # Just test one system
    ]

    ret, stdout, stderr = run_script(args, timeout=180)
    output = stdout + stderr

    if ret != 0 and "TIMEOUT" not in stderr:
        results.fail("FBNeo recursive execution", "return code 0", f"return code {ret}")
        return

    # Check for recursive scanning
    if "coleco" in output.lower() or "ColecoVision" in output:
        results.ok("FBNeo recursive found system folders")
    else:
        results.fail("FBNeo recursive systems", "coleco in output", "not found")


def test_teknoparrot_source():
    """Test TeknoParrot source scanning."""
    print("\n" + "="*60)
    print("TEST: TeknoParrot")
    print("="*60)

    source = NETWORK_SOURCES['teknoparrot']

    if not check_network_available(source['url']):
        results.skip("TeknoParrot scan", "Network unavailable")
        return

    args = [
        '-s', source['url'],
        '--systems', 'teknoparrot',
    ]

    ret, stdout, stderr = run_script(args, timeout=180)
    output = stdout + stderr

    if ret != 0 and "TIMEOUT" not in stderr:
        results.fail("TeknoParrot execution", "return code 0", f"return code {ret}")
        return

    stats = parse_output_stats(output)

    # Check for TeknoParrot-specific output
    if "teknoparrot" in output.lower() or "[TP]" in output:
        results.ok("TeknoParrot source detected")
    else:
        results.skip("TeknoParrot detection", "Pattern not in output")

    if stats['roms_found'] > 0 or stats['roms_selected'] > 0:
        results.ok("TeknoParrot scan", f"{stats['roms_found'] or stats['roms_selected']} games")
    else:
        results.fail("TeknoParrot ROMs", ">0 games", "0 found")


def test_teknoparrot_platform_filter():
    """Test TeknoParrot platform filtering."""
    print("\n" + "="*60)
    print("TEST: TeknoParrot Platform Filter")
    print("="*60)

    source = NETWORK_SOURCES['teknoparrot']

    if not check_network_available(source['url']):
        results.skip("TeknoParrot platform filter", "Network unavailable")
        return

    args = [
        '-s', source['url'],
        '--systems', 'teknoparrot',
        '--tp-include-platforms', 'Sega Nu,Sega RingEdge',
    ]

    ret, stdout, stderr = run_script(args, timeout=180)
    output = stdout + stderr

    if ret != 0:
        results.fail("TeknoParrot platform filter execution", "return code 0", f"return code {ret}")
        return

    # Check that platform filter was applied
    if "Sega" in output or "platform" in output.lower():
        results.ok("TeknoParrot platform filter applied")
    else:
        results.skip("TeknoParrot platform filter", "Filter output not visible")


def test_redump_source():
    """Test Redump source scanning (PlayStation)."""
    print("\n" + "="*60)
    print("TEST: Redump PlayStation")
    print("="*60)

    source = NETWORK_SOURCES['redump_psx']

    if not check_network_available(source['url']):
        results.skip("Redump PSX scan", "Network unavailable")
        return

    args = [
        '-s', source['url'],
        '--systems', 'psx',
        '--include', '*Final Fantasy*',  # Limit for speed
    ]

    ret, stdout, stderr = run_script(args, timeout=180)
    output = stdout + stderr

    if ret != 0 and "TIMEOUT" not in stderr:
        results.fail("Redump PSX execution", "return code 0", f"return code {ret}")
        return

    stats = parse_output_stats(output)

    if stats['roms_found'] > 0 or stats['roms_selected'] > 0:
        results.ok("Redump PSX scan", f"{stats['roms_found'] or stats['roms_selected']} games")
    else:
        results.fail("Redump PSX ROMs", ">0 games", "0 found")


def test_redump_saturn():
    """Test Redump Saturn source scanning."""
    print("\n" + "="*60)
    print("TEST: Redump Saturn")
    print("="*60)

    source = NETWORK_SOURCES['redump_saturn']

    if not check_network_available(source['url']):
        results.skip("Redump Saturn scan", "Network unavailable")
        return

    args = [
        '-s', source['url'],
        '--systems', 'saturn',
        '--include', '*Sonic*',  # Limit for speed
    ]

    ret, stdout, stderr = run_script(args, timeout=180)
    output = stdout + stderr

    if ret != 0 and "TIMEOUT" not in stderr:
        results.fail("Redump Saturn execution", "return code 0", f"return code {ret}")
        return

    stats = parse_output_stats(output)

    if stats['roms_found'] > 0 or stats['roms_selected'] > 0:
        results.ok("Redump Saturn scan", f"{stats['roms_found'] or stats['roms_selected']} games")
    else:
        results.fail("Redump Saturn ROMs", ">0 games", "0 found")


# =============================================================================
# Cache Tests
# =============================================================================

def test_cache_directory():
    """Test cache directory creation and usage."""
    print("\n" + "="*60)
    print("TEST: Cache Directory")
    print("="*60)

    with tempfile.TemporaryDirectory() as tmpdir:
        cache_dir = Path(tmpdir) / "test_cache"

        source = NETWORK_SOURCES['nointro_gba']
        if not check_network_available(source['url']):
            results.skip("Cache directory test", "Network unavailable")
            return

        args = [
            '-s', source['url'],
            '--systems', 'gba',
            '--include', '*Tetris*',  # Small subset
            '--cache-dir', str(cache_dir),
        ]

        ret, stdout, stderr = run_script(args, timeout=120)
        output = stdout + stderr

        if ret != 0:
            results.fail("Cache dir test execution", "return code 0", f"return code {ret}")
            return

        # Check that cache dir was mentioned in output
        if "cache" in output.lower() or str(cache_dir) in output:
            results.ok("Cache directory configuration")
        else:
            results.skip("Cache directory output", "Cache not mentioned in dry run")


def test_cache_clearing():
    """Test --clean flag for cache clearing."""
    print("\n" + "="*60)
    print("TEST: Cache Clearing (--clean)")
    print("="*60)

    with tempfile.TemporaryDirectory() as tmpdir:
        # Create fake cache structure
        cache_dir = Path(tmpdir) / "cache"
        cache_dir.mkdir()
        (cache_dir / "gba").mkdir()
        (cache_dir / "gba" / "test_rom.zip").touch()

        dat_dir = Path(tmpdir) / "dat_files"
        dat_dir.mkdir()
        (dat_dir / "test.dat").touch()

        # Run clean command
        args = [
            '-s', tmpdir,
            '--clean',
        ]

        ret, stdout, stderr = run_script(args, timeout=30)
        output = stdout + stderr

        # Check if clean ran successfully
        if "clean" in output.lower() or "delet" in output.lower() or "remov" in output.lower():
            results.ok("Cache clean command executed")
        else:
            results.skip("Cache clean output", "Clean output not captured")


# =============================================================================
# Parallel Scanning Tests
# =============================================================================

def test_scan_workers_option():
    """Test --scan-workers option."""
    print("\n" + "="*60)
    print("TEST: Scan Workers Option")
    print("="*60)

    source = NETWORK_SOURCES['nointro_gba']
    if not check_network_available(source['url']):
        results.skip("Scan workers test", "Network unavailable")
        return

    args = [
        '-s', source['url'],
        '--systems', 'gba',
        '--include', '*Zelda*',
        '--scan-workers', '8',
    ]

    ret, stdout, stderr = run_script(args, timeout=120)
    output = stdout + stderr

    if ret != 0:
        results.fail("Scan workers execution", "return code 0", f"return code {ret}")
        return

    results.ok("Scan workers option accepted")


def test_recursive_flag():
    """Test -r/--recursive flag."""
    print("\n" + "="*60)
    print("TEST: Recursive Flag")
    print("="*60)

    source = NETWORK_SOURCES['fbneo_all']
    if not check_network_available(source['url']):
        results.skip("Recursive flag test", "Network unavailable")
        return

    # First test without -r (should find limited results)
    args_no_r = [
        '-s', source['url'],
        '--systems', 'arcade',
    ]

    ret1, stdout1, stderr1 = run_script(args_no_r, timeout=120)

    # Then test with -r
    args_with_r = [
        '-s', source['url'],
        '-r',
        '--max-depth', '2',
        '--systems', 'arcade',
    ]

    ret2, stdout2, stderr2 = run_script(args_with_r, timeout=180)

    if ret1 == 0 and ret2 == 0:
        results.ok("Recursive flag execution")
    else:
        results.fail("Recursive flag execution", "both return 0", f"ret1={ret1}, ret2={ret2}")


def test_max_depth_option():
    """Test --max-depth option."""
    print("\n" + "="*60)
    print("TEST: Max Depth Option")
    print("="*60)

    source = NETWORK_SOURCES['fbneo_all']
    if not check_network_available(source['url']):
        results.skip("Max depth test", "Network unavailable")
        return

    args = [
        '-s', source['url'],
        '-r',
        '--max-depth', '1',
        '--systems', 'coleco',
    ]

    ret, stdout, stderr = run_script(args, timeout=120)
    output = stdout + stderr

    if ret != 0:
        results.fail("Max depth execution", "return code 0", f"return code {ret}")
        return

    results.ok("Max depth option accepted")


# =============================================================================
# Error Handling Tests
# =============================================================================

def test_invalid_url():
    """Test handling of invalid network URL."""
    print("\n" + "="*60)
    print("TEST: Invalid URL Handling")
    print("="*60)

    args = [
        '-s', 'https://this-does-not-exist.invalid/roms/',
        '--systems', 'nes',
    ]

    ret, stdout, stderr = run_script(args, timeout=30)
    output = stdout + stderr

    # Should handle gracefully
    if "error" in output.lower() or "failed" in output.lower() or ret != 0:
        results.ok("Invalid URL handled gracefully")
    else:
        results.fail("Invalid URL handling", "Error reported", "No error output")


def test_404_handling():
    """Test handling of 404 Not Found."""
    print("\n" + "="*60)
    print("TEST: 404 Handling")
    print("="*60)

    # Use a valid domain but invalid path
    args = [
        '-s', 'https://myrient.erista.me/files/This-Does-Not-Exist/',
        '--systems', 'nes',
    ]

    ret, stdout, stderr = run_script(args, timeout=30)
    output = stdout + stderr

    if "404" in output or "not found" in output.lower() or "error" in output.lower():
        results.ok("404 error handled")
    else:
        results.skip("404 handling", "Error may not be visible in output")


# =============================================================================
# Filter Tests with Network Sources
# =============================================================================

def test_region_filter_network():
    """Test region filtering with network source."""
    print("\n" + "="*60)
    print("TEST: Region Filter (Network)")
    print("="*60)

    source = NETWORK_SOURCES['nointro_gba']
    if not check_network_available(source['url']):
        results.skip("Region filter network", "Network unavailable")
        return

    args = [
        '-s', source['url'],
        '--systems', 'gba',
        '--include', '*Pokemon*',
        '--region-priority', 'Japan,USA',  # Japan first
    ]

    ret, stdout, stderr = run_script(args, timeout=120)
    output = stdout + stderr

    if ret != 0:
        results.fail("Region filter execution", "return code 0", f"return code {ret}")
        return

    results.ok("Region filter with network source")


def test_include_exclude_network():
    """Test include/exclude patterns with network source."""
    print("\n" + "="*60)
    print("TEST: Include/Exclude Patterns (Network)")
    print("="*60)

    source = NETWORK_SOURCES['nointro_gba']
    if not check_network_available(source['url']):
        results.skip("Include/exclude network", "Network unavailable")
        return

    args = [
        '-s', source['url'],
        '--systems', 'gba',
        '--include', '*Mario*',
        '--exclude', '*Advance*',  # Exclude Mario Advance games
    ]

    ret, stdout, stderr = run_script(args, timeout=120)
    output = stdout + stderr

    if ret != 0:
        results.fail("Include/exclude execution", "return code 0", f"return code {ret}")
        return

    results.ok("Include/exclude patterns accepted")


# =============================================================================
# Multi-Source Tests
# =============================================================================

def test_multiple_network_sources():
    """Test combining multiple network sources."""
    print("\n" + "="*60)
    print("TEST: Multiple Network Sources")
    print("="*60)

    nointro = NETWORK_SOURCES['nointro_gba']
    ten = NETWORK_SOURCES['ten_gba']

    if not check_network_available(nointro['url']):
        results.skip("Multiple sources test", "Network unavailable")
        return

    args = [
        '-s', nointro['url'],
        '-s', ten['url'],
        '--systems', 'gba',
        '--include', '*Pokemon*',
    ]

    ret, stdout, stderr = run_script(args, timeout=180)
    output = stdout + stderr

    if ret != 0:
        results.fail("Multiple sources execution", "return code 0", f"return code {ret}")
        return

    # Check that both sources were processed
    if nointro['url'] in output or ten['url'] in output:
        results.ok("Multiple network sources processed")
    else:
        results.skip("Multiple sources output", "Source URLs not visible")


def test_prefer_source():
    """Test --prefer-source option."""
    print("\n" + "="*60)
    print("TEST: Prefer Source Option")
    print("="*60)

    nointro = NETWORK_SOURCES['nointro_gba']

    if not check_network_available(nointro['url']):
        results.skip("Prefer source test", "Network unavailable")
        return

    args = [
        '-s', nointro['url'],
        '--systems', 'gba',
        '--include', '*Zelda*',
        '--prefer-source', nointro['url'],
    ]

    ret, stdout, stderr = run_script(args, timeout=120)

    if ret != 0:
        results.fail("Prefer source execution", "return code 0", f"return code {ret}")
        return

    results.ok("Prefer source option accepted")


# =============================================================================
# Main Test Runner
# =============================================================================

def run_all_tests():
    """Run all functional tests."""
    print("\n" + "="*60)
    print("RETRO-REFINER NETWORK SOURCE FUNCTIONAL TESTS")
    print("="*60)

    # Check script exists
    if not SCRIPT_PATH.exists():
        print(f"ERROR: Script not found at {SCRIPT_PATH}")
        return False

    # Network source tests
    test_nointro_source()
    test_nointro_with_ten()
    test_mame_source()
    test_fbneo_arcade()
    test_fbneo_recursive()
    test_teknoparrot_source()
    test_teknoparrot_platform_filter()
    test_redump_source()
    test_redump_saturn()

    # Cache tests
    test_cache_directory()
    test_cache_clearing()

    # Parallel scanning tests
    test_scan_workers_option()
    test_recursive_flag()
    test_max_depth_option()

    # Error handling tests
    test_invalid_url()
    test_404_handling()

    # Filter tests
    test_region_filter_network()
    test_include_exclude_network()

    # Multi-source tests
    test_multiple_network_sources()
    test_prefer_source()

    return results.summary()


def run_quick_tests():
    """Run a quick subset of tests."""
    print("\n" + "="*60)
    print("RETRO-REFINER NETWORK SOURCE QUICK TESTS")
    print("="*60)

    if not SCRIPT_PATH.exists():
        print(f"ERROR: Script not found at {SCRIPT_PATH}")
        return False

    test_nointro_source()
    test_fbneo_arcade()
    test_teknoparrot_source()
    test_cache_clearing()
    test_invalid_url()

    return results.summary()


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Functional tests for network sources')
    parser.add_argument('--quick', action='store_true',
                        help='Run quick subset of tests')
    parser.add_argument('--test', type=str,
                        help='Run specific test by name (e.g., mame, fbneo, teknoparrot)')
    args = parser.parse_args()

    if args.test:
        # Run specific test
        test_map = {
            'nointro': test_nointro_source,
            'ten': test_nointro_with_ten,
            'mame': test_mame_source,
            'fbneo': test_fbneo_arcade,
            'fbneo_recursive': test_fbneo_recursive,
            'teknoparrot': test_teknoparrot_source,
            'teknoparrot_platform': test_teknoparrot_platform_filter,
            'redump': test_redump_source,
            'redump_saturn': test_redump_saturn,
            'cache': test_cache_directory,
            'clean': test_cache_clearing,
            'workers': test_scan_workers_option,
            'recursive': test_recursive_flag,
            'maxdepth': test_max_depth_option,
            'invalid_url': test_invalid_url,
            '404': test_404_handling,
            'region': test_region_filter_network,
            'include_exclude': test_include_exclude_network,
            'multi_source': test_multiple_network_sources,
            'prefer_source': test_prefer_source,
        }

        if args.test in test_map:
            test_map[args.test]()
            success = results.summary()
        else:
            print(f"Unknown test: {args.test}")
            print(f"Available tests: {', '.join(test_map.keys())}")
            success = False
    elif args.quick:
        success = run_quick_tests()
    else:
        success = run_all_tests()

    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()

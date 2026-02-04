#!/usr/bin/env python3
"""
Benchmark download performance with different aria2c settings.
Tests various combinations of parallel downloads and connections per file.
Supports both Myrient and Archive.org sources with small and large files.
"""

import subprocess
import time
import os
import shutil
import sys
import argparse
from pathlib import Path

# Test sources organized by site and file size
SOURCES = {
    'myrient': {
        'small': {
            'name': 'Myrient - Game Boy (~32KB-1MB)',
            'url': 'https://myrient.erista.me/files/No-Intro/Nintendo%20-%20Game%20Boy/',
            'system': 'gameboy',
            'filter': '*USA*',
            'requires_auth': False,
        },
        'large': {
            'name': 'Myrient - PlayStation 2 (~1-4GB)',
            'url': 'https://myrient.erista.me/files/Redump/Sony%20-%20PlayStation%202/',
            'system': 'ps2',
            'filter': '*USA*',
            'requires_auth': False,
        },
    },
    'archiveorg': {
        'small': {
            'name': 'Archive.org - Game Boy (~32KB-1MB)',
            'url': 'https://archive.org/download/nointro.gb/',
            'system': 'gameboy',
            'filter': '*USA*',
            'requires_auth': True,
        },
        'large': {
            'name': 'Archive.org - PlayStation 2 (~1-4GB)',
            'url': 'https://archive.org/download/redump.ps2/',
            'system': 'ps2',
            'filter': '*USA*',
            'requires_auth': True,
        },
    },
}

# Test configurations: (parallel_downloads, connections_per_file)
# Tests powers of 2 from 1 to 16
CONFIGS = [
    (1, 1),   # Baseline single
    (1, 2),
    (1, 4),
    (1, 8),
    (1, 16),
    (2, 1),
    (2, 2),
    (2, 4),
    (2, 8),
    (2, 16),
    (4, 1),
    (4, 2),
    (4, 4),   # Default
    (4, 8),
    (4, 16),
    (8, 1),
    (8, 2),
    (8, 4),
    (8, 8),
    (8, 16),
    (16, 1),
    (16, 2),
    (16, 4),
    (16, 8),
    (16, 16), # Maximum
]

# Reduced config set for quick tests
CONFIGS_QUICK = [
    (1, 1),   # Baseline
    (4, 4),   # Default
    (8, 8),   # Balanced high
    (16, 16), # Maximum
]

TEST_DURATION = 30  # seconds per test


def get_cache_size(cache_dir: Path) -> int:
    """Get total size of files in cache directory."""
    total = 0
    if cache_dir.exists():
        for f in cache_dir.rglob('*'):
            if f.is_file():
                total += f.stat().st_size
    return total


def format_size(size_bytes: float) -> str:
    """Format bytes as human-readable size."""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.2f} TB"


def check_archive_org_auth() -> bool:
    """Check if Archive.org credentials are available."""
    access_key = os.environ.get('IA_ACCESS_KEY')
    secret_key = os.environ.get('IA_SECRET_KEY')
    return bool(access_key and secret_key)


def run_benchmark(source: dict, parallel: int, connections: int, cache_dir: Path,
                  test_num: int, total_tests: int, duration: int) -> dict:
    """Run a single benchmark test."""

    # Clear cache before test - handle stubborn directories
    for attempt in range(3):
        try:
            if cache_dir.exists():
                shutil.rmtree(cache_dir)
            break
        except OSError:
            time.sleep(1)
    cache_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*60}")
    print(f"Test {test_num}/{total_tests}: parallel={parallel}, connections={connections}")
    print(f"{'='*60}")

    script_path = Path(__file__).parent.parent / 'retro-refiner.py'
    cmd = [
        sys.executable, str(script_path),
        '-s', source['url'],
        '--parallel', str(parallel),
        '--connections', str(connections),
        '--cache-dir', str(cache_dir),
        '--systems', source['system'],
        '--include', source['filter'],
        '--commit'
    ]

    print(f"Running for {duration} seconds...")

    start_time = time.time()
    start_size = get_cache_size(cache_dir)

    # Start the process
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

    # Let it run for duration seconds
    try:
        proc.wait(timeout=duration)
        actual_duration = time.time() - start_time
        print(f"Process completed in {actual_duration:.1f}s")
    except subprocess.TimeoutExpired:
        actual_duration = duration
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        print(f"Stopped after {duration}s timeout")

    # Measure downloaded data
    end_size = get_cache_size(cache_dir)
    downloaded = end_size - start_size
    speed = downloaded / actual_duration if actual_duration > 0 else 0

    result = {
        'parallel': parallel,
        'connections': connections,
        'duration': actual_duration,
        'downloaded': downloaded,
        'speed': speed,
        'speed_mbps': (speed * 8) / (1024 * 1024),  # Megabits per second
    }

    print(f"Downloaded: {format_size(downloaded)}")
    print(f"Speed: {format_size(speed)}/s ({result['speed_mbps']:.2f} Mbps)")

    return result


def run_source_benchmark(source: dict, configs: list, cache_dir: Path, duration: int) -> list:
    """Run all benchmarks for a single source."""
    results = []
    total_tests = len(configs)

    print(f"\n{'#'*70}")
    print(f"# Testing: {source['name']}")
    print(f"# URL: {source['url']}")
    print(f"{'#'*70}")

    for i, (parallel, connections) in enumerate(configs, 1):
        try:
            result = run_benchmark(source, parallel, connections, cache_dir, i, total_tests, duration)
            results.append(result)
        except KeyboardInterrupt:
            print("\n\nBenchmark interrupted by user")
            break
        except Exception as e:
            print(f"Error during test: {e}")
            results.append({
                'parallel': parallel,
                'connections': connections,
                'error': str(e)
            })

    return results


def print_results(source_name: str, results: list):
    """Print benchmark results for a source."""
    print("\n" + "="*70)
    print(f"RESULTS: {source_name}")
    print("="*70)
    print(f"{'Parallel':<10} {'Conn/File':<10} {'Downloaded':<15} {'Speed':<15} {'Mbps':<10}")
    print("-"*70)

    # Sort by speed
    valid_results = [r for r in results if 'speed' in r]
    valid_results.sort(key=lambda x: x['speed'], reverse=True)

    for r in valid_results:
        print(f"{r['parallel']:<10} {r['connections']:<10} {format_size(r['downloaded']):<15} {format_size(r['speed'])}/s   {r['speed_mbps']:.2f}")

    if valid_results:
        best = valid_results[0]
        print(f"\nBEST: --parallel {best['parallel']} --connections {best['connections']} ({format_size(best['speed'])}/s)")

    return valid_results[0] if valid_results else None


def main():
    parser = argparse.ArgumentParser(description='Benchmark download performance')
    parser.add_argument('--site', choices=['myrient', 'archiveorg', 'both'], default='both',
                        help='Which site(s) to test (default: both)')
    parser.add_argument('--size', choices=['small', 'large', 'both'], default='both',
                        help='Which file sizes to test (default: both)')
    parser.add_argument('--quick', action='store_true',
                        help='Run quick test with fewer configurations')
    parser.add_argument('--duration', type=int, default=TEST_DURATION,
                        help=f'Duration per test in seconds (default: {TEST_DURATION})')
    args = parser.parse_args()

    # Check for aria2c
    try:
        subprocess.run(['aria2c', '--version'], capture_output=True, check=True)
        print("Using aria2c for downloads")
    except Exception:
        print("WARNING: aria2c not found, tests will use curl or Python urllib")

    # Determine which sites/sizes to test
    sites = ['myrient', 'archiveorg'] if args.site == 'both' else [args.site]
    sizes = ['small', 'large'] if args.size == 'both' else [args.size]
    configs = CONFIGS_QUICK if args.quick else CONFIGS

    # Check Archive.org auth if needed
    if 'archiveorg' in sites:
        if not check_archive_org_auth():
            print("\n" + "!"*70)
            print("! WARNING: Archive.org credentials not found!")
            print("! Set IA_ACCESS_KEY and IA_SECRET_KEY environment variables")
            print("! Get credentials at: https://archive.org/account/s3.php")
            print("!"*70)
            if args.site == 'archiveorg':
                print("\nCannot continue without Archive.org credentials.")
                sys.exit(1)
            else:
                print("\nSkipping Archive.org tests, continuing with Myrient only.")
                sites = ['myrient']

    # Build test list
    test_sources = []
    for site in sites:
        for size in sizes:
            if site in SOURCES and size in SOURCES[site]:
                test_sources.append((site, size, SOURCES[site][size]))

    if not test_sources:
        print("No valid test sources found!")
        sys.exit(1)

    cache_dir = Path('/tmp/retro-refiner-benchmark-cache')
    all_results = {}

    total_tests = len(configs) * len(test_sources)
    print(f"\nBenchmarking {len(configs)} configurations x {len(test_sources)} sources")
    print(f"Total: {total_tests} tests, {args.duration}s each")
    print(f"Estimated time: ~{total_tests * (args.duration + 10) // 60} minutes")

    print("\nSources to test:")
    for site, size, source in test_sources:
        print(f"  - {source['name']}")

    # Run benchmarks for each source
    for site, size, source in test_sources:
        key = f"{site}_{size}"
        try:
            results = run_source_benchmark(source, configs, cache_dir, args.duration)
            all_results[key] = {'source': source, 'results': results}
        except KeyboardInterrupt:
            print("\n\nBenchmark interrupted by user")
            break

    # Print summary for each source
    print("\n" + "#"*70)
    print("# FINAL SUMMARY")
    print("#"*70)

    best_configs = {}
    for key, data in all_results.items():
        best = print_results(data['source']['name'], data['results'])
        if best:
            best_configs[key] = {'source': data['source'], 'best': best}

    # Print comparison by site and size
    if len(best_configs) > 1:
        print("\n" + "="*70)
        print("OPTIMAL SETTINGS COMPARISON")
        print("="*70)

        # Group by site
        for site in sites:
            site_results = {k: v for k, v in best_configs.items() if k.startswith(site)}
            if site_results:
                print(f"\n{site.upper()}:")
                for key, data in site_results.items():
                    size = key.split('_')[1]
                    best = data['best']
                    print(f"  {size.upper():6} files: --parallel {best['parallel']} --connections {best['connections']} ({format_size(best['speed'])}/s, {best['speed_mbps']:.1f} Mbps)")

        # Cross-site comparison for same file sizes
        print("\n" + "-"*70)
        print("CROSS-SITE COMPARISON:")
        for size in sizes:
            print(f"\n  {size.upper()} FILES:")
            for site in sites:
                key = f"{site}_{size}"
                if key in best_configs:
                    best = best_configs[key]['best']
                    print(f"    {site:12}: {format_size(best['speed'])}/s ({best['speed_mbps']:.1f} Mbps)")

    # Cleanup
    try:
        if cache_dir.exists():
            shutil.rmtree(cache_dir)
    except OSError:
        print(f"\nNote: Could not fully clean up {cache_dir}")
        print("You can delete it manually: rm -rf /tmp/retro-refiner-benchmark-cache")

    return all_results


if __name__ == '__main__':
    main()

"""Headless CLI runner: loads a config file and executes via the core APIs.

Usage:
    python -m retro_refiner --run config.yaml [--commit]
    python -m retro_refiner --export-config
"""
import sys
import tempfile
from pathlib import Path

from retro_refiner.config import Config, load_config, save_config
from retro_refiner.network import format_size, is_url, validate_source
from retro_refiner.scanner import scan_network_source
from retro_refiner.paths import get_runtime_path


def run_headless(args: list):
    """Run in headless mode with a config file."""
    config_path = None
    commit = False
    export_config = False

    i = 0
    while i < len(args):
        if args[i] in ('--run', '-r') and i + 1 < len(args):
            config_path = args[i + 1]
            i += 2
        elif args[i] == '--commit':
            commit = True
            i += 1
        elif args[i] == '--export-config':
            export_config = True
            i += 1
        else:
            i += 1

    if export_config:
        config = Config()
        with tempfile.NamedTemporaryFile(
                mode='w', suffix='.yaml', delete=False) as tmp_f:
            tmp_path = Path(tmp_f.name)
        save_config(config, tmp_path)
        print(tmp_path.read_text(encoding='utf-8'))
        tmp_path.unlink()
        return

    if not config_path:
        print("Usage: python -m retro_refiner --run <config.yaml> [--commit]")
        print("       python -m retro_refiner --export-config")
        sys.exit(1)

    path = Path(config_path)
    if not path.exists():
        print(f"Error: Config file not found: {config_path}")
        sys.exit(1)

    config = load_config(path)
    print(f"Loaded config from {config_path}")
    print(f"  Sources: {len(config.sources)}")
    print(f"  Destination: {config.destination or '(default)'}")

    if not config.sources:
        print("Error: No sources configured")
        sys.exit(1)

    # Separate sources
    local_sources = []
    network_sources = []
    for src in config.sources:
        if is_url(src):
            network_sources.append(src)
        else:
            local_sources.append(Path(src))

    # Validate
    print("\nValidating sources...")
    for src in config.sources:
        ok, error = validate_source(src)
        status = "OK" if ok else error
        print(f"  {src}... {status}")
        if not ok:
            print("Error: Source validation failed")
            sys.exit(1)

    # Determine cache dir
    if config.advanced.cache_dir:
        cache_dir = Path(config.advanced.cache_dir).resolve()
    elif local_sources:
        cache_dir = local_sources[0] / 'cache'
    else:
        cache_dir = get_runtime_path() / 'cache'

    # Scan network sources
    all_urls = {}
    all_sizes = {}

    for net_url in network_sources:
        print(f"\nScanning: {net_url}")
        result = scan_network_source(
            net_url, config.systems,
            cache_dir=cache_dir,
            no_cache=config.advanced.no_cache,
            scan_workers=config.network.scan_workers,
        )
        for system, urls in result.url_dict.items():
            all_urls.setdefault(system, []).extend(urls)
        all_sizes.update(result.url_sizes)

    # Summary
    total_files = sum(len(urls) for urls in all_urls.values())
    total_size = sum(all_sizes.get(u, 0) for urls in all_urls.values()
                     for u in urls)

    print(f"\n{'='*60}")
    print(f"Results: {total_files} ROMs across {len(all_urls)} systems"
          f" ({format_size(total_size)})")
    for system, urls in sorted(all_urls.items()):
        sys_size = sum(all_sizes.get(u, 0) for u in urls)
        print(f"  {system.upper()}: {len(urls)} files ({format_size(sys_size)})")
    print(f"{'='*60}")

    if not commit:
        print("\nDry run complete. Use --commit to download/transfer files.")
    else:
        print("\nCommit mode not yet implemented in v2 CLI.")

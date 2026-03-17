"""Headless CLI runner: loads a config file and executes via the core APIs.

Usage:
    python -m retro_refiner --run config.yaml [--commit]
    python -m retro_refiner --export-config
"""
import sys
import tempfile
import urllib.parse
from pathlib import Path

from retro_refiner.config import Config, load_config, save_config
from retro_refiner.network import format_size, is_url, validate_source
from retro_refiner.scanner import scan_local_sources, scan_network_source
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

    # Scan local sources
    local_systems = {}
    if local_sources:
        print("\nScanning local sources...")
        local_systems = scan_local_sources(
            local_sources,
            recursive=config.advanced.recursive,
            max_depth=config.advanced.max_depth,
            verbose=config.selection.verbose,
        )

    all_systems = set(all_urls.keys()) | set(local_systems.keys())
    if not all_systems:
        print("No systems found in sources.")
        return

    # Scan summary
    total_source = sum(len(all_urls.get(s, []))
                       + len(local_systems.get(s, []))
                       for s in all_systems)
    print(f"\nFound {len(all_systems)} systems, {total_source} total files")

    # Filter each system
    from retro_refiner.filter import filter_network_roms  # pylint: disable=import-outside-toplevel
    from retro_refiner.mame import (  # pylint: disable=import-outside-toplevel
        download_mame_data, parse_catver_ini, parse_mame_dat,
        filter_mame_network_roms,
    )
    from retro_refiner.teknoparrot import (  # pylint: disable=import-outside-toplevel
        filter_teknoparrot_network_roms,
    )

    total_selected = 0
    total_size = 0
    system_selected_urls = {}  # system -> selected URLs

    print(f"\n{'='*60}")
    for system in sorted(all_systems):
        urls = all_urls.get(system, [])
        local_files = local_systems.get(system, [])
        source_count = len(urls) + len(local_files)

        selected_urls = urls  # default: keep all

        if urls:
            try:
                if system in ('mame', 'fbneo', 'fba', 'arcade'):
                    dat_dir = Path(config.advanced.dat_dir or './dat_files')
                    dat_dir.mkdir(parents=True, exist_ok=True)
                    catver_path, dat_path = download_mame_data(
                        dat_dir, version=config.advanced.mame_version)
                    if catver_path and dat_path:
                        categories = parse_catver_ini(str(catver_path))
                        games = parse_mame_dat(str(dat_path))
                        selected_urls, _ = filter_mame_network_roms(
                            urls, categories=categories, games=games,
                            url_sizes=all_sizes,
                            verbose=config.selection.verbose,
                            no_filter=config.selection.all_roms,
                            english_only=config.selection.english_only,
                        )
                elif system == 'teknoparrot':
                    selected_urls, _ = filter_teknoparrot_network_roms(
                        urls, url_sizes=all_sizes,
                        verbose=config.selection.verbose,
                        no_filter=config.selection.all_roms,
                        english_only=config.selection.english_only,
                    )
                else:
                    # Console system — load DATs if available
                    dat_entries = None
                    if not config.advanced.no_dat:
                        from retro_refiner.dat import (  # pylint: disable=import-outside-toplevel
                            download_libretro_dat, load_all_system_dats,
                        )
                        dat_dir = Path(config.advanced.dat_dir or './dat_files')
                        dat_dir.mkdir(parents=True, exist_ok=True)
                        dat_path = download_libretro_dat(system, dat_dir)
                        if dat_path:
                            dat_entries = load_all_system_dats(
                                system, dat_dir)

                    fr = filter_network_roms(
                        system, urls, config,
                        url_sizes=all_sizes,
                        dat_entries=dat_entries,
                    )
                    selected_urls = fr.selected if fr.selected else urls
            except Exception as exc:  # pylint: disable=broad-except
                print(f"  {system.upper()}: filter error: {exc}",
                      file=sys.stderr)

        selected_size = sum(all_sizes.get(u, 0) for u in selected_urls)
        total_selected += len(selected_urls)
        total_size += selected_size
        system_selected_urls[system] = selected_urls

        print(f"  {system.upper()}: {len(selected_urls)}/{source_count} "
              f"selected ({format_size(selected_size)})")

    print(f"{'='*60}")
    print(f"Total: {total_selected} ROMs ({format_size(total_size)})")

    # ----- Budget filters: --limit, --top, --size -----
    system_selected_urls = _apply_cli_budget_filters(
        config, system_selected_urls, all_sizes)

    # Recount after budget filters
    total_selected = sum(len(v) for v in system_selected_urls.values())
    total_size = sum(
        sum(all_sizes.get(u, 0) for u in urls)
        for urls in system_selected_urls.values()
    )

    # ----- Dedup analysis -----
    if config.deduplication.priority:
        _run_cli_dedup(config, system_selected_urls)

    if not commit:
        print("\nDry run complete. Use --commit to download/transfer files.")
    else:
        from retro_refiner.downloader import (  # pylint: disable=import-outside-toplevel
            get_download_tool, download_batch_with_aria2c,
            download_batch_with_curl, DownloadUI,
        )
        from retro_refiner.transfer import transfer_files  # pylint: disable=import-outside-toplevel

        dest_dir = (Path(config.destination) if config.destination
                    else get_runtime_path() / 'refined')
        dest_dir.mkdir(parents=True, exist_ok=True)

        # Check if DownloadUI can be used (requires aria2c + TTY)
        tool = get_download_tool()
        use_interactive = (tool == 'aria2c' and sys.stdout.isatty())

        print(f"\nDownloading to cache and transferring to {dest_dir}...")
        for system in sorted(system_selected_urls):
            sys_urls = system_selected_urls[system]
            if not sys_urls:
                continue

            downloads = []
            for url in sys_urls:
                filename = urllib.parse.unquote(
                    url.split('?')[0].split('#')[0].split('/')[-1])
                cp = cache_dir / system / filename
                cp.parent.mkdir(parents=True, exist_ok=True)
                if not cp.exists():
                    downloads.append((url, cp))

            if downloads:
                if use_interactive:
                    # Use DownloadUI for interactive progress display
                    ui = DownloadUI(
                        system_name=system,
                        files=downloads,
                        parallel=config.network.parallel,
                        connections=config.network.connections or 4,
                        resume=config.network.resume_downloads,
                    )
                    completed = ui.run()
                    print()  # newline after progress bar
                    print(f"  {system.upper()}: downloaded "
                          f"{len(completed)}/{len(downloads)} files")
                else:
                    print(f"  {system.upper()}: downloading "
                          f"{len(downloads)} files...")
                    if tool == 'aria2c':
                        download_batch_with_aria2c(
                            downloads,
                            parallel=config.network.parallel)
                    elif tool == 'curl':
                        download_batch_with_curl(
                            downloads,
                            parallel=config.network.parallel)
                    else:
                        import urllib.request as urllib_req  # pylint: disable=import-outside-toplevel
                        for dl_url, dl_path in downloads:
                            try:
                                req = urllib_req.Request(
                                    dl_url,
                                    headers={
                                        'User-Agent': 'Mozilla/5.0'})
                                with urllib_req.urlopen(
                                        req, timeout=60) as resp:
                                    import shutil  # pylint: disable=import-outside-toplevel
                                    with open(dl_path, 'wb') as f_out:
                                        shutil.copyfileobj(resp, f_out)
                            except Exception:  # pylint: disable=broad-except
                                pass

            cached = []
            for url in sys_urls:
                filename = urllib.parse.unquote(
                    url.split('?')[0].split('#')[0].split('/')[-1])
                cp = cache_dir / system / filename
                if cp.exists():
                    cached.append(cp)

            if cached:
                stats = transfer_files(
                    cached, dest_dir, system=system,
                    mode=config.output.transfer_mode,
                    flat=config.output.flat,
                )
                print(f"  {system.upper()}: transferred "
                      f"{stats['transferred']}, skipped "
                      f"{stats['skipped']}, errors {stats['errors']}")

        print("\nCommit complete.")


def _parse_size_string(size_str):
    """Parse a size string like '10GB', '500MB' into bytes."""
    if not size_str:
        return None
    size_str = str(size_str).strip().upper()
    multipliers = {
        'TB': 1024 ** 4, 'T': 1024 ** 4,
        'GB': 1024 ** 3, 'G': 1024 ** 3,
        'MB': 1024 ** 2, 'M': 1024 ** 2,
        'KB': 1024, 'K': 1024,
        'B': 1,
    }
    for suffix, mult in multipliers.items():
        if size_str.endswith(suffix):
            try:
                return int(float(size_str[:-len(suffix)].strip()) * mult)
            except ValueError:
                return None
    try:
        return int(float(size_str))
    except ValueError:
        return None


def _apply_cli_budget_filters(config, system_selected_urls, all_sizes):
    """Apply --limit, --top, and --size budget filters in CLI mode."""
    # --limit: simple total cap
    if config.budget.limit:
        remaining = config.budget.limit
        for system in sorted(system_selected_urls):
            sys_urls = system_selected_urls[system]
            if remaining <= 0:
                system_selected_urls[system] = []
            elif len(sys_urls) > remaining:
                system_selected_urls[system] = sys_urls[:remaining]
                remaining = 0
            else:
                remaining -= len(sys_urls)
        new_total = sum(len(v) for v in system_selected_urls.values())
        print(f"\n--limit {config.budget.limit}: {new_total} ROMs retained")

    # --top and --size require ratings
    if config.budget.top or config.budget.size:
        system_selected_urls = _apply_cli_ratings_budget(
            config, system_selected_urls, all_sizes)

    return system_selected_urls


def _apply_cli_ratings_budget(config, system_selected_urls, all_sizes):
    """Load ratings and apply --top / --size in CLI mode."""
    from retro_refiner.ratings import (  # pylint: disable=import-outside-toplevel
        build_ratings_cache, download_launchbox_data,
        apply_top_n_filter, apply_size_budget,
        boost_exclusive_ratings,
    )
    from retro_refiner.filter import parse_rom_filename  # pylint: disable=import-outside-toplevel

    dat_dir = Path(config.advanced.dat_dir or './dat_files')
    dat_dir.mkdir(parents=True, exist_ok=True)

    print("\nLoading ratings data...")
    xml_path = download_launchbox_data(dat_dir)
    if not xml_path:
        print("  WARNING: No ratings data available "
              "(LaunchBox download failed)", file=sys.stderr)
        return system_selected_urls

    cache_path = dat_dir / 'launchbox' / 'ratings_cache.json'
    ratings = build_ratings_cache(xml_path, cache_path=cache_path)

    if not ratings:
        print("  WARNING: No ratings found in data", file=sys.stderr)
        return system_selected_urls

    total_rated = sum(len(v) for v in ratings.values())
    print(f"  {total_rated} games rated")

    if config.budget.prefer_exclusives:
        ratings = boost_exclusive_ratings(
            ratings, boost=config.budget.prefer_exclusives)

    for system in sorted(system_selected_urls):
        sys_urls = system_selected_urls[system]
        if not sys_urls:
            continue
        sys_ratings = ratings.get(system, {})
        if not sys_ratings:
            continue

        # Build RomInfo objects from filenames
        url_roms = []
        url_map = {}
        for url in sys_urls:
            filename = urllib.parse.unquote(
                url.split('?')[0].split('#')[0].split('/')[-1])
            rom = parse_rom_filename(filename)
            url_roms.append(rom)
            url_map[id(rom)] = url

        if config.budget.top:
            before = len(url_roms)
            url_roms = apply_top_n_filter(
                url_roms, sys_ratings, config.budget.top,
                include_unrated=config.budget.include_unrated,
            )
            after = len(url_roms)
            if after < before:
                print(f"  {system.upper()}: top filter "
                      f"{before} -> {after}")

        if config.budget.size:
            budget_bytes = _parse_size_string(config.budget.size)
            if budget_bytes and budget_bytes > 0:
                rom_sizes = {}
                for rom in url_roms:
                    url = url_map[id(rom)]
                    rom_sizes[rom.filename] = all_sizes.get(url, 0)

                before = len(url_roms)
                url_roms, _ = apply_size_budget(
                    url_roms, rom_sizes, budget_bytes,
                    ratings=sys_ratings,
                    name_fn=lambda r: r.filename,
                    rating_name_fn=lambda r: r.base_title,
                )
                after = len(url_roms)
                if after < before:
                    print(f"  {system.upper()}: size budget "
                          f"{before} -> {after}")

        system_selected_urls[system] = [
            url_map[id(rom)] for rom in url_roms
        ]

    return system_selected_urls


def _run_cli_dedup(config, system_selected_urls):
    """Run cross-platform dedup analysis in CLI mode."""
    from retro_refiner.dedup import run_dedupe_analysis  # pylint: disable=import-outside-toplevel
    from types import SimpleNamespace  # pylint: disable=import-outside-toplevel

    # Build a detected dict mapping system -> list of Path-like objects
    # For URL-based results, we create lightweight path proxies from filenames
    detected = {}
    for system, urls in system_selected_urls.items():
        if urls:
            paths = []
            for url in urls:
                filename = urllib.parse.unquote(
                    url.split('?')[0].split('#')[0].split('/')[-1])
                # Create a Path-like object with .name and minimal stat
                paths.append(Path(filename))
            detected[system] = paths

    if not detected:
        return

    args = SimpleNamespace(
        dedupe_priority=config.deduplication.priority,
        dedupe_pc_lists=config.deduplication.pc_lists or [],
        verbose=config.selection.verbose,
    )

    run_dedupe_analysis(detected, args, delete=False, confirm=False)

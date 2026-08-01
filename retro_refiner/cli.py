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
from retro_refiner.log import logger
from retro_refiner.network import format_size, is_url, stream_download, validate_source
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

    # Scan local sources (respect per-source settings if available)
    local_systems = {}
    if local_sources:
        print("\nScanning local sources...")
        ss = config.source_settings or {}
        for src_path in local_sources:
            src_key = str(src_path)
            src_opts = ss.get(src_key, {})
            recursive = src_opts.get('recursive', config.advanced.recursive)
            depth = config.advanced.max_depth or 3
            result_local = scan_local_sources(
                [src_path],
                recursive=recursive,
                max_depth=depth,
                verbose=config.selection.verbose,
            )
            for sys_code, files in result_local.items():
                local_systems.setdefault(sys_code, []).extend(files)

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
                logger.error("{}: filter error: {}", system.upper(), exc)

        # Filter local files
        selected_local = []
        if local_files and not config.selection.all_roms:
            from retro_refiner.filter import filter_roms_from_files  # pylint: disable=import-outside-toplevel
            sel = config.selection
            rp = sel.region_priority
            kr = sel.keep_regions
            keep_list = ([r.strip() for r in kr.split(',')
                          if r.strip()] if kr else None)
            local_roms, _ = filter_roms_from_files(
                [Path(f) for f in local_files],
                dest_dir=config.destination or '.',
                system=system, dry_run=True,
                exclude_protos=sel.exclude_protos,
                include_betas=sel.include_betas,
                include_unlicensed=sel.include_unlicensed,
                include_demos=sel.include_demos,
                include_educational=sel.include_educational,
                include_patterns=sel.include_patterns or None,
                exclude_patterns=sel.exclude_patterns or None,
                region_priority=rp,
                keep_regions=keep_list,
                year_from=sel.year_from,
                year_to=sel.year_to,
                no_filter=sel.all_roms,
                best_version=sel.best_version,
                english_only=sel.english_only,
            )
            selected_local = [str(Path(f).parent / rom.filename)
                              for rom in local_roms
                              for f in local_files
                              if Path(f).name == rom.filename]
        elif local_files:
            selected_local = [str(f) for f in local_files]

        # Combine counts
        all_selected = list(selected_urls) + selected_local
        selected_size = sum(all_sizes.get(u, 0) for u in selected_urls)
        for f in selected_local:
            try:
                selected_size += Path(f).stat().st_size
            except OSError:
                pass
        total_selected += len(all_selected)
        total_size += selected_size
        system_selected_urls[system] = all_selected

        print(f"  {system.upper()}: {len(all_selected)}/{source_count} "
              f"selected ({format_size(selected_size)})")

    print(f"{'='*60}")
    print(f"Total: {total_selected} ROMs ({format_size(total_size)})")

    # ----- Budget filters: --limit, --top, --size -----
    system_selected_urls = _apply_cli_budget_filters(
        config, system_selected_urls, all_sizes)

    # Recount after budget filters
    total_selected = sum(len(v) for v in system_selected_urls.values())
    total_size = sum(
        sum(_entry_size(u, all_sizes) for u in urls)
        for urls in system_selected_urls.values()
    )

    # ----- Dedup analysis -----
    if config.deduplication.priority:
        _run_cli_dedup(config, system_selected_urls)

    if not commit:
        print("\nDry run complete. Use --commit to download/transfer files.")
    else:
        import httpx  # pylint: disable=import-outside-toplevel
        from retro_refiner.transfer import (  # pylint: disable=import-outside-toplevel
            validate_destination, clean_destination,
        )

        dest_dir = (Path(config.destination) if config.destination
                    else get_runtime_path() / 'refined')
        if config.output.local_file_action != 'remove':
            dest_dir.mkdir(parents=True, exist_ok=True)

        print(f"\nCommitting to {dest_dir}...")
        client = httpx.Client(
            follow_redirects=True,
            timeout=60,
            headers={
                'User-Agent':
                    'Mozilla/5.0 (compatible; Retro-Refiner/1.0)',
            },
        )
        try:
            for system in sorted(system_selected_urls):
                sys_urls = system_selected_urls[system]
                if not sys_urls:
                    continue

                if config.output.local_file_action == 'remove':
                    continue

                flat = config.output.flat
                target_dir = dest_dir if flat else dest_dir / system
                target_dir.mkdir(parents=True, exist_ok=True)

                # Build expected file set with sizes
                expected = {}
                for url in sys_urls:
                    fname = _url_to_filename(url)
                    expected[fname] = all_sizes.get(url, 0)

                # Phase 1: Validate destination
                skip_files = set()
                if config.output.validate_destination:
                    validation = validate_destination(
                        dest_dir, system, flat, expected,
                        crc_check=config.output.crc_validation)
                    skip_files = {fn for fn, st in validation.items()
                                  if st == 'valid'}
                    invalid_files = {fn for fn, st in validation.items()
                                     if st == 'invalid'}
                    if skip_files:
                        print(f"  {system.upper()}: {len(skip_files)} "
                              f"files already in destination, skipping")
                    for fname in invalid_files:
                        (target_dir / fname).unlink(missing_ok=True)

                # Phase 2: Download directly to destination
                downloads = []
                for url in sys_urls:
                    fname = _url_to_filename(url)
                    if fname in skip_files:
                        continue
                    dest_path = target_dir / fname
                    tmp_path = target_dir / (fname + '.rrdownload')
                    downloads.append((url, tmp_path, dest_path))

                if downloads:
                    print(f"  {system.upper()}: downloading "
                          f"{len(downloads)} files...")
                    completed = 0
                    succeeded = set()
                    for url, tmp_path, _ in downloads:
                        try:
                            stream_download(client, url, tmp_path)
                            completed += 1
                            succeeded.add(tmp_path)
                        except Exception as exc:  # pylint: disable=broad-except
                            fname = _url_to_filename(url)
                            logger.error("FAILED: {}: {}", fname, exc)
                    print(f"  {system.upper()}: downloaded "
                          f"{completed}/{len(downloads)} files")

                    # Rename only successfully completed downloads
                    for _, tmp_path, final_path in downloads:
                        if tmp_path in succeeded:
                            tmp_path.rename(final_path)
                        elif tmp_path.exists():
                            tmp_path.unlink()

                # Phase 3: Clean destination
                if config.output.clean_destination:
                    keep = set(expected.keys())
                    clean_stats = clean_destination(
                        dest_dir, system, flat, keep)
                    if clean_stats['removed']:
                        print(f"  {system.upper()}: cleaned "
                              f"{clean_stats['removed']} "
                              f"files from destination")
        finally:
            client.close()

        print("\nCommit complete.")


def _parse_size_string(size_str):
    """Parse a size string like '10GB', '500MB' into bytes.

    Thin wrapper around ``network.parse_budget_size`` kept for backward
    compatibility with tests that import from this module.
    """
    from retro_refiner.network import parse_budget_size  # pylint: disable=import-outside-toplevel
    return parse_budget_size(size_str)


def _entry_filename(entry):
    """Extract a ROM filename from either a URL or a local filesystem path."""
    if '://' in entry:
        return urllib.parse.unquote(
            entry.split('?')[0].split('#')[0].split('/')[-1])
    return Path(entry).name


def _entry_size(entry, all_sizes):
    """Size in bytes for a URL (from the scan) or a local file (from disk)."""
    if entry in all_sizes:
        return all_sizes[entry]
    try:
        return Path(entry).stat().st_size
    except OSError:
        return 0


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
        logger.warning("No ratings data available (LaunchBox download failed)")
        return system_selected_urls

    cache_path = dat_dir / 'launchbox' / 'ratings_cache.json'
    ratings = build_ratings_cache(xml_path, cache_path=cache_path)

    if not ratings:
        logger.warning("No ratings found in data")
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

        # Build RomInfo objects from filenames. Entries may be URLs or
        # local filesystem paths, so both forms must be handled.
        # ``roms`` is never rebound, keeping every RomInfo alive so the
        # id() keys below stay valid.
        roms = []
        entry_map = {}  # id(rom) -> url or local path
        rom_sizes = {}  # id(rom) -> size in bytes
        for entry in sys_urls:
            rom = parse_rom_filename(_entry_filename(entry))
            roms.append(rom)
            entry_map[id(rom)] = entry
            rom_sizes[id(rom)] = _entry_size(entry, all_sizes)

        kept = roms

        if config.budget.top:
            before = len(kept)
            kept = apply_top_n_filter(
                kept, sys_ratings, config.budget.top,
                include_unrated=config.budget.include_unrated,
            )
            after = len(kept)
            if after < before:
                print(f"  {system.upper()}: top filter "
                      f"{before} -> {after}")

        if config.budget.size:
            budget_bytes = _parse_size_string(config.budget.size)
            if budget_bytes and budget_bytes > 0:
                before = len(kept)
                kept, _ = apply_size_budget(
                    kept, rom_sizes, budget_bytes,
                    ratings=sys_ratings,
                    name_fn=id,
                    rating_name_fn=lambda r: r.base_title,
                )
                after = len(kept)
                if after < before:
                    print(f"  {system.upper()}: size budget "
                          f"{before} -> {after}")

        system_selected_urls[system] = [entry_map[id(rom)] for rom in kept]

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


def _url_to_filename(url):
    """Extract filename from URL."""
    return urllib.parse.unquote(
        url.split('?')[0].split('#')[0].split('/')[-1])

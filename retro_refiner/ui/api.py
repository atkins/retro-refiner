"""Python API exposed to JavaScript via pywebview."""

import json
import threading
import urllib.parse
from pathlib import Path

import webview

from retro_refiner.config import Config, load_config, save_config
from retro_refiner.systems import load_system_data


class Api:
    """Bridge between the JavaScript frontend and Python backend."""

    def __init__(self):
        self._window = None
        self._config = Config()
        self._running = False
        self._exclude_systems = []
        self._systems_data = load_system_data()
        self._last_results = {}  # system -> {urls, sizes, local_files}
        self._manual_selections = {}  # system -> {filename: bool}

    def set_window(self, window):
        """Store a reference to the pywebview window."""
        self._window = window

    def get_config(self) -> str:
        """Return current config as JSON."""
        return json.dumps(self._config.to_dict())

    def set_config(self, config_json: str):
        """Update config from JSON."""
        data = json.loads(config_json)
        self._config = Config.from_dict(data)

    def get_systems(self) -> str:
        """Return list of known systems as JSON."""
        return json.dumps(self._systems_data.known_systems)

    def save_settings(self, path: str):
        """Save current config to file."""
        save_config(self._config, Path(path))

    def load_settings(self, path: str) -> str:
        """Load config from file and return as JSON."""
        self._config = load_config(Path(path))
        return json.dumps(self._config.to_dict())

    def update_sources(self, sources_json: str):
        """Update sources list from JS."""
        self._config.sources = json.loads(sources_json)

    def update_destination(self, dest: str):
        """Update destination from JS."""
        self._config.destination = dest

    def update_selection(self, selection_json: str):
        """Update selection config from JS."""
        data = json.loads(selection_json)
        for key, value in data.items():
            if hasattr(self._config.selection, key):
                setattr(self._config.selection, key, value)

    def update_config_from_ui(self, ui_json: str):
        """Update full config from UI sidebar state."""
        ui = json.loads(ui_json)
        self._config.sources = ui.get('sources', [])
        self._config.destination = ui.get('destination') or None
        self._config.systems = _parse_csv(ui.get('systems'))

        sel = self._config.selection
        sel.english_only = ui.get('english_only', False)
        sel.exclude_protos = ui.get('exclude_protos', False)
        sel.include_betas = ui.get('include_betas', False)
        sel.include_unlicensed = not ui.get('no_unlicensed', False)
        sel.verbose = ui.get('verbose', False)
        sel.all_roms = ui.get('all_regions', False)
        rp = ui.get('region_priority', '').strip()
        if rp:
            sel.region_priority = [r.strip() for r in rp.split(',') if r.strip()]

        bud = self._config.budget
        bud.top = ui.get('top') or None
        bud.limit = _int_or_none(ui.get('limit'))
        bud.size = ui.get('size') or None

        net = self._config.network
        net.connections = _int_or_none(ui.get('connections'))
        net.scan_workers = int(ui.get('scan_workers', 16) or 16)

        out = self._config.output
        out.playlists = ui.get('playlists', False)
        out.gamelist = ui.get('gamelists', False)
        out.flat = ui.get('flatten', False)
        out.transfer_mode = ui.get('transfer_mode', 'copy')

        adv = self._config.advanced
        adv.no_dat = ui.get('no_dat', False)
        adv.no_cache = ui.get('no_cache', False)
        adv.log_dir = ui.get('log_dir') or None

        excl = ui.get('exclude_systems', '').strip()
        # Store exclude_systems on config for later use
        self._exclude_systems = [s.strip() for s in excl.split(',')
                                 if s.strip()] if excl else []

    def run_preview(self):
        """Start a preview run (no file transfer)."""
        if self._running:
            return
        self._running = True
        thread = threading.Thread(target=self._do_run, args=(False,), daemon=True)
        thread.start()

    def run_commit(self):
        """Start a commit run (with file transfer)."""
        if self._running:
            return
        self._running = True
        thread = threading.Thread(target=self._do_run, args=(True,), daemon=True)
        thread.start()

    def cancel_run(self):
        """Cancel the current run."""
        self._running = False

    def is_running(self) -> bool:
        """Return whether a run is currently in progress."""
        return self._running

    def _do_run(self, commit: bool):
        """Execute the run in a background thread."""
        try:
            mode = 'commit' if commit else 'preview'
            self._push_event('status', {
                'state': 'running',
                'message': f'Starting {mode} run...',
            })

            config = self._config

            # Import core modules
            from retro_refiner.network import (  # pylint: disable=import-outside-toplevel
                is_url, validate_source,
            )
            from retro_refiner.scanner import (  # pylint: disable=import-outside-toplevel
                scan_local_sources, scan_network_source,
            )
            from retro_refiner.paths import get_runtime_path  # pylint: disable=import-outside-toplevel

            # Separate sources into local and network
            local_sources = []
            network_sources = []
            for src in config.sources:
                if is_url(src):
                    network_sources.append(src)
                else:
                    local_sources.append(Path(src))

            if not local_sources and not network_sources:
                self._push_event('status', {
                    'state': 'error',
                    'message': 'No sources configured',
                })
                return

            # Validate sources
            self._push_event('log', {'text': 'Validating sources...\n'})
            for src in config.sources:
                if not self._running:
                    break
                ok, error = validate_source(src)
                status = 'OK' if ok else error
                css = 'log-success' if ok else 'log-error'
                self._push_event('log', {
                    'text': f'  {src}... {status}\n',
                    'className': css,
                })
                if not ok:
                    self._push_event('status', {
                        'state': 'error',
                        'message': f'Source validation failed: {error}',
                    })
                    return

            if not self._running:
                self._push_event('status', {
                    'state': 'cancelled', 'message': 'Cancelled',
                })
                return

            # Determine cache dir
            if config.advanced.cache_dir:
                cache_dir = Path(config.advanced.cache_dir).resolve()
            elif local_sources:
                cache_dir = local_sources[0] / 'cache'
            else:
                cache_dir = get_runtime_path() / 'cache'

            # Scan network sources
            all_urls = {}   # system -> [urls]
            all_sizes = {}  # url -> size

            for net_url in network_sources:
                if not self._running:
                    break
                self._push_event('log', {
                    'text': f'\nScanning: {net_url}\n',
                    'className': 'log-info',
                })

                systems_filter = config.systems
                exclude = getattr(self, '_exclude_systems', [])
                if exclude and systems_filter:
                    systems_filter = [s for s in systems_filter
                                      if s not in exclude]

                result = scan_network_source(
                    net_url, systems_filter,
                    cache_dir=cache_dir,
                    no_cache=config.advanced.no_cache,
                    scan_workers=config.network.scan_workers,
                    on_progress=lambda evt: self._push_event('progress', {
                        'phase': evt.phase, 'message': evt.message,
                        'current': evt.current, 'total': evt.total,
                    }),
                )

                for system, urls in result.url_dict.items():
                    all_urls.setdefault(system, []).extend(urls)
                all_sizes.update(result.url_sizes)

            # Scan local sources
            local_systems = {}
            if local_sources and self._running:
                self._push_event('log', {
                    'text': '\nScanning local sources...\n',
                    'className': 'log-info',
                })
                local_systems = scan_local_sources(
                    local_sources,
                    recursive=config.advanced.recursive,
                    max_depth=config.advanced.max_depth,
                    verbose=config.selection.verbose,
                    on_progress=lambda evt: self._push_event('progress', {
                        'phase': evt.phase, 'message': evt.message,
                        'current': evt.current, 'total': evt.total,
                    }),
                )

            if not self._running:
                self._push_event('status', {
                    'state': 'cancelled', 'message': 'Cancelled',
                })
                return

            # Store scan results for the ROM picker
            self._last_results = {}
            for sys_code in set(all_urls.keys()) | set(local_systems.keys()):
                self._last_results[sys_code] = {
                    'urls': all_urls.get(sys_code, []),
                    'sizes': {u: all_sizes.get(u, 0)
                              for u in all_urls.get(sys_code, [])},
                    'local_files': local_systems.get(sys_code, []),
                }

            # Combine all discovered systems
            all_systems = set(all_urls.keys()) | set(local_systems.keys())
            if not all_systems:
                self._push_event('status', {
                    'state': 'completed',
                    'message': 'No systems found in sources',
                })
                return

            self._push_event('log', {
                'text': f'\nFound {len(all_systems)} systems\n',
                'className': 'log-success',
            })

            # Process each system and push card events
            total_selected = 0
            total_size = 0

            for system in sorted(all_systems):
                if not self._running:
                    break

                urls = all_urls.get(system, [])
                local_files = local_systems.get(system, [])
                source_count = len(urls) + len(local_files)

                # Compute sizes
                net_size = sum(all_sizes.get(u, 0) for u in urls)
                local_size = 0
                for filepath in local_files:
                    try:
                        local_size += Path(filepath).stat().st_size
                    except OSError:
                        pass
                sys_size = net_size + local_size

                # Push card-start event
                self._push_event('card', {
                    'system': system,
                    'state': 'filtering',
                    'source_count': source_count,
                    'source_size': sys_size,
                })

                self._push_event('log', {
                    'text': f'\n{system.upper()}: '
                            f'Filtering {source_count} ROMs...\n',
                })

                # Run actual filtering
                from retro_refiner.filter import filter_network_roms  # pylint: disable=import-outside-toplevel
                from retro_refiner.mame import filter_mame_network_roms  # pylint: disable=import-outside-toplevel
                from retro_refiner.teknoparrot import filter_teknoparrot_network_roms  # pylint: disable=import-outside-toplevel

                selected_urls = urls
                excluded_count = 0
                filter_breakdown = {}

                if urls:
                    try:
                        if system in ('mame', 'fbneo', 'fba', 'arcade'):
                            from retro_refiner.mame import (  # pylint: disable=import-outside-toplevel
                                download_mame_data, parse_catver_ini, parse_mame_dat,
                            )
                            dat_dir = Path(config.advanced.dat_dir or './dat_files')
                            dat_dir.mkdir(parents=True, exist_ok=True)
                            self._push_event('log', {'text': '  Downloading MAME data...\n'})
                            catver_path, dat_path = download_mame_data(
                                dat_dir, version=config.advanced.mame_version
                            )
                            if catver_path and dat_path:
                                categories = parse_catver_ini(str(catver_path))
                                games = parse_mame_dat(str(dat_path))
                                selected_urls, _info = filter_mame_network_roms(
                                    urls,
                                    categories=categories,
                                    games=games,
                                    include_patterns=config.selection.include_patterns or None,
                                    exclude_patterns=config.selection.exclude_patterns or None,
                                    include_adult=not config.advanced.no_adult,
                                    url_sizes=all_sizes,
                                    verbose=config.selection.verbose,
                                    no_filter=config.selection.all_roms,
                                    english_only=config.selection.english_only,
                                )
                                filter_breakdown = _info.get('filter_breakdown', {}) if isinstance(_info, dict) else {}
                        elif system == 'teknoparrot':
                            tp_exclude = None
                            if config.advanced.tp_exclude_platforms:
                                tp_exclude = {p.strip() for p in config.advanced.tp_exclude_platforms.split(',')}
                            tp_include = None
                            if config.advanced.tp_include_platforms:
                                tp_include = {p.strip() for p in config.advanced.tp_include_platforms.split(',')}
                            selected_urls, _info = filter_teknoparrot_network_roms(
                                urls,
                                include_platforms=tp_include,
                                exclude_platforms=tp_exclude,
                                region_priority=config.selection.region_priority,
                                keep_all_versions=config.advanced.tp_all_versions,
                                include_patterns=config.selection.include_patterns or None,
                                exclude_patterns=config.selection.exclude_patterns or None,
                                url_sizes=all_sizes,
                                verbose=config.selection.verbose,
                                no_filter=config.selection.all_roms,
                                english_only=config.selection.english_only,
                            )
                            filter_breakdown = _info.get('filter_breakdown', {}) if isinstance(_info, dict) else {}
                        else:
                            # Console system — load DATs for better filtering
                            dat_entries = None
                            if not config.advanced.no_dat:
                                from retro_refiner.dat import (  # pylint: disable=import-outside-toplevel
                                    download_libretro_dat, load_all_system_dats,
                                )
                                dat_dir = Path(config.advanced.dat_dir or './dat_files')
                                dat_dir.mkdir(parents=True, exist_ok=True)
                                dat_path = download_libretro_dat(system, dat_dir)
                                if dat_path:
                                    dat_entries = load_all_system_dats(system, dat_dir)
                                    if dat_entries:
                                        self._push_event('log', {
                                            'text': f'  Loaded {len(dat_entries)} DAT entries\n',
                                        })

                            result = filter_network_roms(
                                system, urls, config,
                                url_sizes=all_sizes,
                                dat_entries=dat_entries,
                            )
                            selected_urls = result.selected if result.selected else urls
                            filter_breakdown = result.stats.filter_breakdown if result.stats else {}
                    except Exception as exc:
                        self._push_event('log', {
                            'text': f'  Filter error: {exc}\n',
                            'className': 'log-error',
                        })

                excluded_count = source_count - len(selected_urls)
                selected_count = len(selected_urls)
                selected_size = sum(all_sizes.get(u, 0) for u in selected_urls)
                total_selected += selected_count
                total_size += selected_size

                self._push_event('card', {
                    'system': system,
                    'state': 'complete',
                    'selected_count': selected_count,
                    'excluded_count': excluded_count,
                    'selected_size': selected_size,
                    'source_count': source_count,
                    'source_size': sys_size,
                    'filter_breakdown': filter_breakdown,
                })

                # Store selected URLs for commit mode
                if system in self._last_results:
                    self._last_results[system]['selected_urls'] = selected_urls

            # TODO: Budget filters (--top, --limit, --size) require ratings
            # data to apply properly. For now, simple limit is noted but not
            # applied since it requires proportional truncation across systems.
            # Dedup is available in the core engine but not yet exposed in the
            # GUI — wire it when the dedup UI is built.

            if not self._running:
                self._push_event('status', {
                    'state': 'cancelled', 'message': 'Cancelled',
                })
                return

            # Commit mode: download and transfer files
            if commit and self._running:
                from retro_refiner.downloader import (  # pylint: disable=import-outside-toplevel
                    get_download_tool, download_batch_with_aria2c,
                    download_batch_with_curl,
                )
                from retro_refiner.transfer import (  # pylint: disable=import-outside-toplevel
                    transfer_files, generate_m3u_playlist,
                    generate_gamelist_xml,
                )

                dest_dir = (Path(config.destination) if config.destination
                            else get_runtime_path() / 'refined')
                dest_dir.mkdir(parents=True, exist_ok=True)

                for system in sorted(all_systems):
                    if not self._running:
                        break
                    sys_urls = self._last_results.get(
                        system, {}).get('selected_urls', [])
                    if not sys_urls:
                        continue

                    # Build download list for uncached files
                    downloads = []
                    for url in sys_urls:
                        filename = urllib.parse.unquote(
                            url.split('?')[0].split('#')[0].split('/')[-1])
                        cache_path = cache_dir / system / filename
                        cache_path.parent.mkdir(parents=True, exist_ok=True)
                        if not cache_path.exists():
                            downloads.append((url, cache_path))

                    if downloads:
                        self._push_event('log', {
                            'text': f'  {system.upper()}: downloading '
                                    f'{len(downloads)} files...\n',
                        })
                        tool = get_download_tool()
                        if tool == 'aria2c':
                            download_batch_with_aria2c(
                                downloads,
                                parallel=config.network.parallel)
                        elif tool == 'curl':
                            download_batch_with_curl(
                                downloads,
                                parallel=config.network.parallel)
                        else:
                            # urllib fallback
                            import urllib.request as urllib_req  # pylint: disable=import-outside-toplevel
                            for dl_url, dl_path in downloads:
                                try:
                                    req = urllib_req.Request(
                                        dl_url,
                                        headers={
                                            'User-Agent': 'Mozilla/5.0'})
                                    with urllib_req.urlopen(
                                            req, timeout=60) as resp:
                                        import shutil as _shutil  # pylint: disable=import-outside-toplevel
                                        with open(dl_path, 'wb') as f_out:
                                            _shutil.copyfileobj(resp, f_out)
                                except Exception:  # pylint: disable=broad-except
                                    pass

                    # Transfer cached files to destination
                    cached_files = []
                    for url in sys_urls:
                        filename = urllib.parse.unquote(
                            url.split('?')[0].split('#')[0].split('/')[-1])
                        cache_path = cache_dir / system / filename
                        if cache_path.exists():
                            cached_files.append(cache_path)

                    if cached_files:
                        stats = transfer_files(
                            cached_files, dest_dir, system=system,
                            mode=config.output.transfer_mode,
                            flat=config.output.flat,
                        )
                        self._push_event('log', {
                            'text': f'  {system.upper()}: transferred '
                                    f'{stats["transferred"]}, '
                                    f'skipped {stats["skipped"]}, '
                                    f'errors {stats["errors"]}\n',
                        })

                # Generate playlists if configured
                if config.output.playlists and self._running:
                    self._push_event('log', {
                        'text': '\nGenerating playlists...\n',
                    })
                    for system in sorted(all_systems):
                        sys_dir = (dest_dir / system
                                   if not config.output.flat else dest_dir)
                        if sys_dir.exists():
                            rom_files = list(sys_dir.iterdir())
                            if rom_files:
                                generate_m3u_playlist(
                                    system, rom_files, sys_dir)

                if config.output.gamelist and self._running:
                    self._push_event('log', {
                        'text': 'Generating gamelists...\n',
                    })
                    for system in sorted(all_systems):
                        sys_dir = (dest_dir / system
                                   if not config.output.flat else dest_dir)
                        if sys_dir.exists():
                            rom_files = list(sys_dir.iterdir())
                            if rom_files:
                                generate_gamelist_xml(
                                    system, rom_files, sys_dir)

            # Push summary
            self._push_event('summary', {
                'total_selected': total_selected,
                'total_size': total_size,
                'system_count': len(all_systems),
                'commit': commit,
            })

            label = 'Commit' if commit else 'Preview'
            self._push_event('status', {
                'state': 'completed',
                'message': f'{label} complete: {total_selected} ROMs '
                           f'across {len(all_systems)} systems',
            })

        except Exception as exc:  # pylint: disable=broad-except
            self._push_event('status', {
                'state': 'error',
                'message': str(exc),
            })
            self._push_event('log', {
                'text': f'\nERROR: {exc}\n',
                'className': 'log-error',
            })
        finally:
            self._running = False

    def get_system_roms(self, system: str) -> str:
        """Get ROM list for a system as JSON.

        Returns list of {filename, url, size, region, status, reason} dicts.
        """
        roms = []
        result = self._last_results.get(system, {})
        for url in result.get('urls', []):
            filename = urllib.parse.unquote(url.split('/')[-1])
            size = result.get('sizes', {}).get(url, 0)
            roms.append({
                'filename': filename,
                'url': url,
                'size': size,
                'region': '',
                'status': 'selected',
                'reason': '',
            })
        for filepath in result.get('local_files', []):
            filename = Path(filepath).name
            try:
                size = Path(filepath).stat().st_size
            except OSError:
                size = 0
            roms.append({
                'filename': filename,
                'url': '',
                'size': size,
                'region': '',
                'status': 'selected',
                'reason': '',
            })
        return json.dumps(roms)

    def get_all_roms(self) -> str:
        """Get all ROMs across all systems as JSON.

        Returns list of dicts with a system field added.
        """
        all_roms = []
        for system in sorted(self._last_results):
            roms = json.loads(self.get_system_roms(system))
            for rom in roms:
                rom['system'] = system
                all_roms.append(rom)
        return json.dumps(all_roms)

    def update_rom_selection(self, system: str, selections_json: str):
        """Update which ROMs are selected for a system.

        selections_json is a JSON list of {filename, selected} dicts.
        """
        selections = json.loads(selections_json)
        if system not in self._manual_selections:
            self._manual_selections[system] = {}
        for sel in selections:
            self._manual_selections[system][sel['filename']] = sel['selected']

    def _push_event(self, event_type: str, data: dict):
        """Push an event to the JavaScript frontend."""
        if self._window:
            payload = json.dumps({'type': event_type, 'data': data})
            self._window.evaluate_js(
                f'window.handlePythonEvent({payload})'
            )

    def browse_folder(self) -> str:
        """Open a folder browser dialog. Returns selected path or empty."""
        if self._window:
            result = self._window.create_file_dialog(
                webview.FileDialog.FOLDER
            )
            if result and len(result) > 0:
                return result[0]
        return ''

    def browse_file(self, file_types=None) -> str:
        """Open a file browser dialog."""
        if self._window:
            result = self._window.create_file_dialog(
                webview.FileDialog.OPEN,
                file_types=file_types or ('All files (*.*)',),
            )
            if result and len(result) > 0:
                return result[0]
        return ''

    def save_file_dialog(self, file_types=None) -> str:
        """Open a save file dialog."""
        if self._window:
            result = self._window.create_file_dialog(
                webview.FileDialog.SAVE,
                file_types=file_types or ('YAML files (*.yaml)',),
            )
            if result:
                if isinstance(result, str):
                    return result
                return result[0] if result else ''
        return ''


def _parse_csv(value):
    """Parse comma-separated string into list or None."""
    if not value or not value.strip():
        return None
    items = [s.strip() for s in value.split(',') if s.strip()]
    return items if items else None


def _int_or_none(value):
    """Convert value to int or None."""
    if value is None or value == '':
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None

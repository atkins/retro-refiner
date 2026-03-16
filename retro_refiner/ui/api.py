"""Python API exposed to JavaScript via pywebview."""

import json
import threading
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
                is_url, scan_network_source, validate_source,
            )
            from retro_refiner.scanner import (  # pylint: disable=import-outside-toplevel
                scan_local_sources,
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

                # For now, all items pass (filtering will be wired in detail
                # when filter.py is connected to the monolith engine)
                selected_count = source_count
                selected_size = sys_size
                total_selected += selected_count
                total_size += selected_size

                self._push_event('card', {
                    'system': system,
                    'state': 'complete',
                    'selected_count': selected_count,
                    'excluded_count': 0,
                    'selected_size': selected_size,
                    'source_count': source_count,
                    'source_size': sys_size,
                    'filter_breakdown': {},
                })

            if not self._running:
                self._push_event('status', {
                    'state': 'cancelled', 'message': 'Cancelled',
                })
                return

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
                webview.FOLDER_DIALOG
            )
            if result and len(result) > 0:
                return result[0]
        return ''

    def browse_file(self, file_types=None) -> str:
        """Open a file browser dialog."""
        if self._window:
            result = self._window.create_file_dialog(
                webview.OPEN_DIALOG,
                file_types=file_types or ('All files (*.*)',),
            )
            if result and len(result) > 0:
                return result[0]
        return ''

    def save_file_dialog(self, file_types=None) -> str:
        """Open a save file dialog."""
        if self._window:
            result = self._window.create_file_dialog(
                webview.SAVE_DIALOG,
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

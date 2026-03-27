"""Python API exposed to JavaScript via pywebview."""

import re
import threading
import time
import urllib.parse
from collections import Counter
from pathlib import Path
from statistics import median

import orjson
import webview

from retro_refiner.config import Config, load_config, save_config
from retro_refiner.log import logger
from retro_refiner.network import stream_download
from retro_refiner.paths import get_runtime_path
from retro_refiner.systems import load_system_data

_UI_STATE_FILENAME = '.retro-refiner-state.yaml'

_RE_LANG = re.compile(r'\(([A-Z][a-z](?:,[A-Z][a-z])*)\)')

_SYSTEM_ABBREVS = frozenset(
    ('snes', 'nes', 'gba', 'gbc', 'n64', 'psx', 'ps2', 'ps3', 'psp',
     '3do', '3ds', 'dsi', 'fds', 'msx', 'msx2', 'n64dd', 'ngp', 'ngpc',
     'scv', 'sgx', 'tg16', 'tgcd'))


def _display_name(system: str) -> str:
    """Convert a system code to a human-readable display name."""
    if system.lower() in _SYSTEM_ABBREVS:
        return system.upper()
    return system.replace('-', ' ').replace('_', ' ').title()


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
        self._picker_state = {}  # system -> list of rom dicts
        self._run_breakdowns = {}  # system -> filter_breakdown dict
        self._step_prefix = lambda n: f'[{n}/2] '  # run phase indicator
        self._skip_save = False   # set True during reset to prevent save-on-close

    def set_window(self, window):
        """Store a reference to the pywebview window."""
        self._window = window
        self._auto_check_for_updates()

    def get_config(self) -> str:
        """Return current config as JSON."""
        return orjson.dumps(self._config.to_dict()).decode()

    def set_config(self, config_json: str):
        """Update config from JSON."""
        data = orjson.loads(config_json)
        self._config = Config.from_dict(data)

    def get_systems(self) -> str:
        """Return list of known systems as JSON."""
        return orjson.dumps(self._systems_data.known_systems).decode()

    def save_settings(self, path: str):
        """Save current config to file."""
        save_config(self._config, Path(path))

    def load_settings(self, path: str) -> str:
        """Load config from file and return as JSON."""
        self._config = load_config(Path(path))
        return orjson.dumps(self._config.to_dict()).decode()

    def get_default_config(self) -> str:
        """Reset config to defaults and return as JSON."""
        self._config = Config()
        return orjson.dumps(self._config.to_dict()).decode()

    def reset_and_restart(self):
        """Delete state file and cache, then restart the app."""
        import shutil  # pylint: disable=import-outside-toplevel

        self._skip_save = True  # prevent on_closing from rewriting state
        runtime = get_runtime_path()

        # Delete state file
        state_file = runtime / _UI_STATE_FILENAME
        try:
            state_file.unlink(missing_ok=True)
        except OSError:
            pass

        # Delete cache
        cache_dir = runtime / 'cache'
        if cache_dir.exists():
            shutil.rmtree(cache_dir, ignore_errors=True)

        # Delete CRC cache
        crc_cache = runtime / '_crc_cache.json'
        try:
            crc_cache.unlink(missing_ok=True)
        except OSError:
            pass

        # Delete DAT files
        dat_dir = Path(self._config.advanced.dat_dir or './dat_files')
        if not dat_dir.is_absolute():
            dat_dir = runtime / dat_dir
        if dat_dir.exists() and any(dat_dir.glob('*.dat')):
            shutil.rmtree(dat_dir, ignore_errors=True)

        # Relaunch app
        from retro_refiner.updater import launch_and_exit  # pylint: disable=import-outside-toplevel
        if self._window:
            self._window.destroy()
        launch_and_exit()

    def check_for_updates(self, force=False):
        """Check GitHub for a newer version. Returns JSON."""
        from retro_refiner.updater import (  # pylint: disable=import-outside-toplevel
            can_check_for_updates, check_for_update,
            load_update_state, save_update_state, should_check,
        )
        if not can_check_for_updates():
            return orjson.dumps(None).decode()

        state = load_update_state()
        if not force and not should_check(state):
            return orjson.dumps(None).decode()

        info = check_for_update()

        from datetime import datetime, timezone  # pylint: disable=import-outside-toplevel
        state['last_check'] = datetime.now(timezone.utc).isoformat()
        save_update_state(state)

        if not info:
            return orjson.dumps(None).decode()

        if state.get('dismissed_version') == info['version']:
            return orjson.dumps(None).decode()

        return orjson.dumps(info).decode()

    def download_update(self, url, expected_size):
        """Download update and apply it. Pushes progress events."""
        def _do_download():
            from retro_refiner.updater import (  # pylint: disable=import-outside-toplevel
                download_update as dl_update, apply_update,
            )
            def on_progress(downloaded, total):
                pct = int(downloaded / total * 100) if total else 0
                self._push_event('update-progress', {
                    'downloaded': downloaded, 'total': total, 'percent': pct,
                })

            self._push_event('update-downloading', {})

            path = dl_update(url, expected_size, progress_callback=on_progress)
            if not path:
                self._push_event('update-error', {
                    'message': 'Download failed or file size mismatch',
                })
                return

            import sys as _sys  # pylint: disable=import-outside-toplevel
            exe_path = Path(_sys.executable)
            success = apply_update(path, exe_path)
            if success:
                self._push_event('update-ready', {})
            else:
                self._push_event('update-error', {
                    'message': 'Failed to apply update (permission error?)',
                })

        t = threading.Thread(target=_do_download, daemon=True)
        t.start()
        return orjson.dumps({'status': 'started'}).decode()

    def restart_app(self):
        """Save state and restart with the updated executable."""
        self._skip_save = False
        self.save_ui_state()
        from retro_refiner.updater import launch_and_exit  # pylint: disable=import-outside-toplevel
        if self._window:
            self._window.destroy()
        launch_and_exit()

    def dismiss_update(self, version):
        """Dismiss the update banner for a specific version."""
        from retro_refiner.updater import (  # pylint: disable=import-outside-toplevel
            load_update_state, save_update_state,
        )
        state = load_update_state()
        state['dismissed_version'] = version
        save_update_state(state)
        return orjson.dumps({'ok': True}).decode()

    def _auto_check_for_updates(self):
        """Background auto-check for updates on app launch."""
        def _check():
            time.sleep(3)  # Let GUI settle first
            result_json = self.check_for_updates()
            result = orjson.loads(result_json)
            if result:
                self._push_event('update-available', result)

        t = threading.Thread(target=_check, daemon=True)
        t.start()

    def clean_data(self) -> str:
        """Delete all cached and generated data files.

        Returns JSON with list of deleted items.
        """
        import shutil  # pylint: disable=import-outside-toplevel

        runtime = get_runtime_path()
        deleted = []

        # Scan cache
        cache_dir = runtime / 'cache'
        if cache_dir.exists():
            shutil.rmtree(cache_dir)
            deleted.append('cache/ (scan cache)')

        # DAT files
        dat_dir = Path(self._config.advanced.dat_dir or './dat_files')
        if not dat_dir.is_absolute():
            dat_dir = runtime / dat_dir
        if dat_dir.exists() and any(dat_dir.glob('*.dat')):
            shutil.rmtree(dat_dir)
            deleted.append(f'{dat_dir.name}/ (DAT files)')

        # CRC cache
        crc_cache = runtime / '_crc_cache.json'
        if crc_cache.exists():
            crc_cache.unlink()
            deleted.append('_crc_cache.json (CRC cache)')

        # UI state file
        state_file = runtime / _UI_STATE_FILENAME
        if state_file.exists():
            state_file.unlink()
            deleted.append(f'{_UI_STATE_FILENAME} (saved state)')

        # Temp download files (.rrdownload)
        if self._config.destination:
            dest = Path(self._config.destination)
            if dest.exists():
                for tmp in dest.rglob('*.rrdownload'):
                    tmp.unlink()
                    deleted.append(f'{tmp.name} (temp download)')

        return orjson.dumps({'deleted': deleted}).decode()

    def save_ui_state(self):
        """Auto-save current config to the default UI state file.

        Auth credentials are excluded from the persisted state to avoid
        storing secrets in cleartext on disk.
        """
        if self._skip_save:
            return
        path = get_runtime_path() / _UI_STATE_FILENAME
        try:
            # Temporarily clear auth fields so they are not persisted
            saved_auth = self._config.auth
            from retro_refiner.config import AuthConfig  # pylint: disable=import-outside-toplevel
            self._config.auth = AuthConfig()
            try:
                save_config(self._config, path)
            finally:
                self._config.auth = saved_auth
        except OSError:
            pass

    def load_ui_state(self) -> str:
        """Load saved UI state, returning JSON (empty object if none)."""
        path = get_runtime_path() / _UI_STATE_FILENAME
        if not path.exists():
            return '{}'
        try:
            self._config = load_config(path)
            return orjson.dumps(self._config.to_dict()).decode()
        except (OSError, ValueError):
            return '{}'

    def update_sources(self, sources_json: str):
        """Update sources list from JS."""
        self._config.sources = orjson.loads(sources_json)

    def update_destination(self, dest: str):
        """Update destination from JS."""
        self._config.destination = dest

    def update_theme(self, theme_name: str):
        """Update theme immediately so it persists on close."""
        self._config.theme.mode = theme_name

    def open_url(self, url: str):
        """Open a URL in the system default browser."""
        import webbrowser  # pylint: disable=import-outside-toplevel
        webbrowser.open(url)

    def read_clipboard(self):
        """Read text from the system clipboard using platform-native APIs."""
        import subprocess as _sp  # pylint: disable=import-outside-toplevel
        import sys as _sys  # pylint: disable=import-outside-toplevel
        try:
            if _sys.platform == 'win32':
                result = _sp.run(
                    ['powershell', '-NoProfile', '-Command',
                     'Get-Clipboard'],
                    capture_output=True, text=True, timeout=5,
                    check=False,
                    creationflags=_sp.CREATE_NO_WINDOW,
                )
                return result.stdout.rstrip('\r\n')
            if _sys.platform == 'darwin':
                result = _sp.run(
                    ['pbpaste'], capture_output=True, text=True,
                    timeout=5, check=False)
                return result.stdout
            # Linux / other: try xclip, then xsel
            result = _sp.run(
                ['xclip', '-selection', 'clipboard', '-o'],
                capture_output=True, text=True, timeout=5, check=False)
            return result.stdout
        except Exception:  # pylint: disable=broad-except
            return ''

    def copy_to_clipboard(self, text: str):
        """Copy text to the system clipboard using platform-native APIs."""
        import subprocess as _sp  # pylint: disable=import-outside-toplevel
        import sys as _sys  # pylint: disable=import-outside-toplevel
        try:
            if _sys.platform == 'win32':
                # Pipe via stdin fails on unicode (cp1252 can't encode
                # box-drawing chars). Use a temp file with UTF-8 encoding.
                import tempfile  # pylint: disable=import-outside-toplevel
                import os  # pylint: disable=import-outside-toplevel
                fd, tmp = tempfile.mkstemp(suffix='.txt')
                try:
                    with os.fdopen(fd, 'w', encoding='utf-8') as fh:
                        fh.write(text)
                    _sp.run(
                        ['powershell', '-NoProfile', '-Command',
                         f'Get-Content -Raw -Encoding UTF8 "{tmp}"'
                         ' | Set-Clipboard'],
                        timeout=10, check=True,
                        creationflags=_sp.CREATE_NO_WINDOW,
                    )
                finally:
                    try:
                        os.unlink(tmp)
                    except OSError:
                        pass
            elif _sys.platform == 'darwin':
                _sp.run(['pbcopy'], input=text.encode('utf-8'),
                        timeout=10, check=True)
            else:
                _sp.run(
                    ['xclip', '-selection', 'clipboard'],
                    input=text.encode('utf-8'),
                    timeout=10, check=True)
            return True
        except Exception:  # pylint: disable=broad-except
            return False

    def update_selection(self, selection_json: str):
        """Update selection config from JS."""
        data = orjson.loads(selection_json)
        for key, value in data.items():
            if hasattr(self._config.selection, key):
                setattr(self._config.selection, key, value)

    def update_config_from_ui(self, ui_json: str):
        """Update full config from UI sidebar state."""
        ui = orjson.loads(ui_json)
        self._config.sources = ui.get('sources', [])
        self._config.source_settings = ui.get('source_settings', {})
        self._config.destination = ui.get('destination') or None
        self._config.systems = _parse_csv(ui.get('systems'))

        # Selection
        sel = self._config.selection
        sel.all_roms = ui.get('all_roms', False)
        sel.best_version = ui.get('best_version', False)
        sel.english_only = ui.get('english_only', False)
        sel.exclude_protos = ui.get('exclude_protos', False)
        sel.include_betas = ui.get('include_betas', False)
        sel.include_unlicensed = not ui.get('no_unlicensed', False)
        rp = ui.get('region_priority', '').strip()
        if rp:
            sel.region_priority = [r.strip() for r in rp.split(',')
                                   if r.strip()]
        sel.keep_regions = ui.get('keep_regions') or None
        inc = ui.get('include_patterns', '').strip()
        sel.include_patterns = ([p.strip() for p in inc.split(',')
                                 if p.strip()] if inc else [])
        exc = ui.get('exclude_patterns', '').strip()
        sel.exclude_patterns = ([p.strip() for p in exc.split(',')
                                 if p.strip()] if exc else [])
        sel.year_from = _int_or_none(ui.get('year_from'))
        sel.year_to = _int_or_none(ui.get('year_to'))

        # Budget
        bud = self._config.budget
        bud.top = ui.get('top') or None
        bud.limit = _int_or_none(ui.get('limit'))
        bud.size = ui.get('size') or None
        bud.include_unrated = ui.get('include_unrated', False)
        bud.prefer_exclusives = _float_or_none(
            ui.get('prefer_exclusives'))

        # Network
        net = self._config.network
        net.parallel = int(ui.get('parallel', 4) or 4)
        net.scan_workers = int(ui.get('scan_workers', 16) or 16)
        # resume_downloads and auto_tune removed (aria2c-only settings)

        # Output
        out = self._config.output
        out.playlists = ui.get('playlists', False)
        out.gamelist = ui.get('gamelists') or None
        out.flat = ui.get('flatten', False)
        lfa = ui.get('local_file_action',
                     ui.get('transfer_mode', 'copy'))
        out.local_file_action = 'remove' if lfa == 'delete-dupes' else lfa
        out.validate_destination = ui.get('validate_destination', True)
        out.clean_destination = ui.get('clean_destination', False)
        out.crc_validation = ui.get('crc_validation', False)
        out.retroarch_playlists = ui.get('retroarch_playlists') or None

        # Advanced
        adv = self._config.advanced
        adv.no_verify = ui.get('no_verify', False)
        adv.no_dat = ui.get('no_dat', False)
        adv.no_chd = ui.get('no_chd', False)
        adv.no_cache = ui.get('no_cache', False)
        adv.no_adult = ui.get('no_adult', False)
        adv.recursive = ui.get('recursive', False)
        adv.max_depth = int(ui.get('max_depth', 3) or 3)
        adv.mame_version = ui.get('mame_version') or None
        adv.dat_dir = ui.get('dat_dir') or None
        adv.ratings_source = ui.get('ratings_source', 'combined')

        # Auth
        auth = self._config.auth
        auth.igdb_client_id = ui.get('igdb_client_id') or None
        auth.igdb_client_secret = ui.get('igdb_client_secret') or None
        auth.ia_access_key = ui.get('ia_access_key') or None
        auth.ia_secret_key = ui.get('ia_secret_key') or None

        # Dedup
        ded = self._config.deduplication
        ded.priority = ui.get('dedup_priority') or None
        pc = ui.get('dedup_pc_lists', '').strip()
        ded.pc_lists = ([p.strip() for p in pc.split(',')
                         if p.strip()] if pc else [])
        ded.delete = ui.get('dedup_delete', False)

        # Theme
        self._config.theme.mode = ui.get('theme', 'midnight-terminal')

        # Exclude systems (internal, not on Config)
        excl = ui.get('exclude_systems', '').strip()
        self._exclude_systems = ([s.strip() for s in excl.split(',')
                                  if s.strip()] if excl else [])

    def run_preview(self):
        """Start a preview run (no file transfer)."""
        if self._running:
            return
        self._running = True
        total_steps = 2
        self._step_prefix = lambda n: f'[{n}/{total_steps}] '
        thread = threading.Thread(target=self._do_run, args=(False,), daemon=True)
        thread.start()

    def run_commit(self):
        """Start a commit run (with file transfer)."""
        if self._running:
            return
        self._running = True
        total_steps = 3
        self._step_prefix = lambda n: f'[{n}/{total_steps}] '
        thread = threading.Thread(target=self._do_run, args=(True,), daemon=True)
        thread.start()

    def cancel_run(self):
        """Cancel the current run."""
        self._running = False
        from retro_refiner.network import request_shutdown  # pylint: disable=import-outside-toplevel
        request_shutdown()

    def is_running(self) -> bool:
        """Return whether a run is currently in progress."""
        return self._running

    def _do_run(self, commit: bool):
        """Execute the run in a background thread."""
        from retro_refiner.network import reset_shutdown  # pylint: disable=import-outside-toplevel
        reset_shutdown()
        try:
            mode = 'commit' if commit else 'preview'
            self._push_event('status', {
                'state': 'running',
                'message': f'Starting {mode} run...',
            })
            run_start = time.monotonic()

            self._run_breakdowns = {}

            config = Config.from_dict(self._config.to_dict())
            logger.info("Starting {} run", 'commit' if commit else 'preview')
            logger.debug("Config: sources={}, destination={}, selection={}",
                         config.sources, config.destination,
                         {'english_only': config.selection.english_only,
                          'best_version': config.selection.best_version,
                          'all_roms': config.selection.all_roms,
                          'exclude_protos': config.selection.exclude_protos,
                          'include_betas': config.selection.include_betas})

            # Import core modules
            from retro_refiner.network import (  # pylint: disable=import-outside-toplevel
                is_url, validate_source,
            )
            from retro_refiner.scanner import (  # pylint: disable=import-outside-toplevel
                scan_local_sources, scan_network_source,
            )

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

            if not self._validate_sources(config, is_url, validate_source):
                return

            # Determine cache dir
            if config.advanced.cache_dir:
                cache_dir = Path(config.advanced.cache_dir).resolve()
            elif local_sources:
                cache_dir = local_sources[0] / 'cache'
            else:
                cache_dir = get_runtime_path() / 'cache'

            scan = self._scan_sources(
                config, local_sources, network_sources,
                cache_dir, scan_network_source, scan_local_sources)
            if scan is None:
                return
            all_urls, all_sizes, local_systems, all_systems = scan

            # Process each system and push card events
            total_selected = 0
            total_excluded = 0
            total_size = 0
            total_source = 0
            total_source_size = 0

            sorted_systems = sorted(all_systems)
            num_systems = len(sorted_systems)
            filter_t0 = time.monotonic()
            for sys_idx, system in enumerate(sorted_systems, 1):
                if not self._running:
                    break
                elapsed = time.monotonic() - filter_t0
                eta = self._eta_str(elapsed, sys_idx - 1, num_systems)
                elapsed_s = self._elapsed_str(elapsed)
                from retro_refiner.network import format_size as _fmt  # pylint: disable=import-outside-toplevel
                msg = (f'{self._step_prefix(2)}'
                       f'Filtering {sys_idx}/{num_systems}: '
                       f'{_display_name(system)} '
                       f'\u2502 {total_selected:,} selected '
                       f'\u2502 {_fmt(total_size)} '
                       f'\u2502 {elapsed_s}{eta}')
                self._push_event('progress', {
                    'phase': 'filtering',
                    'message': msg,
                    'current': sys_idx,
                    'total': num_systems,
                })
                counts = self._filter_system(
                    system, all_urls.get(system, []),
                    local_systems.get(system, []),
                    config, all_sizes)
                total_selected += counts[0]
                total_excluded += counts[1]
                total_size += counts[2]
                total_source += counts[3]
                total_source_size += counts[4]

            # ----- Budget filters: --limit, --top, --size -----
            if self._running:
                self._apply_budget_filters(config, all_systems, all_sizes)

            # ----- Cross-system dedup -----
            dedup_priority = config.deduplication.priority
            if dedup_priority and self._running:
                self._run_dedup(dedup_priority, all_sizes)

            if not self._running:
                self._push_event('status', {
                    'state': 'cancelled', 'message': 'Cancelled',
                })
                return

            # Commit mode: download and transfer files
            if commit and self._running:
                from retro_refiner.transfer import (  # pylint: disable=import-outside-toplevel
                    generate_m3u_playlist,
                    generate_gamelist_xml,
                    generate_retroarch_playlist,
                )

                dest_dir = (Path(config.destination) if config.destination
                            else get_runtime_path() / 'refined')
                if config.output.local_file_action != 'remove':
                    dest_dir.mkdir(parents=True, exist_ok=True)

                # Check disk space before committing
                if total_size > 0 and dest_dir.exists():
                    import shutil as _shutil  # pylint: disable=import-outside-toplevel
                    try:
                        free = _shutil.disk_usage(dest_dir).free
                        if free < total_size:
                            from retro_refiner.network import format_size  # pylint: disable=import-outside-toplevel
                            self._push_event('log', {
                                'text': (f'\nInsufficient disk space on '
                                         f'{dest_dir.anchor}\n'
                                         f'  Need: {format_size(total_size)}'
                                         f'  Available: {format_size(free)}'
                                         '\n'),
                                'className': 'log-error',
                            })
                            self._push_event('status', {
                                'state': 'error',
                                'message': 'Insufficient disk space',
                            })
                            return
                    except OSError:
                        pass  # can't check, proceed anyway

                for system in sorted(all_systems):
                    if not self._running:
                        break
                    self._commit_system(system, config, dest_dir)

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

                gl_dir = config.output.gamelist
                if gl_dir and self._running:
                    gl_path = Path(gl_dir)
                    gl_path.mkdir(parents=True, exist_ok=True)
                    self._push_event('log', {
                        'text': f'Generating EmulationStation gamelists '
                                f'in {gl_dir}...\n',
                    })
                    for system in sorted(all_systems):
                        sys_dir = (dest_dir / system
                                   if not config.output.flat else dest_dir)
                        if sys_dir.exists():
                            rom_files = [f for f in sys_dir.iterdir()
                                         if f.is_file()]
                            if rom_files:
                                out_dir = gl_path / system
                                out_dir.mkdir(parents=True, exist_ok=True)
                                generate_gamelist_xml(
                                    system, rom_files, out_dir)

                ra_dir = config.output.retroarch_playlists
                if ra_dir and self._running:
                    ra_path = Path(ra_dir)
                    ra_path.mkdir(parents=True, exist_ok=True)
                    self._push_event('log', {
                        'text': f'Generating RetroArch playlists '
                                f'in {ra_dir}...\n',
                    })
                    for system in sorted(all_systems):
                        sys_dir = (dest_dir / system
                                   if not config.output.flat else dest_dir)
                        if sys_dir.exists():
                            rom_files = [f for f in sys_dir.iterdir()
                                         if f.is_file()]
                            if rom_files:
                                generate_retroarch_playlist(
                                    system, rom_files, sys_dir,
                                    ra_path)

            # Recompute totals after budget/dedup filters
            total_selected = 0
            total_size = 0
            for system in all_systems:
                sys_data = self._last_results.get(system, {})
                sys_urls = sys_data.get('selected_urls', [])
                total_selected += len(sys_urls)
                total_size += sum(all_sizes.get(u, 0) for u in sys_urls)
            total_excluded = total_source - total_selected

            # Push summary
            self._push_event('summary', {
                'total_selected': total_selected,
                'total_size': total_size,
                'system_count': len(all_systems),
                'commit': commit,
            })

            logger.info("Run complete: {} selected across {} systems",
                        total_selected, len(all_systems))

            self._compute_fanfare(
                config, total_selected, total_excluded,
                total_size, run_start, all_systems,
                total_source_size)

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

    # ------------------------------------------------------------------
    # Extracted phases called by _do_run
    # ------------------------------------------------------------------

    def _validate_sources(self, config, is_url, validate_source):
        """Validate all configured sources. Returns True if all OK."""
        self._push_event('log', {'text': 'Validating sources...\n'})
        for src in config.sources:
            if not self._running:
                break
            ok, error = validate_source(src)
            status = 'OK' if ok else error
            css = 'log-success' if ok else 'log-error'
            self._push_event('log', {
                'text': f'  {urllib.parse.unquote(src)}... {status}\n',
                'className': css,
                'url': src if is_url(src) else None,
            })
            if not ok:
                self._push_event('status', {
                    'state': 'error',
                    'message': f'Source validation failed: {error}',
                })
                return False

        if not self._running:
            self._push_event('status', {
                'state': 'cancelled', 'message': 'Cancelled',
            })
            return False
        return True

    def _scan_sources(self, config, local_sources, network_sources,
                      cache_dir, scan_network_source, scan_local_sources):
        """Scan network and local sources.

        Returns (all_urls, all_sizes, local_systems, all_systems) tuple
        or None if cancelled / empty.
        """
        all_urls = {}   # system -> [urls]
        all_sizes = {}  # url -> size
        per_source_stats = []

        for net_url in network_sources:
            if not self._running:
                break
            self._push_event('log', {
                'text': f'\nScanning: {urllib.parse.unquote(net_url)}\n',
                'className': 'log-info',
                'url': net_url,
            })

            systems_filter = config.systems
            exclude = getattr(self, '_exclude_systems', [])
            if exclude and systems_filter:
                systems_filter = [s for s in systems_filter
                                  if s not in exclude]

            scan_t0 = time.monotonic()
            used_cache = False

            # Check cache to detect cache hit before scanning
            if cache_dir and not config.advanced.no_cache:
                from retro_refiner.scanner import load_scan_cache  # pylint: disable=import-outside-toplevel
                cached = load_scan_cache(cache_dir, net_url)
                if cached:
                    used_cache = True
                    logger.debug("Using cached scan for {} ({} URLs)",
                                 net_url,
                                 sum(len(v) for v in cached[0].values()))
                else:
                    logger.debug("Fresh scan for {}", net_url)

            ss = config.source_settings or {}
            src_opts = ss.get(net_url, {})
            net_recursive = src_opts.get('recursive', False)
            net_depth = config.advanced.max_depth or 3

            _scan_state = {'last_logged': 0, 't0': time.monotonic()}

            def _on_scan_progress(evt, state=_scan_state):  # pylint: disable=dangerous-default-value
                msg = evt.message or ''
                # Enrich progress events with timing
                if evt.total > 0 and evt.current > 0:
                    elapsed = time.monotonic() - state['t0']
                    rate = evt.current / max(elapsed, 0.1)
                    eta = self._eta_str(
                        elapsed, evt.current, evt.total)
                    msg = (f'{self._step_prefix(1)}'
                           f'Scanning: {evt.current}/{evt.total}'
                           f' folders \u2502 '
                           f'{rate:.0f}/s{eta}')
                self._push_event('progress', {
                    'phase': evt.phase, 'message': msg,
                    'current': evt.current, 'total': evt.total,
                })
                # Log scan messages and progress milestones
                if evt.message and evt.total == 0:
                    self._push_event('log', {
                        'text': f'  {evt.message}\n',
                        'className': 'log-muted',
                    })
                elif (evt.total > 0 and evt.current > state['last_logged']
                      and (evt.current == evt.total
                           or evt.current - state['last_logged']
                           >= max(evt.total // 10, 1))):
                    state['last_logged'] = evt.current
                    self._push_event('log', {
                        'text': (f'  Scanning: {evt.current}'
                                 f'/{evt.total} system folders\n'),
                        'className': 'log-muted',
                    })

            self._push_event('log', {
                'text': f'  Recursive: {net_recursive}, '
                        f'depth: {net_depth}\n',
                'className': 'log-muted',
            })

            result = scan_network_source(
                net_url, systems_filter,
                recursive=net_recursive,
                max_depth=net_depth,
                cache_dir=cache_dir,
                no_cache=config.advanced.no_cache,
                scan_workers=config.network.scan_workers,
                on_progress=_on_scan_progress,
            )

            src_rom_count = sum(len(u) for u in result.url_dict.values())
            src_total_size = sum(result.url_sizes.values())
            per_source_stats.append({
                'url': net_url,
                'type': 'network',
                'systems_found': len(result.url_dict),
                'rom_count': src_rom_count,
                'total_size': src_total_size,
                'cached': used_cache,
                'elapsed_ms': int(
                    (time.monotonic() - scan_t0) * 1000),
            })

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
            ss = config.source_settings or {}
            for src_path in local_sources:
                src_key = str(src_path)
                src_opts = ss.get(src_key, {})
                recursive = src_opts.get('recursive', False)
                depth = config.advanced.max_depth or 3
                scan_t0 = time.monotonic()
                result = scan_local_sources(
                    [src_path],
                    recursive=recursive,
                    max_depth=depth,
                    verbose=config.selection.verbose,
                    on_progress=lambda evt: self._push_event(
                        'progress', {
                            'phase': evt.phase,
                            'message': evt.message,
                            'current': evt.current,
                            'total': evt.total,
                        }),
                )
                src_rom_count = sum(len(f) for f in result.values())
                src_total_size = 0
                for files in result.values():
                    for fpath in files:
                        try:
                            src_total_size += Path(fpath).stat().st_size
                        except OSError:
                            pass
                per_source_stats.append({
                    'path': src_key,
                    'type': 'local',
                    'systems_found': len(result),
                    'rom_count': src_rom_count,
                    'total_size': src_total_size,
                    'elapsed_ms': int(
                        (time.monotonic() - scan_t0) * 1000),
                })
                for sys_code, files in result.items():
                    local_systems.setdefault(
                        sys_code, []).extend(files)

        if not self._running:
            self._push_event('status', {
                'state': 'cancelled', 'message': 'Cancelled',
            })
            return None

        # Store scan results for the ROM picker (clear prior state)
        self._last_results = {}
        self._picker_state = {}
        self._manual_selections = {}
        for sys_code in set(all_urls.keys()) | set(local_systems.keys()):
            self._last_results[sys_code] = {
                'urls': all_urls.get(sys_code, []),
                'sizes': {u: all_sizes.get(u, 0)
                          for u in all_urls.get(sys_code, [])},
                'local_files': local_systems.get(sys_code, []),
            }

        # Combine all discovered systems, then apply include/exclude filters
        all_systems = set(all_urls.keys()) | set(local_systems.keys())
        if config.systems:
            allowed = set(config.systems)
            all_systems = all_systems & allowed
        exclude = getattr(self, '_exclude_systems', [])
        if exclude:
            all_systems -= set(exclude)
        if not all_systems:
            self._push_event('status', {
                'state': 'completed',
                'message': 'No systems found in sources',
            })
            return None

        self._push_event('log', {
            'text': f'\nFound {len(all_systems)} systems\n',
            'className': 'log-success',
        })

        network_rom_count = sum(
            len(urls) for urls in all_urls.values())
        local_rom_count = sum(
            len(files) for files in local_systems.values())
        self._push_event('scan-summary', {
            'sources': per_source_stats,
            'total_systems': len(all_systems),
            'total_roms': network_rom_count + local_rom_count,
            'network_count': network_rom_count,
            'local_count': local_rom_count,
        })

        logger.debug("Scan complete: {} URLs across {} systems",
                     sum(len(v) for v in all_urls.values()),
                     len(all_systems))
        for sys_code, sys_urls in sorted(all_urls.items()):
            logger.debug("  System '{}': {} URLs", sys_code, len(sys_urls))

        return all_urls, all_sizes, local_systems, all_systems

    def _filter_system(self, system, urls, local_files,
                       config, all_sizes):
        """Filter ROMs for a single system.

        Returns (selected_count, excluded_count, selected_size,
        source_count, source_size) tuple.
        """
        from retro_refiner.network import format_size  # pylint: disable=import-outside-toplevel
        logger.debug("Filtering {}: {} URLs + {} local files",
                     system, len(urls), len(local_files))
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

        display_name = _display_name(system)

        # Push card-start event
        self._push_event('card', {
            'system': system,
            'state': 'filtering',
            'source_count': source_count,
            'source_size': sys_size,
        })

        self._push_event('system-start', {
            'system': system,
            'display_name': display_name,
            'total_roms': source_count,
        })
        self._push_event('filter-tick', {
            'system': system,
            'selected': 0,
            'excluded': 0,
            'processed': 0,
            'total': source_count,
            'size_selected': '0 B',
        })

        self._push_event('log', {
            'text': f'\n{system.upper()}: '
                    f'Filtering {source_count} ROMs...\n',
        })
        t_start = time.monotonic()

        # Run actual filtering
        from retro_refiner.filter import (  # pylint: disable=import-outside-toplevel
            filter_network_roms, filter_roms_from_files,
        )
        from retro_refiner.mame import filter_mame_network_roms  # pylint: disable=import-outside-toplevel
        from retro_refiner.teknoparrot import filter_teknoparrot_network_roms  # pylint: disable=import-outside-toplevel

        selected_urls = urls
        selected_local = list(local_files)
        filter_breakdown = {}
        # NOTE: filter_network_roms returns FilterResult,
        # but filter_mame_network_roms / filter_teknoparrot_network_roms
        # return (selected_urls, info_dict) tuples.  The code below
        # handles both shapes; a future refactor should unify them.
        result = None
        sel = config.selection

        # --- Filter network URLs ---
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
                            include_patterns=sel.include_patterns or None,
                            exclude_patterns=sel.exclude_patterns or None,
                            include_adult=not config.advanced.no_adult,
                            url_sizes=all_sizes,
                            verbose=sel.verbose,
                            no_filter=sel.all_roms,
                            english_only=sel.english_only,
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
                        region_priority=sel.region_priority,
                        keep_all_versions=config.advanced.tp_all_versions,
                        include_patterns=sel.include_patterns or None,
                        exclude_patterns=sel.exclude_patterns or None,
                        url_sizes=all_sizes,
                        verbose=sel.verbose,
                        no_filter=sel.all_roms,
                        english_only=sel.english_only,
                    )
                    filter_breakdown = _info.get('filter_breakdown', {}) if isinstance(_info, dict) else {}
                else:
                    # Console system -- load DATs for better filtering
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
                    selected_urls = result.selected
                    filter_breakdown = result.stats.filter_breakdown if result.stats else {}
            except Exception as exc:  # pylint: disable=broad-except
                self._push_event('log', {
                    'text': f'  Filter error: {exc}\n',
                    'className': 'log-error',
                })

        # --- Filter local files ---
        if local_files:
            try:
                region_list = sel.region_priority or None
                kr = sel.keep_regions
                keep_list = ([r.strip() for r in kr.split(',')
                              if r.strip()] if kr else None)
                inc_pats = sel.include_patterns or None
                exc_pats = sel.exclude_patterns or None
                yf = sel.year_from
                yt = sel.year_to
                local_roms, local_info = filter_roms_from_files(
                    local_files,
                    dest_dir=config.destination or '.',
                    system=system,
                    dry_run=True,
                    include_patterns=inc_pats,
                    exclude_patterns=exc_pats,
                    exclude_protos=sel.exclude_protos,
                    include_betas=sel.include_betas,
                    include_unlicensed=sel.include_unlicensed,
                    region_priority=region_list,
                    keep_regions=keep_list,
                    year_from=int(yf) if yf else None,
                    year_to=int(yt) if yt else None,
                    no_filter=sel.all_roms,
                    best_version=sel.best_version,
                    english_only=sel.english_only,
                )
                name_to_path = {Path(f).name: Path(f)
                                for f in local_files}
                selected_local = [
                    name_to_path[rom.filename]
                    for rom in local_roms
                    if rom.filename in name_to_path
                ]
                local_size = local_info.get('selected_size', 0)
            except Exception as exc:  # pylint: disable=broad-except
                self._push_event('log', {
                    'text': f'  Local filter error: {exc}\n',
                    'className': 'log-error',
                })
                selected_local = list(local_files)
                local_size = sum(
                    Path(f).stat().st_size
                    for f in local_files if Path(f).exists())

        # --- Combine results ---
        net_selected = len(selected_urls)
        local_selected = len(selected_local)
        selected_count = net_selected + local_selected
        excluded_count = source_count - selected_count
        net_size = sum(all_sizes.get(u, 0) for u in selected_urls)
        local_sel_size = (local_size if local_files
                          else 0)
        selected_size = net_size + local_sel_size

        # Build preview titles (first 5 selected)
        preview = []
        for u in selected_urls[:5]:
            preview.append(
                urllib.parse.unquote(
                    u.split('?')[0].split('#')[0].split('/')[-1]
                ).rsplit('.', 1)[0])
        for f in selected_local[:max(0, 5 - len(preview))]:
            preview.append(Path(f).stem)

        self._push_event('card', {
            'system': system,
            'state': 'complete',
            'selected_count': selected_count,
            'excluded_count': excluded_count,
            'selected_size': selected_size,
            'source_count': source_count,
            'source_size': sys_size,
            'filter_breakdown': filter_breakdown,
            'preview_titles': preview,
        })

        # Emit system-complete for log renderer
        elapsed_ms = int((time.monotonic() - t_start) * 1000)
        excluded_roms = []
        if result and hasattr(result, 'excluded'):
            for exc_rom in result.excluded[:500]:
                excluded_roms.append({
                    'name': exc_rom.filename,
                    'reason': exc_rom.reason,
                })

        verbose_stats = self._compute_system_stats(
            selected_urls, selected_local, all_sizes, system)
        self._push_event('system-complete', {
            'system': system,
            'display_name': display_name,
            'selected': selected_count,
            'excluded': excluded_count,
            'total': source_count,
            'size': format_size(selected_size),
            'breakdown': filter_breakdown,
            'elapsed_ms': elapsed_ms,
            'excluded_roms': excluded_roms,
            'total_excluded_roms': excluded_count,
            'verbose_stats': verbose_stats,
        })

        # Store breakdown for fanfare aggregation
        self._run_breakdowns[system] = filter_breakdown

        # Store selected URLs/files for commit mode
        if system in self._last_results:
            self._last_results[system]['selected_urls'] = selected_urls
            self._last_results[system]['selected_local'] = [
                str(f) for f in selected_local]

        return (selected_count, excluded_count, selected_size,
                source_count, sys_size)

    def _compute_system_stats(self, selected_urls, selected_local,
                              url_sizes, system):
        """Compute detailed per-system statistics from selected ROMs."""
        from retro_refiner.filter import parse_rom_filename  # pylint: disable=import-outside-toplevel
        from retro_refiner.network import get_filename_from_url  # pylint: disable=import-outside-toplevel

        parsed = []
        file_sizes = {}  # filename -> size

        for url in selected_urls:
            fname = get_filename_from_url(url)
            file_sizes[fname] = url_sizes.get(url, 0)
            try:
                parsed.append(parse_rom_filename(fname))
            except Exception:  # pylint: disable=broad-except
                pass

        for fpath in selected_local:
            p_file = Path(fpath)
            fname = p_file.name
            try:
                file_sizes[fname] = p_file.stat().st_size
            except OSError:
                file_sizes[fname] = 0
            try:
                parsed.append(parse_rom_filename(fname))
            except Exception:  # pylint: disable=broad-except
                pass

        regions = dict(Counter(r.region for r in parsed if r.region))
        years_list = [r.year for r in parsed
                      if 1970 <= r.year <= 2030]
        # Only report year stats if >= 10% of ROMs have year data
        has_year_data = len(years_list) >= max(len(parsed) // 10, 3)
        years = ({str(k): v for k, v in Counter(years_list).items()}
                 if has_year_data else {})
        peak_year = (Counter(years_list).most_common(1)[0][0]
                     if has_year_data and years_list else 0)
        year_range = ([min(years_list), max(years_list)]
                      if has_year_data and years_list else [0, 0])
        formats = dict(Counter(
            Path(r.filename).suffix.lower() for r in parsed
            if Path(r.filename).suffix))

        # Size stats
        sizes_list = [file_sizes.get(r.filename, 0) for r in parsed]
        if sizes_list:
            sorted_sizes = sorted(
                ((r.filename, file_sizes.get(r.filename, 0))
                 for r in parsed if file_sizes.get(r.filename, 0) > 0),
                key=lambda x: x[1])
            if sorted_sizes:
                smallest = sorted_sizes[0]
                largest = sorted_sizes[-1]
            else:
                smallest = ('', 0)
                largest = ('', 0)
            avg_size = sum(sizes_list) // max(len(sizes_list), 1)
            median_size = int(median(sizes_list))
        else:
            smallest = ('', 0)
            largest = ('', 0)
            avg_size = 0
            median_size = 0

        # Size histogram
        histogram = {
            '< 1 MB': 0, '1-10 MB': 0, '10-100 MB': 0,
            '100 MB - 1 GB': 0, '> 1 GB': 0,
        }
        mb_1 = 1024 * 1024
        for sz in sizes_list:
            if sz < mb_1:
                histogram['< 1 MB'] += 1
            elif sz < 10 * mb_1:
                histogram['1-10 MB'] += 1
            elif sz < 100 * mb_1:
                histogram['10-100 MB'] += 1
            elif sz < 1024 * mb_1:
                histogram['100 MB - 1 GB'] += 1
            else:
                histogram['> 1 GB'] += 1

        # Language extraction from filenames
        languages = Counter()
        for rom in parsed:
            lang_match = _RE_LANG.search(rom.filename)
            if lang_match:
                for lang in lang_match.group(1).split(','):
                    languages[lang] += 1
            elif rom.is_english:
                languages['En'] += 1

        return {
            'system': system,
            'net_count': len(selected_urls),
            'local_count': len(selected_local),
            'regions': regions,
            'years': years,
            'peak_year': peak_year,
            'year_range': year_range,
            'formats': formats,
            'sizes': {
                'largest': list(largest),
                'smallest': list(smallest),
                'avg': avg_size,
                'median': median_size,
                'histogram': histogram,
            },
            'translation_count': sum(
                1 for r in parsed if r.is_translation),
            'multi_disc_count': sum(
                1 for r in parsed if r.disc_number > 1),
            'languages': dict(languages),
            'revision_counts': {str(k): v for k, v in Counter(
                r.revision for r in parsed
                if 0 < r.revision < 20).items()},
        }

    def _compute_fanfare(self, _config, total_selected, total_excluded,
                         total_size, run_start, all_systems,
                         total_source_size=0):
        """Compute and emit fanfare statistics from the run results."""
        total_systems = len(all_systems)
        elapsed_secs = time.monotonic() - run_start
        elapsed_str = self._elapsed_str(elapsed_secs)

        from retro_refiner.filter import parse_rom_filename  # pylint: disable=import-outside-toplevel
        from retro_refiner.network import format_size, get_filename_from_url  # pylint: disable=import-outside-toplevel
        tidbits = []
        all_roms = []
        rom_file_sizes = {}  # filename -> size
        for _sys_code, sys_data in self._last_results.items():
            sys_sizes = sys_data.get('sizes', {})
            for url in sys_data.get('selected_urls', []):
                fname = get_filename_from_url(url)
                rom_file_sizes[fname] = sys_sizes.get(url, 0)
                try:
                    all_roms.append(parse_rom_filename(fname))
                except Exception:  # pylint: disable=broad-except
                    pass
            for fpath in sys_data.get('selected_local', []):
                p_file = Path(fpath)
                try:
                    rom_file_sizes[p_file.name] = p_file.stat().st_size
                except OSError:
                    rom_file_sizes[p_file.name] = 0
                try:
                    all_roms.append(parse_rom_filename(p_file.name))
                except Exception:  # pylint: disable=broad-except
                    pass

        # Throughput
        throughput = round(
            total_selected / max(elapsed_secs, 0.1), 1)

        # Space saved
        space_saved = max(total_source_size - total_size, 0)

        # Enriched stats computed from all_roms
        top_series_list = []
        decades_dict = {}
        system_rankings = []
        notable_finds = {}

        if all_roms:
            titles = [r.base_title for r in all_roms if r.base_title]
            series = Counter()
            for t in titles:
                words = t.split()
                key = words[0] if words else t
                for i in range(1, min(3, len(words))):
                    if words[i].isdigit() or words[i] in ('-', '&'):
                        break
                    key = ' '.join(words[:i+1])
                series[key] += 1
            top_series = series.most_common(3)
            top_series_list = [
                {'name': s[0], 'count': s[1]}
                for s in top_series if s[1] > 1]
            if top_series and top_series[0][1] > 1:
                top3_parts = [
                    f"{s[0]} ({s[1]})" for s in top_series
                    if s[1] > 1]
                tidbits.append(
                    f"\u2655 Top series: {', '.join(top3_parts)}")

            regions = Counter(
                r.region for r in all_roms if r.region)
            top_regions = regions.most_common(3)
            if top_regions:
                parts = [f"{reg} ({cnt})" for reg, cnt in top_regions]
                tidbits.append(
                    f"\u2691 Regions: {', '.join(parts)}")

            years = [r.year for r in all_roms if r.year > 0]
            if years:
                oldest = min(years)
                newest = max(years)
                if oldest == newest:
                    tidbits.append(f"\u2605 All from {oldest}")
                else:
                    tidbits.append(
                        f"\u2605 Spanning {oldest}\u2013{newest}")

            if len(years) > 50:
                decades = Counter(
                    (y // 10) * 10 for y in years)
                decades_dict = {str(k): v for k, v in decades.items()}
                peak = decades.most_common(1)[0]
                tidbits.append(
                    f"\u266B Peak decade: {peak[0]}s "
                    f"({peak[1]} titles)")

            translations = sum(
                1 for r in all_roms if r.is_translation)
            if translations:
                tidbits.append(
                    f"\u2694 Fan translations: {translations}")

            multi_disc = sum(
                1 for r in all_roms if r.disc_number > 1)
            if multi_disc:
                tidbits.append(
                    f"\u25CE Multi-disc: {multi_disc} additional discs")

            unique_titles = len(set(
                r.base_title for r in all_roms if r.base_title))
            if unique_titles and unique_titles != len(all_roms):
                tidbits.append(
                    f"\u25A3 Unique titles: {unique_titles:,}")

            if total_selected > 0:
                avg = total_size // total_selected
                tidbits.append(
                    f"\u2394 Avg ROM size: {format_size(avg)}")

            # Notable finds
            common_regions = {'USA', 'Europe', 'Japan', 'World',
                              'Unknown'}
            rare_regions = {
                r.region for r in all_roms
                if r.region and r.region not in common_regions}
            if rare_regions:
                notable_finds['rare_regions'] = sorted(rare_regions)

            if rom_file_sizes:
                sorted_by_size = sorted(
                    rom_file_sizes.items(), key=lambda x: x[1])
                notable_finds['smallest_rom'] = list(sorted_by_size[0])
                notable_finds['largest_rom'] = list(sorted_by_size[-1])

        # System rankings: size and selectivity per system
        for sys_code in sorted(all_systems):
            sys_data = self._last_results.get(sys_code, {})
            sel_urls = sys_data.get('selected_urls', [])
            sel_local = sys_data.get('selected_local', [])
            all_urls_sys = sys_data.get('urls', [])
            all_local_sys = sys_data.get('local_files', [])
            total_sys = len(all_urls_sys) + len(all_local_sys)
            selected_sys = len(sel_urls) + len(sel_local)
            sys_sizes = sys_data.get('sizes', {})
            sys_sel_size = sum(sys_sizes.get(u, 0) for u in sel_urls)
            for fpath in sel_local:
                try:
                    sys_sel_size += Path(fpath).stat().st_size
                except OSError:
                    pass
            selectivity = (round(selected_sys / max(total_sys, 1), 3)
                           if total_sys else 0)
            system_rankings.append({
                'system': _display_name(sys_code),
                'selected': selected_sys,
                'total': total_sys,
                'size': sys_sel_size,
                'selectivity': selectivity,
            })

        # Filter impact: aggregate breakdowns across all systems
        filter_impact = {}
        breakdowns = self._run_breakdowns
        for breakdown in breakdowns.values():
            for reason, count in breakdown.items():
                filter_impact[reason] = (
                    filter_impact.get(reason, 0) + count)
        filter_impact_sorted = dict(sorted(
            filter_impact.items(), key=lambda x: x[1], reverse=True))

        self._push_event('fanfare', {
            'systems': total_systems,
            'selected': total_selected,
            'excluded': total_excluded,
            'total_size': format_size(total_size),
            'elapsed': elapsed_str,
            'tidbits': tidbits,
            'throughput': throughput,
            'space_saved': format_size(space_saved),
            'space_saved_bytes': space_saved,
            'top_series': top_series_list,
            'decade_breakdown': decades_dict,
            'system_rankings': system_rankings,
            'filter_impact': filter_impact_sorted,
            'notable_finds': notable_finds,
        })

    def _download_batch(self, downloads, parallel, system):
        """Download files using httpx with ThreadPoolExecutor."""
        import httpx  # pylint: disable=import-outside-toplevel
        logger.debug("Downloading {} files for {} (parallel={})",
                     len(downloads), system, parallel)

        total = len(downloads)
        fail_count = 0
        display = _display_name(system)

        client = httpx.Client(
            follow_redirects=True,
            timeout=60,
            headers={'User-Agent': 'Mozilla/5.0 (compatible; Retro-Refiner/1.0)'},
        )

        done_set = set()

        def _download_one(idx_url_path):
            idx, (url, dest_path) = idx_url_path
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                stream_download(client, url, dest_path)
                done_set.add(idx)
                return idx, None
            except Exception as exc:  # pylint: disable=broad-except
                return idx, str(exc)

        dl_t0 = time.monotonic()
        from concurrent.futures import ThreadPoolExecutor  # pylint: disable=import-outside-toplevel

        try:
            with ThreadPoolExecutor(max_workers=parallel) as executor:
                futures = {
                    executor.submit(_download_one, (i, d)): i
                    for i, d in enumerate(downloads)
                }

                # Progress polling in main thread
                while not all(f.done() for f in futures):
                    if not self._running:
                        executor.shutdown(wait=False, cancel_futures=True)
                        break
                    completed = len(done_set)
                    elapsed = time.monotonic() - dl_t0
                    eta = self._eta_str(elapsed, completed, total)
                    rate = completed / max(elapsed, 0.1)
                    elapsed_s = self._elapsed_str(elapsed)
                    msg = (f'{self._step_prefix(3)}'
                           f'{display}: {completed}/{total} '
                           f'\u2502 {rate:.1f} files/s '
                           f'\u2502 {elapsed_s}'
                           f'{eta}')
                    self._push_event('progress', {
                        'phase': 'download',
                        'message': msg,
                        'current': completed,
                        'total': total,
                    })
                    time.sleep(1.0)

                # Collect errors
                for future in futures:
                    _idx, error = future.result()
                    if error:
                        fail_count += 1
        finally:
            client.close()

        if fail_count:
            self._push_event('log', {
                'text': f'  {display}: {fail_count} download(s) '
                        f'failed\n',
                'className': 'log-warning',
            })
        self._push_event('log', {
            'text': f'  {display}: downloaded {total - fail_count}'
                    f'/{total} files\n',
        })

    def _url_to_filename(self, url):
        """Extract filename from URL."""
        return urllib.parse.unquote(
            url.split('?')[0].split('#')[0].split('/')[-1])

    def _download_to_destination(self, downloads, parallel, system):
        """Download files to destination with temp file safety.

        Args:
            downloads: List of (url, tmp_path, final_path) tuples.
            parallel: Max parallel downloads.
            system: System code for logging.
        """
        batch = [(url, tmp_path) for url, tmp_path, _ in downloads]
        self._download_batch(batch, parallel, system)

        # Rename completed downloads from .rrdownload to final name
        for _url, tmp_path, final_path in downloads:
            if tmp_path.exists():
                tmp_path.rename(final_path)

    def _commit_system(self, system, config, dest_dir):
        """Commit results for a single system."""
        result = self._last_results.get(system, {})
        selected_urls = list(result.get('selected_urls', []))
        local_files = list(result.get('selected_local', []))

        # Apply manual picker overrides
        manual = self._manual_selections.get(system, {})
        if manual:
            selected_urls = [u for u in selected_urls
                             if manual.get(self._url_to_filename(u), True)]
            local_files = [f for f in local_files
                           if manual.get(Path(f).name, True)]

        if not selected_urls and not local_files:
            return

        # Remove mode only affects local files — no destination needed
        if config.output.local_file_action == 'remove':
            return

        flat = config.output.flat
        target_dir = dest_dir if flat else dest_dir / system
        target_dir.mkdir(parents=True, exist_ok=True)

        # Build expected file set with sizes
        expected = {}
        sizes = result.get('sizes', {})
        for url in selected_urls:
            fname = self._url_to_filename(url)
            expected[fname] = sizes.get(url, 0)
        for filepath in local_files:
            p_file = Path(filepath)
            if p_file.exists():
                expected[p_file.name] = p_file.stat().st_size

        # Phase 1: Validate destination
        logger.debug("{}: validating destination ({} expected files)",
                     system, len(expected))
        skip_files = set()
        if (config.output.validate_destination
                and config.output.local_file_action != 'remove'):
            from retro_refiner.transfer import validate_destination  # pylint: disable=import-outside-toplevel
            validation = validate_destination(
                dest_dir, system, flat, expected,
                crc_check=config.output.crc_validation)
            skip_files = {fn for fn, status in validation.items()
                          if status == 'valid'}
            invalid_files = {fn for fn, status in validation.items()
                             if status == 'invalid'}
            if skip_files:
                self._push_event('log', {
                    'text': f'  {_display_name(system)}: '
                            f'{len(skip_files)} files already in '
                            f'destination, skipping\n',
                })
            # Delete invalid files so they get re-downloaded/copied
            for fname in invalid_files:
                (target_dir / fname).unlink(missing_ok=True)

        # Phase 2: Download remote files directly to destination
        downloads = []
        for url in selected_urls:
            fname = self._url_to_filename(url)
            if fname in skip_files:
                continue
            dest_path = target_dir / fname
            tmp_path = target_dir / (fname + '.rrdownload')
            downloads.append((url, tmp_path, dest_path))

        logger.debug("{}: {} files already valid, {} to download",
                     system, len(skip_files), len(downloads))

        if downloads:
            self._push_event('log', {
                'text': f'  {_display_name(system)}: downloading '
                        f'{len(downloads)} files...\n',
            })
            self._download_to_destination(
                downloads, config.network.parallel, system)

        # Phase 3: Transfer local files
        display = _display_name(system)
        if local_files and config.output.local_file_action != 'remove':
            from retro_refiner.transfer import transfer_files  # pylint: disable=import-outside-toplevel
            files_to_transfer = [Path(f) for f in local_files
                                 if Path(f).name not in skip_files]
            if files_to_transfer:
                total_local = len(files_to_transfer)
                self._push_event('log', {
                    'text': f'  {display}: transferring '
                            f'{total_local} local files...\n',
                })

                def _on_local_progress(evt, _sys=display):
                    self._push_event('progress', {
                        'phase': 'transfer',
                        'message': f'{_sys}: {evt.current}'
                                   f'/{evt.total}',
                        'current': evt.current,
                        'total': evt.total,
                    })

                stats = transfer_files(
                    files_to_transfer, dest_dir, system=system,
                    mode=config.output.local_file_action,
                    flat=flat,
                    on_progress=_on_local_progress)
                logger.debug("{}: transferred {} local files",
                             system, stats["transferred"])
                self._push_event('log', {
                    'text': f'  {display}: '
                            f'transferred {stats["transferred"]}, '
                            f'skipped {stats["skipped"]}, '
                            f'errors {stats["errors"]}\n',
                })

        # Phase 4: Clean destination
        if (config.output.clean_destination
                and config.output.local_file_action != 'remove'):
            from retro_refiner.transfer import clean_destination  # pylint: disable=import-outside-toplevel
            keep = set(expected.keys())
            clean_stats = clean_destination(
                dest_dir, system, flat, keep)
            logger.debug("{}: cleaned {} files from destination",
                         system, clean_stats['removed'])
            if clean_stats['removed']:
                self._push_event('log', {
                    'text': f'  {_display_name(system)}: '
                            f'cleaned {clean_stats["removed"]} '
                            f'files from destination\n',
                })

    def _run_dedup(self, priority_str, all_sizes):
        """Cross-system dedup: keep best version per game title.

        Systems listed earlier in priority_str claim titles first.
        Later systems have duplicates removed from their selected sets.
        """
        from retro_refiner.dat import normalize_title_for_dedupe  # pylint: disable=import-outside-toplevel
        from retro_refiner.filter import parse_rom_filename  # pylint: disable=import-outside-toplevel
        from retro_refiner.network import get_filename_from_url  # pylint: disable=import-outside-toplevel

        priority = [s.strip() for s in priority_str.split(',') if s.strip()]
        if not priority:
            return

        # Build title -> system map for all selected ROMs
        system_titles = {}  # system -> {norm_title: [urls/paths]}
        for system, data in self._last_results.items():
            titles = {}
            for url in data.get('selected_urls', []):
                fname = get_filename_from_url(url)
                try:
                    info = parse_rom_filename(fname)
                    norm = normalize_title_for_dedupe(info.base_title)
                    titles.setdefault(norm, []).append(('url', url))
                except Exception:  # pylint: disable=broad-except
                    pass
            for fpath in data.get('selected_local', []):
                try:
                    info = parse_rom_filename(Path(fpath).name)
                    norm = normalize_title_for_dedupe(info.base_title)
                    titles.setdefault(norm, []).append(('local', fpath))
                except Exception:  # pylint: disable=broad-except
                    pass
            system_titles[system] = titles

        # Walk systems in priority order — earlier systems claim titles
        claimed = set()
        # Process priority systems first, then remaining alphabetically
        all_systems = list(self._last_results.keys())
        ordered = [s for s in priority if s in all_systems]
        ordered += [s for s in sorted(all_systems) if s not in ordered]

        total_deduped = 0
        for system in ordered:
            titles = system_titles.get(system, {})
            dupes_in_system = set(titles.keys()) & claimed
            if not dupes_in_system:
                # No dupes — claim all titles
                claimed |= set(titles.keys())
                continue

            # Remove duplicate titles from this system's selections
            removed_urls = set()
            removed_local = set()
            for norm_title in dupes_in_system:
                for entry_type, entry in titles[norm_title]:
                    if entry_type == 'url':
                        removed_urls.add(entry)
                    else:
                        removed_local.add(entry)

            # Update _last_results
            data = self._last_results[system]
            old_url_count = len(data.get('selected_urls', []))
            old_local_count = len(data.get('selected_local', []))
            if removed_urls:
                data['selected_urls'] = [
                    u for u in data.get('selected_urls', [])
                    if u not in removed_urls]
            if removed_local:
                data['selected_local'] = [
                    f for f in data.get('selected_local', [])
                    if f not in removed_local]

            removed_count = len(removed_urls) + len(removed_local)
            total_deduped += removed_count

            # Claim non-dupe titles
            claimed |= set(titles.keys()) - dupes_in_system

            # Log dedup results for this system
            display = _display_name(system)
            self._push_event('log', {
                'text': f'  Dedup: {display} — removed '
                        f'{removed_count} cross-platform '
                        f'duplicates\n',
                'className': 'log-info',
            })

            # Update card with new counts
            new_selected = (len(data.get('selected_urls', []))
                            + len(data.get('selected_local', [])))
            new_size = sum(
                all_sizes.get(u, 0)
                for u in data.get('selected_urls', []))
            for fpath in data.get('selected_local', []):
                try:
                    new_size += Path(fpath).stat().st_size
                except OSError:
                    pass
            self._push_event('card', {
                'system': system,
                'state': 'complete',
                'selected_count': new_selected,
                'excluded_count': (old_url_count + old_local_count
                                   - new_selected),
                'selected_size': new_size,
                'source_count': old_url_count + old_local_count,
                'source_size': 0,
                'filter_breakdown': {'cross-platform dupe': removed_count},
            })

        if total_deduped > 0:
            self._push_event('log', {
                'text': f'\n  Dedup total: {total_deduped} '
                        f'cross-platform duplicates removed\n',
                'className': 'log-success',
            })

    def _apply_budget_filters(self, config, all_systems, all_sizes):
        """Apply --top and --size budget filters after filtering."""
        if config.budget.top or config.budget.size:
            self._apply_ratings_budget(config, all_systems, all_sizes)

    def _apply_ratings_budget(self, config, all_systems, all_sizes):
        """Load ratings and apply --top / --size budget filters."""
        from retro_refiner.ratings import (  # pylint: disable=import-outside-toplevel
            build_ratings_cache, download_launchbox_data,
            apply_top_n_filter, apply_size_budget,
            boost_exclusive_ratings,
        )
        from retro_refiner.filter import parse_rom_filename  # pylint: disable=import-outside-toplevel

        dat_dir = Path(config.advanced.dat_dir or './dat_files')
        dat_dir.mkdir(parents=True, exist_ok=True)

        self._push_event('log', {
            'text': '\nLoading ratings data...\n',
        })

        # Download LaunchBox data if not cached
        xml_path = download_launchbox_data(
            dat_dir,
            on_progress=lambda dl, total: self._push_event('progress', {
                'phase': 'ratings',
                'message': f'Downloading ratings ({dl // 1024 // 1024}MB)',
                'current': dl,
                'total': total,
            }),
        )

        if not xml_path:
            self._push_event('log', {
                'text': '  No ratings data available '
                        '(LaunchBox download failed)\n',
                'className': 'log-warning',
            })
            return

        cache_path = dat_dir / 'launchbox' / 'ratings_cache.json'
        ratings = build_ratings_cache(
            xml_path, cache_path=cache_path,
            on_progress=lambda br, total, gc: self._push_event('progress', {
                'phase': 'ratings',
                'message': f'Parsing ratings ({gc} games)',
                'current': br,
                'total': total,
            }),
        )

        if not ratings:
            self._push_event('log', {
                'text': '  No ratings found in data\n',
                'className': 'log-warning',
            })
            return

        total_rated = sum(len(v) for v in ratings.values())
        self._push_event('log', {
            'text': f'  {total_rated} games rated\n',
        })

        # Boost exclusives if configured
        if config.budget.prefer_exclusives:
            ratings = boost_exclusive_ratings(
                ratings, boost=config.budget.prefer_exclusives)

        # Apply --top and --size per system
        for system in sorted(all_systems):
            if not self._running:
                return
            sys_data = self._last_results.get(system, {})
            sys_urls = sys_data.get('selected_urls', [])
            if not sys_urls:
                continue

            sys_ratings = ratings.get(system, {})
            # Arcade systems (teknoparrot, fbneo) fall back to mame ratings
            if not sys_ratings and system in ('teknoparrot', 'fbneo', 'fba'):
                sys_ratings = ratings.get('mame', {})
            if not sys_ratings:
                continue

            # Build lightweight RomInfo objects from URL filenames
            url_roms = []
            url_map = {}  # base_title -> url
            for url in sys_urls:
                filename = urllib.parse.unquote(
                    url.split('?')[0].split('#')[0].split('/')[-1])
                rom = parse_rom_filename(filename)
                url_roms.append(rom)
                url_map[id(rom)] = url

            if config.budget.top:
                before = len(url_roms)
                rated_count = sum(1 for r in url_roms
                                  if r.base_title in sys_ratings)
                url_roms = apply_top_n_filter(
                    url_roms, sys_ratings, config.budget.top,
                    include_unrated=config.budget.include_unrated,
                )
                after = len(url_roms)
                logger.debug("{}: top-N filter {} -> {} (rated {} of {})",
                             system, before, after, rated_count, before)
                if after < before:
                    self._push_event('log', {
                        'text': f'  {system.upper()}: top filter '
                                f'{before} -> {after}\n',
                    })

            if config.budget.size:
                budget_bytes = _parse_size_string(config.budget.size)
                if budget_bytes and budget_bytes > 0:
                    # Build size lookup keyed by filename
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
                        self._push_event('log', {
                            'text': f'  {system.upper()}: size budget '
                                    f'{before} -> {after}\n',
                        })

            # Rebuild selected URLs from surviving roms
            new_urls = [url_map[id(rom)] for rom in url_roms]
            if len(new_urls) != len(sys_urls):
                sys_data['selected_urls'] = new_urls
                new_size = sum(all_sizes.get(u, 0) for u in new_urls)
                self._push_event('card', {
                    'system': system,
                    'state': 'complete',
                    'selected_count': len(new_urls),
                    'excluded_count': len(sys_urls) - len(new_urls),
                    'selected_size': new_size,
                    'source_count': len(sys_urls),
                    'source_size': 0,
                    'filter_breakdown': {},
                })

    def get_system_roms(self, system: str) -> str:
        """Get ROM list for a system as JSON.

        Returns list of {filename, url, size, region, status, reason} dicts.
        Uses cached picker state if available (preserves manual edits).
        """
        # Return cached picker state if it exists (preserves manual edits)
        if system in self._picker_state:
            return orjson.dumps(self._picker_state[system]).decode()

        from retro_refiner.filter import parse_rom_filename  # pylint: disable=import-outside-toplevel

        roms = []
        result = self._last_results.get(system, {})
        selected_urls = set(result.get('selected_urls', []))
        selected_local = set(result.get('selected_local', []))

        for url in result.get('urls', []):
            filename = urllib.parse.unquote(url.split('/')[-1])
            size = result.get('sizes', {}).get(url, 0)
            rom_info = parse_rom_filename(filename)
            is_selected = url in selected_urls
            reason = ''
            if not is_selected:
                reason = _get_exclusion_reason(rom_info)
                if not reason:
                    reason = 'cross-platform duplicate'
            roms.append({
                'filename': filename,
                'url': url,
                'size': size,
                'region': rom_info.region,
                'status': 'selected' if is_selected else 'excluded',
                'reason': reason,
            })
        for filepath in result.get('local_files', []):
            filename = Path(filepath).name
            try:
                size = Path(filepath).stat().st_size
            except OSError:
                size = 0
            rom_info = parse_rom_filename(filename)
            is_selected = str(filepath) in selected_local
            reason = ''
            if not is_selected:
                reason = _get_exclusion_reason(rom_info)
                if not reason:
                    reason = 'cross-platform duplicate'
            roms.append({
                'filename': filename,
                'url': str(filepath),
                'size': size,
                'region': rom_info.region,
                'status': 'selected' if is_selected else 'excluded',
                'reason': reason,
            })

        # Cache for persistence across picker reopens
        self._picker_state[system] = roms
        return orjson.dumps(roms).decode()

    def get_all_roms(self) -> str:
        """Get all ROMs across all systems as JSON.

        Returns list of dicts with a system field added.
        """
        all_roms = []
        for system in sorted(self._last_results):
            roms = orjson.loads(self.get_system_roms(system))
            for rom in roms:
                rom['system'] = system
                all_roms.append(rom)
        return orjson.dumps(all_roms).decode()

    def update_rom_selection(self, system: str, selections_json: str):
        """Update which ROMs are selected for a system.

        selections_json is a JSON list of {filename, selected} dicts.
        """
        selections = orjson.loads(selections_json)
        if system not in self._manual_selections:
            self._manual_selections[system] = {}
        for sel in selections:
            self._manual_selections[system][sel['filename']] = sel['selected']
        # Update cached picker state to match
        if system in self._picker_state:
            sel_map = {s['filename']: s['selected'] for s in selections}
            for rom in self._picker_state[system]:
                if rom['filename'] in sel_map:
                    rom['status'] = ('selected' if sel_map[rom['filename']]
                                     else 'excluded')

    def reset_picker(self, system: str):
        """Reset picker state to original filter results for a system.

        Pass empty string to reset all systems.
        """
        if system:
            self._picker_state.pop(system, None)
            self._manual_selections.pop(system, None)
        else:
            self._picker_state.clear()
            self._manual_selections.clear()

    @staticmethod
    def _eta_str(elapsed, completed, total):
        """Compute ETA string like ' · ~45s remaining'."""
        if completed <= 0 or total <= 0:
            return ''
        remaining = total - completed
        rate = completed / max(elapsed, 0.1)
        eta_secs = int(remaining / rate)
        if eta_secs < 60:
            return f' \u2502 ~{eta_secs}s left'
        mins, secs = divmod(eta_secs, 60)
        return f' \u2502 ~{mins}m {secs:02d}s left'

    @staticmethod
    def _elapsed_str(elapsed):
        """Format elapsed seconds as compact string."""
        secs = int(elapsed)
        if secs < 60:
            return f'{secs}s'
        mins, secs = divmod(secs, 60)
        return f'{mins}m {secs:02d}s'

    def _push_event(self, event_type: str, data: dict):
        """Push an event to the JavaScript frontend."""
        logger.debug("Event: {} | {}",
                     event_type,
                     {k: v for k, v in data.items()
                      if k != 'excluded_roms'})
        if self._window:
            payload = orjson.dumps({'type': event_type, 'data': data}).decode()
            self._window.evaluate_js(
                f'window.handlePythonEvent({payload})'
            )

    def open_folder(self, path: str):
        """Open a folder in the system file explorer."""
        import subprocess  # pylint: disable=import-outside-toplevel
        import sys as _sys  # pylint: disable=import-outside-toplevel
        folder = Path(path)
        if not folder.exists():
            folder.mkdir(parents=True, exist_ok=True)
        if _sys.platform == 'win32':
            subprocess.Popen(['explorer', str(folder)])  # pylint: disable=consider-using-with
        elif _sys.platform == 'darwin':
            subprocess.Popen(['open', str(folder)])  # pylint: disable=consider-using-with
        else:
            subprocess.Popen(['xdg-open', str(folder)])  # pylint: disable=consider-using-with

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


def _get_exclusion_reason(rom_info):
    """Return a human-readable reason why a ROM was excluded."""
    reasons = []
    if rom_info.is_bios:
        reasons.append('BIOS')
    if rom_info.is_pirate:
        reasons.append('Pirate')
    if rom_info.is_homebrew:
        reasons.append('Homebrew')
    if rom_info.is_unlicensed:
        reasons.append('Unlicensed')
    if rom_info.is_beta:
        reasons.append('Beta')
    if rom_info.is_demo:
        reasons.append('Demo')
    if rom_info.is_promo:
        reasons.append('Promo')
    if rom_info.is_sample:
        reasons.append('Sample')
    if rom_info.is_proto:
        reasons.append('Prototype')
    if rom_info.is_rerelease:
        reasons.append('Re-release')
    if rom_info.is_compilation:
        reasons.append('Compilation')
    if rom_info.is_lock_on:
        reasons.append('Lock-on')
    if rom_info.has_hacks:
        reasons.append('Hack')
    if reasons:
        return ', '.join(reasons)
    return 'Not best version'


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


def _float_or_none(value):
    """Convert value to float or None."""
    if value is None or value == '':
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _parse_size_string(size_str):
    """Parse a size string like '10GB', '500MB' into bytes.

    Thin wrapper around ``network.parse_budget_size`` kept for backward
    compatibility with tests that import from this module.
    """
    from retro_refiner.network import parse_budget_size  # pylint: disable=import-outside-toplevel
    return parse_budget_size(size_str)

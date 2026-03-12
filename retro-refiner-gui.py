#!/usr/bin/env python3
"""
Retro-Refiner GUI - Tkinter-based graphical interface for retro-refiner.py.

Zero-dependency GUI wrapper that provides a tabbed settings interface and
real-time output display. Runs retro-refiner's main() in a background thread
while keeping the GUI responsive.
"""

import importlib.util
import queue
import subprocess
import sys
import threading
import tkinter as tk
import tkinter.simpledialog  # pylint: disable=unused-import  # accessed via tk.simpledialog
from tkinter import ttk, filedialog, messagebox
from pathlib import Path

# Import retro-refiner module (same pattern as tests/test_selection.py)
_spec = importlib.util.spec_from_file_location(
    "retro_refiner", Path(__file__).parent / "retro-refiner.py"
)
_module = importlib.util.module_from_spec(_spec)

# Prevent the module from running main() during import
_original_name = _module.__name__
_module.__name__ = "retro_refiner"
_spec.loader.exec_module(_module)

# Disable ANSI colors since GUI captures plain text
_module.Style.disable()


# Platform-specific monospace font
if sys.platform == 'win32':
    MONO_FONT = ('Consolas', 10)
    MONO_FONT_SMALL = ('Consolas', 9)
elif sys.platform == 'darwin':
    MONO_FONT = ('Monaco', 11)
    MONO_FONT_SMALL = ('Monaco', 10)
else:
    MONO_FONT = ('Courier', 10)
    MONO_FONT_SMALL = ('Courier', 9)


# ── Theme definitions ─────────────────────────────────────────────

DARK_THEME = {
    'output_bg': '#1e1e1e',
    'output_fg': '#d4d4d4',
    'output_select_bg': '#264f78',
    'output_select_fg': '#ffffff',
    'output_insert': '#d4d4d4',
    'listbox_bg': '#252526',
    'listbox_fg': '#d4d4d4',
    'listbox_select_bg': '#094771',
    'listbox_select_fg': '#ffffff',
    'canvas_bg': '#252526',
    'window_bg': '#1e1e1e',
    'frame_bg': '#2d2d2d',
    'label_fg': '#cccccc',
    'entry_bg': '#3c3c3c',
    'entry_fg': '#d4d4d4',
    'button_bg': '#3c3c3c',
    'button_fg': '#d4d4d4',
    'button_hover_bg': '#505050',
    'button_pressed_bg': '#444444',
    'check_bg': '#3c3c3c',
    'check_hover_bg': '#454545',
    'tab_bg': '#2d2d2d',
    'tab_selected_bg': '#1e1e1e',
    'tab_hover_bg': '#383838',
    'border_color': '#555555',
    'focus_color': '#0078d4',
    'trough_color': '#2d2d2d',
    'combo_hover_bg': '#505050',
    'ttk_theme_base': 'clam',
}

LIGHT_THEME = {
    'output_bg': '#ffffff',
    'output_fg': '#1e1e1e',
    'output_select_bg': '#0078d4',
    'output_select_fg': '#ffffff',
    'output_insert': '#1e1e1e',
    'listbox_bg': '#ffffff',
    'listbox_fg': '#1e1e1e',
    'listbox_select_bg': '#0078d4',
    'listbox_select_fg': '#ffffff',
    'canvas_bg': '#f5f5f5',
    'window_bg': '#f0f0f0',
    'frame_bg': '#f0f0f0',
    'label_fg': '#1e1e1e',
    'entry_bg': '#ffffff',
    'entry_fg': '#1e1e1e',
    'button_bg': '#e1e1e1',
    'button_fg': '#1e1e1e',
    'button_hover_bg': '#c8c8c8',
    'button_pressed_bg': '#b0b0b0',
    'check_bg': '#f0f0f0',
    'check_hover_bg': '#e0e0e0',
    'tab_bg': '#e1e1e1',
    'tab_selected_bg': '#f0f0f0',
    'tab_hover_bg': '#d0d0d0',
    'border_color': '#aaaaaa',
    'focus_color': '#0078d4',
    'trough_color': '#e0e0e0',
    'combo_hover_bg': '#c8c8c8',
    'ttk_theme_base': 'clam',
}


def _detect_system_dark_mode():
    """Detect whether the OS is using dark mode. Returns True for dark."""
    try:
        if sys.platform == 'win32':
            import winreg  # pylint: disable=import-outside-toplevel
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
            )
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            winreg.CloseKey(key)
            return value == 0  # 0 = dark, 1 = light
        if sys.platform == 'darwin':
            result = subprocess.run(
                ['defaults', 'read', '-g', 'AppleInterfaceStyle'],
                capture_output=True, text=True, check=False
            )
            return result.stdout.strip().lower() == 'dark'
        # Linux: try gsettings (GNOME/GTK)
        result = subprocess.run(
            ['gsettings', 'get', 'org.gnome.desktop.interface', 'color-scheme'],
            capture_output=True, text=True, check=False
        )
        if result.returncode == 0:
            return 'dark' in result.stdout.lower()
        # Fallback: try gtk-theme
        result = subprocess.run(
            ['gsettings', 'get', 'org.gnome.desktop.interface', 'gtk-theme'],
            capture_output=True, text=True, check=False
        )
        return 'dark' in result.stdout.lower()
    except Exception:  # pylint: disable=broad-except
        return True  # Default to dark on detection failure


class QueueWriter:
    """File-like object that pushes writes to a queue for GUI consumption."""

    def __init__(self, out_queue):
        self._queue = out_queue
        self._buffer = ""

    def write(self, text):
        """Write text to the queue, splitting on carriage returns."""
        if not text:
            return
        # Split on \r to support progress bar line replacement
        parts = text.split('\r')
        for i, part in enumerate(parts):
            if i > 0:
                # \r means replace current line
                self._queue.put(('replace', part))
            else:
                self._queue.put(('append', part))

    def flush(self):
        """No-op flush for file-like interface compatibility."""

    def isatty(self):
        """Return False to trigger non-TTY mode in retro-refiner."""
        return False

    @property
    def encoding(self):
        """Return UTF-8 encoding for file-like interface compatibility."""
        return 'utf-8'

    def fileno(self):
        """Raise OSError since QueueWriter has no file descriptor."""
        raise OSError("QueueWriter has no file descriptor")


class SystemsDialog(tk.Toplevel):
    """Dialog for selecting systems from the full KNOWN_SYSTEMS list."""

    def __init__(self, parent, current_value, is_dark=True):
        super().__init__(parent)
        self.title("Select Systems")
        self.geometry("400x500")
        self.resizable(True, True)
        self.transient(parent)
        self.grab_set()

        self.result = None
        current_systems = set()
        if current_value.strip():
            current_systems = {s.strip().lower() for s in current_value.split(',')}

        theme = DARK_THEME if is_dark else LIGHT_THEME

        # Search entry
        search_frame = ttk.Frame(self)
        search_frame.pack(fill=tk.X, padx=8, pady=(8, 4))
        ttk.Label(search_frame, text="Filter:").pack(side=tk.LEFT)
        self._search_var = tk.StringVar()
        self._search_var.trace_add('write', self._filter_list)
        search_entry = ttk.Entry(search_frame, textvariable=self._search_var)
        search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 0))

        # Checkbutton list in scrollable frame
        list_frame = ttk.Frame(self)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        canvas = tk.Canvas(list_frame, bg=theme['canvas_bg'], highlightthickness=0)
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=canvas.yview)
        self._inner_frame = ttk.Frame(canvas)

        self._inner_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        canvas.create_window((0, 0), window=self._inner_frame, anchor=tk.NW)
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Build checkbuttons
        self._check_vars = {}
        self._check_widgets = {}
        all_systems = sorted(set(_module.KNOWN_SYSTEMS))
        for system in all_systems:
            var = tk.BooleanVar(value=system.lower() in current_systems)
            self._check_vars[system] = var
            cb = ttk.Checkbutton(self._inner_frame, text=system, variable=var)
            cb.pack(anchor=tk.W)
            self._check_widgets[system] = cb

        # Buttons
        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill=tk.X, padx=8, pady=8)
        ttk.Button(btn_frame, text="Select All", command=self._select_all).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="Clear All", command=self._clear_all).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="OK", command=self._ok).pack(side=tk.RIGHT, padx=2)
        ttk.Button(btn_frame, text="Cancel", command=self.destroy).pack(side=tk.RIGHT, padx=2)

    def _filter_list(self, *_args):
        search = self._search_var.get().lower()
        for system, cb in self._check_widgets.items():
            if search in system.lower():
                cb.pack(anchor=tk.W)
            else:
                cb.pack_forget()

    def _select_all(self):
        for var in self._check_vars.values():
            var.set(True)

    def _clear_all(self):
        for var in self._check_vars.values():
            var.set(False)

    def _ok(self):
        selected = [s for s, v in sorted(self._check_vars.items()) if v.get()]
        self.result = ','.join(selected)
        self.destroy()


class RetroRefinerGUI:
    """Main GUI application for Retro-Refiner."""

    def __init__(self, root):
        self.root = root
        self.root.title("Retro-Refiner")
        self.root.geometry("920x720")
        self.root.minsize(700, 500)

        self._running = False
        self._worker_thread = None
        self._output_queue = queue.Queue()

        # Track all widget variables for argv construction
        self._vars = {}
        self._listbox_data = {}  # name -> list of strings

        # Listbox widgets (initialized in tab builders)
        self._source_listbox = None
        self._include_listbox = None
        self._exclude_listbox = None
        self._dedup_pc_listbox = None

        # Theme state
        self._is_dark = _detect_system_dark_mode()
        self._listboxes = []  # All Listbox widgets for theme updates
        self._canvases = []   # All Canvas widgets for theme updates

        self._build_ui()
        self._apply_theme()
        self._poll_queue()

    def _build_ui(self):
        """Build the complete UI layout."""
        # Main container
        main_pane = ttk.PanedWindow(self.root, orient=tk.VERTICAL)
        main_pane.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

        # Top: tabbed settings
        notebook_frame = ttk.Frame(main_pane)
        main_pane.add(notebook_frame, weight=1)

        self._notebook = ttk.Notebook(notebook_frame)
        self._notebook.pack(fill=tk.BOTH, expand=True)

        self._create_sources_tab()
        self._create_filtering_tab()
        self._create_region_tab()
        self._create_output_tab()
        self._create_network_tab()
        self._create_advanced_tab()

        # Bottom: output + controls
        bottom_frame = ttk.Frame(main_pane)
        main_pane.add(bottom_frame, weight=2)

        # Progress bar
        self._progress_var = tk.DoubleVar(value=0)
        self._progress_label = tk.StringVar(value="")
        prog_frame = ttk.Frame(bottom_frame)
        prog_frame.pack(fill=tk.X, pady=(0, 4))
        self._progress_bar = ttk.Progressbar(
            prog_frame, variable=self._progress_var, maximum=100
        )
        self._progress_bar.pack(fill=tk.X, side=tk.LEFT, expand=True)
        ttk.Label(prog_frame, textvariable=self._progress_label, width=30).pack(
            side=tk.RIGHT, padx=(8, 0)
        )

        # Output text
        output_frame = ttk.Frame(bottom_frame)
        output_frame.pack(fill=tk.BOTH, expand=True)

        self._output_text = tk.Text(
            output_frame,
            font=MONO_FONT,
            wrap=tk.WORD,
            state=tk.DISABLED,
            height=12,
        )
        scrollbar = ttk.Scrollbar(
            output_frame, orient=tk.VERTICAL, command=self._output_text.yview
        )
        self._output_text.configure(yscrollcommand=scrollbar.set)
        self._output_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Control buttons
        ctrl_frame = ttk.Frame(bottom_frame)
        ctrl_frame.pack(fill=tk.X, pady=(6, 0))

        self._dry_btn = ttk.Button(
            ctrl_frame, text="Dry Run", command=self._run_dry
        )
        self._dry_btn.pack(side=tk.LEFT, padx=(0, 4))

        self._commit_btn = ttk.Button(
            ctrl_frame, text="Run (Commit)", command=self._run_commit
        )
        self._commit_btn.pack(side=tk.LEFT, padx=(0, 4))

        self._cancel_btn = ttk.Button(
            ctrl_frame, text="Cancel", command=self._cancel_run, state=tk.DISABLED
        )
        self._cancel_btn.pack(side=tk.LEFT, padx=(0, 4))

        ttk.Button(
            ctrl_frame, text="Clear Output", command=self._clear_output
        ).pack(side=tk.LEFT, padx=(0, 4))

        self._status_var = tk.StringVar(value="Ready")
        ttk.Label(ctrl_frame, textvariable=self._status_var).pack(
            side=tk.RIGHT, padx=(8, 0)
        )

        self._theme_btn = ttk.Button(
            ctrl_frame, text="Light", command=self._toggle_theme, width=6
        )
        self._theme_btn.pack(side=tk.RIGHT, padx=(0, 4))

    # ── Tab builders ──────────────────────────────────────────────────

    def _create_sources_tab(self):
        tab = ttk.Frame(self._notebook, padding=10)
        self._notebook.add(tab, text="Sources")

        # Source dirs/URLs
        ttk.Label(tab, text="Source directories / URLs:").grid(
            row=0, column=0, sticky=tk.W, pady=(0, 2)
        )
        src_frame = ttk.Frame(tab)
        src_frame.grid(row=1, column=0, columnspan=3, sticky=tk.NSEW, pady=(0, 8))

        self._source_listbox = tk.Listbox(src_frame, height=4, font=MONO_FONT_SMALL)
        self._source_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._listboxes.append(self._source_listbox)
        self._listbox_data['source'] = []

        src_btn_frame = ttk.Frame(src_frame)
        src_btn_frame.pack(side=tk.RIGHT, padx=(4, 0))
        ttk.Button(src_btn_frame, text="Add Folder", command=self._add_source_folder).pack(
            fill=tk.X, pady=1
        )
        ttk.Button(src_btn_frame, text="Add URL", command=self._add_source_url).pack(
            fill=tk.X, pady=1
        )
        ttk.Button(src_btn_frame, text="Remove", command=self._remove_source).pack(
            fill=tk.X, pady=1
        )

        # Destination
        row = 2
        ttk.Label(tab, text="Destination:").grid(row=row, column=0, sticky=tk.W, pady=2)
        self._vars['dest'] = tk.StringVar()
        ttk.Entry(tab, textvariable=self._vars['dest'], width=50).grid(
            row=row, column=1, sticky=tk.EW, padx=4, pady=2
        )
        ttk.Button(tab, text="Browse", command=lambda: self._browse_dir('dest')).grid(
            row=row, column=2, pady=2
        )

        # Systems
        row = 3
        ttk.Label(tab, text="Systems:").grid(row=row, column=0, sticky=tk.W, pady=2)
        sys_frame = ttk.Frame(tab)
        sys_frame.grid(row=row, column=1, columnspan=2, sticky=tk.EW, pady=2)
        self._vars['systems'] = tk.StringVar()
        ttk.Entry(sys_frame, textvariable=self._vars['systems']).pack(
            side=tk.LEFT, fill=tk.X, expand=True
        )
        ttk.Button(sys_frame, text="Browse...", command=self._browse_systems).pack(
            side=tk.RIGHT, padx=(4, 0)
        )

        # Config file
        row = 4
        ttk.Label(tab, text="Config file:").grid(row=row, column=0, sticky=tk.W, pady=2)
        self._vars['config'] = tk.StringVar()
        ttk.Entry(tab, textvariable=self._vars['config'], width=50).grid(
            row=row, column=1, sticky=tk.EW, padx=4, pady=2
        )
        ttk.Button(tab, text="Browse", command=lambda: self._browse_file(
            'config', [("YAML files", "*.yaml *.yml"), ("All files", "*.*")]
        )).grid(row=row, column=2, pady=2)

        # Checkbuttons row
        row = 5
        check_frame = ttk.Frame(tab)
        check_frame.grid(row=row, column=0, columnspan=3, sticky=tk.W, pady=(8, 2))

        self._vars['recursive'] = tk.BooleanVar()
        ttk.Checkbutton(check_frame, text="Recursive (-r)", variable=self._vars['recursive']).pack(
            side=tk.LEFT, padx=(0, 12)
        )

        self._vars['auto_detect'] = tk.BooleanVar()
        ttk.Checkbutton(check_frame, text="Auto-detect systems", variable=self._vars['auto_detect']).pack(
            side=tk.LEFT, padx=(0, 12)
        )

        # Max depth
        ttk.Label(check_frame, text="Max depth:").pack(side=tk.LEFT)
        self._vars['max_depth'] = tk.IntVar(value=3)
        ttk.Spinbox(check_frame, from_=1, to=10, width=4, textvariable=self._vars['max_depth']).pack(
            side=tk.LEFT, padx=(2, 0)
        )

        tab.columnconfigure(1, weight=1)

    def _create_filtering_tab(self):
        tab = ttk.Frame(self._notebook, padding=10)
        self._notebook.add(tab, text="Filtering")

        # Left column: checkbuttons
        left = ttk.LabelFrame(tab, text="Options", padding=6)
        left.grid(row=0, column=0, sticky=tk.NSEW, padx=(0, 6))

        self._vars['all'] = tk.BooleanVar()
        ttk.Checkbutton(left, text="Select all (no filter)", variable=self._vars['all']).pack(
            anchor=tk.W, pady=1
        )
        self._vars['exclude_protos'] = tk.BooleanVar()
        ttk.Checkbutton(left, text="Exclude protos", variable=self._vars['exclude_protos']).pack(
            anchor=tk.W, pady=1
        )
        self._vars['include_betas'] = tk.BooleanVar()
        ttk.Checkbutton(left, text="Include betas", variable=self._vars['include_betas']).pack(
            anchor=tk.W, pady=1
        )
        self._vars['include_unlicensed'] = tk.BooleanVar()
        ttk.Checkbutton(left, text="Include unlicensed", variable=self._vars['include_unlicensed']).pack(
            anchor=tk.W, pady=1
        )
        self._vars['english_only'] = tk.BooleanVar()
        ttk.Checkbutton(left, text="English only", variable=self._vars['english_only']).pack(
            anchor=tk.W, pady=1
        )
        self._vars['verbose'] = tk.BooleanVar()
        ttk.Checkbutton(left, text="Verbose output (-v)", variable=self._vars['verbose']).pack(
            anchor=tk.W, pady=1
        )

        # Budget fields
        budget_frame = ttk.LabelFrame(left, text="Budget / Limits", padding=4)
        budget_frame.pack(fill=tk.X, pady=(8, 0))

        for label, key in [("Top N:", "top"), ("Limit:", "limit"), ("Size:", "size"),
                           ("Prefer exclusives:", "prefer_exclusives")]:
            f = ttk.Frame(budget_frame)
            f.pack(fill=tk.X, pady=1)
            ttk.Label(f, text=label, width=18).pack(side=tk.LEFT)
            self._vars[key] = tk.StringVar()
            ttk.Entry(f, textvariable=self._vars[key], width=12).pack(side=tk.LEFT)

        self._vars['include_unrated'] = tk.BooleanVar()
        ttk.Checkbutton(budget_frame, text="Include unrated", variable=self._vars['include_unrated']).pack(
            anchor=tk.W, pady=1
        )

        # Year range
        year_frame = ttk.Frame(budget_frame)
        year_frame.pack(fill=tk.X, pady=1)
        ttk.Label(year_frame, text="Year range:").pack(side=tk.LEFT)
        self._vars['year_from'] = tk.StringVar()
        ttk.Entry(year_frame, textvariable=self._vars['year_from'], width=6).pack(side=tk.LEFT, padx=2)
        ttk.Label(year_frame, text="to").pack(side=tk.LEFT)
        self._vars['year_to'] = tk.StringVar()
        ttk.Entry(year_frame, textvariable=self._vars['year_to'], width=6).pack(side=tk.LEFT, padx=2)

        # Genres
        genre_frame = ttk.Frame(budget_frame)
        genre_frame.pack(fill=tk.X, pady=1)
        ttk.Label(genre_frame, text="Genres:", width=18).pack(side=tk.LEFT)
        self._vars['genres'] = tk.StringVar()
        ttk.Entry(genre_frame, textvariable=self._vars['genres']).pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Right column: include/exclude patterns
        right = ttk.Frame(tab)
        right.grid(row=0, column=1, sticky=tk.NSEW)

        # Include patterns
        ttk.Label(right, text="Include patterns:").pack(anchor=tk.W)
        inc_frame = ttk.Frame(right)
        inc_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 6))
        self._include_listbox = tk.Listbox(inc_frame, height=5, font=MONO_FONT_SMALL)
        self._include_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._listboxes.append(self._include_listbox)
        self._listbox_data['include'] = []
        inc_btns = ttk.Frame(inc_frame)
        inc_btns.pack(side=tk.RIGHT, padx=(4, 0))
        ttk.Button(inc_btns, text="Add", command=lambda: self._add_pattern('include')).pack(fill=tk.X, pady=1)
        ttk.Button(inc_btns, text="Remove", command=lambda: self._remove_pattern('include')).pack(fill=tk.X, pady=1)

        # Exclude patterns
        ttk.Label(right, text="Exclude patterns:").pack(anchor=tk.W)
        exc_frame = ttk.Frame(right)
        exc_frame.pack(fill=tk.BOTH, expand=True)
        self._exclude_listbox = tk.Listbox(exc_frame, height=5, font=MONO_FONT_SMALL)
        self._exclude_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._listboxes.append(self._exclude_listbox)
        self._listbox_data['exclude'] = []
        exc_btns = ttk.Frame(exc_frame)
        exc_btns.pack(side=tk.RIGHT, padx=(4, 0))
        ttk.Button(exc_btns, text="Add", command=lambda: self._add_pattern('exclude')).pack(fill=tk.X, pady=1)
        ttk.Button(exc_btns, text="Remove", command=lambda: self._remove_pattern('exclude')).pack(fill=tk.X, pady=1)

        tab.columnconfigure(0, weight=1)
        tab.columnconfigure(1, weight=1)
        tab.rowconfigure(0, weight=1)

    def _create_region_tab(self):
        tab = ttk.Frame(self._notebook, padding=10)
        self._notebook.add(tab, text="Region / Dedup")

        row = 0
        ttk.Label(tab, text="Region priority:").grid(row=row, column=0, sticky=tk.W, pady=2)
        self._vars['region_priority'] = tk.StringVar()
        ttk.Entry(tab, textvariable=self._vars['region_priority'], width=50).grid(
            row=row, column=1, sticky=tk.EW, padx=4, pady=2
        )

        row = 1
        ttk.Label(tab, text="Keep regions:").grid(row=row, column=0, sticky=tk.W, pady=2)
        self._vars['keep_regions'] = tk.StringVar()
        ttk.Entry(tab, textvariable=self._vars['keep_regions'], width=50).grid(
            row=row, column=1, sticky=tk.EW, padx=4, pady=2
        )

        row = 2
        ttk.Label(tab, text="Dedup priority:").grid(row=row, column=0, sticky=tk.W, pady=2)
        self._vars['dedup_priority'] = tk.StringVar()
        ttk.Entry(tab, textvariable=self._vars['dedup_priority'], width=50).grid(
            row=row, column=1, sticky=tk.EW, padx=4, pady=2
        )

        # Dedup PC lists
        row = 3
        ttk.Label(tab, text="Dedup PC lists:").grid(row=row, column=0, sticky=tk.NW, pady=2)
        pc_frame = ttk.Frame(tab)
        pc_frame.grid(row=row, column=1, sticky=tk.NSEW, padx=4, pady=2)
        self._dedup_pc_listbox = tk.Listbox(pc_frame, height=4, font=MONO_FONT_SMALL)
        self._dedup_pc_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._listboxes.append(self._dedup_pc_listbox)
        self._listbox_data['dedup_pc_lists'] = []
        pc_btns = ttk.Frame(pc_frame)
        pc_btns.pack(side=tk.RIGHT, padx=(4, 0))
        ttk.Button(pc_btns, text="Add", command=self._add_dedup_pc_list).pack(fill=tk.X, pady=1)
        ttk.Button(pc_btns, text="Remove", command=self._remove_dedup_pc_list).pack(fill=tk.X, pady=1)

        tab.columnconfigure(1, weight=1)

    def _create_output_tab(self):
        tab = ttk.Frame(self._notebook, padding=10)
        self._notebook.add(tab, text="Output")

        row = 0
        ttk.Label(tab, text="Transfer mode:").grid(row=row, column=0, sticky=tk.W, pady=2)
        self._vars['transfer_mode'] = tk.StringVar(value="Copy")
        ttk.Combobox(
            tab, textvariable=self._vars['transfer_mode'],
            values=["Copy", "Symlink", "Hardlink", "Move"],
            state="readonly", width=15
        ).grid(row=row, column=1, sticky=tk.W, padx=4, pady=2)

        row = 1
        check_frame = ttk.Frame(tab)
        check_frame.grid(row=row, column=0, columnspan=3, sticky=tk.W, pady=4)

        self._vars['flat'] = tk.BooleanVar()
        ttk.Checkbutton(check_frame, text="Flat output", variable=self._vars['flat']).pack(
            side=tk.LEFT, padx=(0, 12)
        )
        self._vars['print_roms'] = tk.BooleanVar()
        ttk.Checkbutton(check_frame, text="Print ROMs", variable=self._vars['print_roms']).pack(
            side=tk.LEFT, padx=(0, 12)
        )
        self._vars['playlists'] = tk.BooleanVar()
        ttk.Checkbutton(check_frame, text="Playlists (.m3u)", variable=self._vars['playlists']).pack(
            side=tk.LEFT, padx=(0, 12)
        )
        self._vars['gamelist'] = tk.BooleanVar()
        ttk.Checkbutton(check_frame, text="Gamelist (.xml)", variable=self._vars['gamelist']).pack(
            side=tk.LEFT, padx=(0, 12)
        )

        row = 2
        ttk.Label(tab, text="RetroArch playlists:").grid(row=row, column=0, sticky=tk.W, pady=2)
        self._vars['retroarch_playlists'] = tk.StringVar()
        ttk.Entry(tab, textvariable=self._vars['retroarch_playlists'], width=50).grid(
            row=row, column=1, sticky=tk.EW, padx=4, pady=2
        )
        ttk.Button(tab, text="Browse", command=lambda: self._browse_dir('retroarch_playlists')).grid(
            row=row, column=2, pady=2
        )

        row = 3
        ttk.Label(tab, text="Prefer source:").grid(row=row, column=0, sticky=tk.W, pady=2)
        self._vars['prefer_source'] = tk.StringVar()
        ttk.Entry(tab, textvariable=self._vars['prefer_source'], width=50).grid(
            row=row, column=1, sticky=tk.EW, padx=4, pady=2
        )
        ttk.Button(tab, text="Browse", command=lambda: self._browse_dir('prefer_source')).grid(
            row=row, column=2, pady=2
        )

        tab.columnconfigure(1, weight=1)

    def _create_network_tab(self):
        tab = ttk.Frame(self._notebook, padding=10)
        self._notebook.add(tab, text="Network")

        row = 0
        ttk.Label(tab, text="Parallel downloads:").grid(row=row, column=0, sticky=tk.W, pady=2)
        self._vars['parallel'] = tk.IntVar(value=4)
        ttk.Spinbox(tab, from_=1, to=32, width=6, textvariable=self._vars['parallel']).grid(
            row=row, column=1, sticky=tk.W, padx=4, pady=2
        )

        row = 1
        ttk.Label(tab, text="Connections/file:").grid(row=row, column=0, sticky=tk.W, pady=2)
        self._vars['connections'] = tk.StringVar()
        ttk.Spinbox(tab, from_=1, to=32, width=6, textvariable=self._vars['connections']).grid(
            row=row, column=1, sticky=tk.W, padx=4, pady=2
        )

        row = 2
        self._vars['auto_tune'] = tk.BooleanVar(value=True)
        ttk.Checkbutton(tab, text="Auto-tune parallelism", variable=self._vars['auto_tune']).grid(
            row=row, column=0, columnspan=2, sticky=tk.W, pady=2
        )

        row = 3
        ttk.Label(tab, text="Scan workers:").grid(row=row, column=0, sticky=tk.W, pady=2)
        self._vars['scan_workers'] = tk.IntVar(value=16)
        ttk.Spinbox(tab, from_=1, to=64, width=6, textvariable=self._vars['scan_workers']).grid(
            row=row, column=1, sticky=tk.W, padx=4, pady=2
        )

        row = 4
        ttk.Label(tab, text="Cache dir:").grid(row=row, column=0, sticky=tk.W, pady=2)
        self._vars['cache_dir'] = tk.StringVar()
        ttk.Entry(tab, textvariable=self._vars['cache_dir'], width=50).grid(
            row=row, column=1, sticky=tk.EW, padx=4, pady=2
        )
        ttk.Button(tab, text="Browse", command=lambda: self._browse_dir('cache_dir')).grid(
            row=row, column=2, pady=2
        )

        row = 5
        ttk.Label(tab, text="DAT dir:").grid(row=row, column=0, sticky=tk.W, pady=2)
        self._vars['dat_dir'] = tk.StringVar()
        ttk.Entry(tab, textvariable=self._vars['dat_dir'], width=50).grid(
            row=row, column=1, sticky=tk.EW, padx=4, pady=2
        )
        ttk.Button(tab, text="Browse", command=lambda: self._browse_dir('dat_dir')).grid(
            row=row, column=2, pady=2
        )

        tab.columnconfigure(1, weight=1)

    def _create_advanced_tab(self):
        tab = ttk.Frame(self._notebook, padding=10)
        self._notebook.add(tab, text="Advanced")

        # Checkbuttons
        check_frame = ttk.LabelFrame(tab, text="Options", padding=6)
        check_frame.grid(row=0, column=0, columnspan=3, sticky=tk.EW, pady=(0, 8))

        self._vars['no_verify'] = tk.BooleanVar()
        ttk.Checkbutton(check_frame, text="No verify", variable=self._vars['no_verify']).pack(
            side=tk.LEFT, padx=(0, 12)
        )
        self._vars['no_dat'] = tk.BooleanVar()
        ttk.Checkbutton(check_frame, text="No DAT", variable=self._vars['no_dat']).pack(
            side=tk.LEFT, padx=(0, 12)
        )
        self._vars['no_chd'] = tk.BooleanVar()
        ttk.Checkbutton(check_frame, text="No CHD", variable=self._vars['no_chd']).pack(
            side=tk.LEFT, padx=(0, 12)
        )
        self._vars['no_adult'] = tk.BooleanVar()
        ttk.Checkbutton(check_frame, text="No adult", variable=self._vars['no_adult']).pack(
            side=tk.LEFT, padx=(0, 12)
        )
        self._vars['tp_all_versions'] = tk.BooleanVar()
        ttk.Checkbutton(check_frame, text="TP all versions", variable=self._vars['tp_all_versions']).pack(
            side=tk.LEFT, padx=(0, 12)
        )

        # MAME version
        row = 1
        ttk.Label(tab, text="MAME version:").grid(row=row, column=0, sticky=tk.W, pady=2)
        self._vars['mame_version'] = tk.StringVar()
        ttk.Entry(tab, textvariable=self._vars['mame_version'], width=20).grid(
            row=row, column=1, sticky=tk.W, padx=4, pady=2
        )

        # Ratings source
        row = 2
        ttk.Label(tab, text="Ratings source:").grid(row=row, column=0, sticky=tk.W, pady=2)
        self._vars['ratings_source'] = tk.StringVar()
        ttk.Combobox(
            tab, textvariable=self._vars['ratings_source'],
            values=["", "combined", "igdb", "launchbox"],
            state="readonly", width=15
        ).grid(row=row, column=1, sticky=tk.W, padx=4, pady=2)

        # Authentication section
        auth_frame = ttk.LabelFrame(tab, text="Authentication", padding=6)
        auth_frame.grid(row=3, column=0, columnspan=3, sticky=tk.EW, pady=(8, 4))

        auth_entries = [
            ("IA access key:", "ia_access_key", False),
            ("IA secret key:", "ia_secret_key", True),
            ("IGDB client ID:", "igdb_client_id", False),
            ("IGDB client secret:", "igdb_client_secret", True),
        ]
        for i, (label, key, is_secret) in enumerate(auth_entries):
            ttk.Label(auth_frame, text=label).grid(row=i, column=0, sticky=tk.W, pady=1)
            self._vars[key] = tk.StringVar()
            entry = ttk.Entry(
                auth_frame, textvariable=self._vars[key], width=40,
                show='*' if is_secret else ''
            )
            entry.grid(row=i, column=1, sticky=tk.EW, padx=4, pady=1)
        auth_frame.columnconfigure(1, weight=1)

        # TeknoParrot section
        tp_frame = ttk.LabelFrame(tab, text="TeknoParrot", padding=6)
        tp_frame.grid(row=4, column=0, columnspan=3, sticky=tk.EW, pady=(4, 0))

        ttk.Label(tp_frame, text="Include platforms:").grid(row=0, column=0, sticky=tk.W, pady=1)
        self._vars['tp_include_platforms'] = tk.StringVar()
        ttk.Entry(tp_frame, textvariable=self._vars['tp_include_platforms'], width=40).grid(
            row=0, column=1, sticky=tk.EW, padx=4, pady=1
        )

        ttk.Label(tp_frame, text="Exclude platforms:").grid(row=1, column=0, sticky=tk.W, pady=1)
        self._vars['tp_exclude_platforms'] = tk.StringVar()
        ttk.Entry(tp_frame, textvariable=self._vars['tp_exclude_platforms'], width=40).grid(
            row=1, column=1, sticky=tk.EW, padx=4, pady=1
        )
        tp_frame.columnconfigure(1, weight=1)

        tab.columnconfigure(1, weight=1)

    # ── Helpers ───────────────────────────────────────────────────────

    def _browse_dir(self, var_key):
        path = filedialog.askdirectory()
        if path:
            self._vars[var_key].set(path)

    def _browse_file(self, var_key, filetypes):
        path = filedialog.askopenfilename(filetypes=filetypes)
        if path:
            self._vars[var_key].set(path)

    def _browse_systems(self):
        dlg = SystemsDialog(self.root, self._vars['systems'].get(), self._is_dark)
        self.root.wait_window(dlg)
        if dlg.result is not None:
            self._vars['systems'].set(dlg.result)

    def _add_source_folder(self):
        path = filedialog.askdirectory()
        if path:
            self._listbox_data['source'].append(path)
            self._source_listbox.insert(tk.END, path)

    def _add_source_url(self):
        url = tk.simpledialog.askstring("Add URL", "Enter source URL:", parent=self.root)
        if url and url.strip():
            self._listbox_data['source'].append(url.strip())
            self._source_listbox.insert(tk.END, url.strip())

    def _remove_source(self):
        sel = self._source_listbox.curselection()
        if sel:
            idx = sel[0]
            self._source_listbox.delete(idx)
            self._listbox_data['source'].pop(idx)

    def _add_pattern(self, key):
        pattern = tk.simpledialog.askstring(
            f"Add {key} pattern", "Enter glob pattern:", parent=self.root
        )
        if pattern and pattern.strip():
            self._listbox_data[key].append(pattern.strip())
            listbox = self._include_listbox if key == 'include' else self._exclude_listbox
            listbox.insert(tk.END, pattern.strip())

    def _remove_pattern(self, key):
        listbox = self._include_listbox if key == 'include' else self._exclude_listbox
        sel = listbox.curselection()
        if sel:
            idx = sel[0]
            listbox.delete(idx)
            self._listbox_data[key].pop(idx)

    def _add_dedup_pc_list(self):
        path = filedialog.askopenfilename(
            filetypes=[("XML files", "*.xml"), ("All files", "*.*")]
        )
        if path:
            self._listbox_data['dedup_pc_lists'].append(path)
            self._dedup_pc_listbox.insert(tk.END, path)

    def _remove_dedup_pc_list(self):
        sel = self._dedup_pc_listbox.curselection()
        if sel:
            idx = sel[0]
            self._dedup_pc_listbox.delete(idx)
            self._listbox_data['dedup_pc_lists'].pop(idx)

    # ── Build argv ────────────────────────────────────────────────────

    def _build_argv(self, commit=False):
        """Convert widget values into a sys.argv list for retro-refiner."""
        argv = ['retro-refiner']

        # Sources (append mode)
        for src in self._listbox_data.get('source', []):
            argv.extend(['--source', src])

        # Dest
        dest = self._vars['dest'].get().strip()
        if dest:
            argv.extend(['--dest', dest])

        # Systems
        systems = self._vars['systems'].get().strip()
        if systems:
            argv.append('--systems')
            argv.extend(s.strip() for s in systems.split(',') if s.strip())

        # Config
        config = self._vars['config'].get().strip()
        if config:
            argv.extend(['--config', config])

        # Boolean flags from Sources tab
        if self._vars['recursive'].get():
            argv.append('--recursive')
        if self._vars['auto_detect'].get():
            argv.append('--auto-detect')

        # Max depth (only meaningful with recursive)
        max_depth = self._vars['max_depth'].get()
        if max_depth != 3:
            argv.extend(['--max-depth', str(max_depth)])

        # Filtering tab booleans
        if self._vars['all'].get():
            argv.append('--all')
        if self._vars['exclude_protos'].get():
            argv.append('--exclude-protos')
        if self._vars['include_betas'].get():
            argv.append('--include-betas')
        if self._vars['include_unlicensed'].get():
            argv.append('--include-unlicensed')
        if self._vars['english_only'].get():
            argv.append('--english-only')
        if self._vars['verbose'].get():
            argv.append('--verbose')
        if self._vars['include_unrated'].get():
            argv.append('--include-unrated')

        # Include/Exclude patterns
        for pattern in self._listbox_data.get('include', []):
            argv.extend(['--include', pattern])
        for pattern in self._listbox_data.get('exclude', []):
            argv.extend(['--exclude', pattern])

        # String entries (skip if empty)
        str_args = {
            'top': '--top',
            'limit': '--limit',
            'size': '--size',
            'prefer_exclusives': '--prefer-exclusives',
            'year_from': '--year-from',
            'year_to': '--year-to',
            'genres': '--genres',
            'region_priority': '--region-priority',
            'keep_regions': '--keep-regions',
            'dedup_priority': '--dedup-priority',
            'mame_version': '--mame-version',
            'ia_access_key': '--ia-access-key',
            'ia_secret_key': '--ia-secret-key',
            'igdb_client_id': '--igdb-client-id',
            'igdb_client_secret': '--igdb-client-secret',
            'tp_include_platforms': '--tp-include-platforms',
            'tp_exclude_platforms': '--tp-exclude-platforms',
        }
        for var_key, arg_name in str_args.items():
            val = self._vars[var_key].get().strip() if isinstance(self._vars[var_key].get(), str) else str(self._vars[var_key].get())
            if val:
                argv.extend([arg_name, val])

        # Dedup PC lists
        for path in self._listbox_data.get('dedup_pc_lists', []):
            argv.extend(['--dedup-pc-lists', path])

        # Transfer mode
        mode = self._vars['transfer_mode'].get()
        if mode == "Symlink":
            argv.append('--link')
        elif mode == "Hardlink":
            argv.append('--hardlink')
        elif mode == "Move":
            argv.append('--move')

        # Output booleans
        if self._vars['flat'].get():
            argv.append('--flat')
        if self._vars['print_roms'].get():
            argv.append('--print')
        if self._vars['playlists'].get():
            argv.append('--playlists')
        if self._vars['gamelist'].get():
            argv.append('--gamelist')

        # Output paths
        retroarch = self._vars['retroarch_playlists'].get().strip()
        if retroarch:
            argv.extend(['--retroarch-playlists', retroarch])
        prefer_src = self._vars['prefer_source'].get().strip()
        if prefer_src:
            argv.extend(['--prefer-source', prefer_src])

        # Ratings source
        ratings = self._vars['ratings_source'].get().strip()
        if ratings:
            argv.extend(['--ratings-source', ratings])

        # Network settings
        parallel = self._vars['parallel'].get()
        if parallel != 4:
            argv.extend(['--parallel', str(parallel)])

        connections = self._vars['connections'].get().strip()
        if connections:
            argv.extend(['--connections', connections])

        if not self._vars['auto_tune'].get():
            argv.append('--no-auto-tune')

        scan_workers = self._vars['scan_workers'].get()
        if scan_workers != 16:
            argv.extend(['--scan-workers', str(scan_workers)])

        cache_dir = self._vars['cache_dir'].get().strip()
        if cache_dir:
            argv.extend(['--cache-dir', cache_dir])

        dat_dir = self._vars['dat_dir'].get().strip()
        if dat_dir:
            argv.extend(['--dat-dir', dat_dir])

        # Advanced booleans
        if self._vars['no_verify'].get():
            argv.append('--no-verify')
        if self._vars['no_dat'].get():
            argv.append('--no-dat')
        if self._vars['no_chd'].get():
            argv.append('--no-chd')
        if self._vars['no_adult'].get():
            argv.append('--no-adult')
        if self._vars['tp_all_versions'].get():
            argv.append('--tp-all-versions')

        # Commit flag
        if commit:
            argv.append('--commit')

        return argv

    # ── Run controls ──────────────────────────────────────────────────

    def _run_dry(self):
        """Start a dry run (no file transfer)."""
        if self._running:
            return
        self._start_run(commit=False)

    def _run_commit(self):
        """Start a commit run (with file transfer)."""
        if self._running:
            return
        if not messagebox.askyesno(
            "Confirm Commit",
            "This will actually transfer files to the destination.\n\nContinue?"
        ):
            return
        self._start_run(commit=True)

    def _cancel_run(self):
        """Request graceful cancellation of the running task."""
        if self._running:
            _module._shutdown_requested = True  # pylint: disable=protected-access
            self._status_var.set("Cancelling...")

    def _start_run(self, commit):
        """Launch the worker thread."""
        # Validate that at least one source is specified
        if not self._listbox_data.get('source'):
            messagebox.showwarning("No Source", "Please add at least one source directory or URL.")
            return

        self._running = True
        self._update_button_states()
        self._progress_var.set(0)
        self._status_var.set("Running...")

        # Reset shutdown flag from any previous run
        _module._shutdown_requested = False  # pylint: disable=protected-access

        argv = self._build_argv(commit=commit)
        self._worker_thread = threading.Thread(
            target=self._run_worker, args=(argv,), daemon=True
        )
        self._worker_thread.start()

    def _run_worker(self, argv):
        """Worker thread: redirect IO, call main(), restore."""
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        writer = QueueWriter(self._output_queue)

        try:
            sys.stdout = writer
            sys.stderr = writer
            sys.argv = argv

            _module.main()
        except SystemExit:
            # main() calls sys.exit() in several paths (list-systems, clean, errors)
            pass
        except Exception as exc:
            self._output_queue.put(('append', f"\n--- ERROR ---\n{exc}\n"))
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr

            # Schedule completion callback on main thread
            self.root.after(0, self._on_run_complete)

    def _on_run_complete(self):
        """Called on the main thread when the worker finishes."""
        self._running = False
        self._update_button_states()
        # pylint: disable=protected-access
        if _module._shutdown_requested:
            self._status_var.set("Cancelled")
            _module._shutdown_requested = False
        # pylint: enable=protected-access
        else:
            self._status_var.set("Completed")
        self._progress_var.set(100)

    def _update_button_states(self):
        """Enable/disable buttons based on running state."""
        if self._running:
            self._dry_btn.configure(state=tk.DISABLED)
            self._commit_btn.configure(state=tk.DISABLED)
            self._cancel_btn.configure(state=tk.NORMAL)
        else:
            self._dry_btn.configure(state=tk.NORMAL)
            self._commit_btn.configure(state=tk.NORMAL)
            self._cancel_btn.configure(state=tk.DISABLED)

    def _clear_output(self):
        """Clear the output text widget."""
        self._output_text.configure(state=tk.NORMAL)
        self._output_text.delete('1.0', tk.END)
        self._output_text.configure(state=tk.DISABLED)

    # ── Theme ─────────────────────────────────────────────────────────

    def _toggle_theme(self):
        """Switch between light and dark theme."""
        self._is_dark = not self._is_dark
        self._apply_theme()

    def _apply_theme(self):
        """Apply the current theme to all widgets."""
        theme = DARK_THEME if self._is_dark else LIGHT_THEME
        self._theme_btn.configure(text="Light" if self._is_dark else "Dark")

        # Output text widget
        self._output_text.configure(
            bg=theme['output_bg'], fg=theme['output_fg'],
            insertbackground=theme['output_insert'],
            selectbackground=theme['output_select_bg'],
            selectforeground=theme['output_select_fg'],
        )

        # All tracked listboxes
        for lb in self._listboxes:
            lb.configure(
                bg=theme['listbox_bg'], fg=theme['listbox_fg'],
                selectbackground=theme['listbox_select_bg'],
                selectforeground=theme['listbox_select_fg'],
            )

        # All tracked canvases
        for canvas in self._canvases:
            canvas.configure(bg=theme['canvas_bg'])

        # Configure ttk styles for themed widgets
        s = ttk.Style()

        # Use clam as base on all platforms for consistent custom styling
        try:
            s.theme_use(theme['ttk_theme_base'])
        except tk.TclError:
            pass

        bc = theme['border_color']

        s.configure('TFrame', background=theme['frame_bg'])
        s.configure('TLabel', background=theme['frame_bg'], foreground=theme['label_fg'])
        s.configure('TLabelframe', background=theme['frame_bg'], bordercolor=bc)
        s.configure('TLabelframe.Label', background=theme['frame_bg'],
                     foreground=theme['label_fg'])

        # Buttons
        s.configure('TButton', background=theme['button_bg'],
                     foreground=theme['button_fg'], bordercolor=bc,
                     darkcolor=theme['button_bg'], lightcolor=theme['button_bg'])
        s.map('TButton',
              background=[('pressed', theme['button_pressed_bg']),
                          ('active', theme['button_hover_bg'])],
              darkcolor=[('pressed', theme['button_pressed_bg']),
                         ('active', theme['button_hover_bg'])],
              lightcolor=[('pressed', theme['button_pressed_bg']),
                          ('active', theme['button_hover_bg'])])

        # Checkbuttons
        s.configure('TCheckbutton', background=theme['frame_bg'],
                     foreground=theme['label_fg'],
                     indicatorbackground=theme['check_bg'],
                     indicatorforeground=theme['label_fg'])
        s.map('TCheckbutton',
              background=[('active', theme['check_hover_bg'])],
              indicatorbackground=[('pressed', theme['check_hover_bg']),
                                   ('active', theme['check_hover_bg'])])

        # Notebook tabs
        s.configure('TNotebook', background=theme['frame_bg'], bordercolor=bc)
        s.configure('TNotebook.Tab', background=theme['tab_bg'],
                     foreground=theme['button_fg'], padding=[8, 4],
                     bordercolor=bc,
                     lightcolor=theme['tab_bg'], darkcolor=theme['tab_bg'])
        s.map('TNotebook.Tab',
              background=[('selected', theme['tab_selected_bg']),
                          ('active', theme['tab_hover_bg'])],
              lightcolor=[('selected', theme['tab_selected_bg']),
                          ('!selected', theme['tab_bg'])],
              foreground=[('selected', theme['label_fg'])])

        # Entry / Spinbox / Combobox
        s.configure('TEntry', fieldbackground=theme['entry_bg'],
                     foreground=theme['entry_fg'], bordercolor=bc,
                     lightcolor=theme['entry_bg'], darkcolor=theme['entry_bg'])
        s.map('TEntry',
              bordercolor=[('focus', theme['focus_color'])],
              lightcolor=[('focus', theme['focus_color'])])
        s.configure('TSpinbox', fieldbackground=theme['entry_bg'],
                     foreground=theme['entry_fg'], bordercolor=bc,
                     arrowcolor=theme['label_fg'],
                     background=theme['button_bg'])
        s.map('TSpinbox',
              bordercolor=[('focus', theme['focus_color'])],
              arrowcolor=[('pressed', theme['button_fg']),
                          ('active', theme['button_fg'])])
        s.configure('TCombobox', fieldbackground=theme['entry_bg'],
                     foreground=theme['entry_fg'], bordercolor=bc,
                     arrowcolor=theme['label_fg'],
                     background=theme['button_bg'])
        s.map('TCombobox',
              fieldbackground=[('readonly', 'focus', theme['entry_bg']),
                               ('readonly', theme['entry_bg'])],
              background=[('active', theme['combo_hover_bg']),
                          ('pressed', theme['combo_hover_bg'])],
              bordercolor=[('focus', theme['focus_color'])],
              arrowcolor=[('pressed', theme['button_fg']),
                          ('active', theme['button_fg'])])

        # Scrollbar
        s.configure('TScrollbar', background=theme['button_bg'],
                     troughcolor=theme['trough_color'], bordercolor=bc,
                     arrowcolor=theme['label_fg'])
        s.map('TScrollbar',
              background=[('active', theme['button_hover_bg']),
                          ('pressed', theme['button_pressed_bg'])])

        # Progressbar
        s.configure('TProgressbar', background=theme['focus_color'],
                     troughcolor=theme['trough_color'], bordercolor=bc)

        # Panedwindow
        s.configure('TPanedwindow', background=theme['frame_bg'])
        s.configure('Sash', sashthickness=6, gripcount=0,
                     background=theme['frame_bg'])

        # Window background
        self.root.configure(bg=theme['window_bg'])

    # ── Output queue polling ──────────────────────────────────────────

    def _poll_queue(self):
        """Drain the output queue into the Text widget (called every 50ms)."""
        try:
            autoscroll = self._output_text.yview()[1] >= 0.95
            batch_count = 0

            while batch_count < 200:  # Process up to 200 items per poll
                try:
                    action, text = self._output_queue.get_nowait()
                except queue.Empty:
                    break

                self._output_text.configure(state=tk.NORMAL)

                if action == 'replace':
                    # Replace the current line (for \r progress bars)
                    # Delete from start of current line to end of line
                    current_line = self._output_text.index('end-1c linestart')
                    self._output_text.delete(current_line, 'end-1c')
                    self._output_text.insert(tk.END, text)
                    self._try_parse_progress(text)
                else:
                    self._output_text.insert(tk.END, text)

                self._output_text.configure(state=tk.DISABLED)
                batch_count += 1

            if autoscroll and batch_count > 0:
                self._output_text.see(tk.END)

        except Exception:
            pass  # Don't crash the poll loop

        self.root.after(50, self._poll_queue)

    def _try_parse_progress(self, text):
        """Try to extract progress percentage from progress bar text."""
        # ProgressBar output looks like: [####----] 10/20 (50%)
        try:
            if '(' in text and '%)' in text:
                pct_str = text.split('(')[-1].split('%')[0]
                pct = float(pct_str)
                self._progress_var.set(pct)
                # Extract label if present after the percentage
                after_pct = text.split('%)')[1].strip() if '%)' in text else ''
                if after_pct:
                    self._progress_label.set(after_pct.strip())
        except (ValueError, IndexError):
            pass


def main():
    """Create and run the GUI."""
    root = tk.Tk()
    RetroRefinerGUI(root)
    root.mainloop()


if __name__ == '__main__':
    main()

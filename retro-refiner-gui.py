#!/usr/bin/env python3
"""
Retro-Refiner GUI - Tkinter-based graphical interface for retro-refiner.py.

Zero-dependency GUI wrapper that provides a tabbed settings interface and
real-time output display. Runs retro-refiner's main() in a background thread
while keeping the GUI responsive.
"""

import importlib.util
import os
import queue
import subprocess
import sys
import threading
import time
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
    'accent_bg': '#0078d4',
    'accent_fg': '#ffffff',
    'accent_hover_bg': '#1a8ad4',
    'accent_pressed_bg': '#005a9e',
    'sublabel_fg': '#888888',
    'preview_bg': '#252526',
    'preview_fg': '#888888',
    'welcome_fg': '#666666',
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
    'accent_bg': '#0078d4',
    'accent_fg': '#ffffff',
    'accent_hover_bg': '#1a8ad4',
    'accent_pressed_bg': '#005a9e',
    'sublabel_fg': '#777777',
    'preview_bg': '#f5f5f5',
    'preview_fg': '#777777',
    'welcome_fg': '#aaaaaa',
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


# Auto-save state file location (next to script, hidden dotfile)
_STATE_FILE = Path(__file__).parent / '.retro-refiner-gui-state.yaml'


def _center_window(window, width, height):
    """Center a window on the screen."""
    window.update_idletasks()
    screen_w = window.winfo_screenwidth()
    screen_h = window.winfo_screenheight()
    x = (screen_w - width) // 2
    y = (screen_h - height) // 2
    window.geometry(f"{width}x{height}+{x}+{y}")


class Tooltip:
    """Hover tooltip for any tkinter widget."""

    DELAY_MS = 500  # Delay before showing tooltip

    def __init__(self, widget, text, get_theme=None):
        self._widget = widget
        self._text = text
        self._get_theme = get_theme  # callable returning current theme dict
        self._tip_window = None
        self._after_id = None
        widget.bind('<Enter>', self._schedule, add='+')
        widget.bind('<Leave>', self._cancel, add='+')
        widget.bind('<ButtonPress>', self._cancel, add='+')

    def _schedule(self, _event):
        """Schedule tooltip display after delay."""
        self._cancel()
        self._after_id = self._widget.after(self.DELAY_MS, self._show)

    def _cancel(self, _event=None):
        """Cancel pending tooltip and hide if visible."""
        if self._after_id:
            self._widget.after_cancel(self._after_id)
            self._after_id = None
        self._hide()

    def _show(self):
        """Display the tooltip near the widget."""
        if self._tip_window:
            return
        # Position below the widget
        x = self._widget.winfo_rootx() + 20
        y = self._widget.winfo_rooty() + self._widget.winfo_height() + 4

        self._tip_window = tw = tk.Toplevel(self._widget)
        tw.wm_overrideredirect(True)

        # Theme colors
        if self._get_theme:
            theme = self._get_theme()
            bg = theme['entry_bg']
            fg = theme['entry_fg']
            border = theme['border_color']
        else:
            bg = '#ffffe0'
            fg = '#000000'
            border = '#888888'

        tw.wm_geometry(f"+{x}+{y}")
        frame = tk.Frame(tw, background=border, padx=1, pady=1)
        frame.pack()
        label = tk.Label(
            frame, text=self._text, justify=tk.LEFT,
            background=bg, foreground=fg,
            wraplength=350, padx=6, pady=4,
        )
        label.pack()

    def _hide(self):
        """Hide the tooltip."""
        if self._tip_window:
            self._tip_window.destroy()
            self._tip_window = None


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
        _center_window(self, 400, 500)
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

        # Enable mouse wheel scrolling
        def _on_mousewheel(event):
            if sys.platform == 'darwin':
                canvas.yview_scroll(-1 * event.delta, "units")
            else:
                canvas.yview_scroll(-1 * (event.delta // 120), "units")

        canvas.bind_all('<MouseWheel>', _on_mousewheel)
        # Linux scroll events
        canvas.bind_all('<Button-4>', lambda e: canvas.yview_scroll(-3, "units"))
        canvas.bind_all('<Button-5>', lambda e: canvas.yview_scroll(3, "units"))

        # Unbind global scroll on dialog close
        self._canvas = canvas
        self.protocol("WM_DELETE_WINDOW", self._on_close)

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
        ttk.Button(btn_frame, text="Cancel", command=self._on_close).pack(side=tk.RIGHT, padx=2)

    def _on_close(self):
        """Unbind global mouse wheel events and close the dialog."""
        self._canvas.unbind_all('<MouseWheel>')
        self._canvas.unbind_all('<Button-4>')
        self._canvas.unbind_all('<Button-5>')
        self.destroy()

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
        self._on_close()


class RetroRefinerGUI:
    """Main GUI application for Retro-Refiner."""

    def __init__(self, root):
        self.root = root
        self.root.title("Retro-Refiner")
        _center_window(self.root, 920, 960)
        self.root.minsize(700, 500)

        self._running = False
        self._worker_thread = None
        self._output_queue = queue.Queue()
        self._start_time = None
        self._progress_is_indeterminate = False

        # Track all widget variables for argv construction
        self._vars = {}
        self._listbox_data = {}  # name -> list of strings

        # Listbox widgets (initialized in tab builders)
        self._source_listbox = None
        self._include_listbox = None
        self._exclude_listbox = None
        self._dedup_pc_listbox = None

        # Dedupe-dependent widgets (disabled when priority is empty)
        self._dedupe_dependent_widgets = []
        self._dedup_add_btn = None
        self._dedup_remove_btn = None
        self._dedupe_delete_cb = None
        self._welcome_shown = False
        self._main_pane = None
        self._notebook_frame = None

        # Theme state
        self._is_dark = _detect_system_dark_mode()
        self._listboxes = []  # All Listbox widgets for theme updates
        self._canvases = []   # All Canvas widgets for theme updates

        # Suppress preview updates during initial build
        self._building = True
        self._build_ui()
        self._building = False

        self._apply_theme()

        # Restore previous session state (before traces so preview updates once)
        self._auto_load_state()

        self._update_button_states()
        self._update_preview()

        # Add variable traces for live preview updates
        for var in self._vars.values():
            var.trace_add('write', lambda *_: self._update_preview())

        self._poll_queue()

        # Auto-save state on window close
        self.root.protocol('WM_DELETE_WINDOW', self._on_close)

    def _tip(self, widget, text):
        """Attach a hover tooltip to a widget."""
        Tooltip(widget, text, get_theme=lambda: DARK_THEME if self._is_dark else LIGHT_THEME)
        return widget

    def _build_ui(self):
        """Build the complete UI layout."""
        # Main container
        main_pane = ttk.PanedWindow(self.root, orient=tk.VERTICAL)
        main_pane.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

        # Top: tabbed settings (sash positioned dynamically after render)
        notebook_frame = ttk.Frame(main_pane)
        main_pane.add(notebook_frame, weight=0)

        self._notebook = ttk.Notebook(notebook_frame)
        self._notebook.pack(fill=tk.BOTH, expand=True)

        self._create_sources_tab()
        self._create_selection_tab()
        self._create_output_tab()
        self._create_advanced_tab()

        # Command preview line
        preview_frame = ttk.Frame(main_pane)
        main_pane.add(preview_frame, weight=0)

        self._preview_var = tk.StringVar(value="")
        self._preview_entry = tk.Entry(
            preview_frame, textvariable=self._preview_var,
            font=MONO_FONT_SMALL, state='readonly', readonlybackground='#252526',
            fg='#888888', relief=tk.FLAT, bd=1,
        )
        self._preview_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, pady=(2, 2))
        self._tip(self._preview_entry,
                  "Command preview: shows the CLI arguments that will be passed to retro-refiner.")

        self._preview_copy_btn = ttk.Button(
            preview_frame, text="Copy", width=5, command=self._copy_preview
        )
        self._preview_copy_btn.pack(side=tk.RIGHT, padx=(4, 0), pady=(2, 2))
        self._tip(self._preview_copy_btn, "Copy the command preview to the clipboard.")

        # Bottom: output + controls (gets all extra space when resizing)
        bottom_frame = ttk.Frame(main_pane)
        main_pane.add(bottom_frame, weight=1)

        # After all widgets are built, position sash to fit tabs exactly
        self._main_pane = main_pane
        self._notebook_frame = notebook_frame
        self.root.after_idle(self._position_sash)

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
            height=8,
        )
        scrollbar = ttk.Scrollbar(
            output_frame, orient=tk.VERTICAL, command=self._output_text.yview
        )
        self._output_text.configure(yscrollcommand=scrollbar.set)
        self._output_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Allow text selection and Ctrl+C copy in disabled text widget
        self._output_text.bind('<Button-1>', self._output_click)
        self._output_text.bind('<B1-Motion>', self._output_drag)
        self._output_text.bind('<Control-c>', self._output_copy)
        self._output_text.bind('<Control-a>', self._output_select_all)

        # Insert welcome text
        self._output_text.configure(state=tk.NORMAL)
        self._output_text.insert(
            tk.END,
            "Getting started: Add a source folder or URL in the Setup tab, "
            "then click Preview to see what will be selected.\n\n"
            "Tip: Hover over any widget for a description of what it does."
        )
        self._output_text.configure(state=tk.DISABLED)
        self._welcome_shown = True

        # Control buttons
        ctrl_frame = ttk.Frame(bottom_frame)
        ctrl_frame.pack(fill=tk.X, pady=(6, 0))

        self._dry_btn = ttk.Button(
            ctrl_frame, text="Preview", command=self._run_dry
        )
        self._dry_btn.pack(side=tk.LEFT, padx=(0, 4))
        self._tip(self._dry_btn, "Preview what would be selected without transferring any files.")

        self._commit_btn = ttk.Button(
            ctrl_frame, text="Run (Commit)", command=self._run_commit,
            style='Accent.TButton'
        )
        self._commit_btn.pack(side=tk.LEFT, padx=(0, 4))
        self._tip(self._commit_btn, "Run with file transfer enabled. Files will be copied/linked/moved to the destination.")

        self._cancel_btn = ttk.Button(
            ctrl_frame, text="Cancel", command=self._cancel_run, state=tk.DISABLED
        )
        self._cancel_btn.pack(side=tk.LEFT, padx=(0, 4))
        self._tip(self._cancel_btn, "Gracefully stop the current run. Processing finishes the current operation then exits.")

        ttk.Button(
            ctrl_frame, text="Clear", command=self._clear_output
        ).pack(side=tk.LEFT, padx=(0, 4))

        ttk.Button(
            ctrl_frame, text="Copy", command=self._copy_output
        ).pack(side=tk.LEFT, padx=(0, 4))

        # Auto-scroll checkbox
        self._auto_scroll = tk.BooleanVar(value=True)
        cb = ttk.Checkbutton(ctrl_frame, text="Auto-scroll", variable=self._auto_scroll)
        cb.pack(side=tk.LEFT, padx=(8, 4))
        self._tip(cb, "Automatically scroll to the bottom as new output appears.")

        # Right side controls
        self._theme_btn = ttk.Button(
            ctrl_frame, text="Theme: Dark", command=self._toggle_theme, width=12
        )
        self._theme_btn.pack(side=tk.RIGHT, padx=(0, 4))

        self._tip(self._theme_btn, "Toggle between dark and light themes.")

        # Save / Load settings
        load_btn = ttk.Button(ctrl_frame, text="Load", command=self._load_settings)
        load_btn.pack(side=tk.RIGHT, padx=(0, 4))
        self._tip(load_btn, "Load GUI settings from a previously saved YAML file.")

        save_btn = ttk.Button(ctrl_frame, text="Save", command=self._save_settings)
        save_btn.pack(side=tk.RIGHT, padx=(0, 4))
        self._tip(save_btn, "Save current GUI settings to a YAML file for later reuse.")

        # Status and elapsed time
        self._elapsed_var = tk.StringVar(value="")
        ttk.Label(ctrl_frame, textvariable=self._elapsed_var, width=10).pack(
            side=tk.RIGHT, padx=(0, 4)
        )
        self._status_var = tk.StringVar(value="Ready")
        ttk.Label(ctrl_frame, textvariable=self._status_var).pack(
            side=tk.RIGHT, padx=(4, 0)
        )

    def _position_sash(self):
        """Position the first sash so the notebook gets exactly the height it needs."""
        self.root.update_idletasks()
        # Measure what the notebook actually needs
        needed = self._notebook.winfo_reqheight()
        # Add a small margin for the frame padding
        self._main_pane.sashpos(0, needed + 12)

    # ── Tab builders ──────────────────────────────────────────────────

    def _create_sources_tab(self):
        tab = ttk.Frame(self._notebook, padding=10)
        self._notebook.add(tab, text="Setup")

        # Source dirs/URLs
        self._tip(ttk.Label(tab, text="Source directories / URLs:"), (
            "Local folders or HTTP/HTTPS URLs containing ROMs. "
            "You can add multiple sources and they will be merged together."
        )).grid(row=0, column=0, sticky=tk.W, pady=(0, 2))
        src_frame = ttk.Frame(tab)
        src_frame.grid(row=1, column=0, columnspan=3, sticky=tk.NSEW, pady=(0, 8))

        self._source_listbox = tk.Listbox(src_frame, height=6, font=MONO_FONT_SMALL)
        self._source_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._tip(self._source_listbox, (
            "Local folders or HTTP/HTTPS URLs containing ROMs. "
            "You can add multiple sources and they will be merged together."
        ))
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
        ttk.Button(src_btn_frame, text="Edit", command=self._edit_source).pack(
            fill=tk.X, pady=1
        )
        ttk.Button(src_btn_frame, text="Remove", command=self._remove_source).pack(
            fill=tk.X, pady=1
        )

        # Destination
        row = 2
        self._tip(ttk.Label(tab, text="Destination:"), (
            "Where refined ROMs will be placed. "
            "Defaults to a 'refined/' folder next to the script if left empty."
        )).grid(row=row, column=0, sticky=tk.W, pady=2)
        self._vars['dest'] = tk.StringVar()
        self._tip(ttk.Entry(tab, textvariable=self._vars['dest'], width=50), (
            "Where refined ROMs will be placed. "
            "Defaults to a 'refined/' folder next to the script if left empty."
        )).grid(row=row, column=1, sticky=tk.EW, padx=4, pady=2)
        ttk.Button(tab, text="Browse", command=lambda: self._browse_dir('dest')).grid(
            row=row, column=2, pady=2
        )

        # Systems
        row = 3
        self._tip(ttk.Label(tab, text="Systems:"), (
            "Comma-separated list of system codes to process (e.g. nes,snes,gba). "
            "Leave empty to auto-detect from folder names."
        )).grid(row=row, column=0, sticky=tk.W, pady=2)
        sys_frame = ttk.Frame(tab)
        sys_frame.grid(row=row, column=1, columnspan=2, sticky=tk.EW, pady=2)
        self._vars['systems'] = tk.StringVar()
        self._tip(ttk.Entry(sys_frame, textvariable=self._vars['systems']), (
            "Comma-separated list of system codes to process (e.g. nes,snes,gba). "
            "Leave empty to auto-detect from folder names."
        )).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(sys_frame, text="Select...", command=self._browse_systems).pack(
            side=tk.RIGHT, padx=(4, 0)
        )

        # Config file
        row = 4
        self._tip(ttk.Label(tab, text="Config file:"), (
            "Path to a YAML or JSON config file with default settings. "
            "CLI/GUI settings override config values. Auto-generated on first commit run."
        )).grid(row=row, column=0, sticky=tk.W, pady=2)
        self._vars['config'] = tk.StringVar()
        self._tip(ttk.Entry(tab, textvariable=self._vars['config'], width=50), (
            "Path to a YAML or JSON config file with default settings. "
            "CLI/GUI settings override config values. Auto-generated on first commit run."
        )).grid(row=row, column=1, sticky=tk.EW, padx=4, pady=2)
        ttk.Button(tab, text="Browse", command=lambda: self._browse_file(
            'config', [("YAML files", "*.yaml *.yml"), ("All files", "*.*")]
        )).grid(row=row, column=2, pady=2)

        # Checkbuttons row
        row = 5
        check_frame = ttk.Frame(tab)
        check_frame.grid(row=row, column=0, columnspan=3, sticky=tk.W, pady=(8, 2))

        self._vars['recursive'] = tk.BooleanVar()
        cb = ttk.Checkbutton(check_frame, text="Recursive (-r)", variable=self._vars['recursive'])
        cb.pack(side=tk.LEFT, padx=(0, 12))
        self._tip(cb, (
            "Recursively scan subdirectories for ROMs. "
            "Useful when ROMs are organized in nested folder structures."
        ))

        self._vars['auto_detect'] = tk.BooleanVar()
        cb = ttk.Checkbutton(check_frame, text="Auto-detect systems", variable=self._vars['auto_detect'])
        cb.pack(side=tk.LEFT, padx=(0, 12))
        self._tip(cb, (
            "Identify systems from file extensions instead of folder names. "
            "Use this when ROMs are in a single flat directory."
        ))

        # Max depth
        lbl = ttk.Label(check_frame, text="Max depth:")
        lbl.pack(side=tk.LEFT)
        self._tip(lbl, "Maximum number of directory levels to scan when recursive mode is enabled.")
        self._vars['max_depth'] = tk.IntVar(value=3)
        self._tip(
            ttk.Spinbox(check_frame, from_=1, to=10, width=4, textvariable=self._vars['max_depth']),
            "Maximum number of directory levels to scan when recursive mode is enabled."
        ).pack(side=tk.LEFT, padx=(2, 0))

        tab.columnconfigure(1, weight=1)

    def _create_selection_tab(self):
        """Create the Selection tab (merged Filtering + Region/Dedupe)."""
        tab = ttk.Frame(self._notebook, padding=10)
        self._notebook.add(tab, text="Selection")

        # ── Left column: options + budget ──
        left = ttk.Frame(tab)
        left.grid(row=0, column=0, sticky=tk.NSEW, padx=(0, 6))

        # ROM selection options
        opt_frame = ttk.LabelFrame(left, text="ROM Selection", padding=6)
        opt_frame.pack(fill=tk.X)

        checks = [
            ('all', "Select all (no filter)", "Keep every ROM variant, skip 1G1R selection",
             "Skip all filtering and select every ROM. Overrides 1G1R selection, "
             "so you get every regional variant instead of just the best one."),
            ('exclude_protos', "Exclude protos", None,
             "Remove prototype ROMs from selection. "
             "Prototypes are included by default since some are the only version of a game."),
            ('english_only', "English only", "Drop Japan-only games with no translation",
             "Only keep ROMs playable in English: official English releases plus fan translations. "
             "Drops Japan-only games that have no translation available."),
            ('verbose', "Verbose output (-v)", None,
             "Show detailed filtering decisions in the output: which ROMs were selected, "
             "skipped, matched by DAT, etc."),
        ]
        for key, text, subtitle, tip in checks:
            self._vars[key] = tk.BooleanVar()
            f = ttk.Frame(opt_frame)
            f.pack(anchor=tk.W, fill=tk.X)
            cb = ttk.Checkbutton(f, text=text, variable=self._vars[key])
            cb.pack(anchor=tk.W)
            self._tip(cb, tip)
            if subtitle:
                sl = ttk.Label(f, text=subtitle, style='Sub.TLabel')
                sl.pack(anchor=tk.W, padx=(24, 0))

        # Include normally-excluded section
        inc_exc_frame = ttk.LabelFrame(opt_frame, text="Include normally-excluded", padding=4)
        inc_exc_frame.pack(fill=tk.X, pady=(6, 0))

        inc_checks = [
            ('include_betas', "Include betas",
             "Include beta/pre-release ROMs. "
             "These are excluded by default as they are usually incomplete."),
            ('include_unlicensed', "Include unlicensed",
             "Include unlicensed and pirate ROM dumps. "
             "These are excluded by default."),
        ]
        for key, text, tip in inc_checks:
            self._vars[key] = tk.BooleanVar()
            cb = ttk.Checkbutton(inc_exc_frame, text=text, variable=self._vars[key])
            cb.pack(anchor=tk.W, pady=1)
            self._tip(cb, tip)

        # Budget / Limits
        budget_frame = ttk.LabelFrame(left, text="Budget / Limits", padding=6)
        budget_frame.pack(fill=tk.X, pady=(8, 0))

        budget_tips = {
            'top': ("Top N:",
                    "Keep only the top N highest-rated games per system, or a percentage. "
                    "Examples: 50 (top 50 games) or 10% (top 10%). Requires rating data."),
            'limit': ("Limit:",
                      "Maximum total ROMs to select across all systems combined. "
                      "Selection stops once this count is reached."),
            'size': ("Size:",
                     "Maximum total size budget (e.g. 10G, 500M, 1T). "
                     "Fills the budget with the highest-rated games that fit."),
            'prefer_exclusives': ("Prefer exclusives:",
                                  "Boost the rating of platform-exclusive games by this many points "
                                  "(default: 1.0). Helps prioritize games unique to each system."),
        }
        for key, (label, tip) in budget_tips.items():
            f = ttk.Frame(budget_frame)
            f.pack(fill=tk.X, pady=1)
            self._tip(ttk.Label(f, text=label, width=18), tip).pack(side=tk.LEFT)
            self._vars[key] = tk.StringVar()
            self._tip(ttk.Entry(f, textvariable=self._vars[key], width=12), tip).pack(side=tk.LEFT)

        self._vars['include_unrated'] = tk.BooleanVar()
        cb = ttk.Checkbutton(budget_frame, text="Include unrated", variable=self._vars['include_unrated'])
        cb.pack(anchor=tk.W, pady=1)
        self._tip(cb, (
            "When using --top, append unrated games after the rated ones. "
            "Without this, games with no rating data are dropped."
        ))

        # Year range
        year_frame = ttk.Frame(budget_frame)
        year_frame.pack(fill=tk.X, pady=1)
        year_tip = "Filter games by release year. Only games within this range are included."
        self._tip(ttk.Label(year_frame, text="Year range:"), year_tip).pack(side=tk.LEFT)
        self._vars['year_from'] = tk.StringVar()
        self._tip(ttk.Entry(year_frame, textvariable=self._vars['year_from'], width=6),
                  year_tip).pack(side=tk.LEFT, padx=2)
        ttk.Label(year_frame, text="to").pack(side=tk.LEFT)
        self._vars['year_to'] = tk.StringVar()
        self._tip(ttk.Entry(year_frame, textvariable=self._vars['year_to'], width=6),
                  year_tip).pack(side=tk.LEFT, padx=2)

        # Genres
        genre_frame = ttk.Frame(budget_frame)
        genre_frame.pack(fill=tk.X, pady=1)
        genre_tip = "Comma-separated genre filter (e.g. platformer,rpg). Only games matching these genres are kept."
        self._tip(ttk.Label(genre_frame, text="Genres:", width=18), genre_tip).pack(side=tk.LEFT)
        self._vars['genres'] = tk.StringVar()
        self._tip(ttk.Entry(genre_frame, textvariable=self._vars['genres']),
                  genre_tip).pack(side=tk.LEFT, fill=tk.X, expand=True)

        # ── Right column: patterns + region/dedupe ──
        right = ttk.Frame(tab)
        right.grid(row=0, column=1, sticky=tk.NSEW)

        # Include patterns
        inc_tip = (
            "Glob-style patterns to include. Only ROMs matching at least one pattern are kept. "
            'Examples: "*Mario*", "*(USA)*", "Super *"'
        )
        self._tip(ttk.Label(right, text="Include patterns:"), inc_tip).pack(anchor=tk.W)
        inc_frame = ttk.Frame(right)
        inc_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 6))
        self._include_listbox = tk.Listbox(inc_frame, height=4, font=MONO_FONT_SMALL)
        self._include_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._tip(self._include_listbox, inc_tip)
        self._listboxes.append(self._include_listbox)
        self._listbox_data['include'] = []
        inc_btns = ttk.Frame(inc_frame)
        inc_btns.pack(side=tk.RIGHT, padx=(4, 0))
        ttk.Button(inc_btns, text="Add", command=lambda: self._add_pattern('include')).pack(fill=tk.X, pady=1)
        ttk.Button(inc_btns, text="Remove", command=lambda: self._remove_pattern('include')).pack(fill=tk.X, pady=1)

        # Exclude patterns
        exc_tip = (
            "Glob-style patterns to exclude. ROMs matching any pattern are removed. "
            'Examples: "*Beta*", "*(Japan)*", "*Demo*"'
        )
        self._tip(ttk.Label(right, text="Exclude patterns:"), exc_tip).pack(anchor=tk.W)
        exc_frame = ttk.Frame(right)
        exc_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 6))
        self._exclude_listbox = tk.Listbox(exc_frame, height=4, font=MONO_FONT_SMALL)
        self._exclude_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._tip(self._exclude_listbox, exc_tip)
        self._listboxes.append(self._exclude_listbox)
        self._listbox_data['exclude'] = []
        exc_btns = ttk.Frame(exc_frame)
        exc_btns.pack(side=tk.RIGHT, padx=(4, 0))
        ttk.Button(exc_btns, text="Add", command=lambda: self._add_pattern('exclude')).pack(fill=tk.X, pady=1)
        ttk.Button(exc_btns, text="Remove", command=lambda: self._remove_pattern('exclude')).pack(fill=tk.X, pady=1)

        # ── Region / Dedupe section ──
        region_frame = ttk.LabelFrame(right, text="Region / Dedupe", padding=6)
        region_frame.pack(fill=tk.X, pady=(0, 0))

        fields = [
            (0, "Region priority:", 'region_priority',
             "Comma-separated region order for version preference (e.g. USA,Europe,Japan). "
             "The first region listed is most preferred. Default: USA, World, Europe, Australia."),
            (1, "Keep regions:", 'keep_regions',
             "Comma-separated regions to keep multiple versions of. "
             "For example, 'USA,Japan' keeps both the English and Japanese version of each game."),
        ]
        for row, label, key, tip in fields:
            self._tip(ttk.Label(region_frame, text=label), tip).grid(row=row, column=0, sticky=tk.W, pady=1)
            self._vars[key] = tk.StringVar()
            self._tip(ttk.Entry(region_frame, textvariable=self._vars[key]), tip).grid(
                row=row, column=1, sticky=tk.EW, padx=4, pady=1
            )

        # Dedupe section with description
        dedupe_sep = ttk.Separator(region_frame, orient=tk.HORIZONTAL)
        dedupe_sep.grid(row=2, column=0, columnspan=2, sticky=tk.EW, pady=(6, 4))

        dedupe_desc = ttk.Label(
            region_frame,
            text="Remove games that exist on multiple platforms,\nkeeping only the highest-priority version.",
            style='Sub.TLabel'
        )
        dedupe_desc.grid(row=3, column=0, columnspan=2, sticky=tk.W, pady=(0, 4))

        dedup_tip = (
            "Cross-platform deduplication: comma-separated system codes, highest priority first "
            "(e.g. pc,ps2,ps1,gamecube). When the same game exists on multiple systems, "
            "only the highest-priority version is kept."
        )
        self._tip(ttk.Label(region_frame, text="Dedupe priority:"), dedup_tip).grid(
            row=4, column=0, sticky=tk.W, pady=1
        )
        self._vars['dedup_priority'] = tk.StringVar()
        self._vars['dedup_priority'].trace_add('write', lambda *_: self._update_dedupe_state())
        self._tip(ttk.Entry(region_frame, textvariable=self._vars['dedup_priority']), dedup_tip).grid(
            row=4, column=1, sticky=tk.EW, padx=4, pady=1
        )

        # Dedupe PC lists
        pc_tip = (
            "LaunchBox XML playlists of PC games to seed the dedupe system. "
            "Games in these lists are treated as already claimed by PC, "
            "so console versions of the same game are skipped."
        )
        pc_label = self._tip(ttk.Label(region_frame, text="PC lists:"), pc_tip)
        pc_label.grid(row=5, column=0, sticky=tk.NW, pady=2)
        self._dedupe_dependent_widgets.append(pc_label)

        pc_frame = ttk.Frame(region_frame)
        pc_frame.grid(row=5, column=1, sticky=tk.NSEW, padx=4, pady=2)
        self._dedup_pc_listbox = tk.Listbox(pc_frame, height=3, font=MONO_FONT_SMALL)
        self._dedup_pc_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._tip(self._dedup_pc_listbox, pc_tip)
        self._listboxes.append(self._dedup_pc_listbox)
        self._listbox_data['dedup_pc_lists'] = []
        self._dedupe_dependent_widgets.append(self._dedup_pc_listbox)

        pc_btns = ttk.Frame(pc_frame)
        pc_btns.pack(side=tk.RIGHT, padx=(4, 0))
        self._dedup_add_btn = ttk.Button(pc_btns, text="Add", command=self._add_dedup_pc_list)
        self._dedup_add_btn.pack(fill=tk.X, pady=1)
        self._dedupe_dependent_widgets.append(self._dedup_add_btn)
        self._dedup_remove_btn = ttk.Button(pc_btns, text="Remove", command=self._remove_dedup_pc_list)
        self._dedup_remove_btn.pack(fill=tk.X, pady=1)
        self._dedupe_dependent_widgets.append(self._dedup_remove_btn)

        # Dedupe delete checkbox
        dedupe_del_tip = (
            "Delete duplicate ROM files from source directories in-place instead of "
            "copying selected ROMs to a new destination. Saves disk space by removing "
            "lower-priority versions directly. Requires Dedupe priority to be set."
        )
        self._vars['dedupe_delete'] = tk.BooleanVar()
        self._dedupe_delete_cb = ttk.Checkbutton(
            region_frame, text="Delete duplicates in-place",
            variable=self._vars['dedupe_delete']
        )
        self._dedupe_delete_cb.grid(row=6, column=0, columnspan=2, sticky=tk.W, pady=(2, 0))
        self._tip(self._dedupe_delete_cb, dedupe_del_tip)
        self._dedupe_dependent_widgets.append(self._dedupe_delete_cb)

        region_frame.columnconfigure(1, weight=1)

        # Initialize dedupe state
        self._update_dedupe_state()

        tab.columnconfigure(0, weight=1)
        tab.columnconfigure(1, weight=1)
        tab.rowconfigure(0, weight=1)

    def _create_output_tab(self):
        tab = ttk.Frame(self._notebook, padding=10)
        self._notebook.add(tab, text="Output")

        row = 0
        transfer_tip = (
            "How files are transferred to the destination. Copy duplicates files, "
            "Symlink creates symbolic links (saves space), Hardlink creates hard links, "
            "Move relocates files from source."
        )
        self._tip(ttk.Label(tab, text="Transfer mode:"), transfer_tip).grid(
            row=row, column=0, sticky=tk.W, pady=2
        )
        self._vars['transfer_mode'] = tk.StringVar(value="Copy")
        self._tip(ttk.Combobox(
            tab, textvariable=self._vars['transfer_mode'],
            values=["Copy", "Symlink", "Hardlink", "Move"],
            state="readonly", width=15
        ), transfer_tip).grid(row=row, column=1, sticky=tk.W, padx=4, pady=2)

        row = 1
        check_frame = ttk.Frame(tab)
        check_frame.grid(row=row, column=0, columnspan=3, sticky=tk.W, pady=4)

        out_checks = [
            ('flat', "Flat output",
             "Put all ROMs in a single folder instead of organizing by system subfolders."),
            ('print_roms', "Print ROMs",
             "Print selected ROM filenames to the output. Useful for piping to other tools."),
            ('playlists', "Playlists (.m3u)",
             "Generate M3U playlist files for each system. Useful for multi-disc games."),
            ('gamelist', "Gamelist (.xml)",
             "Generate EmulationStation-compatible gamelist.xml files for each system."),
        ]
        for key, text, tip in out_checks:
            self._vars[key] = tk.BooleanVar()
            cb = ttk.Checkbutton(check_frame, text=text, variable=self._vars[key])
            cb.pack(side=tk.LEFT, padx=(0, 12))
            self._tip(cb, tip)

        row = 2
        ra_tip = (
            "Directory to write RetroArch .lpl playlist files. "
            "Typically your RetroArch playlists folder."
        )
        self._tip(ttk.Label(tab, text="RetroArch playlists:"), ra_tip).grid(
            row=row, column=0, sticky=tk.W, pady=2
        )
        self._vars['retroarch_playlists'] = tk.StringVar()
        self._tip(ttk.Entry(tab, textvariable=self._vars['retroarch_playlists'], width=50),
                  ra_tip).grid(row=row, column=1, sticky=tk.EW, padx=4, pady=2)
        ttk.Button(tab, text="Browse", command=lambda: self._browse_dir('retroarch_playlists')).grid(
            row=row, column=2, pady=2
        )

        row = 3
        ps_tip = (
            "When the same ROM exists in multiple sources, prefer the copy from this directory. "
            "Useful when you have a curated local set and a network fallback."
        )
        self._tip(ttk.Label(tab, text="Prefer source:"), ps_tip).grid(
            row=row, column=0, sticky=tk.W, pady=2
        )
        self._vars['prefer_source'] = tk.StringVar()
        self._tip(ttk.Entry(tab, textvariable=self._vars['prefer_source'], width=50),
                  ps_tip).grid(row=row, column=1, sticky=tk.EW, padx=4, pady=2)
        ttk.Button(tab, text="Browse", command=lambda: self._browse_dir('prefer_source')).grid(
            row=row, column=2, pady=2
        )

        tab.columnconfigure(1, weight=1)

    def _create_advanced_tab(self):
        """Create the Advanced tab (merged Network + Advanced) with scrolling."""
        outer = ttk.Frame(self._notebook)
        self._notebook.add(outer, text="Advanced")

        # Scrollable container
        canvas = tk.Canvas(outer, highlightthickness=0)
        scrollbar = ttk.Scrollbar(outer, orient=tk.VERTICAL, command=canvas.yview)
        tab = ttk.Frame(canvas, padding=10)

        tab.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=tab, anchor=tk.NW)
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self._canvases.append(canvas)

        # Bind mouse wheel for this tab
        def _bind_scroll(_event):
            canvas.bind_all('<MouseWheel>',
                            lambda e: canvas.yview_scroll(-1 * (e.delta // 120), "units"))
            canvas.bind_all('<Button-4>', lambda e: canvas.yview_scroll(-3, "units"))
            canvas.bind_all('<Button-5>', lambda e: canvas.yview_scroll(3, "units"))

        def _unbind_scroll(_event):
            canvas.unbind_all('<MouseWheel>')
            canvas.unbind_all('<Button-4>')
            canvas.unbind_all('<Button-5>')

        canvas.bind('<Enter>', _bind_scroll)
        canvas.bind('<Leave>', _unbind_scroll)

        # Match inner frame width to canvas
        def _on_canvas_resize(event):
            canvas.itemconfigure(canvas.find_all()[0], width=event.width)
        canvas.bind('<Configure>', _on_canvas_resize)

        # ── Network section ──
        net_frame = ttk.LabelFrame(tab, text="Network", padding=6)
        net_frame.grid(row=0, column=0, columnspan=3, sticky=tk.EW, pady=(0, 8))

        # Spinners row
        spin_frame = ttk.Frame(net_frame)
        spin_frame.pack(fill=tk.X)

        spinners = [
            ("Parallel downloads:", 'parallel', tk.IntVar(value=4), 1, 32,
             "Number of files to download simultaneously. "
             "Higher values speed up downloads but use more bandwidth."),
            ("Connections/file:", 'connections', tk.StringVar(), 1, 32,
             "Number of connections per file when using aria2c. "
             "Higher values can speed up large file downloads. Defaults to match parallel."),
            ("Scan workers:", 'scan_workers', tk.IntVar(value=16), 1, 64,
             "Number of parallel workers for scanning network directory listings. "
             "Higher values scan faster but may trigger rate limiting."),
        ]
        for i, (label, key, var, lo, hi, tip) in enumerate(spinners):
            self._vars[key] = var
            self._tip(ttk.Label(spin_frame, text=label), tip).grid(
                row=0, column=i * 2, sticky=tk.W, padx=(0 if i == 0 else 12, 0)
            )
            self._tip(ttk.Spinbox(spin_frame, from_=lo, to=hi, width=5, textvariable=var),
                      tip).grid(row=0, column=i * 2 + 1, sticky=tk.W, padx=(4, 0))

        # Auto-tune checkbox
        self._vars['auto_tune'] = tk.BooleanVar(value=True)
        cb = ttk.Checkbutton(net_frame, text="Auto-tune parallelism", variable=self._vars['auto_tune'])
        cb.pack(anchor=tk.W, pady=(4, 2))
        self._tip(cb, (
            "Automatically adjust parallel downloads and connections based on file sizes. "
            "Uses more connections for large files and fewer for small files."
        ))

        # Directory fields
        dir_frame = ttk.Frame(net_frame)
        dir_frame.pack(fill=tk.X, pady=(2, 0))
        dir_fields = [
            (0, "Cache dir:", 'cache_dir',
             "Directory for caching downloaded files from network sources. "
             "Defaults to a cache/ folder in the source directory. Re-runs skip cached files."),
            (1, "DAT dir:", 'dat_dir',
             "Directory for No-Intro, Redump, and MAME DAT files used for ROM verification. "
             "Defaults to dat_files/ in the source directory. Auto-downloaded on first run."),
        ]
        for row, label, key, tip in dir_fields:
            self._tip(ttk.Label(dir_frame, text=label), tip).grid(
                row=row, column=0, sticky=tk.W, pady=1
            )
            self._vars[key] = tk.StringVar()
            self._tip(ttk.Entry(dir_frame, textvariable=self._vars[key], width=50), tip).grid(
                row=row, column=1, sticky=tk.EW, padx=4, pady=1
            )
            ttk.Button(dir_frame, text="Browse", command=lambda k=key: self._browse_dir(k)).grid(
                row=row, column=2, pady=1
            )
        dir_frame.columnconfigure(1, weight=1)

        # ── Options section ──
        check_frame = ttk.LabelFrame(tab, text="Options", padding=6)
        check_frame.grid(row=1, column=0, columnspan=3, sticky=tk.EW, pady=(0, 8))

        adv_checks = [
            ('no_verify', "No verify",
             "Skip CRC32 verification of selected ROMs against DAT files. "
             "Faster but won't flag bad dumps or misnamed files."),
            ('no_cache', "No cache",
             "Skip all file caching (CRC checksums, download cache, ratings). "
             "Downloads go directly to destination, saving disk space."),
            ('no_dat', "No DAT",
             "Use filename parsing instead of DAT file metadata for ROM identification. "
             "Faster but less accurate for non-standard filenames."),
            ('no_chd', "No CHD",
             "Skip copying CHD (compressed hard disk) files for MAME arcade games. "
             "Saves significant disk space but some games won't work without them."),
            ('no_adult', "No adult",
             "Exclude adult/mature-rated MAME arcade games from selection."),
            ('tp_all_versions', "TP all versions",
             "Keep all versions of TeknoParrot arcade games instead of just the latest. "
             "By default, only the newest version of each game is selected."),
        ]
        for key, text, tip in adv_checks:
            self._vars[key] = tk.BooleanVar()
            cb = ttk.Checkbutton(check_frame, text=text, variable=self._vars[key])
            cb.pack(side=tk.LEFT, padx=(0, 12))
            self._tip(cb, tip)

        # MAME version
        row = 2
        mame_tip = (
            "Specific MAME version to use for DAT downloads (e.g. 0.274). "
            "Leave empty to auto-detect the latest available version."
        )
        self._tip(ttk.Label(tab, text="MAME version:"), mame_tip).grid(
            row=row, column=0, sticky=tk.W, pady=2
        )
        self._vars['mame_version'] = tk.StringVar()
        self._tip(ttk.Entry(tab, textvariable=self._vars['mame_version'], width=20),
                  mame_tip).grid(row=row, column=1, sticky=tk.W, padx=4, pady=2)

        # Ratings source
        row = 3
        ratings_tip = (
            "Which rating database to use for --top and --size filtering. "
            "'combined' merges IGDB + LaunchBox (best coverage), "
            "'igdb' or 'launchbox' uses one source only. "
            "Default: combined if IGDB credentials are set, else launchbox."
        )
        self._tip(ttk.Label(tab, text="Ratings source:"), ratings_tip).grid(
            row=row, column=0, sticky=tk.W, pady=2
        )
        self._vars['ratings_source'] = tk.StringVar()
        self._tip(ttk.Combobox(
            tab, textvariable=self._vars['ratings_source'],
            values=["", "combined", "igdb", "launchbox"],
            state="readonly", width=15
        ), ratings_tip).grid(row=row, column=1, sticky=tk.W, padx=4, pady=2)

        # Authentication section
        auth_frame = ttk.LabelFrame(tab, text="Authentication", padding=6)
        auth_frame.grid(row=4, column=0, columnspan=3, sticky=tk.EW, pady=(8, 4))

        auth_entries = [
            ("IA access key:", "ia_access_key", False,
             "Internet Archive S3 access key for authenticated downloads. "
             "Get credentials at https://archive.org/account/s3.php"),
            ("IA secret key:", "ia_secret_key", True,
             "Internet Archive S3 secret key. Keep this private."),
            ("IGDB client ID:", "igdb_client_id", False,
             "Twitch/IGDB client ID for game rating data. "
             "Get free credentials at https://dev.twitch.tv/console"),
            ("IGDB client secret:", "igdb_client_secret", True,
             "Twitch/IGDB client secret. Keep this private."),
        ]
        for i, (label, key, is_secret, tip) in enumerate(auth_entries):
            self._tip(ttk.Label(auth_frame, text=label), tip).grid(
                row=i, column=0, sticky=tk.W, pady=1
            )
            self._vars[key] = tk.StringVar()
            entry = ttk.Entry(
                auth_frame, textvariable=self._vars[key], width=40,
                show='*' if is_secret else ''
            )
            entry.grid(row=i, column=1, sticky=tk.EW, padx=4, pady=1)
            self._tip(entry, tip)
        auth_frame.columnconfigure(1, weight=1)

        # TeknoParrot section
        tp_frame = ttk.LabelFrame(tab, text="TeknoParrot", padding=6)
        tp_frame.grid(row=5, column=0, columnspan=3, sticky=tk.EW, pady=(4, 0))

        tp_fields = [
            (0, "Include platforms:", 'tp_include_platforms',
             'Comma-separated TeknoParrot hardware platforms to include '
             '(e.g. "Sega Nu,Taito Type X2"). Only games on these platforms are kept.'),
            (1, "Exclude platforms:", 'tp_exclude_platforms',
             "Comma-separated TeknoParrot hardware platforms to exclude. "
             "Games on these platforms are removed from selection."),
        ]
        for i, label, key, tip in tp_fields:
            self._tip(ttk.Label(tp_frame, text=label), tip).grid(
                row=i, column=0, sticky=tk.W, pady=1
            )
            self._vars[key] = tk.StringVar()
            self._tip(ttk.Entry(tp_frame, textvariable=self._vars[key], width=40), tip).grid(
                row=i, column=1, sticky=tk.EW, padx=4, pady=1
            )
        tp_frame.columnconfigure(1, weight=1)

        # Logging section
        log_frame = ttk.LabelFrame(tab, text="Logging", padding=6)
        log_frame.grid(row=6, column=0, columnspan=3, sticky=tk.EW, pady=(4, 0))

        self._vars['log_enabled'] = tk.BooleanVar()
        log_cb = ttk.Checkbutton(log_frame, text="Log output to file",
                                 variable=self._vars['log_enabled'])
        log_cb.pack(side=tk.LEFT, padx=(0, 12))
        self._tip(log_cb, (
            "Save a timestamped copy of all output to the logs/ directory. "
            "Each run creates a new log file. Useful for troubleshooting."
        ))

        log_open_btn = ttk.Button(log_frame, text="Open Logs Folder",
                                  command=self._open_logs_folder)
        log_open_btn.pack(side=tk.LEFT, padx=(0, 12))
        self._tip(log_open_btn, "Open the logs/ directory in the system file explorer.")

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

    @staticmethod
    def _source_display(path):
        """Format a source path/URL for display with a type prefix."""
        if path.startswith(('http://', 'https://')):
            return f"[HTTP]  {path}"
        return f"[LOCAL] {path}"

    @staticmethod
    def _source_raw(display_text):
        """Strip the display prefix to get the raw source path/URL."""
        for prefix in ('[HTTP]  ', '[LOCAL] '):
            if display_text.startswith(prefix):
                return display_text[len(prefix):]
        return display_text

    def _add_source_folder(self):
        path = filedialog.askdirectory()
        if path:
            self._listbox_data['source'].append(path)
            self._source_listbox.insert(tk.END, self._source_display(path))
            self._update_button_states()
            self._update_preview()

    def _add_source_url(self):
        url = tk.simpledialog.askstring("Add URL", "Enter source URL:", parent=self.root)
        if url and url.strip():
            self._listbox_data['source'].append(url.strip())
            self._source_listbox.insert(tk.END, self._source_display(url.strip()))
            self._update_button_states()
            self._update_preview()

    def _edit_source(self):
        """Edit the selected source entry."""
        sel = self._source_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        current = self._listbox_data['source'][idx]
        new_value = tk.simpledialog.askstring(
            "Edit Source", "Edit source path/URL:",
            initialvalue=current, parent=self.root
        )
        if new_value and new_value.strip():
            self._listbox_data['source'][idx] = new_value.strip()
            self._source_listbox.delete(idx)
            self._source_listbox.insert(idx, self._source_display(new_value.strip()))
            self._update_preview()

    def _remove_source(self):
        sel = self._source_listbox.curselection()
        if sel:
            idx = sel[0]
            self._source_listbox.delete(idx)
            self._listbox_data['source'].pop(idx)
            self._update_button_states()
            self._update_preview()

    def _add_pattern(self, key):
        pattern = tk.simpledialog.askstring(
            f"Add {key} pattern", "Enter glob pattern:", parent=self.root
        )
        if pattern and pattern.strip():
            self._listbox_data[key].append(pattern.strip())
            listbox = self._include_listbox if key == 'include' else self._exclude_listbox
            listbox.insert(tk.END, pattern.strip())
            self._update_preview()

    def _remove_pattern(self, key):
        listbox = self._include_listbox if key == 'include' else self._exclude_listbox
        sel = listbox.curselection()
        if sel:
            idx = sel[0]
            listbox.delete(idx)
            self._listbox_data[key].pop(idx)
            self._update_preview()

    def _add_dedup_pc_list(self):
        path = filedialog.askopenfilename(
            filetypes=[("XML files", "*.xml"), ("All files", "*.*")]
        )
        if path:
            self._listbox_data['dedup_pc_lists'].append(path)
            self._dedup_pc_listbox.insert(tk.END, path)
            self._update_preview()

    def _remove_dedup_pc_list(self):
        sel = self._dedup_pc_listbox.curselection()
        if sel:
            idx = sel[0]
            self._dedup_pc_listbox.delete(idx)
            self._listbox_data['dedup_pc_lists'].pop(idx)
            self._update_preview()

    def _has_sources(self):
        """Return True if at least one source is configured."""
        return bool(self._listbox_data.get('source'))

    def _open_logs_folder(self):
        """Open the logs directory in the system file explorer."""
        logs_dir = Path(__file__).parent / 'logs'
        logs_dir.mkdir(exist_ok=True)
        if sys.platform == 'win32':
            os.startfile(str(logs_dir))  # pylint: disable=no-member
        elif sys.platform == 'darwin':
            subprocess.Popen(['open', str(logs_dir)])  # pylint: disable=consider-using-with
        else:
            subprocess.Popen(['xdg-open', str(logs_dir)])  # pylint: disable=consider-using-with

    def _update_dedupe_state(self):
        """Enable/disable dedupe-dependent widgets based on whether priority is set."""
        has_priority = bool(self._vars.get('dedup_priority', tk.StringVar()).get().strip())
        state = tk.NORMAL if has_priority else tk.DISABLED
        for widget in self._dedupe_dependent_widgets:
            try:
                widget.configure(state=state)
            except tk.TclError:
                pass  # Some widgets don't support state
        self._update_preview()

    # ── Command preview ──────────────────────────────────────────────

    def _update_preview(self):
        """Update the command preview line with current settings."""
        if self._building:
            return
        try:
            argv = self._build_argv(commit=False)
            # Skip 'retro-refiner' prefix for brevity
            preview = ' '.join(argv[1:]) if len(argv) > 1 else '(add a source to get started)'
            self._preview_var.set(preview)
        except Exception:  # pylint: disable=broad-except
            self._preview_var.set('')

    # ── Save / Load settings ─────────────────────────────────────────

    def _serialize_state(self):
        """Serialize current GUI state to YAML lines."""
        lines = ["# Retro-Refiner GUI settings\n"]
        # Sources
        sources = self._listbox_data.get('source', [])
        if sources:
            lines.append("sources:")
            for src in sources:
                lines.append(f'  - "{src}"')
        # String vars
        for key, var in sorted(self._vars.items()):
            val = var.get()
            if isinstance(val, bool):
                if val:
                    lines.append(f"{key}: true")
            elif isinstance(val, int):
                lines.append(f"{key}: {val}")
            elif isinstance(val, str) and val.strip():
                lines.append(f'{key}: "{val.strip()}"')
        # Listbox data (patterns, pc lists)
        for key in ('include', 'exclude', 'dedup_pc_lists'):
            items = self._listbox_data.get(key, [])
            if items:
                lines.append(f"{key}:")
                for item in items:
                    lines.append(f'  - "{item}"')
        return '\n'.join(lines)

    def _restore_state(self, text):
        """Restore GUI state from YAML text. Clears existing state first."""
        # Clear existing state
        for key in ('source', 'include', 'exclude', 'dedup_pc_lists'):
            self._listbox_data[key] = []
        self._source_listbox.delete(0, tk.END)
        self._include_listbox.delete(0, tk.END)
        self._exclude_listbox.delete(0, tk.END)
        self._dedup_pc_listbox.delete(0, tk.END)
        for var in self._vars.values():
            if isinstance(var, tk.BooleanVar):
                var.set(False)
            elif isinstance(var, tk.IntVar):
                pass  # Keep defaults (parallel=4, etc.)
            elif isinstance(var, tk.StringVar):
                var.set('')
        # Restore defaults that aren't empty
        self._vars['transfer_mode'].set('Copy')
        self._vars['auto_tune'].set(True)

        # Simple YAML parsing (key: value and key:\n  - item)
        current_list_key = None
        for line in text.split('\n'):
            stripped = line.strip()
            if not stripped or stripped.startswith('#'):
                current_list_key = None
                continue
            if stripped.startswith('- '):
                # List item
                val = stripped[2:].strip().strip('"').strip("'")
                if current_list_key == 'sources':
                    self._listbox_data.setdefault('source', []).append(val)
                    self._source_listbox.insert(tk.END, self._source_display(val))
                elif current_list_key in self._listbox_data:
                    self._listbox_data[current_list_key].append(val)
                    if current_list_key == 'include':
                        self._include_listbox.insert(tk.END, val)
                    elif current_list_key == 'exclude':
                        self._exclude_listbox.insert(tk.END, val)
                    elif current_list_key == 'dedup_pc_lists':
                        self._dedup_pc_listbox.insert(tk.END, val)
                continue
            if ':' in stripped:
                key, _, val = stripped.partition(':')
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                if not val:
                    # List header
                    current_list_key = key
                    continue
                current_list_key = None
                if key in self._vars:
                    var = self._vars[key]
                    if isinstance(var, tk.BooleanVar):
                        var.set(val.lower() in ('true', '1', 'yes'))
                    elif isinstance(var, tk.IntVar):
                        try:
                            var.set(int(val))
                        except ValueError:
                            pass
                    else:
                        var.set(val)

    def _save_settings(self):
        """Export current GUI settings to a user-chosen YAML file."""
        path = filedialog.asksaveasfilename(
            defaultextension=".yaml",
            filetypes=[("YAML files", "*.yaml *.yml"), ("All files", "*.*")],
            initialfile="retro-refiner-gui-settings.yaml"
        )
        if not path:
            return
        Path(path).write_text(self._serialize_state(), encoding='utf-8')
        self._status_var.set(f"Saved: {Path(path).name}")

    def _load_settings(self):
        """Import GUI settings from a user-chosen YAML file."""
        path = filedialog.askopenfilename(
            filetypes=[("YAML files", "*.yaml *.yml"), ("All files", "*.*")]
        )
        if not path:
            return
        try:
            text = Path(path).read_text(encoding='utf-8')
        except OSError as exc:
            messagebox.showerror("Load Error", str(exc))
            return
        self._restore_state(text)
        self._update_button_states()
        self._update_preview()
        self._status_var.set(f"Loaded: {Path(path).name}")

    def _auto_save_state(self):
        """Silently save GUI state to the fixed state file."""
        try:
            _STATE_FILE.write_text(self._serialize_state(), encoding='utf-8')
        except OSError:
            pass  # Don't disrupt shutdown if write fails

    def _auto_load_state(self):
        """Silently restore GUI state from the fixed state file on startup."""
        if not _STATE_FILE.exists():
            return
        try:
            text = _STATE_FILE.read_text(encoding='utf-8')
        except OSError:
            return
        self._restore_state(text)
        self._update_button_states()
        # Hide welcome text if state was restored with sources
        if self._has_sources():
            self._clear_output()
            self._welcome_shown = False

    def _on_close(self):
        """Auto-save state and exit."""
        self._auto_save_state()
        self.root.destroy()

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
            'dedup_priority': '--dedupe-priority',
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

        # Dedupe PC lists
        for path in self._listbox_data.get('dedup_pc_lists', []):
            argv.extend(['--dedupe-pc-lists', path])
        if self._vars['dedupe_delete'].get():
            argv.append('--dedupe-delete')

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
        if self._vars['no_cache'].get():
            argv.append('--no-cache')
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

        # Always skip CLI confirmation prompts — GUI handles confirmation itself
        argv.append('--yes')

        # Logging
        if self._vars['log_enabled'].get():
            log_dir = str(Path(__file__).parent / 'logs')
            argv.extend(['--log-dir', log_dir])

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
        if not self._has_sources():
            messagebox.showwarning("No Source", "Please add at least one source directory or URL.")
            return

        # Pre-run validation warnings
        warnings = []
        if self._vars['dedupe_delete'].get() and not self._vars['dedup_priority'].get().strip():
            warnings.append("'Delete duplicates in-place' is checked but no dedupe priority is set. "
                            "The delete option will have no effect.")
        if warnings:
            msg = '\n\n'.join(warnings) + '\n\nContinue anyway?'
            if not messagebox.askyesno("Configuration Warning", msg):
                return

        # Clear welcome text on first run
        if self._welcome_shown:
            self._clear_output()
            self._welcome_shown = False

        self._running = True
        self._start_time = time.monotonic()
        self._update_button_states()
        self._progress_var.set(0)
        self._status_var.set("Running...")
        self._elapsed_var.set("0:00")

        # Start indeterminate progress bar
        self._progress_bar.configure(mode='indeterminate')
        self._progress_bar.start(15)
        self._progress_is_indeterminate = True

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
            # Close log file before restoring streams (unwraps TeeWriter)
            _module.close_log()
            sys.stdout = old_stdout
            sys.stderr = old_stderr

            # Schedule completion callback on main thread
            self.root.after(0, self._on_run_complete)

    def _on_run_complete(self):
        """Called on the main thread when the worker finishes."""
        self._running = False

        # Stop indeterminate animation if still running
        if self._progress_is_indeterminate:
            self._progress_bar.stop()
            self._progress_bar.configure(mode='determinate')
            self._progress_is_indeterminate = False

        self._update_button_states()
        # pylint: disable=protected-access
        if _module._shutdown_requested:
            self._status_var.set("Cancelled")
            _module._shutdown_requested = False
        # pylint: enable=protected-access
        else:
            self._status_var.set("Completed")
        self._progress_var.set(100)

        # Show final elapsed time
        if self._start_time:
            elapsed = time.monotonic() - self._start_time
            self._elapsed_var.set(self._format_elapsed(elapsed))
            self._start_time = None

    def _update_button_states(self):
        """Enable/disable buttons based on running state and source availability."""
        has_sources = self._has_sources()
        if self._running:
            self._dry_btn.configure(state=tk.DISABLED)
            self._commit_btn.configure(state=tk.DISABLED)
            self._cancel_btn.configure(state=tk.NORMAL)
        else:
            self._dry_btn.configure(state=tk.NORMAL if has_sources else tk.DISABLED)
            self._commit_btn.configure(state=tk.NORMAL if has_sources else tk.DISABLED)
            self._cancel_btn.configure(state=tk.DISABLED)

    def _clear_output(self):
        """Clear the output text widget."""
        self._output_text.configure(state=tk.NORMAL)
        self._output_text.delete('1.0', tk.END)
        self._output_text.configure(state=tk.DISABLED)

    def _copy_output(self):
        """Copy output text content to the system clipboard."""
        content = self._output_text.get('1.0', tk.END).strip()
        if content:
            self.root.clipboard_clear()
            self.root.clipboard_append(content)
            self._status_var.set("Copied to clipboard")

    def _copy_preview(self):
        """Copy command preview text to the system clipboard."""
        content = self._preview_var.get().strip()
        if content:
            self.root.clipboard_clear()
            self.root.clipboard_append(content)
            self._status_var.set("Command copied to clipboard")

    def _output_click(self, event):
        """Handle click in disabled output text to position cursor for selection."""
        self._output_text.configure(state=tk.NORMAL)
        self._output_text.mark_set(tk.INSERT, f"@{event.x},{event.y}")
        self._output_text.tag_remove(tk.SEL, '1.0', tk.END)
        self._output_text.configure(state=tk.DISABLED)
        return 'break'

    def _output_drag(self, event):
        """Handle click-drag in disabled output text to select text."""
        self._output_text.configure(state=tk.NORMAL)
        pos = self._output_text.index(f"@{event.x},{event.y}")
        self._output_text.tag_remove(tk.SEL, '1.0', tk.END)
        self._output_text.tag_add(tk.SEL, tk.INSERT, pos)
        self._output_text.configure(state=tk.DISABLED)
        return 'break'

    def _output_copy(self, _event=None):
        """Copy selected text from output, or all text if nothing is selected."""
        try:
            content = self._output_text.get(tk.SEL_FIRST, tk.SEL_LAST)
        except tk.TclError:
            content = self._output_text.get('1.0', tk.END).strip()
        if content:
            self.root.clipboard_clear()
            self.root.clipboard_append(content)
        return 'break'

    def _output_select_all(self, _event=None):
        """Select all text in the output widget."""
        self._output_text.configure(state=tk.NORMAL)
        self._output_text.tag_add(tk.SEL, '1.0', tk.END)
        self._output_text.configure(state=tk.DISABLED)
        return 'break'

    @staticmethod
    def _format_elapsed(seconds):
        """Format elapsed seconds as M:SS or H:MM:SS."""
        m, s = divmod(int(seconds), 60)
        if m >= 60:
            h, m = divmod(m, 60)
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m}:{s:02d}"

    # ── Theme ─────────────────────────────────────────────────────────

    def _toggle_theme(self):
        """Switch between light and dark theme."""
        self._is_dark = not self._is_dark
        self._apply_theme()

    def _apply_theme(self):
        """Apply the current theme to all widgets."""
        theme = DARK_THEME if self._is_dark else LIGHT_THEME
        theme_name = "Dark" if self._is_dark else "Light"
        self._theme_btn.configure(text=f"Theme: {theme_name}")

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

        # Command preview entry
        self._preview_entry.configure(
            readonlybackground=theme['preview_bg'],
            fg=theme['preview_fg'],
        )

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

        # Subtitle label style
        s.configure('Sub.TLabel', background=theme['frame_bg'],
                     foreground=theme['sublabel_fg'], font=('TkDefaultFont', 8))

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

        # Accent button style (for Commit button)
        s.configure('Accent.TButton', background=theme['accent_bg'],
                     foreground=theme['accent_fg'], bordercolor=theme['accent_bg'],
                     darkcolor=theme['accent_bg'], lightcolor=theme['accent_bg'])
        s.map('Accent.TButton',
              background=[('disabled', theme['button_bg']),
                          ('pressed', theme['accent_pressed_bg']),
                          ('active', theme['accent_hover_bg'])],
              foreground=[('disabled', theme['button_fg'])],
              darkcolor=[('pressed', theme['accent_pressed_bg']),
                         ('active', theme['accent_hover_bg'])],
              lightcolor=[('pressed', theme['accent_pressed_bg']),
                          ('active', theme['accent_hover_bg'])])

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

        # Separator
        s.configure('TSeparator', background=bc)

        # Window background
        self.root.configure(bg=theme['window_bg'])

    # ── Output queue polling ──────────────────────────────────────────

    def _poll_queue(self):
        """Drain the output queue into the Text widget (called every 50ms)."""
        try:
            autoscroll = self._auto_scroll.get() and self._output_text.yview()[1] >= 0.95
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

            # Update elapsed time while running
            if self._running and self._start_time:
                elapsed = time.monotonic() - self._start_time
                self._elapsed_var.set(self._format_elapsed(elapsed))

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

                # Switch from indeterminate to determinate on first percentage
                if self._progress_is_indeterminate:
                    self._progress_bar.stop()
                    self._progress_bar.configure(mode='determinate')
                    self._progress_is_indeterminate = False

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

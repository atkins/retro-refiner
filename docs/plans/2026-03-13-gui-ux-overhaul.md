# GUI UX Overhaul Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve Retro-Refiner GUI usability with tab consolidation, better feedback, and workflow guidance.

**Architecture:** All changes in `retro-refiner-gui.py`. No changes to `retro-refiner.py`. Pure Tkinter, zero new dependencies.

**Tech Stack:** Python 3.10+, tkinter (stdlib)

---

## Chunk 1: Structural — Tab Consolidation (6→4)

### Task 1: Merge Region/Dedupe into Selection tab

**Files:**
- Modify: `retro-refiner-gui.py:388-393` (tab creation calls in `_build_ui`)
- Modify: `retro-refiner-gui.py:581-713` (`_create_filtering_tab` → rename to `_create_selection_tab`)
- Delete: `retro-refiner-gui.py:714-773` (`_create_region_tab` — merge content into selection tab)

- [ ] **Step 1:** Rename `_create_filtering_tab` to `_create_selection_tab`, change tab text to "Selection"
- [ ] **Step 2:** Move Region/Dedupe content (region_priority, keep_regions, dedup_priority, dedupe PC lists, dedupe_delete checkbox) into selection tab as a new LabelFrame "Region / Dedupe" in the right column below the include/exclude patterns
- [ ] **Step 3:** Remove `_create_region_tab` method entirely
- [ ] **Step 4:** Update `_build_ui` tab creation calls: remove `_create_region_tab()`, rename `_create_filtering_tab()` to `_create_selection_tab()`

### Task 2: Merge Network into Advanced tab

**Files:**
- Modify: `retro-refiner-gui.py:900-1016` (`_create_advanced_tab` — add network content)
- Delete: `retro-refiner-gui.py:846-899` (`_create_network_tab`)

- [ ] **Step 1:** Move network controls (parallel, connections, auto-tune, scan_workers, cache_dir, dat_dir) into Advanced tab as a new LabelFrame "Network" at the top
- [ ] **Step 2:** Remove `_create_network_tab` method entirely
- [ ] **Step 3:** Update `_build_ui`: remove `_create_network_tab()` call

- [ ] **Step 4:** Test: launch GUI, verify 4 tabs appear, all widgets functional

---

## Chunk 2: Source List & Filtering Improvements

### Task 3: Source list improvements

**Files:**
- Modify: `retro-refiner-gui.py:468-500` (`_create_sources_tab` — source listbox area)
- Modify: `retro-refiner-gui.py:1035-1052` (source helper methods — add edit, update prefixes)

- [ ] **Step 1:** Increase source listbox height from 4 to 6
- [ ] **Step 2:** Add "Edit" button to source button frame
- [ ] **Step 3:** Implement `_edit_source()` method — opens dialog pre-filled with selected item
- [ ] **Step 4:** Add `[LOCAL]`/`[HTTP]` prefixes when inserting into listbox display (strip in `_build_argv`)
- [ ] **Step 5:** Update `_add_source_folder`, `_add_source_url`, `_edit_source` to use prefixes

### Task 4: Filtering visual hierarchy

**Files:**
- Modify: `_create_selection_tab` (formerly filtering tab)

- [ ] **Step 1:** Add inline grey descriptions under ambiguous checkboxes ("Select all" → subtitle "Keep every ROM variant, skip 1G1R selection")
- [ ] **Step 2:** Group "Include betas" and "Include unlicensed" under a "Include normally-excluded" visual separator
- [ ] **Step 3:** Move Budget/Limits into its own right-side section with clearer separation

### Task 5: Dedupe workflow guidance

**Files:**
- Modify: selection tab dedupe section

- [ ] **Step 1:** Add description label at top of dedupe section: "Remove games that exist on multiple platforms, keeping only the highest-priority version."
- [ ] **Step 2:** Add trace on dedup_priority variable; disable/enable PC lists and delete checkbox when priority is empty/set
- [ ] **Step 3:** Implement `_update_dedupe_state()` method called by trace

---

## Chunk 3: Button Bar & Command Preview

### Task 6: Button bar polish

**Files:**
- Modify: `retro-refiner-gui.py:431-464` (control buttons section)
- Modify: `_apply_theme` (add accent button style)

- [ ] **Step 1:** Rename "Dry Run" button to "Preview"
- [ ] **Step 2:** Add `Accent.TButton` ttk style with colored background (blue accent from theme focus_color)
- [ ] **Step 3:** Apply accent style to "Run (Commit)" button
- [ ] **Step 4:** Add "Save Settings" and "Load Settings" buttons that export/import GUI state as YAML config
- [ ] **Step 5:** Implement `_save_settings()` and `_load_settings()` methods

### Task 7: Command preview line

**Files:**
- Modify: `_build_ui` — add preview label between tabs and output

- [ ] **Step 1:** Add a read-only Entry widget showing the constructed argv, placed between the notebook and the output panel
- [ ] **Step 2:** Add `_update_preview()` method that calls `_build_argv(commit=False)` and formats it
- [ ] **Step 3:** Add variable traces on all `self._vars` entries to trigger `_update_preview()` on change
- [ ] **Step 4:** Call `_update_preview()` after listbox add/remove operations too

### Task 8: Theme toggle label

**Files:**
- Modify: `retro-refiner-gui.py:461-464` (theme button)
- Modify: `_apply_theme` (button text update)

- [ ] **Step 1:** Change theme button text from "Light"/"Dark" to "Theme: Dark"/"Theme: Light" showing current state
- [ ] **Step 2:** Increase button width to accommodate longer text

---

## Chunk 4: Output Panel & Progress

### Task 9: Output panel improvements

**Files:**
- Modify: `_build_ui` output/control section

- [ ] **Step 1:** Add "Copy" button next to "Clear Output" that copies output text to clipboard
- [ ] **Step 2:** Implement `_copy_output()` method using `root.clipboard_clear()`/`root.clipboard_append()`
- [ ] **Step 3:** Add elapsed time display — `self._start_time` set in `_start_run`, label updated in `_poll_queue`
- [ ] **Step 4:** Add "Auto-scroll" checkbox (BooleanVar, default True) in control bar; condition autoscroll on it

### Task 10: Welcome/empty state text

**Files:**
- Modify: `__init__` or `_build_ui` — insert default text

- [ ] **Step 1:** After output text is created, insert welcome message: "Getting started: Add a source folder or URL in the Sources tab, then click Preview to see what will be selected."
- [ ] **Step 2:** Clear welcome text at start of `_start_run()`

### Task 11: Disable Run buttons reactively

**Files:**
- Modify: `_update_button_states`, source add/remove methods

- [ ] **Step 1:** Add `_has_sources()` helper returning `bool(self._listbox_data.get('source'))`
- [ ] **Step 2:** In `_update_button_states`, also disable Preview/Commit when no sources and not running
- [ ] **Step 3:** Call `_update_button_states()` after every source add/remove operation

### Task 12: Progress bar improvements

**Files:**
- Modify: `_start_run`, `_on_run_complete`, `_try_parse_progress`

- [ ] **Step 1:** In `_start_run()`, set progress bar to indeterminate mode: `self._progress_bar.configure(mode='indeterminate')` and `self._progress_bar.start(15)`
- [ ] **Step 2:** In `_try_parse_progress()`, when first percentage is parsed, switch to determinate mode: `self._progress_bar.stop()` and `self._progress_bar.configure(mode='determinate')`
- [ ] **Step 3:** In `_on_run_complete()`, stop indeterminate animation and set to 100%
- [ ] **Step 4:** Parse additional progress patterns from scanner output (e.g., "Scanning:" lines with counts)

---

## Chunk 5: Validation & Final Polish

### Task 13: Pre-run validation warnings

- [ ] **Step 1:** In `_start_run()`, check for contradictory settings:
  - `dedupe_delete` checked but no `dedup_priority` → warn
  - `top`/`size` set but no IGDB credentials and no launchbox fallback awareness → info note
- [ ] **Step 2:** Show warnings via `messagebox.showwarning()` with option to continue

### Task 14: Run pylint and test

- [ ] **Step 1:** Run `python -m pylint retro-refiner-gui.py` — fix any issues (note: GUI has no pylintrc, just avoid obvious issues)
- [ ] **Step 2:** Run `python tests/test_selection.py` — verify 277 tests still pass
- [ ] **Step 3:** Launch GUI manually and verify all 4 tabs, all widgets, preview, theme toggle
- [ ] **Step 4:** Commit

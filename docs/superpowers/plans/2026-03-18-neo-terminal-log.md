# Neo-Terminal Log Output Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform the GUI log panel into a visually spectacular neo-terminal with animated boot sequences, box-drawing system headers, live progress lines, easter egg quips, expandable audit trails, and a spinning ASCII donut completion fanfare.

**Architecture:** Hybrid approach — Python emits rich structured events (`boot`, `system-start`, `filter-tick`, `system-complete`, `fanfare`) from `_do_run()` in `api.py`. A new JS `LogRenderer` object in `index.html` intercepts these events and renders them with animations, box-drawing art, and CSS effects. Existing `appendLog()` continues to handle plain `log` events unchanged.

**Tech Stack:** Python (event emission), JavaScript (LogRenderer, donut algorithm, quip pool), CSS (animations, keyframes, transitions)

**Spec:** `docs/superpowers/specs/2026-03-18-neo-terminal-log-design.md`

**Test runner:** `python tests/test_file.py` (custom TestResult framework, not pytest)

**Lint:** `python -m pylint retro_refiner/` — must stay at 10.00/10

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `retro_refiner/ui/api.py` | Modify | Emit new event types from `_do_run()` |
| `retro_refiner/ui/assets/index.html` | Modify | LogRenderer, CSS, donut, quips, all rendering |
| `tests/test_v2_modules.py` | Modify | Tests for new event emission |

---

## Task 1: Python Event Emission — boot, system-start, system-complete

Emit the three core structured events from `_do_run()`. This is the data foundation that all JS rendering depends on.

**Files:**
- Modify: `retro_refiner/ui/api.py` (lines 213-637, the `_do_run` method)

- [ ] **Step 1: Add `boot` event emission**

At the top of `_do_run()`, right after the initial `status` event (line ~225), emit the boot event:

```python
self._push_event('boot', {
    'phases': [
        'Validating sources',
        'Initializing scanner',
        'Loading DAT files',
        'Calibrating filters',
    ]
})
```

- [ ] **Step 2: Add `system-start` event emission**

Inside the system processing loop (line ~372), right before the existing `card` event with `state='filtering'`, emit system-start. Compute `display_name` from the system code:

```python
display_name = system.replace('-', ' ').replace('_', ' ').title()
if system.lower() in ('snes', 'nes', 'gba', 'gbc', 'n64', 'psx', 'ps2', 'ps3', 'psp'):
    display_name = system.upper()

self._push_event('system-start', {
    'system': system,
    'display_name': display_name,
    'total_roms': len(urls),
})
```

- [ ] **Step 3: Add `system-complete` event emission**

After the existing `card` event with `state='complete'` (line ~502), emit system-complete. Add timing with `time.monotonic()` around the per-system filtering block:

```python
# Before filter call:
t_start = time.monotonic()

# After card event:
elapsed_ms = int((time.monotonic() - t_start) * 1000)

excluded_roms = []
if result and hasattr(result, 'excluded'):
    for exc in result.excluded[:500]:
        excluded_roms.append({
            'name': exc.filename,
            'reason': exc.reason,
        })

self._push_event('system-complete', {
    'system': system,
    'display_name': display_name,
    'selected': selected_count,
    'excluded': excluded_count,
    'total': source_count,
    'size': self._format_size(selected_size),
    'breakdown': filter_breakdown,
    'elapsed_ms': elapsed_ms,
    'excluded_roms': excluded_roms,
})
```

Note: `result` is only a `FilterResult` for console systems. For MAME/TeknoParrot it will be `None` — `excluded_roms` will be empty, which is by design.

- [ ] **Step 4: Add `filter-tick` event emission**

Emit a single tick right before filtering starts (creates the live line placeholder in JS):

```python
self._push_event('filter-tick', {
    'system': system,
    'selected': 0,
    'excluded': 0,
    'processed': 0,
    'total': len(urls),
    'size_selected': '0 B',
})
```

Place after `system-start` event, before the actual filter call.

- [ ] **Step 5: Add `fanfare` event emission**

After the existing `summary` event (line ~630), emit fanfare:

```python
top_system = {'name': '', 'count': 0}
for sys_code, sys_data in self._last_results.items():
    count = len(sys_data.get('selected_urls', []))
    if count > top_system['count']:
        top_system = {
            'name': sys_code.replace('-', ' ').replace('_', ' ').title(),
            'count': count
        }

filters_applied = []
sel = self._config.selection
if sel.english_only:
    filters_applied.append('english_only')
if sel.exclude_protos:
    filters_applied.append('exclude_protos')
if sel.best_version:
    filters_applied.append('best_version')
if sel.no_unlicensed:
    filters_applied.append('no_unlicensed')

self._push_event('fanfare', {
    'systems': total_systems,
    'selected': total_selected,
    'excluded': total_excluded,
    'total_size': self._format_size(total_size),
    'elapsed': elapsed_str,
    'top_system': top_system,
    'filters_applied': filters_applied,
})
```

Note: `total_excluded` must be accumulated in the system loop. `elapsed_str` computed from run timer. These variables already exist or are easy to derive from existing `summary` data.

- [ ] **Step 6: Run tests and lint**

Run: `python tests/test_selection.py && python tests/test_v2_modules.py && python tests/test_v2_cli.py && python -m pylint retro_refiner/`

Expected: all pass, lint 10.00/10.

- [ ] **Step 7: Commit**

Message: `feat: emit structured log events (boot, system-start, system-complete, fanfare)`

---

## Task 2: CSS Foundation — Animations, Keyframes, Log Classes

Add all CSS for the LogRenderer before writing JS.

**Files:**
- Modify: `retro_refiner/ui/assets/index.html` (CSS section, lines ~1-230)

- [ ] **Step 1: Add log renderer CSS classes**

Add inside the existing `<style>` block, after the theme definitions. All classes scoped under `.log-view`:

```css
/* === Neo-Terminal Log Renderer === */
.log-view .log-boot-line { color: var(--text-muted); white-space: pre; }
.log-view .log-boot-line.ready { color: var(--accent); text-shadow: 0 0 8px var(--accent); font-weight: bold; }
.log-view .log-cursor { animation: blink-cursor 0.6s step-end infinite; color: var(--accent); }

.log-view .log-system-header { color: var(--text-heading); white-space: pre; margin: 0.6em 0 0.2em 0; overflow: hidden; }
.log-view .log-system-header .header-bar { display: inline-block; animation: draw-bar 0.3s ease-out forwards; }

.log-view .log-filter-line { white-space: pre; font-variant-numeric: tabular-nums; color: var(--text-muted); min-height: 1.5em; }
.log-view .log-filter-line .progress-bar { color: var(--accent); }

.log-view .log-breakdown { white-space: pre; color: var(--text-muted); font-variant-numeric: tabular-nums; }
.log-view .log-breakdown .count { color: var(--text-heading); }
.log-view .log-breakdown .summary-line { color: var(--accent); }

.log-view .log-quip { font-style: italic; color: var(--text-muted); opacity: 0.6; padding-left: 2ch; animation: fade-in 0.5s ease; }

.log-view .log-fanfare { white-space: pre; color: var(--text-heading); margin: 1em 0; font-variant-numeric: tabular-nums; }
.log-view .log-fanfare .fanfare-border { color: var(--accent); animation: glow-border 0.5s ease-out; }
.log-view .log-fanfare .fanfare-title { font-weight: bold; color: var(--accent); }
.log-view .log-fanfare .donut-area { display: block; line-height: 1; color: var(--text-muted); }

.log-view .log-audit-toggle { cursor: pointer; color: var(--accent); text-decoration: underline; white-space: pre; }
.log-view .log-audit-toggle:hover { opacity: 0.8; }
.log-view .log-audit-list { display: none; white-space: pre; color: var(--text-muted); max-height: 300px; overflow-y: auto; font-size: 10px; padding-left: 2ch; border-left: 1px solid var(--border-subtle); margin-left: 2ch; }
.log-view .log-audit-list.expanded { display: block; }

@keyframes blink-cursor { 0%, 100% { opacity: 1; } 50% { opacity: 0; } }
@keyframes draw-bar { from { clip-path: inset(0 100% 0 0); } to { clip-path: inset(0 0 0 0); } }
@keyframes fade-in { from { opacity: 0; } to { opacity: 0.6; } }
@keyframes glow-border { 0% { text-shadow: 0 0 12px var(--accent); } 100% { text-shadow: none; } }

@media (prefers-reduced-motion: reduce) {
  .log-view .log-cursor { animation: none; }
  .log-view .log-system-header .header-bar { animation: none; }
  .log-view .log-fanfare .fanfare-border { animation: none; }
  .log-view .log-quip { animation: none; opacity: 0.6; }
}
```

- [ ] **Step 2: Commit**

Message: `feat: add CSS foundation for neo-terminal log renderer`

---

## Task 3: LogRenderer Core — Object, Boot Sequence, Event Routing

Build the `LogRenderer` JS object with event routing and the boot typewriter effect.

**Files:**
- Modify: `retro_refiner/ui/assets/index.html` (JS section)

- [ ] **Step 1: Create LogRenderer object with event routing**

Add in the JS section, before `handlePythonEvent`. Create the object with `handle()`, `_flushQueue()`, `reset()`, and stub render methods. Wire into `handlePythonEvent` by extracting the existing handler body into `handlePythonEventOriginal`, and making the new `handlePythonEvent` try `LogRenderer.handle()` first with fallthrough.

Add `LogRenderer.reset()` call when run status becomes 'running'.

- [ ] **Step 2: Implement renderBoot with typewriter effect**

Types out each phase line character-by-character (~40-70ms per char with jitter, ~250-400ms between lines). Blinking cursor advances. "READY" line uses `.ready` class. Respects `prefers-reduced-motion` (instant render). Queues incoming events during boot, flushes after READY.

- [ ] **Step 3: Test boot sequence manually**

Run app, start preview. Verify typewriter effect, cursor blink, READY flash, and that queued events appear after boot completes.

- [ ] **Step 4: Commit**

Message: `feat: add LogRenderer core with boot typewriter sequence`

---

## Task 4: System Headers and Quips

Implement the box-drawing system headers and easter egg quip system.

**Files:**
- Modify: `retro_refiner/ui/assets/index.html` (JS section)

- [ ] **Step 1: Add quip pool**

Add `_quips` object to LogRenderer with categories: `scanning` (~10), `filtering` (~10), `system` (per-system-code entries, ~25 systems), `nerdy` (~20). Total pool ~50+ unique quips.

Add `_pickQuip(system)` method: builds combined pool from system-specific + general categories, filters out already-used quips, picks random, tracks in `_usedQuips`.

- [ ] **Step 2: Implement renderSystemStart**

Builds box-drawing header: `══╡ DISPLAY NAME ╞══════════ N ROMs ══`. Uses `clip-path` animation via `.header-bar` class. Shows quip with ~30% probability before header.

- [ ] **Step 3: Test manually**

Verify headers render with box-drawing, bar animates, quips appear ~30% of time and never repeat.

- [ ] **Step 4: Commit**

Message: `feat: add system headers with box-drawing animation and quip system`

---

## Task 5: Live Filter Line and System Complete Breakdown

Implement the in-place progress line and the final breakdown with count-up animation.

**Files:**
- Modify: `retro_refiner/ui/assets/index.html` (JS section)

- [ ] **Step 1: Implement renderFilterTick**

Creates/updates a single live DOM element per system in `_systemLines`. Renders block-char progress bar (`▓░`), processed/total counts, selected count, size. Updated in-place on each tick.

- [ ] **Step 2: Implement renderSystemComplete**

Removes live filter line. Renders breakdown line with tree-drawing chars (`├─`, `└─`). Summary line shows selected count, percentage, size, elapsed. Numbers animate via `_animateCountUp()` helper (ease-out cubic, 300ms duration). Only animates if `!_reducedMotion`.

- [ ] **Step 3: Add audit trail toggle**

If `excluded_roms` has data, append `[+]` toggle. Click handler toggles `.expanded` class on the audit list. Audit list contains padded ROM names with reasons. Lazy DOM creation (only build list elements on first expand).

- [ ] **Step 4: Test manually**

Verify: live line appears during filtering, breakdown renders on completion, numbers count up, audit toggle works, MAME systems show breakdown but no audit toggle.

- [ ] **Step 5: Commit**

Message: `feat: add live filter line, system breakdown, and audit trail`

---

## Task 6: Completion Fanfare with Spinning ASCII Donut

The grand finale.

**Files:**
- Modify: `retro_refiner/ui/assets/index.html` (JS section)

- [ ] **Step 1: Implement donut algorithm**

Add `_donut` object to LogRenderer with `renderFrame(width, height)` and `reset()`. Our own Sloane donut.c implementation: double-loop over theta/phi, torus surface math, z-buffer, luminance-to-character mapping. Character set: `.,-~:;=!*#$@`. Buffer size 20x20.

- [ ] **Step 2: Implement renderFanfare**

Animated sequence:
1. Separator line
2. Top border draws left-to-right (~200ms)
3. Title + mid bar appear
4. Stats lines appear, donut starts spinning (15fps, 75 frames = 5s)
5. Top system typewriters in
6. Bottom separator

Uses box-drawing chars: `╔═╗╚═╝║╠╣`. Sets `_fanfareShown = true` to suppress default summary.

Respects `_reducedMotion` (instant render, static donut frame).

- [ ] **Step 3: Suppress default summary when fanfare shown**

In `handlePythonEventOriginal`, check `LogRenderer._fanfareShown` before calling `renderSummary()`.

- [ ] **Step 4: Test manually**

Verify: box draws itself, donut spins for 5s then freezes, stats are correct, top system typewriters in, default summary is suppressed.

- [ ] **Step 5: Commit**

Message: `feat: add completion fanfare with spinning ASCII donut`

---

## Task 7: Integration Testing and Polish

Final pass — full flow verification, edge cases, all tests, lint.

**Files:**
- Modify: `retro_refiner/ui/api.py` (if fixes needed)
- Modify: `retro_refiner/ui/assets/index.html` (if fixes needed)

- [ ] **Step 1: Full end-to-end test**

Run app, do complete preview with multiple sources. Verify full sequence: boot -> headers -> quips -> filter lines -> breakdowns -> audit -> fanfare -> donut. Check all 10 themes. Check log scroll/copy/clear.

- [ ] **Step 2: Edge case testing**

- Single system run
- Cancel mid-run (no fanfare, no crash)
- Empty results (0 ROMs)
- Error during run
- MAME system (no audit trail)
- Rapid consecutive runs (reset clears state)

- [ ] **Step 3: Run all tests**

Run: `python tests/test_selection.py && python tests/test_v2_modules.py && python tests/test_v2_config.py && python tests/test_v2_systems.py && python tests/test_v2_paths.py && python tests/test_v2_cli.py && python tests/test_v2_integration.py`

Expected: all pass.

- [ ] **Step 4: Run lint**

Run: `python -m pylint retro_refiner/`

Expected: 10.00/10.

- [ ] **Step 5: Fix any issues found**

Address any test failures, lint warnings, or visual bugs.

- [ ] **Step 6: Final commit and push**

Message: `feat: neo-terminal log output with animations, quips, and ASCII donut`

Then push.

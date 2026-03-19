# Neo-Terminal Log Output Redesign

## Summary

Redesign the GUI log panel to be visually spectacular while surfacing richer filtering stats. The log becomes the star of the UI — a modern terminal aesthetic with box-drawing characters, animated progress, easter eggs, and a spinning ASCII donut fanfare. Cards remain unchanged.

## Approach

**Hybrid: Python Data, JS Spectacle.** Python emits rich structured events with stats and timing data. A new JS `LogRenderer` interprets these events and adds all visual flair. Existing `appendLog()` still works for plain log messages.

## Event Contract

### Existing events (unchanged)

| Event Type | Purpose |
|---|---|
| `log` | Raw text output (validation, download, errors) |
| `card` | System result card in main panel |
| `progress` | Scan progress (phase, current, total) |
| `status` | Run state (running/completed/error/cancelled) |
| `summary` | Aggregate stats at end |

### New events from Python

| Event Type | When | Data |
|---|---|---|
| `boot` | Run starts | `{ phases: string[] }` |
| `system-start` | System begins filtering | `{ system: string, display_name: string, total_roms: number }` |
| `filter-tick` | During filtering (periodic) | `{ system: string, selected: number, excluded: number, processed: number, total: number, size_selected: string }` |
| `system-complete` | System filtering done | `{ system: string, display_name: string, selected: number, excluded: number, total: number, size: string, breakdown: Record<string, number>, elapsed_ms: number, excluded_roms: Array<{name: string, reason: string}> }` |
| `fanfare` | Run complete | `{ systems: number, selected: number, excluded: number, total_size: string, elapsed: string, top_system: {name: string, count: number}, filters_applied: string[] }` |

### Design decisions

**`display_name` derivation:** No display name mapping exists in `data/systems.json`. The display name is derived in JS by replacing hyphens/underscores with spaces and title-casing: `"snes"` → `"SNES"`, `"game-boy-advance"` → `"Game Boy Advance"`. This matches what the card renderer already does.

**`filter-tick` scope:** Filtering is synchronous in-memory and typically completes in under a second per system. Adding progress callbacks to all three filter functions (`filter.py`, `mame.py`, `teknoparrot.py`) is not worth the refactor cost. Instead, `filter-tick` is emitted **once** immediately before filtering starts (with `processed: 0`) to create the live line, and the line is replaced by `system-complete` when done. For systems that take >500ms (rare, large sets), an optional timer-based synthetic tick can be added later. The live line serves primarily as a visual placeholder showing "this system is being processed."

**`excluded_roms` for MAME/TeknoParrot:** MAME and TeknoParrot filter functions return `(selected_urls, size_info_dict)` tuples, not `FilterResult` with `ExcludedRom` objects. The `excluded_roms` array will be empty for these system types. The audit trail `[+]` toggle simply won't appear when the array is empty. The breakdown dict is still available for MAME (category counts) so the summary line still renders.

**`filters_applied` source:** Derived from the `Config` object at run time — the list of config flags that were enabled. e.g., `config.selection.english_only` → `"english_only"`, `config.selection.exclude_protos` → `"exclude_protos"`, `config.selection.best_version` → `"best_version"`. This tells the user which filters were active for the run.

**`fanfare` vs `summary` ordering:** `fanfare` is emitted immediately after `summary`. The JS `handlePythonEvent` suppresses the default `summary` rendering when a `fanfare` event has been received (the fanfare contains all the same data in a richer format). The `summary` event is still emitted for backward compatibility (CLI, future consumers).

**Boot sequence event queueing:** The boot animation takes ~3-4 seconds but real `log` events (validation messages) arrive during this time. `LogRenderer` queues all incoming events during the boot sequence and flushes them after the "READY" line completes. This prevents interleaving.

### JS-only presentation (not emitted from Python)

- Boot typewriter animation timing
- ASCII system header box-drawing
- Easter egg quip selection and display
- Counter count-up animations
- Fanfare box-draw animation and spinning donut
- Audit trail expand/collapse

## LogRenderer Architecture

```
handlePythonEvent(event)
  -> LogRenderer.handle(event)
    -> routes to: renderBoot(), renderSystemStart(),
       renderFilterTick(), renderSystemComplete(), renderFanfare()
    -> falls through to appendLog() for plain 'log' events
```

`LogRenderer` is a JS object/class in `index.html`. It manages DOM elements for each active system's live line, the boot sequence, and the fanfare block. It owns a pool of quip strings and tracks which have been used in the current run.

## Spectacle Moments

### 1. Boot Sequence (~3-4 seconds)

Triggered by `boot` event. Creates a block element in the log.

- Types out each phase line character-by-character (~60ms/char, ~400ms between lines)
- Blinking `█` cursor advances with each line
- Lines use dimmed color (`--text-muted`)
- Final "READY" line flashes bright in `--accent` with brief `text-shadow` glow
- Phase strings come from Python: `["Validating sources", "Initializing scanner", "Loading DAT files", "Calibrating filters", "READY"]`

### 2. System Headers (instant with flair)

Triggered by `system-start` event.

- Box-drawing banner: `══╡ SUPER NINTENDO ╞══════════ 2,847 ROMs ══`
- The `══` bars "draw" left-to-right via CSS `clip-path` animation (~300ms)
- System name appears fully formed (no typewriter — should feel authoritative)
- ~30% chance a quip line appears below in dim italic before filtering starts
- Fade-in over ~200ms

### 3. Live Filter Line (updates in-place)

Triggered by `filter-tick` events. One live line per system, replaced in-place.

```
  ▓▓▓▓▓▓▓▓░░░░ 1,847/2,847 | selected 423 | 12.4 GB
```

- Progress bar uses block chars `░▓` in accent color
- Numbers use CSS `font-variant-numeric: tabular-nums` to prevent jitter
- On `system-complete`, bar flashes green briefly then settles into static breakdown:

```
  |- region: 1,200  duplicate: 890  proto: 45
  '- 450 selected (15.8%) | 13.1 GB | 340ms
```

- Breakdown numbers do a quick count-up animation (~300ms) from 0 to final value

### 4. Easter Egg Quips

Managed entirely in JS. Pool of ~50 rotating messages in categories:

- **Scanning:** "Consulting the ancient DAT scrolls...", "Searching for proto cartridges in the couch cushions..."
- **Filtering:** "Separating the wheat from the chaff...", "Applying the 1G1R sacred texts..."
- **System-specific:** "It's-a me, filtering!" (nes/snes), "SEGA!" (genesis/gamegear), "Blast processing engaged" (genesis)
- **Nerdy:** "Reticulating splines...", "Reversing the polarity...", "Adjusting the flux capacitor..."

Behavior:
- Appear in dim italic, slightly indented
- Shown between ~30% of systems (random)
- Never repeat within a single run
- Fade in, hold, then dim further (remain in log history, don't disappear)

### 5. Completion Fanfare (~6 seconds total)

Triggered by `fanfare` event. A dramatic box-drawing summary with a spinning ASCII donut.

```
----------------------------------------------------

  +==========================================+
  |           SCAN COMPLETE                  |
  +==========================================+
  |                                          |
  |   Systems    24      Selected  8,430     |
  |   Excluded   42,000  Size    1.2 TB      |
  |   Elapsed    4m 32s             ,oo.     |
  |                                :o  o;    |
  |                                 `oo'     |
  +==========================================+

        * Top: PlayStation (1,200)

----------------------------------------------------
```

Animation sequence:
1. Top border draws left-to-right (~200ms)
2. Side borders drop down (~200ms)
3. Content fades in, numbers count up from 0 (~400ms)
4. Bottom border closes (~200ms)
5. Border characters get brief `text-shadow` glow in accent color, fades over ~500ms
6. Spinning ASCII donut (20x20 chars) renders live in right-hand area for ~5 seconds at 15fps
7. Donut freezes on final frame, remains as static art
8. `Top` line typewriters in last

Donut implementation: our own Sloane donut.c algorithm (~60-80 lines of JS including buffer management and DOM updates). Pure trig math (sin/cos over torus surface), character-based depth shading with z-buffer, 20x20 text buffer rendered into a `<pre>` block via `textContent` replacement at 15fps.

### 6. Audit Trail (expandable, no animation)

Part of `system-complete` rendering. After each system's breakdown line:

```
  |- [+] 2,397 excluded ROMs
  |   Super Mario World (Europe).zip         region (USA preferred)
  |   Super Mario World (Japan).zip          region (USA preferred)
  |   Pilotwings (Proto).zip                 prototype
  |   ...
```

- `[+]` toggle expands/collapses via JS click handler
- Scrollable block with max-height when expanded
- Collapsed by default — doesn't clutter the spectacle
- No animation — fast and functional for power users
- Data comes from `excluded_roms` array in `system-complete` event

## Files to Modify

### Python (event emission)

- **`retro_refiner/ui/api.py`** — Emit new event types (`boot`, `system-start`, `filter-tick`, `system-complete`, `fanfare`) from `_do_run()`. Add timing instrumentation. Build `excluded_roms` list from `FilterResult.excluded`. Compute `elapsed_ms` per system.
- **`retro_refiner/models.py`** — May need to extend `FilterResult` or `ExcludedRom` if additional data is needed for the audit trail.

### JavaScript (rendering)

- **`retro_refiner/ui/assets/index.html`** — Add `LogRenderer` class/object with all rendering methods. Add donut algorithm. Add quip pool. Add CSS for animations (glow keyframes, clip-path transitions, tabular-nums, expand/collapse). Modify `handlePythonEvent()` to route new events through `LogRenderer`.

### CSS additions (within index.html)

- `.log-boot-line` — typewriter styling, cursor blink
- `.log-system-header` — box-drawing banner, clip-path animation
- `.log-filter-line` — tabular-nums, progress bar colors
- `.log-breakdown` — tree-drawing chars, count-up transitions
- `.log-quip` — dim italic, fade-in
- `.log-fanfare` — glow keyframes, box-draw animation
- `.log-audit` — expandable block, max-height, scrollable
- `.log-donut` — monospace pre block for donut render

## Performance Considerations

- `filter-tick` is a single event per system (not continuous) — see Design Decisions
- Donut runs at 15fps for 5 seconds = 75 frames, then stops — negligible cost
- Counter animations use `requestAnimationFrame` with duration cap
- Audit trail DOM nodes only created on expand (lazy)
- All CSS animations use `transform`/`opacity` where possible for GPU compositing

## Theme Compatibility

All new CSS classes use existing theme variables:
- `--accent` for highlights, progress bar, glow
- `--text-muted` for dimmed content, quips
- `--text-heading` for system headers
- `--bg-panel` for audit trail background
- `--border-subtle` for box-drawing characters
- `--success` for completion flash

No hardcoded colors. Light themes work automatically.

All new CSS classes are scoped under `.log-view` to avoid collision with existing `.log-info`, `.log-success`, `.log-warning`, `.log-error` classes.

## Accessibility

Respect `prefers-reduced-motion: reduce` media query. When active:
- Boot sequence appears instantly (no typewriter delay)
- System headers appear without clip-path animation
- Counter numbers appear at final values (no count-up)
- Fanfare box appears fully rendered (no draw animation)
- Donut renders a single static frame instead of spinning
- Quips still appear (they're content, not motion)

## What Stays the Same

- Result cards — unchanged
- Plain `log` events — still go through `appendLog()`
- `progress` events for scanning — still handled by existing code
- `status` events — unchanged
- `summary` event — still emitted (fanfare is additional, not replacement)
- All existing config, sidebar, ROM picker functionality — untouched

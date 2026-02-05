# Top-N Games Feature Design

**Date:** 2026-02-04
**Status:** Approved

## Overview

Add the ability to filter ROM collections to only include the top N highest-rated games per system, using LaunchBox community ratings as the data source.

## User Interface

### CLI Arguments

```
--top N                 Keep only top N rated games per system
--include-unrated       Include games without ratings (after rated games)
```

### Examples

```bash
# Top 50 rated games per system
python retro-refiner.py -s /roms --top 50 --commit

# Top 25 Mario games
python retro-refiner.py -s /roms --top 25 --include "*Mario*" --commit

# Top 100, including unrated games if slots remain
python retro-refiner.py -s /roms --top 100 --include-unrated --commit
```

### Config File

```yaml
top: 50
include_unrated: false
```

## Data Source

**LaunchBox Games Database** (https://gamesdb.launchbox-app.com/)

- Download URL: http://gamesdb.launchbox-app.com/Metadata.zip
- Size: ~50MB compressed, ~480MB uncompressed
- Updated daily
- Fields used:
  - `CommunityRating` - User rating (0-5 scale)
  - `CommunityRatingCount` - Number of votes
  - `Name` - Game title
  - `Platform` - System name

## Data Storage

```
dat_files/
  launchbox/
    Metadata.xml        # Full database (~480MB)
    ratings_cache.json  # Extracted ratings index (~5-10MB)
```

### Ratings Cache Format

```json
{
  "snes": {
    "super mario world": {"rating": 4.73, "votes": 892},
    "legend of zelda a link to the past": {"rating": 4.81, "votes": 756}
  },
  "nes": {
    "super mario bros": {"rating": 4.52, "votes": 1203}
  }
}
```

### Platform Name Mapping

LaunchBox uses full platform names that must be mapped to retro-refiner system codes:

```python
LAUNCHBOX_PLATFORM_MAP = {
    "Super Nintendo Entertainment System": "snes",
    "Nintendo Entertainment System": "nes",
    "Sega Genesis": "genesis",
    "Sega Mega Drive": "genesis",
    "Nintendo 64": "n64",
    "Sony Playstation": "psx",
    "Nintendo Game Boy": "gameboy",
    "Nintendo Game Boy Color": "gameboy-color",
    "Nintendo Game Boy Advance": "gba",
    # ... etc for all 144 supported systems
}
```

## Processing Pipeline

```
1. Scan source -> find all ROMs
2. Parse filenames -> extract metadata (region, revision, etc.)
3. Apply --include/--exclude filters
4. Group by normalized title -> select best version per game
5. [NEW] If --top N specified:
   a. Load LaunchBox ratings for this system
   b. Match ROMs to LaunchBox entries by normalized name
   c. Sort by CommunityRating (descending)
   d. Take top N rated games
   e. If --include-unrated: append unrated games until N reached
6. Transfer files to destination
```

## ROM Matching

ROMs are matched to LaunchBox entries using normalized titles:

```
ROM filename: "Super Mario World (USA).zip"
    |
    v parse_rom_filename()
Base title: "Super Mario World"
    |
    v normalize_title()
Lookup key: "super mario world"
    |
    v match against ratings_cache
LaunchBox entry with rating: 4.73
```

Matching leverages existing `title_mappings.json` for regional name variants (e.g., "Rockman" -> "Mega Man").

## Download Behavior

1. **First run with `--top`:** Check if `Metadata.xml` exists
   - If missing: prompt user, download ~50MB zip, extract
   - If exists: use cached data
2. **`--update-dats` flag:** Re-downloads LaunchBox data alongside other DATs
3. **Cache rebuild:** `ratings_cache.json` is rebuilt if older than `Metadata.xml`

## Output

### Console Output

```
--- SNES (--top 50) ------------------------------------------------
  Rating data: 847 of 1,243 games matched (68%)

  [OK] Super Mario World                          * 4.73 (892 votes)
  [OK] Legend of Zelda, The - A Link to the Past  * 4.81 (756 votes)
  [OK] Chrono Trigger                             * 4.89 (634 votes)
  ...

  Selected: 50 | Skipped (unrated): 396 | Skipped (below top 50): 797
```

### Selection Log

Additions to `_selection_log.txt`:

```
=== TOP 50 SELECTION (by LaunchBox CommunityRating) ===
#1  *4.89  Chrono Trigger (USA).zip
#2  *4.81  Legend of Zelda, The - A Link to the Past (USA).zip
#3  *4.73  Super Mario World (USA).zip
...
#50 *3.92  Some Game (USA).zip

EXCLUDED (unrated): 396 games
EXCLUDED (below cutoff *3.92): 797 games
```

## Key Functions to Add

```python
def download_launchbox_data(dat_dir: str) -> bool:
    """Download LaunchBox Metadata.zip and extract."""

def build_ratings_cache(xml_path: str, cache_path: str) -> dict:
    """Parse Metadata.xml and build ratings lookup by platform/title."""

def load_ratings_cache(dat_dir: str, system: str) -> dict:
    """Load ratings for a specific system from cache."""

def match_rom_to_rating(rom: RomInfo, ratings: dict) -> Optional[float]:
    """Match a ROM to its LaunchBox rating by normalized title."""

def apply_top_n_filter(roms: List[RomInfo], ratings: dict,
                       top_n: int, include_unrated: bool) -> List[RomInfo]:
    """Filter ROMs to top N by rating."""
```

## Edge Cases

1. **System not in LaunchBox:** Log warning, include all games (no filtering)
2. **No rated games for system:** If `--include-unrated`, include all; otherwise include none
3. **Fewer than N rated games:** Include all rated, fill remainder with unrated if flag set
4. **Tie scores:** Secondary sort by vote count (more votes = higher confidence)

## Testing

- Unit tests for rating matching with various title formats
- Unit tests for top-N selection with rated/unrated mixes
- Integration test with sample LaunchBox data subset

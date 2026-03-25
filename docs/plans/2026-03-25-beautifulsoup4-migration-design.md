# BeautifulSoup4 Migration Design

## Goal

Replace regex-based HTML parsing in `network.py` with BeautifulSoup4 for more robust, maintainable parsing of directory listing pages from Myrient, archive.org, and other ROM sources.

## Scope

Replace the internals of `extract_links_from_html()` and `extract_file_sizes_from_html()` in `retro_refiner/network.py`. The 3 public functions (`parse_html_for_files`, `parse_html_for_files_with_sizes`, `parse_html_for_directories`) keep identical signatures.

## What BS4 Replaces

| Current regex | BS4 replacement |
|---|---|
| `_RE_HREF` — find `href="..."` | `soup.find_all('a', href=True)` |
| `_RE_SRC` — find `src="..."` on ROM files | `soup.find_all(src=True)` |
| `_RE_DATA_ATTR` — find `data-url/href/src/link/file` | `soup.find_all(attrs={'data-url': True})` etc. |
| `_RE_ONCLICK` — find `onclick="location.href='...'"` | `soup.find_all(onclick=True)` + regex on value |
| `_RE_URL_PATH` — bare paths in text | Keep as-is (text content, not HTML structure) |
| `_RE_TEXT_FILE` — ROM filenames in `<pre>` text | `soup.find_all('pre')` → `.get_text()` + regex |
| `_RE_PRE_SECTION` — find `<pre>` blocks | `soup.find_all('pre')` |
| `_RE_MYRIENT_SIZE` — `<td class="size">` cells | `soup.find_all('td', class_='link')` → sibling |
| `_RE_AUTOINDEX_SIZE` — autoindex size after link | `soup.find_all('a')` + parse text after anchor |
| `_RE_TABLE_ROW_SIZE` — generic `<tr>` with `<a>` + `<td>` | `soup.find_all('tr')` → find `<a>` + `<td>` |
| `_RE_FTP_LISTING` — FTP text in `<pre>` | Keep regex (parses text, not HTML) |
| `_RE_SIMPLE_SIZE` — `filename size` text | Keep regex (parses text, not HTML) |

## What Stays as Regex

- `_RE_FTP_LISTING` and `_RE_SIMPLE_SIZE` — parse text content inside `<pre>` blocks
- `_RE_SIZE_STRING` / `parse_size_string()` — parses size strings like "1.5M"
- `_RE_URL_PATH` — finds bare paths in text content
- `is_rom_file()`, `is_directory_link()`, `normalize_url()` — pure string logic

## Key Behaviors to Preserve

1. Size extraction cascade: Myrient → autoindex → generic table → FTP listing. Return early when a pattern matches.
2. Both `href` value and display filename stored in size map (callers look up by either).
3. `extract_links_from_html` finds links in `href`, `src`, `data-*` attributes, `onclick` handlers, bare URL paths, and filenames in `<pre>` blocks.
4. Archive.org compatibility: Pattern 2/3 handles archive.org directory listings. The 200KB regex scan limit for Pattern 3 becomes unnecessary with BS4 (no backtracking risk).

## Parser Choice

Use `html.parser` (Python stdlib) as the BS4 backend, not `lxml`. This avoids adding a C dependency and is fast enough for directory listing pages (typically < 2MB).

```python
from bs4 import BeautifulSoup
soup = BeautifulSoup(html, 'html.parser')
```

## Files Changed

| File | Change |
|------|--------|
| `retro_refiner/network.py` | Rewrite `extract_links_from_html()` and `extract_file_sizes_from_html()` with BS4. Delete ~12 regex patterns. |
| `tests/test_network.py` | No changes expected — tests verify function outputs with real HTML, not regex internals. |

## Dependencies

- **Add**: `beautifulsoup4` (pip install beautifulsoup4, import as `bs4`)
- No new C dependencies (uses stdlib `html.parser` backend)

## Testing

All existing HTML parsing tests should pass unchanged. The test suite uses raw HTML strings that represent real Myrient, archive.org, and Apache autoindex pages. These test the public function contracts, not implementation details.

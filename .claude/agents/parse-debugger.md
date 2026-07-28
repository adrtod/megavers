---
name: parse-debugger
description: Diagnoses why specific files are missing or wrong in megavers-analyze output. Use when parse() produces unexpected results — missing files, wrong version counts, bad sizes. Requires a --raw-dump file.
tools: Read, Bash
---

You diagnose failures in the megavers `parse()` function at /media/adrien/data/MEGAsync/megavers/analyze_versions.py.

## How to get a raw dump

If the user doesn't have one:
```bash
megavers-analyze --raw-dump raw.txt
```
Or for a specific path:
```bash
megavers-analyze /some/path --raw-dump raw.txt
```

## parse() state machine — full spec

Input: lines from `mega-ls -l -r --versions --show-handles --time-format=ISO6081_WITH_TIME`

Three state variables:
- `current_dir` — updated on each `path:` section header
- `versions_of_path` — set on `Versions of <path>:`, cleared on next section header or unrecognised line
- `version_line_idx` — reset to 0 on each new versions block; index 0 = current version (skip)

**Line classification (in order):**
1. Blank / decoration (`|`, all dashes+spaces) → skip
2. `FLAGS VERS SIZE DATE NAME` header → skip
3. `Versions of <path>:` → enter versions block, set `versions_of_path`, reset `version_line_idx = 0`
4. `<path>:` section header (not matching NODE_RE) → set `current_dir`, clear `versions_of_path`
5. NODE_RE match → file/version node line (see below)
6. Anything else → clear `versions_of_path`, continue

**NODE_RE pattern:**
```
^([a-z-]{4})\s+(\d+|-)\s+(\d+|-)\s+(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})\s+(?:(H:[A-Za-z0-9]+)\s+)?(.+)$
```
Groups: flags, vers, size, date, handle (optional), name

**Inside a versions block:**
- `version_line_idx == 0`: current version → skip, increment
- `version_line_idx > 0`: old version → append `OldVersion(size, mtime, version_num=vers, handle)` to `versioned[versions_of_path]`
- Name has `#<timestamp>` suffix stripped: `re.sub(r'#\d+$', '', name)`

**Regular directory listing (not in versions block):**
- Skip if `is_dir` (flags[0] == 'd') or `vers <= 1`
- Otherwise: `full_path = current_dir.rstrip('/') + '/' + name`, add to `versioned`

## Diagnostic procedure

1. **Read the raw dump** provided by the user.

2. **Identify the missing/wrong file** — get its exact MEGA path from the user.

3. **Trace the section header** — find the `<dir>:` line that should set `current_dir` to the file's parent directory. Check:
   - Does the path start with `/`? (`normalize_path` prepends `/` if missing)
   - Is there a decoration box around it that could be mistaken for the header?

4. **Find the file's node line** in the directory listing. Check:
   - Does it match NODE_RE? Test with Python: `NODE_RE.match(line.strip())`
   - Is `VERS > 1`? If `VERS == 1` the file is correctly excluded.
   - Is `flags[0] != 'd'`? Directories are skipped.

5. **Find the `Versions of <path>:` block**. Check:
   - Does the path in the block exactly match `full_path` computed in step 3?
   - Is there anything between the directory listing and the versions block that could have cleared `versions_of_path` (an unrecognised line, another section header)?

6. **Count version lines in the block**:
   - Line 0 = current version (skipped)
   - Lines 1..N = old versions
   - Does the count match what the user expects?

7. **Check handle parsing** — if handles are missing, verify `--show-handles` was passed to `mega-ls`.

8. **Report findings** clearly: which rule caused the file to be missed or miscounted, with the exact offending line(s) quoted from the raw dump.

# megavers

[![CI](https://github.com/adrtod/megavers/actions/workflows/ci.yml/badge.svg)](https://github.com/adrtod/megavers/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/megavers)](https://pypi.org/project/megavers/)
[![Downloads](https://img.shields.io/pypi/dm/megavers)](https://pypi.org/project/megavers/)
[![Python](https://img.shields.io/pypi/pyversions/megavers)](https://pypi.org/project/megavers/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Tools for analyzing and selectively pruning file version history in a [MEGA](https://mega.nz) cloud storage account.

## Contents

- [Motivation](#motivation)
- [Requirements](#requirements)
- [Install](#install)
  - [megavers](#install-megavers)
  - [MEGAcmd](#install-megacmd)
  - [Log in](#log-in)
- [Quickstart](#quickstart)
- [Walkthrough](#walkthrough)
- [Commands](#commands)
  - [`megavers-analyze` — Space analyzer](#megavers-analyze)
  - [`.megavers.toml` — Filter definitions](#megavers-toml)
  - [`megavers-prune` — Version pruner](#megavers-prune)
- [Contributing](#contributing)

## Motivation

[MEGA](https://mega.nz) keeps full version history for every file it syncs. Over time this accumulates silently and can consume significant storage quota. MEGA's own web/desktop clients only offer all-or-nothing clearing of previous versions — either per file, or for every file in the account at once — with no way to keep the last few versions, apply an age cutoff, or target files matching a pattern. This toolset fills that gap: see exactly how much space versions are consuming and which files are the worst offenders, then prune selectively — by file/folder pattern, extension, age, or "keep the N most recent" — instead of losing all history or none.

## Requirements

- **Python** ≥ 3.11 — uses `tomllib` from the standard library
- **[MEGAcmd](https://github.com/meganz/MEGAcmd)** ≥ 2.5 — official MEGA CLI with version support

No third-party Python packages required.

## Install

### megavers
<a id="install-megavers"></a>

```bash
pip install megavers
# or, in an isolated environment:
pipx install megavers
```

### [MEGAcmd](https://github.com/meganz/MEGAcmd) (Ubuntu / Debian)
<a id="install-megacmd"></a>

MEGAcmd is separate from the MEGAsync desktop client and must be installed independently:

```bash
sudo apt install megacmd
```

If the package is not found, add the MEGA repository first:

```bash
curl -fsSL https://mega.nz/linux/repo/xUbuntu_$(lsb_release -rs)/Release.key \
  | sudo gpg --dearmor -o /usr/share/keyrings/mega-keyring.gpg
echo "deb [signed-by=/usr/share/keyrings/mega-keyring.gpg] \
  https://mega.nz/linux/repo/xUbuntu_$(lsb_release -rs)/ ./" \
  | sudo tee /etc/apt/sources.list.d/megacmd.list
sudo apt update && sudo apt install megacmd
```

### Log in

MEGAcmd maintains its own session, independent of [MEGAsync](https://mega.nz/sync):

```bash
mega-login your@email.com
# prompts for password interactively — do not pass the password as an argument,
# as it would be visible in shell history and process listings
```

Verify with:

```bash
mega-whoami
```

## Quickstart

```bash
megavers-analyze                # see what's eating your quota
megavers-prune --init-config    # optional: copy the default filters so you can customize them
megavers-prune                  # preview what would be deleted (dry-run by default — nothing is deleted yet)
megavers-prune --yes            # actually delete, once you're happy with the preview
```

`megavers-prune` uses a handful of broadly-applicable filters out of the box (git internals, OS junk files, Python caches) — the `--init-config` step above is only needed if you want to add or change filters. The walkthrough below shows a complete example, including how to write your own filters for your own storage patterns.

## Walkthrough

A full cleanup example, putting `megavers-analyze` and `megavers-prune` together on a real account:

1. **Analyze, and look for patterns — not just individual files.** Run a scan and check the three ranked tables for *folders or extensions* that show up repeatedly, not one-off large files.

    ```bash
    megavers-analyze --top 30 --json results.json   # save so prune can reuse the scan
    ```

    A snippet from a real scan:

    ```
     VER SPACE   VERS    CUR SIZE  PATH
        3.1 GB     46    312.4 MB  /MEGAsync/Backups/project-backup.zip
    ...
      V/DAY   VERS  PATH
       8.62    101  /MEGAsync/code/project/__pycache__/utils.cpython-312.pyc
    ```

    `utils.cpython-312.pyc` dominates the version-count and churn-rate tables (101 versions, ~8.6/day — recompiled on every test run) — that's a build artifact, not something worth keeping version history for at all. `Backups/project-backup.zip` topping the space table is a different pattern: worth keeping *some* history, but maybe not all 46 copies.

2. **Add or adjust filters** in `.megavers.toml` for what you found. Bootstrap a config first if you don't have one:

    ```bash
    megavers-prune --init-config   # writes ~/.config/megavers/config.toml
    ```

    The bundled `python-bytecode` filter already covers `.pyc`/`.pyo` churn. For the backups pattern, add your own:

    ```toml
    [[filter]]
    name = "backups"
    description = "Old backup archives — keep a few, not all"
    path_contains = ["/MEGAsync/Backups/"]
    extensions = [".zip"]
    ```

3. **Preview with `megavers-prune` before deleting anything.** No `--yes` yet — scope it to just the new filter first, so you can check it matches what you expect without the noise of every other active filter:

    ```bash
    megavers-prune --from-json results.json --filter backups --keep-n 5
    ```

    Check the dry-run report — files affected, versions to delete, space to recover. Once it looks right, re-run the identical command with `--yes` appended to actually delete:

    ```bash
    megavers-prune --from-json results.json --filter backups --keep-n 5 --yes
    ```

    Drop `--filter backups` (and `--from-json`, to pick up any changes since the scan) once you're comfortable running all your configured filters together.

4. **Once your filters are dialed in, run `megavers-prune --yes` periodically** to keep version buildup from creeping back — e.g. weekly by hand:

    ```bash
    megavers-prune --yes   # every configured filter, no dry-run
    ```

    Or via [cron](https://man7.org/linux/man-pages/man5/crontab.5.html):

    ```cron
    # MEGAcmd keeps its login session on disk, so cron doesn't need to log in again
    # Runs every Sunday at 3:00 AM; on failure, prints a clearly-flagged line
    # instead of a normal-looking log entry, so a broken session doesn't go unnoticed
    0 3 * * 0 megavers-prune --yes >> ~/megavers.log 2>&1 || echo "$(date): FAILED - check 'mega-whoami'; session may need 'mega-login' again" >> ~/megavers.log
    ```

    The login session (`~/.megaCmd/session`) can be invalidated by an explicit `mega-logout`, a password change, or MEGA revoking the device — if that happens, the cron job can't recover on its own (`mega-login` needs an interactive password prompt, and putting a password in the crontab would defeat the point of avoiding shell history exposure). Check the log occasionally, or re-run `mega-login` interactively if you see a `FAILED` line.

    No `--keep-n`/`--older-than` needed at this point unless you want them — with none set, matched files have *all* their old versions deleted, keeping only the current one. Re-run without `--yes` occasionally afterward to sanity-check what the filters are still catching.

## Commands

### `megavers-analyze` — Space analyzer
<a id="megavers-analyze"></a>

Scans your MEGA account via [MEGAcmd](https://github.com/meganz/MEGAcmd) and produces a ranked report of versioning space usage.

```
usage: megavers-analyze [-h] [--version] [--top N] [--json FILE] [--raw-dump FILE]
                         [-v | -q] [path]

positional arguments:
  path           Cloud path to analyze, absolute (default: /)

options:
  --version      Show version and exit
  --top N        Number of top files to display (default: 20)
  --json FILE    Save full results as JSON
  --raw-dump FILE  Save raw mega-ls output for debugging
  -v, --verbose  Show debug output (e.g. the mega-* commands being run)
  -q, --quiet    Suppress progress messages; only warnings/errors and the report
                 are shown
```

The report has three ranked tables:

1. **By version space** — which files consume the most quota through old versions
2. **By version count** — which files have the most historical snapshots
3. **By churn rate** — which files change most frequently (versions/day), useful for spotting files that should be excluded from sync entirely

**Examples:**

```bash
# Analyze entire account
megavers-analyze

# Analyze a specific subfolder, show top 30, save JSON
megavers-analyze /MEGAsync/MyFolder --top 30 --json results.json

# Debug: inspect raw mega-ls output
megavers-analyze --raw-dump raw.txt
```

**Example output:**

```
============================================================================
MEGA VERSIONING SPACE REPORT
============================================================================
  Files with old versions:         1204
  Total old version count:         8731
  Space used by old versions:      12.7 GB
  Overhead vs. current file size:  26.3%

TOP 20 FILES BY VERSION SPACE
----------------------------------------------------------------------------
 VER SPACE   VERS    CUR SIZE  PATH
----------------------------------------------------------------------------
    3.1 GB     46    312.4 MB  /MEGAsync/Backups/project-backup.zip
                   oldest:     2025-04-12 09:15 UTC
...

TOP 20 FILES BY VERSION COUNT
----------------------------------------------------------------------------
 VERS   VER SPACE    CUR SIZE  PATH
----------------------------------------------------------------------------
  101      4.1 MB     41.0 KB  /MEGAsync/code/project/__pycache__/utils.cpython-312.pyc
...

TOP 20 FILES BY CHURN RATE (versions/day)
----------------------------------------------------------------------------
  V/DAY   VERS         SINCE  PATH
----------------------------------------------------------------------------
   8.62    101  2026-07-16 14:20 UTC  /MEGAsync/code/project/__pycache__/utils.cpython-312.pyc
   2.20     44  2026-07-08 12:36 UTC  /MEGAsync/code/script.py
...
```

"Overhead vs. current file size" is the ratio of old-version space to current-file space, computed only over files that have old versions — it does not include files with a single version.

### `.megavers.toml` — Filter definitions
<a id="megavers-toml"></a>

Filters are defined in a config file. Each filter has a name and at least one of: a list of path substrings (`path_contains`, case-sensitive, matching MEGA's own path semantics) or a list of extensions. If both are set, both must match (AND). Across filters, any match selects the file (OR). A filter with neither `path_contains` nor `extensions` is rejected at startup, since it would otherwise match every file in the account.

**Syntax**, shown using two of the bundled filters plus a commented-out custom one:

```toml
[[filter]]
name = "os-junk"
description = "OS-generated metadata files (macOS Finder, Windows Explorer)"
path_contains = ["/.DS_Store", "/Thumbs.db", "/desktop.ini"]

[[filter]]
name = "python-bytecode"
description = "Compiled Python bytecode and JIT cache files"
extensions = [".pyc", ".pyo"]

# [[filter]]
# name = "results"
# description = "Binary output files under result/sandbox directories"
# path_contains = ["/results/", "/sandbox/", "/outputs/"]
# extensions = [".pkl", ".gz", ".png", ".csv"]   # etc.
```

Add, remove, or modify filters freely — the tool has no hardcoded logic.

**The bundled default.** The snippet above is only a syntax sample, not the full file — see [`megavers/config.toml`](megavers/config.toml) for the real thing. It ships with more filters active than shown above — broadly applicable ones regardless of your workflow: common OS/editor junk files (`.DS_Store`, `Thumbs.db`, `desktop.ini`, Vim swap files, Office lock files), Python caches (`__pycache__`, `.pytest_cache`, `.pyc`/`.pyo`, etc.), and git internals — plus the `results` filter above included commented out as a more workflow-specific example.

**Creating your own.** Run `megavers-prune --init-config` to copy the bundled default to `~/.config/megavers/config.toml` as a starting point (pass a path to write it elsewhere; it refuses to overwrite an existing file). Or write `./.megavers.toml` / `~/.config/megavers/config.toml` from scratch, using the syntax above. For one-off needs without any config file at all, use `--path-contains` / `--ext` on the command line instead.

**Listing what's active.** Run `megavers-prune --list-filters` to see the full current list of filters in effect (bundled default, or your own config if you've created one).

### `megavers-prune` — Version pruner
<a id="megavers-prune"></a>

Deletes old version histories for files matched by filters in `.megavers.toml` using [MEGAcmd](https://github.com/meganz/MEGAcmd). **Only previews by default — pass `--yes` to actually delete.** The current (latest) version of every file is always kept.

> **Warning:** deletion is permanent. MEGA does not keep a recycle bin for pruned versions — once deleted with `--yes`, old versions cannot be recovered. Always run without `--yes` first (or with `--dry-run`) to review what would be deleted.

```
usage: megavers-prune [-h] [--from-json FILE] [--config FILE]
                         [--filter NAME] [--path-contains STR] [--ext EXT]
                         [--min-version-size SIZE] [--keep-n N] [--older-than DAYS]
                         [--yes] [--dry-run] [--list-filters] [--init-config [PATH]]
                         [--version] [-v | -q] [path]

source:
  path                  Cloud path to scan, absolute (default: /)
  --from-json FILE      Load from megavers-analyze --json output (skips re-scanning)
  --config FILE         Config file path (default: ./.megavers.toml → ~/.config/megavers/config.toml → bundled)

filters:
  --filter NAME         Activate only this config filter by name (repeatable;
                        default: all filters in config)
  --path-contains STR   Ad-hoc: select files whose path contains STR (repeatable)
  --ext EXT             Ad-hoc: select files with this extension (repeatable)
  --min-version-size SIZE  Only select files where version space >= SIZE (e.g. 10MB)

version selection (applied after filters):
  --keep-n N            Keep the N most recent old versions; delete the rest
  --older-than DAYS     Delete old versions whose age exceeds DAYS days

mode:
  --yes                 Actually delete. Without this flag, only a preview is shown.
  --dry-run             Preview what would be deleted (the default; this flag mainly
                        exists to make an already-explicit preview clearer).
  --list-filters        List filters defined in config and exit.
  --init-config [PATH]  Write a copy of the bundled default config to PATH
                        (default: ~/.config/megavers/config.toml) and exit.
  --version             Show version and exit
  -v, --verbose         Show debug output (e.g. the mega-* commands being run)
  -q, --quiet           Suppress progress messages; only warnings/errors and the
                        report are shown
```

Old-version dates from MEGA are in UTC; `--older-than` cutoffs are computed in UTC too, regardless of your local timezone.

**Examples:**

```bash
# Preview what would be deleted (default — nothing is deleted without --yes)
megavers-prune

# Actually delete, using all filters from .megavers.toml
megavers-prune --yes

# Run only the 'python-bytecode' filter
megavers-prune --filter python-bytecode --yes

# Preview keeping only the 3 most recent old versions per matched file
megavers-prune --keep-n 3

# Delete versions older than 90 days (all filters)
megavers-prune --older-than 90 --yes

# Ad-hoc: any file whose path contains 'backup'
megavers-prune --path-contains backup --yes

# Reuse a previously saved scan
megavers-prune --from-json results.json
```

## Contributing

Bug reports, feature requests, and pull requests are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md) for setup, tests, and PR expectations.

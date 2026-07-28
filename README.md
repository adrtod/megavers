# megavers

Tools for analyzing and selectively pruning file version history in a MEGA cloud storage account.

## Motivation

MEGA keeps full version history for every file it syncs. Over time this accumulates silently and can consume significant storage quota. This toolset lets you see exactly how much space versions are consuming and which files are the worst offenders, before deciding what to delete.

## Scripts

### `megavers-analyze` — Space analyzer

Scans your MEGA account via MEGAcmd and produces a ranked report of versioning space usage.

```
usage: megavers-analyze [-h] [--top N] [--json FILE] [--raw-dump FILE] [path]

positional arguments:
  path           Cloud path to analyze (default: /)

options:
  --top N        Number of top files to display (default: 20)
  --json FILE    Save full results as JSON
  --raw-dump FILE  Save raw mega-ls output for debugging
```

The report has three ranked tables:

1. **By version space** — which files consume the most quota through old versions
2. **By version count** — which files have the most historical snapshots
3. **By churn rate** — which files change most frequently (versions/day), useful for spotting files that should be excluded from sync entirely

**Example output:**

```
============================================================================
MEGA VERSIONING SPACE REPORT
============================================================================
  Files with old versions:         1 204
  Total old version count:         8 731
  Space used by old versions:      12.7 GB
  Overhead vs. current file size:  26.3%

TOP 20 FILES BY VERSION SPACE
----------------------------------------------------------------------------
 VER SPACE   VERS    CUR SIZE  PATH
----------------------------------------------------------------------------
    3.1 GB     46    312.4 MB  /MEGAsync/Backups/project-backup.zip
                   oldest:     2023-04-12 09:15
...

TOP 20 FILES BY VERSION COUNT
----------------------------------------------------------------------------
 VERS   VER SPACE    CUR SIZE  PATH
----------------------------------------------------------------------------
  101      3.0 MB     39.0 KB  /MEGAsync/code/repo/.git/FETCH_HEAD
...

TOP 20 FILES BY CHURN RATE (versions/day)
----------------------------------------------------------------------------
  V/DAY   VERS         SINCE  PATH
----------------------------------------------------------------------------
  95.71    101  2026-07-27 10:24  /MEGAsync/code/repo/.git/FETCH_HEAD
   2.20     44  2026-07-08 12:36  /MEGAsync/code/script.py
...
```

### `config.toml` — Filter definitions

Filters are defined in `config.toml`. Each filter has a name, an optional list of path substrings, and an optional list of extensions. Within a filter, both conditions must be satisfied (AND). Across filters, any match selects the file (OR).

```toml
[[filter]]
name = "git"
description = "Git repository internals"
path_contains = ["/.git/"]

[[filter]]
name = "results"
description = "Binary output files under result/sandbox directories"
path_contains = ["/results/", "/sandbox/", "/outputs/"]
extensions = [".pkl", ".gz", ".png", ".csv"]   # etc.
```

Add, remove, or modify filters freely — the tool has no hardcoded logic.

### `megavers-prune` — Version pruner

Deletes old version histories for files matched by filters in `config.toml`. Deletes by default — pass `--dry-run` to preview first. The current (latest) version of every file is always kept.

```
usage: megavers-prune [-h] [--from-json FILE] [--config FILE]
                         [--filter NAME] [--path-contains STR] [--ext EXT]
                         [--min-version-size SIZE] [--keep-n N] [--older-than DAYS]
                         [--dry-run] [--list-filters] [path]

source:
  path                  Cloud path to scan (default: /)
  --from-json FILE      Load from megavers-analyze --json output (skips re-scanning)
  --config FILE         Config file path (default: ./config.toml → ~/.config/megavers/config.toml → bundled)

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
  --dry-run             Preview what would be deleted without actually deleting.
  --list-filters        List filters defined in config and exit.
```

**Examples:**

```bash
# Delete with all filters from config.toml
megavers-prune

# Preview before deleting
megavers-prune --dry-run

# Run only the 'git' filter
megavers-prune --filter git

# Keep only the 3 most recent old versions per matched file
megavers-prune --keep-n 3 --dry-run

# Delete versions older than 90 days (all filters)
megavers-prune --older-than 90

# Ad-hoc: any file whose path contains 'backup'
megavers-prune --path-contains backup

# Reuse a previously saved scan
megavers-prune --from-json results.json
```

## How MEGA versioning works

Each time a synced file is modified, MEGA stores the previous copy as a version. `mega-ls -l` reports the total version count in the `VERS` column. With the `--versions` flag it emits a `Versions of <path>:` block after each directory listing, containing all versions in descending order (current first). The analyzer parses this structure: the first entry in each block is the live file (already counted in current size); all subsequent entries are old versions whose sizes are summed.

## Requirements

- **Python** ≥ 3.11 — uses `tomllib` from the standard library
- **MEGAcmd** ≥ 2.5 — official MEGA CLI with version support

No third-party Python packages required.

## Install

### MEGAcmd (Ubuntu / Debian)

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

MEGAcmd maintains its own session, independent of MEGAsync:

```bash
mega-login your@email.com
# prompts for password interactively — do not pass the password as an argument,
# as it would be visible in shell history and process listings
```

Verify with:

```bash
mega-whoami
```

## Usage

```bash
# Analyze entire account
megavers-analyze

# Analyze a specific subfolder, show top 30, save JSON
megavers-analyze /MEGAsync/MyFolder --top 30 --json results.json

# Debug: inspect raw mega-ls output
megavers-analyze --raw-dump raw.txt
```


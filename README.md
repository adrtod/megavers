# mega-version-cleaner

Tools for analyzing and selectively pruning file version history in a MEGA cloud storage account.

## Motivation

MEGA keeps full version history for every file it syncs. Over time this accumulates silently and can consume significant storage quota. This toolset lets you see exactly how much space versions are consuming and which files are the worst offenders, before deciding what to delete.

## Scripts

### `analyze_versions.py` — Space analyzer

Scans your MEGA account via MEGAcmd and produces a ranked report of versioning space usage.

```
usage: analyze_versions.py [-h] [--top N] [--json FILE] [--raw-dump FILE] [path]

positional arguments:
  path           Cloud path to analyze (default: /)

options:
  --top N        Number of top files to display (default: 20)
  --json FILE    Save full results as JSON
  --raw-dump FILE  Save raw mega-ls output for debugging
```

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

### `prune_versions.py` — Version pruner

Deletes old version histories for files matched by filters in `config.toml`. Deletes by default — pass `--dry-run` to preview first. The current (latest) version of every file is always kept.

```
usage: prune_versions.py [-h] [--from-json FILE] [--config FILE]
                         [--filter NAME] [--path-contains STR] [--ext EXT]
                         [--min-version-size SIZE] [--keep-n N] [--older-than DAYS]
                         [--dry-run] [--list-filters] [path]

source:
  path                  Cloud path to scan (default: /)
  --from-json FILE      Load from analyze_versions.py --json output (skips re-scanning)
  --config FILE         Config file path (default: config.toml next to this script)

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
python3 prune_versions.py

# Preview before deleting
python3 prune_versions.py --dry-run

# Run only the 'git' filter
python3 prune_versions.py --filter git

# Keep only the 3 most recent old versions per matched file
python3 prune_versions.py --keep-n 3 --dry-run

# Delete versions older than 90 days (all filters)
python3 prune_versions.py --older-than 90

# Ad-hoc: any file whose path contains 'backup'
python3 prune_versions.py --path-contains backup

# Reuse a previously saved scan
python3 prune_versions.py --from-json results.json
```

## How MEGA versioning works

Each time a synced file is modified, MEGA stores the previous copy as a version. `mega-ls -l` reports the total version count in the `VERS` column. With the `--versions` flag it emits a `Versions of <path>:` block after each directory listing, containing all versions in descending order (current first). The analyzer parses this structure: the first entry in each block is the live file (already counted in current size); all subsequent entries are old versions whose sizes are summed.

## Requirements

- **MEGAcmd** ≥ 2.5 — official MEGA CLI with version support

No Python dependencies beyond the standard library.

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
# prompts for password interactively
```

Verify with:

```bash
mega-whoami
```

## Usage

```bash
# Analyze entire account
python3 analyze_versions.py

# Analyze a specific subfolder, show top 30, save JSON
python3 analyze_versions.py /MEGAsync/FindNOrder --top 30 --json results.json

# Debug: inspect raw mega-ls output
python3 analyze_versions.py --raw-dump raw.txt
```

## Roadmap

- [x] `prune_versions.py` — selective pruner driven by `config.toml`, with `--filter`, `--path-contains`, `--ext` overrides
- [x] Dry-run mode with summary before any deletion
- [x] Keep N most recent versions with `--keep-n`
- [x] Drop versions older than X days with `--older-than`

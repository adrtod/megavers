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

### `prune_versions.py` — Version pruner

Deletes old version histories for files matched by one or more filters. Always dry-runs by default — pass `--execute` to actually delete. The current (latest) version of every file is always kept.

```
usage: prune_versions.py [-h] [--from-json FILE]
                         [--no-git] [--no-results] [--path-contains STR] [--ext EXT]
                         [--min-version-size SIZE] [--keep-n N] [--older-than DAYS]
                         [--dry-run] [path]

source:
  path                  Cloud path to scan (default: /)
  --from-json FILE      Load from analyze_versions.py --json output (skips re-scanning)

filters (combinable, OR logic — git and results are on by default):
  --no-git              Disable the .git/ filter
  --no-results          Disable the binary result/output files filter
  --path-contains STR   Select files whose path contains STR (repeatable)
  --ext EXT             Select files with this extension, e.g. .pkl (repeatable)
  --min-version-size SIZE  Only select files where version space >= SIZE (e.g. 50MB)

version selection (applied after filters):
  --keep-n N            Keep the N most recent old versions; delete the rest
  --older-than DAYS     Delete old versions whose age exceeds DAYS days

mode:
  --dry-run             Preview what would be deleted without actually deleting.
```

**Examples:**

```bash
# Delete with default filters (git + results)
python3 prune_versions.py

# Preview before deleting
python3 prune_versions.py --dry-run

# Keep only the 3 most recent old versions of each matched file
python3 prune_versions.py --keep-n 3 --dry-run

# Delete versions older than 90 days for all files (not just git/results)
python3 prune_versions.py --no-git --no-results --older-than 90

# Delete, reusing a previously saved scan to avoid re-fetching
python3 prune_versions.py --from-json results.json

# Only git, skip results
python3 prune_versions.py --no-results
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

- [x] `prune_versions.py` — selective pruner (git + results on by default, `--path-contains`, `--ext` for extra filters)
- [x] Dry-run mode with summary before any deletion
- [x] Keep N most recent versions with `--keep-n`
- [x] Drop versions older than X days with `--older-than`

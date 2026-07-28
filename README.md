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
                         [--git] [--results] [--path-contains STR] [--ext EXT]
                         [--min-version-size SIZE] [--execute] [path]

source:
  path                Cloud path to scan (default: /)
  --from-json FILE    Load from analyze_versions.py --json output (skips re-scanning)

filters (combinable, OR logic — git is on by default):
  --no-git            Disable the .git/ filter
  --results           Binary output files (.pkl, .tar.gz, .png …) under results/ or sandbox/ dirs
  --path-contains S   Path contains the given string (repeatable)
  --ext EXT           File extension, e.g. .pkl (repeatable)
  --min-version-size  Only select files where version space >= SIZE (e.g. 50MB)

mode:
  --execute           Actually delete. Without this flag: dry-run only.
```

**Examples:**

```bash
# Preview .git/ versions (default behaviour)
python3 prune_versions.py

# Also include result files, only if version overhead > 50 MB
python3 prune_versions.py --results --min-version-size 50MB

# Delete, reusing a previously saved scan to avoid re-fetching
python3 prune_versions.py --results --from-json results.json --execute

# Delete versions of all .pkl files (git filter still applies too)
python3 prune_versions.py --ext .pkl --execute

# Only .pkl files, skip git
python3 prune_versions.py --no-git --ext .pkl --execute
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

- [x] `prune_versions.py` — selective pruner with `--git`, `--results`, `--path-contains`, `--ext` filters
- [x] Dry-run mode with summary before any deletion
- [ ] Keep N most recent versions instead of deleting all
- [ ] Drop versions older than X days

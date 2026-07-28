# Changelog

All notable changes to this project will be documented in this file.

## [0.1.0] — 2026-07-28

Initial release.

### Added
- `megavers-analyze` — scans a MEGA account via MEGAcmd and reports versioning space
  usage ranked by version space, version count, and churn rate (versions/day)
- `megavers-prune` — selectively deletes old file versions based on filters defined
  in `config.toml`; supports `--yes`, `--dry-run`, `--keep-n`, `--older-than`,
  `--filter`, `--path-contains`, `--ext`, `--min-version-size`, `--list-filters`.
  Only previews by default — nothing is deleted without `--yes`.
- Config file lookup chain: `./config.toml` → `~/.config/megavers/config.toml`
  → bundled default
- JSON export (`--json`) and re-import (`--from-json`) to avoid re-scanning
- Handle-based deletion (`mega-rm`) for every version selected for pruning, so
  paths are never passed to MEGAcmd as (potentially wildcard) patterns
- `--version` flag on both commands

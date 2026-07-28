# Changelog

All notable changes to this project will be documented in this file.

## [0.1.0] — 2026-07-28

Initial release.

### Added
- `megavers-analyze` — scans a MEGA account via MEGAcmd and reports versioning space
  usage ranked by version space, version count, and churn rate (versions/day)
- `megavers-prune` — selectively deletes old file versions based on filters defined
  in `config.toml`; supports `--dry-run`, `--keep-n`, `--older-than`, `--filter`,
  `--path-contains`, `--ext`, `--min-version-size`, `--list-filters`
- Config file lookup chain: `./config.toml` → `~/.config/megavers/config.toml`
  → bundled default
- JSON export (`--json`) and re-import (`--from-json`) to avoid re-scanning
- Handle-based per-version deletion (`mega-rm`) for selective pruning;
  bulk deletion (`mega-deleteversions`) for all-or-nothing fast path
- `--version` flag on both commands

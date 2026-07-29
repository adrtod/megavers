# Changelog

All notable changes to this project will be documented in this file.

## [0.1.1] — 2026-07-29

### Changed
- The cwd-searched config file is now `.megavers.toml` (was `config.toml`) so
  the file is self-identifying when found in a project directory, matching
  the convention of tools like `.flake8`/`.prettierrc`. The `~/.config/megavers/`
  location is unaffected — that directory already namespaces it.

### Added
- `-v`/`--verbose` and `-q`/`--quiet` flags on both commands. Progress and
  warning/error messages now go through `logging` to stderr instead of `print`,
  so stdout carries only the report/JSON output; `--verbose` additionally logs
  the underlying `mega-*` commands being run.
- `megavers-prune --init-config [PATH]` — writes a copy of the bundled default
  config to `~/.config/megavers/config.toml` (or `PATH`) as a starting point
  for customization. Refuses to overwrite an existing file. Passing an
  existing directory (e.g. `.`) writes `.megavers.toml` inside it rather than
  refusing.

## [0.1.0] — 2026-07-28

Initial release.

### Added
- `megavers-analyze` — scans a MEGA account via MEGAcmd and reports versioning space
  usage ranked by version space, version count, and churn rate (versions/day).
  Dates are reported in UTC, matching what MEGA itself records.
- `megavers-prune` — selectively deletes old file versions based on filters defined
  in `config.toml`; supports `--yes`, `--dry-run`, `--keep-n`, `--older-than`,
  `--filter`, `--path-contains`, `--ext`, `--min-version-size`, `--list-filters`.
  Only previews by default — nothing is deleted without `--yes`. `--older-than`
  cutoffs are computed in UTC regardless of local timezone.
- Config file lookup chain: `./config.toml` → `~/.config/megavers/config.toml`
  → bundled default. Filters must have a name and at least one of
  `path_contains`/`extensions` — a filter with neither, or an unrecognized key,
  is rejected at startup rather than silently matching everything.
- Bundled default config ships with a few broadly-applicable filters active
  (git internals, OS/editor junk files, Python caches) and a workflow-specific
  example (`results`) included commented out
- JSON export (`--json`) and re-import (`--from-json`) to avoid re-scanning
- Handle-based deletion (`mega-rm`) for every version selected for pruning, so
  paths are never passed to MEGAcmd as (potentially wildcard) patterns
- `--version` flag on both commands

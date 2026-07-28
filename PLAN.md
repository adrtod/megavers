# Open-source release plan

## Distribution

- [x] `pyproject.toml` — package metadata, `megavers-analyze` and `megavers-prune` CLI entry points
- [x] Config file lookup: current dir → `~/.config/megavers/config.toml` → bundled default
- [x] Update GitHub URL in `pyproject.toml` once repo is created
- [x] Publish to PyPI so users can `pip install megavers` — [v0.1.0 live](https://pypi.org/project/megavers/0.1.0/)

## Pre-publish review (2026-07-28)

Opus-reviewed the codebase for correctness/safety/packaging issues before the first
PyPI release. All must-fix and should-fix items addressed:
- [x] Restructured into a proper `megavers/` package; bundled `config.toml` as
      package-data (previously not shipped in the wheel at all)
- [x] Fixed wrong-file path derivation, `#` suffix over-stripping, fragile block
      termination, and unenforced version ordering in `parse()`
- [x] Switched deletion to handle-based (`mega-rm`), since paths are wildcard
      patterns to MEGAcmd with no literal-path mode
- [x] Unified dry-run preview and real execution onto the same row computation
- [x] Fixed UTC-vs-local time bug in `--older-than` and churn rate
- [x] Rejected config filters with no criteria / unrecognised keys / no name
- [x] Rejected negative `--keep-n` / `--older-than`
- [x] `megavers-prune` now requires `--yes` to actually delete (was delete-by-default)
- [x] `run_mega()`: explicit UTF-8 decoding, `stdin=DEVNULL`, friendly missing-MEGAcmd error
- [x] Added tests for the deletion path, config lookup, and CLI argument parsing

## Robustness

- [ ] Auto-start MEGAcmd server if not running (`mega-cmd` in background before first API call)
- [x] Surface skipped files — `warn_on_count_mismatches()` flags files where mega-ls
      reports more total versions than were parsed (e.g. contact-owned versions)
- [ ] Timeout / retry on large accounts — `mega-ls -r /` can take minutes or fail mid-stream
- [ ] Progress indicator during scan (spinner or live line count)

## Testing

- [x] Unit tests for `parse()` — cover edge cases in `mega-ls` output formatting
- [x] Unit tests for filter logic (`build_filter_fn`, `apply_filters`, `versions_to_delete`)
- [x] CI with GitHub Actions — run tests on push ✓ green on 3.11/3.12/3.13

## Cross-platform

- [ ] MEGAcmd install instructions for macOS and Windows in README
- [ ] Test on macOS (MEGAcmd paths and behaviour may differ)

## Usability

- [x] `--version` flag
- [x] `CHANGELOG.md`
- [x] README badges (license, Python version, PyPI)
- [x] Warn in README that `mega-login email password` exposes password in shell history — prefer interactive `mega-login email`

## Lower priority

- [ ] `CONTRIBUTING.md`
- [ ] `--verbose` / `--quiet` flags using `logging` instead of `print`

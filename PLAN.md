# Open-source release plan

## Distribution

- [x] `pyproject.toml` — package metadata, `megavers-analyze` and `megavers-prune` CLI entry points
- [x] Config file lookup: current dir → `~/.config/megavers/config.toml` → bundled default
- [x] Update GitHub URL in `pyproject.toml` once repo is created
- [ ] Publish to PyPI so users can `pip install megavers`

## Robustness

- [ ] Auto-start MEGAcmd server if not running (`mega-cmd` in background before first API call)
- [ ] Surface skipped files — `deleteversions` silently ignores versions owned by contacts; detect and warn
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

# Open-source release plan

## Distribution

- [ ] `pyproject.toml` — package metadata, dependencies, CLI entry point (`mega-version-cleaner` command)
- [ ] Publish to PyPI so users can `pip install mega-version-cleaner`
- [ ] Config file fallback to `~/.config/mega-version-cleaner/config.toml` for installed use

## Robustness

- [ ] Auto-start MEGAcmd server if not running (`mega-cmd` in background before first API call)
- [ ] Surface skipped files — `deleteversions` silently ignores versions owned by contacts; detect and warn
- [ ] Timeout / retry on large accounts — `mega-ls -r /` can take minutes or fail mid-stream
- [ ] Progress indicator during scan (spinner or live line count)

## Testing

- [ ] Unit tests for `parse()` — cover edge cases in `mega-ls` output formatting
- [ ] Unit tests for filter logic (`build_filter_fn`, `apply_filters`, `versions_to_delete`)
- [ ] CI with GitHub Actions — run tests on push

## Cross-platform

- [ ] MEGAcmd install instructions for macOS and Windows in README
- [ ] Test on macOS (MEGAcmd paths and behaviour may differ)

## Usability

- [ ] `--version` flag
- [ ] `CHANGELOG.md`
- [ ] README badges (license, Python version, PyPI)
- [ ] Warn in README that `mega-login email password` exposes password in shell history — prefer interactive `mega-login email`

## Lower priority

- [ ] `CONTRIBUTING.md`
- [ ] `--verbose` / `--quiet` flags using `logging` instead of `print`

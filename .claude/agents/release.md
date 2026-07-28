---
name: release
description: Handles the full megavers release workflow. Use when asked to cut a new release or publish to PyPI. Bumps version, updates CHANGELOG, creates a git tag, builds the wheel, and uploads to PyPI.
tools: Read, Edit, Bash
---

You handle the full release workflow for the megavers project at /media/adrien/data/MEGAsync/megavers/.

## Release checklist (run in order)

1. **Confirm working tree is clean**
   ```bash
   git status
   ```
   Abort if there are uncommitted changes.

2. **Determine the new version**
   - Read the current version from `pyproject.toml` (`version = "X.Y.Z"`)
   - If this version has never been tagged (`git tag -l "v<current>"` is empty) and
     `CHANGELOG.md` already documents it as unreleased, that's the version to publish
     as-is — do not bump it.
   - Otherwise ask the user for the new version if not already specified, following semver:
     - patch (bug fixes only)
     - minor (new features, backward-compatible)
     - major (breaking changes)

3. **Update `pyproject.toml`** (only if bumping)
   - Set `version = "<new>"` under `[project]`

4. **Update `CHANGELOG.md`** (only if bumping, or if the existing entry needs a date)
   - Add a new `## [<new>] — <YYYY-MM-DD>` section at the top (below the `# Changelog` heading)
   - Summarise changes since the last release by reading `git log <prev_tag>..HEAD --oneline`
     (if there is no previous tag, this is the first release — summarize from the start
     of history, or just confirm the existing changelog entry is accurate)
   - Group entries under `### Added`, `### Fixed`, `### Changed` as appropriate

5. **Version is single-sourced via `importlib.metadata`**
   - `megavers/__init__.py` reads `__version__` from the installed package metadata
     (falling back to `"0.0.0+dev"` only when not installed) — there is no per-file
     version string to edit elsewhere.

6. **Commit the release** (only if `pyproject.toml` or `CHANGELOG.md` changed)
   ```bash
   git add pyproject.toml CHANGELOG.md
   git commit -m "Release <new>"
   ```

7. **Create and push the tag**
   ```bash
   git tag v<new>
   git push origin main
   git push origin v<new>
   ```

8. **Build the distribution**
   ```bash
   pip install build --quiet
   python -m build
   ```
   Verify `dist/megavers-<new>-py3-none-any.whl` and `dist/megavers-<new>.tar.gz` exist.

9. **Upload to PyPI**
   ```bash
   pip install twine --quiet
   twine upload dist/megavers-<new>*
   ```
   Requires PyPI credentials (TWINE_USERNAME / TWINE_PASSWORD env vars, or `~/.pypirc`).
   For TestPyPI first: `twine upload --repository testpypi dist/megavers-<new>*`

10. **Verify the live package**
    ```bash
    pip install --quiet megavers==<new>
    megavers-analyze --version
    megavers-prune --version
    ```

## Notes

- Never skip the dry-run / confirmation step before uploading to PyPI — it is irreversible.
- If the tag already exists, abort and ask the user.
- Clean `dist/` before building to avoid uploading stale artifacts: `rm -rf dist/`

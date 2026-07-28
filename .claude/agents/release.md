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
   - Ask the user for the new version if not already specified, following semver:
     - patch (bug fixes only)
     - minor (new features, backward-compatible)
     - major (breaking changes)

3. **Update `pyproject.toml`**
   - Set `version = "<new>"` under `[project]`

4. **Update `CHANGELOG.md`**
   - Add a new `## [<new>] — <YYYY-MM-DD>` section at the top (below the `# Changelog` heading)
   - Summarise changes since the last release by reading `git log <prev_tag>..HEAD --oneline`
   - Group entries under `### Added`, `### Fixed`, `### Changed` as appropriate

5. **Update `analyze_versions.py` fallback version**
   - Find the `__version__ = "X.Y.Z"` fallback in the `except PackageNotFoundError` block
   - Update it to match the new version

6. **Commit the release**
   ```bash
   git add pyproject.toml CHANGELOG.md analyze_versions.py
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
    pip install --quiet megavers=<new>
    megavers-analyze --version
    megavers-prune --version
    ```

## Notes

- Never skip the dry-run / confirmation step before uploading to PyPI — it is irreversible.
- If the tag already exists, abort and ask the user.
- Clean `dist/` before building to avoid uploading stale artifacts: `rm -rf dist/`

---
name: release
description: Handles the full megavers release workflow. Use when asked to cut a new release or publish to PyPI. Bumps version, updates CHANGELOG, creates and pushes a git tag, then waits for GitHub Actions to build and publish to PyPI.
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

3. **Ensure `hatch` is available**
   ```bash
   pip install hatch --quiet
   ```
   Used below for the version bump. Building and publishing happen in
   GitHub Actions now, not locally.

4. **Bump the version** (only if bumping, per step 2)
   ```bash
   hatch version <new>
   ```
   This reads and rewrites the static `version = "..."` field under `[project]` in
   `pyproject.toml`. `hatch version` refuses to set a version that isn't strictly
   higher than the current one — if that happens, double-check the intended version
   before overriding.

5. **Update `CHANGELOG.md`** (only if bumping, or if the existing entry needs a date)
   - Add a new `## [<new>] — <YYYY-MM-DD>` section at the top (below the `# Changelog` heading)
   - Summarise changes since the last release by reading `git log <prev_tag>..HEAD --oneline`
     (if there is no previous tag, this is the first release — summarize from the start
     of history, or just confirm the existing changelog entry is accurate)
   - Group entries under `### Added`, `### Fixed`, `### Changed` as appropriate

6. **Version is single-sourced via `importlib.metadata`**
   - `megavers/__init__.py` reads `__version__` from the installed package metadata
     (falling back to `"0.0.0+dev"` only when not installed) — there is no per-file
     version string to edit elsewhere.

7. **Commit the release** (only if `pyproject.toml` or `CHANGELOG.md` changed)
   ```bash
   git add pyproject.toml CHANGELOG.md
   git commit -m "Release <new>"
   ```

8. **Create and push the tag**
   ```bash
   git tag v<new>
   git push origin main
   git push origin v<new>
   ```

9. **Wait for GitHub Actions to build and publish**
   Pushing the `v<new>` tag in step 8 triggers `.github/workflows/release.yml`
   (test → build → publish, using PyPI Trusted Publishing — no local
   credentials involved). Find the exact run tied to the tagged commit
   (don't rely on "most recent run" — sleep briefly first, since GitHub
   needs a moment to register the triggered run) and watch it to completion:
   ```bash
   sleep 5
   RUN_ID=$(gh run list --workflow=release.yml --commit="$(git rev-parse HEAD)" --json databaseId --jq '.[0].databaseId')
   gh run watch "$RUN_ID" --exit-status
   ```
   If `RUN_ID` comes back empty, wait a few more seconds and retry the `gh run list`
   before giving up. If the watched run reports failure, **stop and report it** — do
   not fall back to building/publishing locally. A failed release needs diagnosing,
   not a silent local workaround; that would defeat the point of moving publish
   credentials off this machine.

10. **Verify the live package** (only after step 9 succeeds)
    ```bash
    pip install --quiet megavers==<new>
    megavers-analyze --version
    megavers-prune --version
    megavers-config-init --version
    megavers-config-list --version
    ```

## Notes

- Publishing to PyPI is irreversible — double check the version and `CHANGELOG.md`
  entry before pushing the tag in step 8, since that's what triggers it.
- If the tag already exists, abort and ask the user.
- Build and publish happen in GitHub Actions via PyPI Trusted Publishing (OIDC) —
  no PyPI credentials are read or used on the local machine for a standard release.
  `~/.config/hatch/config.toml` still has PyPI credentials configured from before this
  change, kept only as a manual-fallback capability, not part of the standard flow.

# Design decisions

Lightweight ADR log: why the project works the way it does, not just what
changed (see `CHANGELOG.md` for that). Add an entry whenever a non-obvious
choice is made, especially ones that were debated or that reject a tempting
alternative — the goal is to not re-litigate the same question twice.

Each entry: **Context** (the question/problem) → **Decision** → **Rationale**
(why, including alternatives rejected and their tradeoffs).

## Config file format: TOML

**Context:** `.megavers.toml` needs a human-edited format for a list of named
filter records (`name`, `description`, `path_contains`, `extensions`).

**Decision:** TOML.

**Rationale:**
- Python 3.11+ (this project's floor) ships `tomllib` in the standard
  library — zero runtime dependency, consistent with the project's explicit
  "no runtime dependencies" stance (MEGAcmd is the only external requirement).
- Supports comments, unlike JSON — the bundled default config leans on
  comments to explain each filter and the search order.
- `[[filter]]` array-of-tables maps directly onto "a list of records with the
  same shape," which is more readable here than YAML's indentation-sensitive
  lists-of-maps or JSON's bracket/brace nesting, for a file people hand-edit.

**Alternatives considered and rejected:**
- **YAML** — needs a third-party parser (`PyYAML`), which conflicts with the
  no-dependency stance for no real gain over TOML for this shape of data.
- **JSON** — no comments; stdlib `json` is fine otherwise, but losing
  documentation-in-the-config was the dealbreaker.
- **INI** (`configparser`, stdlib) — no native array-of-tables; multiple
  filters would need synthetic section names (`[filter:git]`) and manual
  list-splitting for `path_contains`/`extensions` (INI values are just
  strings). Uglier than `[[filter]]`.
- **.env / flat key=value** — can't express a filter's multiple fields or a
  list of filters at all.
- **XML** — verbose, unpleasant to hand-edit.
- **HCL** — no maintained stdlib/well-supported Python parser; would add a
  dependency for no gain over TOML here.
- **A `config.py` file** (`FILTERS = [...]`) — no parsing dependency either,
  but it's a security footgun: a "config" that's actually executable Python
  means anything importing it runs arbitrary code. Bad fit for a file users
  might copy from someone else's dotfiles repo.

## Config filename: `.megavers.toml`, not `config.toml`

**Context:** The cwd-searched config file was originally named `config.toml`.
A bare `config.toml` sitting in a project root is ambiguous — you can't tell
which tool it belongs to just by looking at the directory listing.

**Decision:** Renamed the *cwd*-searched file to `.megavers.toml`. Left
`~/.config/megavers/config.toml` unchanged.

**Rationale:**
- A dotfile prefix makes the file self-identifying, matching the convention
  of `.flake8`, `.prettierrc`, etc. — tools whose config lives at a project
  root and needs to say what it's for at a glance.
- `~/.config/megavers/config.toml` doesn't have this problem: the `megavers/`
  directory already namespaces it (same pattern most XDG-following CLIs use),
  so renaming it would add no clarity, only breakage.
- The rename was cheap because the package was brand new (v0.1.0, days old)
  with essentially no users who'd have created a `./config.toml` yet.
- Kept the `.toml` extension (didn't shorten to bare `.megavers`): editors
  key syntax highlighting off the extension, not the dotfile prefix — a bare
  `.megavers` would need manual file-association config in every editor to
  get TOML highlighting. This also matches the compound-dotfile convention
  (`.eslintrc.json`, `.babelrc.js`) of keeping the real extension specifically
  for tooling support.

## The cloud `path` argument must be absolute

**Context:** `megavers-analyze`/`megavers-prune` take a positional MEGA cloud
path (default `/`). It was originally forwarded to `mega-ls` as a raw string
with no validation.

**Decision:** Reject non-absolute cloud paths at argument-parsing time
(`cloud_path()` in `megavers/analyze.py`, shared by both CLIs) with a clear
error, rather than forwarding them to MEGAcmd.

**Rationale:** A relative path forwarded as-is gets resolved by MEGAcmd
against *its own remote working directory* — hidden state, local to the
MEGAcmd session, that persists across unrelated `mega-*` invocations (e.g.
set by a previous `mega-cd` run by anything, at any time). That makes scans
and prunes non-reproducible in a way that's invisible from megavers itself:
the same command could resolve to a different cloud subtree depending on
MEGAcmd session history nobody can see from here. Rejecting relative paths
trades away an undocumented, rarely-used `mega-cd`-relative workflow for
deterministic, session-independent behavior — consistent with the project's
existing bias toward explicitness (handle-based deletion instead of path
patterns, UTC-normalized `--older-than` cutoffs, rejecting ambiguous config
filters at startup rather than guessing).

## Rejected: auto-resolving the cloud path from the local cwd

**Context:** Idea — when running from inside a locally-synced MEGA folder,
default the cloud `path` argument to whatever cloud path the cwd corresponds
to, instead of always defaulting to `/`.

**Decision:** Dropped. Not implemented.

**Rationale:** Investigated whether MEGAcmd exposes queryable sync-pair info
to make this possible. `mega-sync` *does* list local↔remote pairs — but only
for syncs configured through MEGAcmd itself. Tested empirically from inside
`/media/adrien/data/MEGAsync/megavers`, a directory actively synced by the
**MEGAsync desktop app** (separate product, own package, own autostart
entry, own cache dir under `Mega Limited/MEGAsync`): `mega-sync` returned no
pairs at all. MEGAcmd and the MEGAsync desktop client maintain independent,
non-shared sync configuration. Since most users run the desktop app for
day-to-day sync and only reach for MEGAcmd/megavers occasionally, cwd-based
resolution via `mega-sync` would silently do nothing for the majority case
it was meant to help. The only alternative — reading the desktop app's own
local config/database directly — is an undocumented, proprietary,
version-specific format with no public API, not something to build a public
tool's core behavior on. Verdict: fragility/complexity not justified by the
ergonomic win, given it wouldn't reliably serve the target use case anyway.

## Rejected: renaming `megavers-prune` to `megavers-clean`

**Context:** "prune" vs. "clean" as the command name for deleting old file
version histories.

**Decision:** Keep `megavers-prune`. Not renamed.

**Rationale:** "prune" is the established term in dev tooling for exactly
this operation — `git prune`/`gc`, `docker system prune`, `npm prune` all
mean "remove stale-but-safe-to-remove things while keeping the current state
intact," which is precisely what this command does (the current version of
every file is always kept; only old version snapshots are deletable).
"clean" is more ambiguous and carries baggage from `git clean` (deletes
untracked *files* entirely, not old versions of tracked ones) and `mvn
clean` (wipe build output) — a user could reasonably expect
`megavers-clean` to delete files outright, which is exactly the kind of
misunderstanding to avoid given deletion here is permanent. Secondary
factor: `megavers-prune` is already published on PyPI (v0.1.1) as the entry
point and referenced throughout the README/CHANGELOG, so a rename now has a
real (if small) cost, unlike the config-filename rename which happened in
the zero-cost pre-release window.

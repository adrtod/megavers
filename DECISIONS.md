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

## No code needed: MEGAcmd server auto-start

**Context:** `PLAN.md` carried an open item to auto-start `mega-cmd-server`
in the background before megavers' first `mega-*` call, on the assumption
that a `mega-*` command fails if the server isn't already running.

**Decision:** No code added. Verified the assumption was wrong and closed
the item.

**Rationale:** Inspected the MEGAcmd client binaries directly (`strings` on
`mega-exec`, which every `mega-*` wrapper script like `mega-ls`/`mega-whoami`
shells out to) and found MEGAcmd already auto-starts `mega-cmd-server` on
first use. Verified empirically: stopped the server with `mega-quit`
(graceful — keeps the session file, so no re-login needed) and ran a cold
`mega-whoami` through megavers' own `run_mega()`/`check_logged_in()` — it
auto-started the server, blocked until ready, and returned exit code 0 on
the *first* call (~0.76s cold vs. ~8ms warm; no retry needed). The
"Initiating MEGAcmd server in background..." notice goes to stderr only,
never touching stdout, and doesn't match any of megavers' existing
stderr-substring checks (e.g. `check_logged_in()`'s `"Not logged in"` check),
so it can't be misread as an error. Conclusion: this was already correctly
handled by MEGAcmd + megavers' existing stdout/stderr separation; building
our own server-start logic would have been solving an already-solved
problem.

## "No such file or directory" from mega-rm is a soft warning, not a hard error

**Context:** A user reported `megavers-prune --yes` batch errors like
`H:RVtSnSIT: No such file or directory` after re-running the same prune
command against the same tree more than once. `mega-rm -f H1 H2 ...`
returns nonzero when *any* handle in the batch can't be found, even though
it still deletes everything else in the batch that does exist. The
pre-existing code treated any nonzero batch as a hard failure: printed an
alarming "Completed with N batch error(s)" dump and made the whole run
exit 1.

**Decision:** In `_run_batched()` (`megavers/prune.py`), classify each
failed batch by its stderr content. If every error line matches
`NOT_FOUND_RE` (`H:<handle>: No such file or directory`), treat the batch
as successful: log one `log.warning()` summary of how many versions were
already gone, and subtract their bytes from the "Recovered approximately"
total (they weren't recovered *by this run*). If a batch has any other kind
of error line mixed in, keep the existing hard-failure behavior unchanged
(full dump, `execute_prune()` returns `False`, `sys.exit(1)`).

**Rationale:** "No such file or directory" means the tool's actual goal for
that handle — the version not taking up space — is already achieved; it's
not a sign anything went wrong, just that the work was already done
(typically by an earlier `megavers-prune` run over the same account state,
confirmed as the cause in this case). Failing the whole run and dumping a
scary-looking error list for a benign, common condition (re-running prune
more than once) is bad UX and could make users distrust the tool's error
reporting in general. Deliberately kept conservative in the other
direction, though: a batch is only downgraded if *every* error line in it
is a "not found," so a real error co-occurring with some already-gone
handles still fails loudly rather than being silently swallowed alongside
the benign ones.

## Rejected: a GitHub Pages docs site

**Context:** Whether to add a GitHub Pages site alongside the README and
PyPI page.

**Decision:** Not doing it. README + PyPI page remain the only docs.

**Rationale:** GitHub Pages earns its cost when there's content a README
can't hold well — a searchable multi-page docs site, versioned docs across
releases, diagrams, screenshots-heavy walkthroughs, an interactive demo.
`megavers` doesn't have any of that: it's two commands, a handful of flags,
and a config file, which a well-organized `README.md` handles fine, and it
already renders natively on both GitHub and PyPI. A separate site's real
cost isn't the initial setup, it's ongoing — a second place to keep in
sync (easy to let go stale) and another surface to point people to,
fragmenting away from the two canonical locations rather than reinforcing
them. Revisit only if the project grows enough to need genuinely separate
docs (e.g. a filter-writing guide with many worked examples).

## Split `--init-config`/`--list-filters` into their own commands

**Context:** `megavers-prune` carried two flags — `--init-config [PATH]` and
`--list-filters` — that both short-circuit before any scanning/deletion
happens and don't conceptually belong to "pruning." `--init-config`
bootstraps a copy of the bundled default config; `--list-filters` just
prints the active filter set and exits.

**Decision:** Removed both flags from `megavers-prune`. Added two new
standalone commands instead: `megavers-config-init` and
`megavers-config-list`, each with its own entry point in `pyproject.toml`
and its own tiny argparse parser in the new `megavers/config.py` module.
This is a breaking CLI change, accepted because the project has no adopted
user base yet (still pre-1.0) — now is the cheap time to make it.

**Rationale:** A flag whose entire job is "print something unrelated to
pruning and exit" doesn't compose well with the rest of `megavers-prune`'s
flag surface (filters, version-selection, mode), and its `--help` output
was carrying examples that had nothing to do with pruning. Giving each its
own command makes `--help` for all three commands describe exactly one job.
Also extracted the underlying config-loading/validation/bootstrap logic
into `megavers/config.py`, since it's a genuinely separate concern from
`prune.py`'s scan/filter/delete pipeline and both new commands (plus
`megavers-prune` itself) need it — a clean one-directional dependency
(`config.py` → `analyze.py`; `prune.py` → `config.py` + `analyze.py`, no
cycle).

**Naming:** initially named `megavers-init-config`/`megavers-list-filters`
(verb-first), then renamed to `megavers-config-init`/`megavers-config-list`
(noun-first) after checking how MEGAcmd itself names *related* commands,
not just standalone ones — it groups them noun-first, verb/qualifier after:
`mega-fuse-add`/`mega-fuse-remove`/`mega-fuse-config`/`mega-fuse-show`, and
`mega-sync-config`/`mega-sync-issues`/`mega-sync-ignore`. Matching that
puts the shared `megavers-config-` prefix first, so the relationship
between the two commands is visible from the name itself (and groups them
in `megavers-<TAB>` completion) rather than requiring you to read past the
first word. `megavers-analyze`/`megavers-prune` don't need this treatment —
they're standalone verbs with no sibling command to group against, matching
`mega-ls`/`mega-rm`.

**Alternatives considered and rejected:**
- **A single `megavers <subcommand>` dispatcher** (git/docker style, e.g.
  `megavers prune`, `megavers analyze`, `megavers config init`) — rejected.
  `megavers`'s actual sibling/parent tool is MEGAcmd, and MEGAcmd itself uses
  a flat `mega-<verb>` multi-binary convention (`mega-ls`, `mega-rm`,
  `mega-login`, `mega-cd`, `mega-sync`, `mega-du`, ...), not a single `mega`
  dispatcher. `megavers-analyze`/`megavers-prune` were deliberately named to
  match that convention from the start, so consolidating into one dispatcher
  now would break consistency with the tool this package exists to wrap,
  for no benefit specific to `megavers`.
- **Leave them as flags on `megavers-prune`** — rejected per the Context
  above: both flags exit before any pruning logic runs, so they're not
  really "prune options," just squatting on the same binary.

## Default retention policy: `[defaults]` table, CLI always wins

**Context:** `--keep-n`/`--older-than` had to be retyped on every
`megavers-prune` invocation, including scripted/cron runs — there was no
way to persist "always keep the 5 most recent" without wrapping the command
in a shell alias or script.

**Decision:** Added an optional `[defaults]` table to `.megavers.toml` with
`keep_n`/`older_than` keys, loaded via `load_defaults()`/validated via
`validate_defaults()` in `megavers/config.py`. `megavers-prune` resolves the
effective values via a new `resolve_retention()` in `prune.py`: an explicit
CLI flag always wins; otherwise it falls back to the config value, if set.
Ships commented out in the bundled default config (like the `results`
filter example) — opt-in, since most users should review what a policy
would delete before it runs unattended on a schedule.

**Rationale:**
- **CLI-always-wins, not the reverse:** a config default that silently
  overrode an explicit `--keep-n` on the command line would be surprising
  and hard to debug ("why isn't my flag doing anything"). Explicit input
  should never be shadowed by a fallback.
- **`keep_n=0` must not be treated as "unset":** it's a meaningful value
  (delete all old versions), so the resolution logic checks `is not None`,
  not truthiness — a naive `cli_keep_n or defaults.get("keep_n")` would
  incorrectly fall through to the config default when the CLI explicitly
  passed `0`.
- **Validation rejects `bool` values explicitly:** TOML's `true`/`false`
  parse as Python `bool`, which is a subclass of `int` — `isinstance(True,
  int)` is `True` — so a plain `isinstance(value, int)` check would silently
  accept `keep_n = true` as `1`. Checked and rejected separately.
- **Loading/validation (`config.py`) stays separate from resolution
  (`prune.py`):** `config.py` only knows how to read and validate the raw
  `[defaults]` table; deciding what `keep_n`/`older_than` mean and how CLI
  flags interact with them is prune-specific behavior, consistent with the
  existing `config.py`/`prune.py` split (loading vs. using).

## Build backend: switched from setuptools to Hatchling

**Context:** Reconsidered the project's build backend not just for this
package's own needs (which are minimal — zero runtime dependencies, one
small package-data file, no compiled extensions) but as a template for
future projects: a one-time switch that pays off every time a new project
starts, even if this particular project barely benefits from it.

**Decision:** Switched `[build-system]` from `setuptools.build_meta` to
`hatchling.build`. Removed `[tool.setuptools]`/`[tool.setuptools.package-data]`
entirely — Hatchling auto-includes non-`.py` files inside the package
directory (`megavers/config.toml`) for the wheel with no config needed.

**Rationale:** Hatchling is PEP 621-native (matching the project's existing
metadata style, unlike poetry's historically non-standard `[tool.poetry]`
section), well-maintained, and its extras (env management, matrix testing)
are opt-in rather than requiring a rewrite later if ever wanted. Verified
before adopting: built both wheel and sdist, inspected contents directly
(`zipfile -l` / `tar tzf`), installed each into a fresh venv, confirmed all
four console-script entry points work and `config.toml` is actually
readable as package data at runtime — not just assumed the switch would
work.

**Found and fixed during verification: sdist over-inclusion.** Hatchling's
default sdist file-selection pulled in `.claude/settings.local.json` — a
file that's *not* excluded by this repo's own `.gitignore`, only by this
machine's personal `~/.config/git/ignore` (a global, per-user git config,
invisible to the repo itself). Building the sdist on a different machine
would silently produce different contents depending on that machine's
global gitignore — a real reproducibility gap, and in this case one that
would have shipped a maintainer's local Claude Code permission settings to
PyPI. Fixed by replacing implicit VCS-based inclusion with an explicit
`[tool.hatch.build.targets.sdist] include` allowlist (package source,
tests, README, CHANGELOG, LICENSE) — immune to *any* future untracked or
locally-ignored file showing up unannounced, not just this specific one.
The wheel target was unaffected (Hatchling scopes wheel contents to the
package directory by default, which was already correct).

## Release subagent switched to `hatch` (version/build/publish)

**Context:** `.claude/agents/release.md` bumped the version by hand-editing
`pyproject.toml`, built via `python -m build`, and published via `twine
upload` (credentials from `~/.pypirc`). This predated the Hatchling
build-backend switch; `python -m build` kept working unchanged since it's
backend-agnostic. With Hatchling in place, `hatch` (its own reference CLI)
can do all three natively.

**Decision:** Full switch — `hatch version`, `hatch build`, and `hatch
publish` for real PyPI uploads going forward, not a hybrid that keeps
`twine`. Before trusting `hatch publish` for a real release, did a
**one-time** shadow release to TestPyPI to prove the credential-passing
mechanism actually works, rather than assuming. That verification is not
written into the agent's instructions — every release after this one calls
`hatch publish` directly with no recurring TestPyPI detour.

**Verification performed (not just assumed):** installed `hatch` in an
isolated `/tmp` venv, tested against a scratch copy of the repo — confirmed
`hatch version <X>` correctly rewrites the static `version = "..."` field
(and refuses to set a version that isn't strictly higher than the current
one — a nice built-in safety check), confirmed `hatch build` produces
identical wheel/sdist contents to what was already verified for Hatchling
directly, and read `hatch publish --help` plus its source
(`hatch/publish/index.py`) to confirm real flags rather than assumed ones:
`-r/--repo` (env `HATCH_INDEX_REPO`) with built-in `main`/`test` aliases
(`test` → `test.pypi.org`, default is `main` → `pypi.org`), and
`-u/--user`/`-a/--auth` (env `HATCH_INDEX_USER`/`HATCH_INDEX_AUTH`) for
credentials — `hatch publish` does *not* read `~/.pypirc` the way `twine`
does, so the token has to be extracted from it and passed via these env
vars instead. No `--dry-run` flag exists; publishing to `-r test`
(TestPyPI) is the closest equivalent, which is exactly what the one-time
shadow release used. Then actually built a throwaway dev-suffixed version
(`0.3.1.dev0`) from the scratch copy, published it to TestPyPI with the
real `[testpypi]` token from `~/.pypirc`, and installed it from
`test.pypi.org` into a fresh venv to confirm all four console-script entry
points and `config.toml` package-data still work through the full
`hatch`-built artifact — before ever touching real PyPI or the rewritten
agent file.

**Rationale:** An attempt to delegate this CLI research to a read-only
Explore subagent failed — it correctly refused to run `pip install`/write
to `/tmp`, since that agent type is restricted to read-only search. The
verification had to be done directly, outside subagent delegation, for
anything requiring real installs/builds/network calls.

## Correction: credentials moved into hatch's own config, not sourced from `~/.pypirc`

**Context:** The entry above says `hatch publish` doesn't read `~/.pypirc`.
That was based on its `--help` output and docs, not its actual source —
reading `hatch/publish/auth.py` afterward showed it *does* have a
`~/.pypirc`-reading fallback (`AuthenticationCredentials._read_pypirc()`).
But that fallback looks for a `.pypirc` *section* matching the literal
`--repo` name — and hatch's built-in aliases are `main`/`test`, while
`.pypirc`'s convention (used by `twine`) is `pypi`/`testpypi`. Those never
match, so the fallback is practically dead for any standard `.pypirc` —
confirmed empirically: `hatch publish` with *no* `-r`/`-u`/`-a` at all
still failed with `Missing required option: user`.

**Decision:** Stored the PyPI and TestPyPI tokens directly in hatch's own
persistent config instead (`~/.config/hatch/config.toml`, via `hatch config
set publish.index.repos.<main|test>.{user,auth,url}`), rather than passing
them via `HATCH_INDEX_USER`/`HATCH_INDEX_AUTH` env vars extracted from
`~/.pypirc` each run. Verified with the `test` repo first (a real, if
disposable, publish to TestPyPI succeeded with zero explicit
credentials/flags) before configuring `main` with the real token the same
way. `.claude/agents/release.md`'s publish step simplified accordingly —
`hatch publish -n dist/megavers-<new>*` now needs nothing else.

**Non-obvious bit:** setting `publish.index.repos.<name>.user`/`.auth`
alone isn't enough — `hatch`'s config loader validates that any *manually
defined* repo entry includes a `url` key and aborts otherwise (`Hatch
config field ... must define a url key`), even though the built-in
`main`/`test` aliases would have auto-supplied that same URL if the entry
had been left absent entirely. Had to also explicitly set
`publish.index.repos.<name>.url` to the standard upload URLs
(`https://upload.pypi.org/legacy/` / `https://test.pypi.org/legacy/`) for
each.

**Also tightened `~/.pypirc` and `~/.config/hatch/config.toml` to `600`**
(owner-only) — `~/.pypirc` was found at `664` (group- and world-readable)
before this work; hatch's own config file was already `600` by default.

## Releases moved to GitHub Actions, publishing via Trusted Publishing

**Context:** Even after moving PyPI credentials into hatch's own config
(previous entry), a long-lived PyPI publish token still lived on the local
development machine — if that machine were ever compromised, the token
could be used to publish malicious releases under the `megavers` name.

**Decision:** Added `.github/workflows/release.yml`, triggered by pushing a
`v*` tag (the exact convention `.claude/agents/release.md` already used).
Three jobs: `test` (single-version sanity gate on the tagged commit) →
`build` (`hatch build`, artifact passed via `actions/upload-artifact`) →
`publish` (`pypa/gh-action-pypi-publish`, using PyPI **Trusted Publishing**
— OIDC-based, no stored secret at all; PyPI issues a short-lived token per
run). `permissions: id-token: write` is scoped to the `publish` job only
(least privilege), and `environment: pypi` on that job matches the
environment name registered in PyPI's trusted-publisher config for this
repo — that's what scopes PyPI's trust to *this specific job*, not "any
job in this workflow file."

`.claude/agents/release.md` updated to hand off accordingly: it still does
everything that needs judgment (version bump, changelog prose, git
tag/push — steps requiring an LLM's read of `git log`/decisions a CI
workflow can't sensibly make), but no longer runs `hatch build`/`hatch
publish` itself. After pushing the tag, it now finds the exact triggered
run (`gh run list --workflow=release.yml --commit=<sha>`, not "most recent
run" — avoids ambiguity if another run is in flight) and watches it to
completion (`gh run watch <id> --exit-status`) before doing the final
live-package verification. On failure, the agent's instructions explicitly
say to stop and report rather than silently fall back to a local
`hatch publish` — doing so would defeat the entire point of moving publish
credentials off the local machine.

The PyPI-side trusted-publisher registration (project → Owner `adrtod`,
Repository `megavers`, Workflow `release.yml`, Environment `pypi`) is a
one-time manual step on PyPI's website that only the project owner can do
— nothing in the repo can register it, and it isn't repo/version-controlled
state.

**Rationale:** GitHub Actions' OIDC-based Trusted Publishing eliminates the
long-lived-secret risk entirely for the *standard* release path — there's
no PyPI token to leak from a compromised laptop, stolen `~/.config/hatch/config.toml`,
or an accidentally-committed dotfile, because none exists for this purpose
anymore. `~/.config/hatch/config.toml`'s credentials (previous entry) were
left in place rather than removed, as an explicit manual fallback — not
part of the standard flow, but not deleted either, in case CI-based
publishing is ever unavailable and a human needs to intervene directly.
`pypa/gh-action-pypi-publish` was chosen over `hatch publish
--trusted-publishing` for the actual upload step since it's the
PyPA-official, documented reference implementation PyPI's own trusted
publishing guide uses as the example — `hatch build` is still used for the
build step itself, since that's already proven identical to a plain
Hatchling build (see earlier entries) and keeping it keeps the artifact
byte-for-byte consistent with what `hatch build` already produces locally.

**Also added `.github/workflows/release-test.yml`**, a permanent but
`workflow_dispatch`-only diagnostic workflow — never runs automatically —
that mirrors `release.yml`'s test→build→publish structure but targets
TestPyPI (`repository-url: https://test.pypi.org/legacy/`, its own
`environment: testpypi`, its own separate trusted-publisher registration on
`test.pypi.org` — TestPyPI is a fully separate service from PyPI, with
independent trust config). Kept permanently rather than added-then-deleted
(unlike the earlier one-time local hatch shadow test), since it's inert
unless someone deliberately triggers it, so it doesn't violate the
"don't bake recurring verification into the standard path" principle — it
just makes re-verifying the pipeline cheap in the future (e.g. after
bumping the `pypa/gh-action-pypi-publish` or `hatch` version). Each run
computes a throwaway unique version (`<current-version>.dev<run-number>`,
via `hatch version --force` — `--force` needed because PEP 440 orders
`dev` releases *before* their base version, which `hatch version` would
otherwise reject as a "downgrade") in the ephemeral CI checkout only —
never touches the real `pyproject.toml`, never risks colliding with a real
release or a previous test run.

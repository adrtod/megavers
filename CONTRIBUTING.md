# Contributing

## Setup

```bash
git clone https://github.com/adrtod/megavers.git
cd megavers
pip install -e ".[test]"
```

Requires Python 3.11+ and [MEGAcmd](https://github.com/meganz/MEGAcmd) for anything that talks to a real MEGA account.

## Tests

```bash
python -m pytest
```

Tests cover `parse()`, filter logic, config lookup, CLI argument parsing, and the deletion path — all against captured `mega-ls` output or mocked `mega-*` calls, so no MEGA account or MEGAcmd install is needed to run them. CI runs the suite on push against Python 3.11/3.12/3.13.

## Making changes

- Add or update tests for anything you change in `megavers/analyze.py` or `megavers/prune.py`.
- Update `CHANGELOG.md` under `[Unreleased]` for anything user-visible.
- If you're proposing a non-obvious design choice, or reconsidering one already made, check `DECISIONS.md` first — it records the reasoning behind past calls (e.g. config format, path handling) so we don't relitigate them. Add an entry there for new decisions worth remembering.
- Keep PRs focused. If you're fixing a bug and notice something else worth cleaning up, open a separate PR.

## Pull requests

Open a PR against `main`. CI must pass. Describe *why* the change is needed, not just what it does — that context is what makes review fast.

## Bug reports

Open a [GitHub issue](https://github.com/adrtod/megavers/issues). Include the `mega-ls`/`mega-rm` output if relevant (redact anything sensitive) — `--raw-dump FILE` on `megavers-analyze` is useful for this.

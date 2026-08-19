#!/usr/bin/env python3
"""
MEGA Version Filter Config

Loads, validates, and bootstraps the .megavers.toml filter config used by
megavers-prune and megavers-config-list.
"""

import sys
import logging
import argparse
import tomllib
from importlib.resources import files
from pathlib import Path

from megavers import __version__
from megavers.analyze import configure_logging

log = logging.getLogger(__name__)

DEFAULT_USER_CONFIG_PATH = Path.home() / ".config" / "megavers" / "config.toml"

USER_CONFIG_SEARCH_PATH = [
    Path.cwd() / ".megavers.toml",
    DEFAULT_USER_CONFIG_PATH,
]

BUNDLED_CONFIG_LABEL = "<bundled default>"

FILTER_KEYS = {"name", "description", "path_contains", "extensions"}

DEFAULTS_KEYS = {"keep_n", "older_than"}


# ── Config loading ────────────────────────────────────────────────────────────

def find_user_config() -> Path | None:
    """Return the first user-supplied config found on disk, or None."""
    for candidate in USER_CONFIG_SEARCH_PATH:
        if candidate.exists():
            return candidate
    return None


def bundled_config_text() -> str:
    return files("megavers").joinpath("config.toml").read_text("utf-8")


def _load_toml_data(path: Path | None) -> dict:
    if path is None:
        return tomllib.loads(bundled_config_text())
    with open(path, "rb") as fh:
        return tomllib.load(fh)


def load_config(path: Path | None) -> list[dict]:
    """Load filters from `path`, or from the bundled default config when `path` is None."""
    return _load_toml_data(path).get("filter", [])


def load_defaults(path: Path | None) -> dict:
    """Load the [defaults] table (keep_n/older_than) from `path`, or from the
    bundled default config when `path` is None. Returns {} if the table is
    absent - most configs won't set a default retention policy."""
    return _load_toml_data(path).get("defaults", {})


def init_config(dest: Path) -> None:
    """Copy the bundled default config to `dest` so the user has a starting
    point to customize, without touching the package-installed original."""
    if dest.is_dir():
        dest = dest / ".megavers.toml"
    if dest.exists():
        log.error("Error: %s already exists. Remove it, edit it directly, or "
                  "pass a different destination to megavers-config-init.", dest)
        sys.exit(1)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(bundled_config_text(), encoding="utf-8")
    print(f"Wrote default config to: {dest}")
    if dest.resolve() in (p.resolve() for p in USER_CONFIG_SEARCH_PATH):
        print("Both megavers-prune and megavers-config-list will pick it up "
              "automatically. Edit it to customize filters.")
    else:
        print(f"Pass --config {dest} to use it (it's outside the default search path).")


def validate_filters(filters: list[dict]) -> None:
    """Reject config filters that would match every file (missing criteria) or
    that contain a typo'd/unrecognised key — both are easy to write by accident
    and, combined with delete-by-default semantics, expensive to get wrong."""
    for i, f in enumerate(filters):
        label = f.get("name") or f"filter #{i + 1}"
        unknown = set(f) - FILTER_KEYS
        if unknown:
            log.error("Error: unrecognized key(s) in config filter %r: %s",
                      label, sorted(unknown))
            sys.exit(1)
        if not f.get("name"):
            log.error("Error: %s is missing a 'name'.", label)
            sys.exit(1)
        if not f.get("path_contains") and not f.get("extensions"):
            log.error("Error: config filter %r has neither 'path_contains' nor "
                      "'extensions' set, so it would match every file. Add at least "
                      "one, or remove the filter.", label)
            sys.exit(1)


def validate_defaults(defaults: dict) -> None:
    """Reject a [defaults] table with unrecognized keys or invalid values -
    same rationale as validate_filters(): typos are easy to make and,
    combined with delete-by-default semantics, expensive to get wrong."""
    unknown = set(defaults) - DEFAULTS_KEYS
    if unknown:
        log.error("Error: unrecognized key(s) in [defaults]: %s", sorted(unknown))
        sys.exit(1)
    for key in DEFAULTS_KEYS:
        if key not in defaults:
            continue
        value = defaults[key]
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            log.error("Error: [defaults].%s must be a non-negative integer, got %r.",
                      key, value)
            sys.exit(1)


def resolve_config(explicit: Path | None) -> tuple[Path | None, list[dict], str]:
    """Resolve the effective config path/filters/label from an explicit --config
    override (or the auto-discovery search path), validating filters along the
    way. Shared by megavers-prune and megavers-config-list so both always agree
    on what's currently active."""
    config_path = explicit or find_user_config()
    config_filters = load_config(config_path)
    validate_filters(config_filters)
    config_label = str(config_path) if config_path else BUNDLED_CONFIG_LABEL
    return config_path, config_filters, config_label


# ── megavers-config-init ──────────────────────────────────────────────────────

def build_config_init_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="megavers-config-init",
        description="Write a copy of the bundled default filter config to PATH, "
                    "as a starting point to customize (default: "
                    "~/.config/megavers/config.toml). Refuses to overwrite an "
                    "existing file. Passing an existing directory (e.g. '.') "
                    "writes .megavers.toml inside it rather than refusing.",
    )
    parser.add_argument("path", nargs="?", type=Path, default=DEFAULT_USER_CONFIG_PATH,
                        metavar="PATH",
                        help="Destination path (default: ~/.config/megavers/config.toml)")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    verbosity = parser.add_mutually_exclusive_group()
    verbosity.add_argument("-v", "--verbose", action="store_true",
                           help="Show debug output")
    verbosity.add_argument("-q", "--quiet", action="store_true",
                           help="Suppress progress messages; only warnings/errors are shown")
    return parser


def main_config_init() -> None:
    args = build_config_init_parser().parse_args()
    configure_logging(args.verbose, args.quiet)
    init_config(args.path)


# ── megavers-config-list ──────────────────────────────────────────────────────

def build_config_list_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="megavers-config-list",
        description="List the filters currently in effect (bundled default, or "
                    "your own config if you've created one) and exit.",
    )
    parser.add_argument("--config", metavar="FILE", type=Path, default=None,
                        help="Config file path (default: ./.megavers.toml "
                             "→ ~/.config/megavers/config.toml → bundled)")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    verbosity = parser.add_mutually_exclusive_group()
    verbosity.add_argument("-v", "--verbose", action="store_true",
                           help="Show debug output")
    verbosity.add_argument("-q", "--quiet", action="store_true",
                           help="Suppress progress messages; only warnings/errors are shown")
    return parser


def main_config_list() -> None:
    args = build_config_list_parser().parse_args()
    configure_logging(args.verbose, args.quiet)
    _, config_filters, config_label = resolve_config(args.config)
    print(f"Filters in {config_label}:")
    for f in config_filters:
        print(f"  [{f['name']}]  {f.get('description', '')}")
        if f.get("path_contains"):
            print(f"    path_contains: {f['path_contains']}")
        if f.get("extensions"):
            print(f"    extensions:    {f['extensions']}")

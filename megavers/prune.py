#!/usr/bin/env python3
"""
MEGA Version Pruner

Selectively deletes old file versions based on filters defined in a config file
(.megavers.toml). Only previews by default — pass --yes to actually delete.

Keeps the current (latest) version of every file untouched.
"""

import re
import sys
import json
import logging
import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath

from megavers import __version__
from megavers.analyze import (
    OldVersion, VersionedFile, check_logged_in, cloud_path, configure_logging, fetch_raw,
    parse, fmt_size, fmt_date, parse_mtime, run_mega,
)
from megavers.config import resolve_config, load_defaults, validate_defaults

log = logging.getLogger(__name__)


def extension_suffix(path: str) -> str:
    """The file's extension, case-insensitive, treating .tar.gz/.tar.bz2/.tar.xz
    as a single compound extension rather than PurePosixPath's ".gz" of ".tar.gz"."""
    lower = path.lower()
    for compound in (".tar.gz", ".tar.bz2", ".tar.xz"):
        if lower.endswith(compound):
            return "." + compound.rsplit(".", 1)[-1]
    return PurePosixPath(lower).suffix


def build_filter_fn(f: dict):
    """Return a match function for a config filter entry."""
    path_patterns = f.get("path_contains", [])
    extensions    = {e.lower() for e in f.get("extensions", [])}

    def match(vf: VersionedFile) -> bool:
        # MEGA paths are case-sensitive; match them as such.
        if path_patterns and not any(p in vf.path for p in path_patterns):
            return False
        if not extensions:
            return True
        return extension_suffix(vf.path) in extensions

    return match


# ── Scanning / loading ────────────────────────────────────────────────────────

def load_versioned(args) -> dict[str, VersionedFile]:
    if args.from_json:
        try:
            with open(args.from_json, encoding="utf-8") as fh:
                records = json.load(fh)
            out = {}
            for r in records:
                vf = VersionedFile(
                    path=r["path"], name=r["name"],
                    current_size=r["current_size"], current_mtime=r["current_mtime"],
                    total_versions=r["old_count"] + 1,
                    flags=r.get("flags", ""), handle=r.get("handle", ""),
                    old_versions=sorted(
                        (
                            OldVersion(
                                size=v["size"], mtime=v["mtime"], version_num=v["version_num"],
                                handle=v.get("handle", ""),
                            )
                            for v in r["versions"]
                        ),
                        key=lambda v: v.version_num, reverse=True,
                    ),
                )
                out[vf.path] = vf
        except FileNotFoundError:
            log.error("Error: %s not found.", args.from_json)
            sys.exit(1)
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            log.error("Error: %s is not a valid megavers-analyze --json file (%s).",
                      args.from_json, e)
            sys.exit(1)
        log.info("Loaded %d versioned files from %s.", len(out), args.from_json)
        return out
    else:
        log.info("Scanning %r ...", args.path)
        lines = fetch_raw(args.path)
        log.info("  %d lines received.", len(lines))
        versioned = parse(lines)
        log.info("  %d files have old versions.", len(versioned))
        return versioned


def warn_on_count_mismatches(versioned: dict[str, VersionedFile]) -> None:
    """Flag files where fewer old versions were parsed than mega-ls reported —
    e.g. versions owned by a contact, which deleteversions/rm cannot remove."""
    for vf in versioned.values():
        if vf.old_count != vf.total_versions - 1:
            log.warning("Warning: %s reports %d total versions but only %d were "
                        "parsed - some old versions may not be deletable (e.g. "
                        "owned by a contact).", vf.path, vf.total_versions, vf.old_count)


# ── Filtering ─────────────────────────────────────────────────────────────────

def apply_filters(versioned: dict[str, VersionedFile], args, config_filters: list[dict]) \
        -> list[VersionedFile]:
    active_fns = []

    # Config-defined filters
    requested = set(args.filter) if args.filter else None
    for f in config_filters:
        name = f.get("name", "")
        if requested is None or name in requested:
            active_fns.append(build_filter_fn(f))

    # Ad-hoc CLI filters
    if args.path_contains:
        for pat in args.path_contains:
            active_fns.append(lambda vf, p=pat: p in vf.path)
    if args.ext:
        exts = {e.lower() if e.startswith(".") else "." + e.lower() for e in args.ext}
        active_fns.append(lambda vf, exts=exts: extension_suffix(vf.path) in exts)

    if not active_fns:
        log.error("Error: no active filters. Check your config file or --filter arguments.")
        sys.exit(1)

    # OR logic across all active filters
    selected = [vf for vf in versioned.values() if any(fn(vf) for fn in active_fns)]

    if args.min_version_size:
        try:
            threshold = parse_size(args.min_version_size)
        except ValueError as e:
            log.error("Error: --min-version-size: %s", e)
            sys.exit(1)
        selected = [vf for vf in selected if vf.version_size >= threshold]

    return selected


def parse_size(s: str) -> int:
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(B|KB|MB|GB|TB)?", s.strip(), re.IGNORECASE)
    if not m:
        raise ValueError(f"Cannot parse size: {s!r}")
    value = float(m.group(1))
    unit = (m.group(2) or "B").upper()
    return int(value * {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3, "TB": 1024**4}[unit])


# ── Version selection (--keep-n / --older-than) ───────────────────────────────

def resolve_retention(cli_keep_n: int | None, cli_older_than: int | None,
                       defaults: dict) -> tuple[int | None, int | None]:
    """CLI --keep-n/--older-than always win when given; otherwise fall back to
    the config's [defaults] table, if it sets one."""
    keep_n = cli_keep_n if cli_keep_n is not None else defaults.get("keep_n")
    older_than = cli_older_than if cli_older_than is not None else defaults.get("older_than")
    return keep_n, older_than


def versions_to_delete(vf: VersionedFile, keep_n: int | None, older_than: int | None) \
        -> list[OldVersion]:
    if keep_n is not None and older_than is not None:
        # OR logic: delete if outside the top N *or* older than the cutoff.
        # Anything that fails either condition is removed.
        recent = set(id(v) for v in vf.old_versions[:keep_n])
        cutoff = datetime.now(timezone.utc) - timedelta(days=older_than)
        return [
            v for v in vf.old_versions
            if id(v) not in recent or parse_mtime(v.mtime) < cutoff
        ]
    if keep_n is not None:
        return vf.old_versions[keep_n:]
    if older_than is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=older_than)
        return [v for v in vf.old_versions if parse_mtime(v.mtime) < cutoff]
    return list(vf.old_versions)


# ── Row computation (shared by dry-run preview and real execution) ────────────

def compute_rows(
    selected: list[VersionedFile],
    keep_n: int | None,
    older_than: int | None,
) -> list[tuple[VersionedFile, list[OldVersion]]]:
    rows = [(vf, versions_to_delete(vf, keep_n, older_than)) for vf in selected]
    return [(vf, vs) for vf, vs in rows if vs]


# ── Dry-run report ────────────────────────────────────────────────────────────

def print_dry_run(
    selected: list[VersionedFile],
    all_version_bytes: int,
    keep_n: int | None,
    older_than: int | None,
) -> None:
    rows = compute_rows(selected, keep_n, older_than)

    total_bytes = sum(sum(v.size for v in vs) for _, vs in rows)
    total_count = sum(len(vs) for _, vs in rows)

    print()
    print("=" * 72)
    print("DRY RUN - nothing deleted")
    print("=" * 72)
    print(f"  Files affected:              {len(rows)}")
    print(f"  Old versions to delete:      {total_count}")
    print(f"  Space to recover:            {fmt_size(total_bytes)}")
    if all_version_bytes:
        print(f"  % of total version space:   {total_bytes / all_version_bytes * 100:.1f}%")
    print()

    if keep_n is not None or older_than is not None:
        print(f"{'DELETE':>6}  {'KEEP':>4}  {'RECOVER':>9}  PATH")
        print("-" * 72)
        for vf, to_del in sorted(rows, key=lambda r: sum(v.size for v in r[1]), reverse=True):
            kept = vf.old_count - len(to_del)
            print(f"{len(to_del):>6}  {kept:>4}  {fmt_size(sum(v.size for v in to_del)):>9}  {vf.path}")
    else:
        print(f"{'VER SPACE':>10}  {'VERS':>5}  PATH")
        print("-" * 72)
        for vf, _ in sorted(rows, key=lambda r: r[0].version_size, reverse=True):
            print(f"{fmt_size(vf.version_size):>10}  {vf.old_count:>5}  {vf.path}")

    print()
    print("Re-run with --yes to permanently delete.")


# ── Execution ─────────────────────────────────────────────────────────────────

BATCH_SIZE = 50

# mega-rm reports this, per handle, when a version no longer exists - most
# commonly because a previous megavers-prune run (or another client) already
# deleted it. The tool's goal (that version not taking up space) is already
# met, so this is treated as benign rather than a failure.
NOT_FOUND_RE = re.compile(r'(H:[A-Za-z0-9]+):\s*No such file or directory')


def execute_prune(
    selected: list[VersionedFile],
    keep_n: int | None,
    older_than: int | None,
) -> bool:
    """Delete the selected old versions. Returns True on success (no batch errors)."""
    rows = compute_rows(selected, keep_n, older_than)

    all_handles = [v.handle for _, vs in rows for v in vs if v.handle]
    no_handle   = sum(1 for _, vs in rows for v in vs if not v.handle)
    total_bytes = sum(v.size for _, vs in rows for v in vs)
    handle_sizes = {v.handle: v.size for _, vs in rows for v in vs if v.handle}

    # Never delete a file's current version — old-version handles must never
    # collide with the current-version handles of the files we scanned.
    current_handles = {vf.handle for vf, _ in rows if vf.handle}
    unsafe = [h for h in all_handles if h in current_handles]
    if unsafe:
        log.error("Refusing to continue: %d version(s) scheduled for deletion match "
                  "a file's current-version handle. This should not happen - "
                  "aborting without deleting anything.", len(unsafe))
        return False

    if no_handle:
        log.warning("Warning: %d version(s) have no handle and will be skipped. "
                    "Re-scan without --from-json to get handles.", no_handle)
    if not all_handles:
        print("No deletable versions found (no handles available).")
        return True

    log.info("\nDeleting %d old version(s) across %d file(s) (%s to recover) ...",
             len(all_handles), len(rows), fmt_size(total_bytes))
    return _run_batched("mega-rm", all_handles, total_bytes, handle_sizes)


def _run_batched(cmd: str, items: list[str], total_bytes: int,
                  handle_sizes: dict[str, int]) -> bool:
    """Run `cmd -f <items...>` in batches. Returns True unless a batch hit an
    error other than "already gone" (see NOT_FOUND_RE)."""
    errors = []
    already_gone: list[str] = []
    for i in range(0, len(items), BATCH_SIZE):
        batch = items[i:i + BATCH_SIZE]
        end = min(i + BATCH_SIZE, len(items))
        print(f"  [{i + 1}-{end} / {len(items)}] ...", end=" ", flush=True)
        r = run_mega([cmd, "-f", *batch])
        if r.returncode == 0:
            print("OK")
            continue

        lines = [ln for ln in r.stderr.strip().splitlines() if ln.strip()]
        if any(not NOT_FOUND_RE.search(ln) for ln in lines):
            print("ERROR")
            errors.append((batch, r.stderr.strip()))
        else:
            already_gone.extend(m.group(1) for m in NOT_FOUND_RE.finditer(r.stderr))
            print("OK")

    print()
    if errors:
        print(f"Completed with {len(errors)} batch error(s):")
        for batch, msg in errors:
            print(f"  {msg}")
            for item in batch:
                print(f"    {item}")
        return False

    if already_gone:
        log.warning("%d version(s) were already deleted (e.g. by an earlier "
                    "megavers-prune run) and skipped - not a problem.", len(already_gone))
    recovered_bytes = total_bytes - sum(handle_sizes.get(h, 0) for h in already_gone)
    print(f"Done. {len(items)} version(s) processed.")
    print(f"Recovered approximately {fmt_size(recovered_bytes)}.")
    return True


# ── Entry point ───────────────────────────────────────────────────────────────

def _non_negative_int(s: str) -> int:
    v = int(s)
    if v < 0:
        raise argparse.ArgumentTypeError(f"must be >= 0, got {v}")
    return v


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prune MEGA file version histories (requires MEGAcmd). "
                    "Filters are defined in a config file (.megavers.toml). "
                    "Only previews by default — pass --yes to actually delete.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  # Preview what would be deleted (default — nothing is deleted without --yes)
  megavers-prune

  # Actually delete, using all filters from config.toml
  megavers-prune --yes

  # Run only the 'python-bytecode' filter defined in config.toml
  megavers-prune --filter python-bytecode --yes

  # Preview keeping only the 3 most recent old versions per matched file
  megavers-prune --keep-n 3

  # Delete versions older than 90 days (all config filters)
  megavers-prune --older-than 90 --yes

  # Ad-hoc: any file whose path contains 'backup'
  megavers-prune --path-contains backup --yes

  # Reuse a previously saved scan
  megavers-prune --from-json results.json

see also:
  megavers-config-init    write a starting-point filter config
  megavers-config-list    show which filters are currently active
""",
    )

    src = parser.add_argument_group("source")
    src.add_argument("path", nargs="?", default="/", type=cloud_path,
                     help="Cloud path to scan, absolute (default: /)")
    src.add_argument("--from-json", metavar="FILE",
                     help="Load from megavers-analyze --json output (skips re-scanning)")
    src.add_argument("--config", metavar="FILE", type=Path, default=None,
                     help="Config file path (default: ./.megavers.toml "
                          "→ ~/.config/megavers/config.toml → bundled)")

    flt = parser.add_argument_group("filters")
    flt.add_argument("--filter", metavar="NAME", action="append",
                     help="Activate only this config filter by name (repeatable; "
                          "default: all filters in config)")
    flt.add_argument("--path-contains", metavar="STR", action="append",
                     help="Ad-hoc: select files whose path contains STR (repeatable)")
    flt.add_argument("--ext", metavar="EXT", action="append",
                     help="Ad-hoc: select files with this extension (repeatable)")
    flt.add_argument("--min-version-size", metavar="SIZE",
                     help="Only select files where version space >= SIZE (e.g. 10MB)")

    sel = parser.add_argument_group("version selection (applied after filters)")
    sel.add_argument("--keep-n", type=_non_negative_int, metavar="N",
                     help="Keep the N most recent old versions; delete the rest "
                          "(overrides [defaults].keep_n in the config, if set)")
    sel.add_argument("--older-than", type=_non_negative_int, metavar="DAYS",
                     help="Delete old versions whose age exceeds DAYS days "
                          "(overrides [defaults].older_than in the config, if set)")

    mode = parser.add_argument_group("mode")
    mode.add_argument("--yes", action="store_true",
                      help="Actually delete. Without this flag, only a preview is shown.")
    mode.add_argument("--dry-run", action="store_true",
                      help="Preview what would be deleted (the default; this flag mainly "
                           "exists to make an already-explicit preview clearer).")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    verbosity = parser.add_mutually_exclusive_group()
    verbosity.add_argument("-v", "--verbose", action="store_true",
                           help="Show debug output (e.g. the mega-* commands being run)")
    verbosity.add_argument("-q", "--quiet", action="store_true",
                           help="Suppress progress messages; only warnings/errors and "
                                "the report are shown")

    return parser


def main() -> None:
    args = build_parser().parse_args()
    configure_logging(args.verbose, args.quiet)

    config_path, config_filters, _ = resolve_config(args.config)
    defaults = load_defaults(config_path)
    validate_defaults(defaults)
    keep_n, older_than = resolve_retention(args.keep_n, args.older_than, defaults)
    if args.keep_n is None and defaults.get("keep_n") is not None:
        log.info("Using keep_n=%d from config [defaults]", keep_n)
    if args.older_than is None and defaults.get("older_than") is not None:
        log.info("Using older_than=%d from config [defaults]", older_than)

    check_logged_in()
    versioned = load_versioned(args)
    warn_on_count_mismatches(versioned)
    selected  = apply_filters(versioned, args, config_filters)

    all_version_bytes = sum(vf.version_size for vf in versioned.values())

    if not selected:
        print("No files matched the active filters.")
        return

    if args.dry_run or not args.yes:
        print_dry_run(selected, all_version_bytes, keep_n, older_than)
    else:
        ok = execute_prune(selected, keep_n, older_than)
        if not ok:
            sys.exit(1)


if __name__ == "__main__":
    main()

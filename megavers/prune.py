#!/usr/bin/env python3
"""
MEGA Version Pruner

Selectively deletes old file versions based on filters defined in config.toml.
Deletes by default — pass --dry-run to preview first.

Keeps the current (latest) version of every file untouched.
"""

import re
import sys
import json
import argparse
import subprocess
import tomllib
from datetime import datetime, timedelta
from importlib.resources import files
from pathlib import Path, PurePosixPath

from megavers import __version__
from megavers.analyze import (
    OldVersion, VersionedFile, check_logged_in, fetch_raw, parse, fmt_size, fmt_date,
)

USER_CONFIG_SEARCH_PATH = [
    Path.cwd() / "config.toml",
    Path.home() / ".config" / "megavers" / "config.toml",
]

BUNDLED_CONFIG_LABEL = "<bundled default>"


# ── Config loading ────────────────────────────────────────────────────────────

def find_user_config() -> Path | None:
    """Return the first user-supplied config found on disk, or None."""
    for candidate in USER_CONFIG_SEARCH_PATH:
        if candidate.exists():
            return candidate
    return None


def load_config(path: Path | None) -> list[dict]:
    """Load filters from `path`, or from the bundled default config when `path` is None."""
    if path is None:
        data = tomllib.loads(files("megavers").joinpath("config.toml").read_text("utf-8"))
    else:
        with open(path, "rb") as fh:
            data = tomllib.load(fh)
    return data.get("filter", [])


def build_filter_fn(f: dict):
    """Return a match function for a config filter entry."""
    path_patterns = f.get("path_contains", [])
    extensions    = {e.lower() for e in f.get("extensions", [])}

    def match(vf: VersionedFile) -> bool:
        path = vf.path.lower()
        path_ok = not path_patterns or any(p.lower() in path for p in path_patterns)
        if not path_ok:
            return False
        if not extensions:
            return True
        # Handle double extensions like .tar.gz
        suffix = PurePosixPath(path).suffix
        if path.endswith(".tar.gz"):
            suffix = ".gz"
        elif path.endswith(".tar.bz2"):
            suffix = ".bz2"
        elif path.endswith(".tar.xz"):
            suffix = ".xz"
        return suffix in extensions

    return match


# ── Scanning / loading ────────────────────────────────────────────────────────

def load_versioned(args) -> dict[str, VersionedFile]:
    if args.from_json:
        with open(args.from_json) as fh:
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
        print(f"Loaded {len(out)} versioned files from {args.from_json}.")
        return out
    else:
        print(f"Scanning {args.path!r} …", flush=True)
        lines = fetch_raw(args.path)
        print(f"  {len(lines)} lines received.", flush=True)
        versioned = parse(lines)
        print(f"  {len(versioned)} files have old versions.")
        return versioned


def warn_on_count_mismatches(versioned: dict[str, VersionedFile]) -> None:
    """Flag files where fewer old versions were parsed than mega-ls reported —
    e.g. versions owned by a contact, which deleteversions/rm cannot remove."""
    for vf in versioned.values():
        if vf.old_count != vf.total_versions - 1:
            print(f"Warning: {vf.path} reports {vf.total_versions} total versions "
                  f"but only {vf.old_count} were parsed — some old versions may not "
                  "be deletable (e.g. owned by a contact).", file=sys.stderr)


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
        def _ext_match(vf: VersionedFile, exts=exts) -> bool:
            p = vf.path.lower()
            if any(p.endswith(e) for e in exts if e in (".gz", ".bz2", ".xz")):
                return True
            return PurePosixPath(p).suffix in exts
        active_fns.append(_ext_match)

    if not active_fns:
        print("Error: no active filters. Check your config.toml or --filter arguments.",
              file=sys.stderr)
        sys.exit(1)

    # OR logic across all active filters
    selected = [vf for vf in versioned.values() if any(fn(vf) for fn in active_fns)]

    if args.min_version_size:
        threshold = parse_size(args.min_version_size)
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

def versions_to_delete(vf: VersionedFile, keep_n: int | None, older_than: int | None) \
        -> list[OldVersion]:
    if keep_n is not None and older_than is not None:
        # OR logic: delete if outside the top N *or* older than the cutoff.
        # Anything that fails either condition is removed.
        recent = set(id(v) for v in vf.old_versions[:keep_n])
        cutoff = datetime.now() - timedelta(days=older_than)
        return [
            v for v in vf.old_versions
            if id(v) not in recent or datetime.fromisoformat(v.mtime) < cutoff
        ]
    if keep_n is not None:
        return vf.old_versions[keep_n:]
    if older_than is not None:
        cutoff = datetime.now() - timedelta(days=older_than)
        return [v for v in vf.old_versions if datetime.fromisoformat(v.mtime) < cutoff]
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
    print("DRY RUN — nothing deleted")
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
    print("Re-run without --dry-run to permanently delete.")


# ── Execution ─────────────────────────────────────────────────────────────────

BATCH_SIZE = 50

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

    # Never delete a file's current version — old-version handles must never
    # collide with the current-version handles of the files we scanned.
    current_handles = {vf.handle for vf, _ in rows if vf.handle}
    unsafe = [h for h in all_handles if h in current_handles]
    if unsafe:
        print(f"Refusing to continue: {len(unsafe)} version(s) scheduled for deletion "
              "match a file's current-version handle. This should not happen — "
              "aborting without deleting anything.", file=sys.stderr)
        return False

    if no_handle:
        print(f"Warning: {no_handle} version(s) have no handle and will be skipped. "
              "Re-scan without --from-json to get handles.", file=sys.stderr)
    if not all_handles:
        print("No deletable versions found (no handles available).")
        return True

    print(f"\nDeleting {len(all_handles)} old version(s) across {len(rows)} file(s) "
          f"({fmt_size(total_bytes)} to recover) …")
    return _run_batched("mega-rm", all_handles, total_bytes)


def _run_batched(cmd: str, items: list[str], total_bytes: int) -> bool:
    """Run `cmd -f <items...>` in batches. Returns True if every batch succeeded."""
    errors = []
    for i in range(0, len(items), BATCH_SIZE):
        batch = items[i:i + BATCH_SIZE]
        end = min(i + BATCH_SIZE, len(items))
        print(f"  [{i + 1}–{end} / {len(items)}] …", end=" ", flush=True)
        r = subprocess.run(
            [cmd, "-f", *batch],
            capture_output=True, text=True, stdin=subprocess.DEVNULL,
        )
        if r.returncode != 0:
            print("ERROR")
            errors.append((batch, r.stderr.strip()))
        else:
            print("OK")

    print()
    if errors:
        print(f"Completed with {len(errors)} batch error(s):")
        for batch, msg in errors:
            print(f"  {msg}")
            for item in batch:
                print(f"    {item}")
        return False

    print(f"Done. {len(items)} version(s) processed.")
    print(f"Recovered approximately {fmt_size(total_bytes)}.")
    return True


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Prune MEGA file version histories (requires MEGAcmd). "
                    "Filters are defined in config.toml. "
                    "Deletes by default — pass --dry-run to preview first.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  # Delete with all filters from config.toml
  megavers-prune

  # Preview before deleting
  megavers-prune --dry-run

  # Run only the 'git' filter defined in config.toml
  megavers-prune --filter git

  # Keep only the 3 most recent old versions per matched file
  megavers-prune --keep-n 3 --dry-run

  # Delete versions older than 90 days (all config filters)
  megavers-prune --older-than 90

  # Ad-hoc: any file whose path contains 'backup'
  megavers-prune --path-contains backup

  # Reuse a previously saved scan
  megavers-prune --from-json results.json
""",
    )

    src = parser.add_argument_group("source")
    src.add_argument("path", nargs="?", default="/",
                     help="Cloud path to scan (default: /)")
    src.add_argument("--from-json", metavar="FILE",
                     help="Load from megavers-analyze --json output (skips re-scanning)")
    src.add_argument("--config", metavar="FILE", type=Path, default=None,
                     help="Config file path. Default search order: "
                          "./config.toml → ~/.config/megavers/config.toml "
                          "→ bundled default")

    flt = parser.add_argument_group("filters")
    flt.add_argument("--filter", metavar="NAME", action="append",
                     help="Activate only this config filter by name (repeatable; "
                          "default: all filters in config)")
    flt.add_argument("--path-contains", metavar="STR", action="append",
                     help="Ad-hoc: select files whose path contains STR (repeatable)")
    flt.add_argument("--ext", metavar="EXT", action="append",
                     help="Ad-hoc: select files with this extension, e.g. .pkl (repeatable)")
    flt.add_argument("--min-version-size", metavar="SIZE",
                     help="Only select files where version space >= SIZE (e.g. 10MB)")

    sel = parser.add_argument_group("version selection (applied after filters)")
    sel.add_argument("--keep-n", type=int, metavar="N",
                     help="Keep the N most recent old versions; delete the rest")
    sel.add_argument("--older-than", type=int, metavar="DAYS",
                     help="Delete old versions whose age exceeds DAYS days")

    mode = parser.add_argument_group("mode")
    mode.add_argument("--dry-run", action="store_true",
                      help="Preview what would be deleted without actually deleting.")
    mode.add_argument("--list-filters", action="store_true",
                      help="List filters defined in config and exit.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    args = parser.parse_args()

    config_path = args.config or find_user_config()
    config_filters = load_config(config_path)
    config_label = str(config_path) if config_path else BUNDLED_CONFIG_LABEL

    if args.list_filters:
        print(f"Filters in {config_label}:")
        for f in config_filters:
            print(f"  [{f['name']}]  {f.get('description', '')}")
            if f.get("path_contains"):
                print(f"    path_contains: {f['path_contains']}")
            if f.get("extensions"):
                print(f"    extensions:    {f['extensions']}")
        return

    check_logged_in()
    versioned = load_versioned(args)
    warn_on_count_mismatches(versioned)
    selected  = apply_filters(versioned, args, config_filters)

    all_version_bytes = sum(vf.version_size for vf in versioned.values())

    if not selected:
        print("No files matched the active filters.")
        return

    if args.dry_run:
        print_dry_run(selected, all_version_bytes, args.keep_n, args.older_than)
    else:
        ok = execute_prune(selected, args.keep_n, args.older_than)
        if not ok:
            sys.exit(1)


if __name__ == "__main__":
    main()

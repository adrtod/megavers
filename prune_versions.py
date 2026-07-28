#!/usr/bin/env python3
"""
MEGA Version Pruner

Selectively deletes old file versions based on filters.
Deletes by default — pass --dry-run to preview first.

Keeps the current (latest) version of every file untouched.
"""

import re
import sys
import json
import argparse
import subprocess
from datetime import datetime, timedelta
from pathlib import PurePosixPath

from analyze_versions import (
    OldVersion, VersionedFile, check_logged_in, fetch_raw, parse, fmt_size, fmt_date,
)


# ── Built-in filter definitions ───────────────────────────────────────────────

FILTER_GIT = dict(
    name="git",
    description="files inside .git/ directories",
    match=lambda vf: "/.git/" in vf.path,
)

_RESULT_EXTS = {
    ".pkl", ".gz", ".zip", ".tar",
    ".png", ".jpg", ".jpeg", ".svg",
    ".bin", ".h5", ".hdf5", ".npy", ".npz",
    ".pt", ".pth", ".mat", ".csv", ".parquet",
}

def _is_result(vf: VersionedFile) -> bool:
    path = vf.path.lower()
    parts = set(PurePosixPath(path).parts)
    in_results_dir = bool(parts & {"results", "sandbox", "outputs", "out", "artifacts"})
    suffix = PurePosixPath(path).suffix
    if path.endswith(".tar.gz") or path.endswith(".tar.bz2"):
        suffix = ".gz"
    return in_results_dir and suffix in _RESULT_EXTS

FILTER_RESULTS = dict(
    name="results",
    description="binary result/output files (.pkl, .tar.gz, .png …) under results/ dirs",
    match=_is_result,
)


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
                old_versions=[
                    OldVersion(
                        size=v["size"], mtime=v["mtime"], version_num=v["version_num"],
                        handle=v.get("handle", ""),
                    )
                    for v in r["versions"]
                ],
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


# ── Filtering ─────────────────────────────────────────────────────────────────

def apply_filters(versioned: dict[str, VersionedFile], args) -> list[VersionedFile]:
    active = []

    if not args.no_git:
        active.append(FILTER_GIT["match"])
    if not args.no_results:
        active.append(FILTER_RESULTS["match"])
    if args.path_contains:
        for pat in args.path_contains:
            active.append(lambda vf, p=pat: p in vf.path)
    if args.ext:
        exts = {e if e.startswith(".") else "." + e for e in args.ext}
        active.append(lambda vf: PurePosixPath(vf.path).suffix in exts)

    if not active:
        print("Error: no filters active. All built-in filters were disabled and none added.",
              file=sys.stderr)
        sys.exit(1)

    selected = [vf for vf in versioned.values() if any(f(vf) for f in active)]

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


# ── Version selection (for --keep-n / --older-than) ───────────────────────────

def versions_to_delete(vf: VersionedFile, keep_n: int | None, older_than: int | None) \
        -> list[OldVersion]:
    """
    Return the subset of old versions that should be deleted for this file.
    Versions are ordered most-recent-first (as returned by mega-ls --versions).
    """
    if keep_n is not None and older_than is not None:
        # Both: keep the N most recent AND drop the age filter on those kept ones
        recent = set(id(v) for v in vf.old_versions[:keep_n])
        cutoff = datetime.now() - timedelta(days=older_than)
        return [
            v for v in vf.old_versions
            if id(v) not in recent
            or datetime.fromisoformat(v.mtime) < cutoff
        ]
    if keep_n is not None:
        return vf.old_versions[keep_n:]
    if older_than is not None:
        cutoff = datetime.now() - timedelta(days=older_than)
        return [v for v in vf.old_versions if datetime.fromisoformat(v.mtime) < cutoff]
    return list(vf.old_versions)   # delete all old versions


# ── Dry-run report ────────────────────────────────────────────────────────────

def print_dry_run(
    selected: list[VersionedFile],
    all_version_bytes: int,
    keep_n: int | None,
    older_than: int | None,
) -> None:
    rows = [(vf, versions_to_delete(vf, keep_n, older_than)) for vf in selected]
    rows = [(vf, vs) for vf, vs in rows if vs]   # skip files with nothing to delete

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

    selective = keep_n is not None or older_than is not None
    if selective:
        print(f"{'DELETE':>6}  {'KEEP':>4}  {'RECOVER':>9}  PATH")
        print("-" * 72)
        for vf, to_del in sorted(rows, key=lambda r: sum(v.size for v in r[1]), reverse=True):
            kept = vf.old_count - len(to_del)
            size = sum(v.size for v in to_del)
            print(f"{len(to_del):>6}  {kept:>4}  {fmt_size(size):>9}  {vf.path}")
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
) -> None:
    selective = keep_n is not None or older_than is not None

    if not selective:
        # Fast path: mega-deleteversions removes all old versions in one call per file
        total = sum(vf.version_size for vf in selected)
        print(f"\nDeleting all old versions for {len(selected)} files "
              f"({fmt_size(total)} to recover) …")
        paths = [vf.path for vf in selected]
        _run_batched("mega-deleteversions", ["-f"], paths, total, len(selected), "files")

    else:
        # Selective path: collect individual version handles and delete with mega-rm
        rows = [(vf, versions_to_delete(vf, keep_n, older_than)) for vf in selected]
        rows = [(vf, vs) for vf, vs in rows if vs]

        all_handles = [v.handle for _, vs in rows for v in vs if v.handle]
        no_handle   = sum(1 for _, vs in rows for v in vs if not v.handle)
        total_bytes = sum(v.size for _, vs in rows for v in vs)

        if no_handle:
            print(f"Warning: {no_handle} version(s) have no handle and will be skipped. "
                  "Re-scan without --from-json to get handles.", file=sys.stderr)
        if not all_handles:
            print("No deletable versions found (no handles available).")
            return

        print(f"\nDeleting {len(all_handles)} specific old versions "
              f"({fmt_size(total_bytes)} to recover) …")
        _run_batched("mega-rm", [], all_handles, total_bytes, len(all_handles), "versions")


def _run_batched(
    cmd: str, flags: list[str], items: list[str],
    total_bytes: int, total_items: int, label: str,
) -> None:
    errors = []
    for i in range(0, len(items), BATCH_SIZE):
        batch = items[i:i + BATCH_SIZE]
        end = min(i + BATCH_SIZE, len(items))
        print(f"  [{i + 1}–{end} / {len(items)}] …", end=" ", flush=True)
        r = subprocess.run([cmd] + flags + batch, capture_output=True, text=True)
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
    else:
        print(f"Done. {total_items} {label} processed.")
        print(f"Recovered approximately {fmt_size(total_bytes)}.")


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Prune MEGA file version histories (requires MEGAcmd). "
                    "Deletes by default — pass --dry-run to preview first.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
filters (combinable, OR logic — git and results are on by default):
  --no-git           disable the .git/ filter
  --no-results       disable the binary result/output files filter
  --path-contains S  path contains the given string (repeatable)
  --ext EXT          file extension, e.g. .pkl (repeatable)

examples:
  # Delete with default filters (git + results)
  python3 prune_versions.py

  # Preview before deleting
  python3 prune_versions.py --dry-run

  # Keep only the 3 most recent old versions of each matched file
  python3 prune_versions.py --keep-n 3 --dry-run

  # Drop versions older than 90 days across all files
  python3 prune_versions.py --no-git --no-results --ext "" --older-than 90

  # Delete, reusing a previously saved scan
  python3 prune_versions.py --from-json results.json
""",
    )

    src = parser.add_argument_group("source")
    src.add_argument("path", nargs="?", default="/",
                     help="Cloud path to scan (default: /)")
    src.add_argument("--from-json", metavar="FILE",
                     help="Load versioned-file list from analyze_versions.py --json output "
                          "(skips re-scanning)")

    flt = parser.add_argument_group("filters")
    flt.add_argument("--no-git", action="store_true",
                     help="Disable the .git/ filter (on by default)")
    flt.add_argument("--no-results", action="store_true",
                     help="Disable the binary result/output files filter (on by default)")
    flt.add_argument("--path-contains", metavar="STR", action="append",
                     help="Select files whose path contains STR (repeatable)")
    flt.add_argument("--ext", metavar="EXT", action="append",
                     help="Select files with this extension, e.g. .pkl (repeatable)")
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

    args = parser.parse_args()

    check_logged_in()
    versioned = load_versioned(args)
    selected  = apply_filters(versioned, args)

    all_version_bytes = sum(vf.version_size for vf in versioned.values())

    if not selected:
        print("No files matched the given filters.")
        return

    if args.dry_run:
        print_dry_run(selected, all_version_bytes, args.keep_n, args.older_than)
    else:
        execute_prune(selected, args.keep_n, args.older_than)


if __name__ == "__main__":
    main()

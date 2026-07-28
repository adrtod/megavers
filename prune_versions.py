#!/usr/bin/env python3
"""
MEGA Version Pruner

Selectively deletes old file versions based on filters.
Always runs as dry-run by default; pass --execute to actually delete.

Keeps the current (latest) version of every file untouched.
"""

import re
import sys
import json
import argparse
import subprocess
from pathlib import PurePosixPath

from analyze_versions import (
    VersionedFile, check_logged_in, fetch_raw, parse, fmt_size,
)


# ── Built-in filter definitions ───────────────────────────────────────────────

# Files inside a .git/ directory — pack files, loose objects, index, etc.
FILTER_GIT = dict(
    name="git",
    description="files inside .git/ directories",
    match=lambda vf: "/.git/" in vf.path,
)

# Large binary result/output files that regenerate often
_RESULT_EXTS = {
    ".pkl", ".gz", ".zip", ".tar",
    ".png", ".jpg", ".jpeg", ".svg",
    ".bin", ".h5", ".hdf5", ".npy", ".npz",
    ".pt", ".pth", ".mat", ".csv", ".parquet",
}
# A path is a "result file" if it sits under a results/ or sandbox/ directory
# AND has a recognised binary/output extension.
def _is_result(vf: VersionedFile) -> bool:
    path = vf.path.lower()
    parts = set(PurePosixPath(path).parts)
    in_results_dir = bool(parts & {"results", "sandbox", "outputs", "out", "artifacts"})
    suffix = PurePosixPath(path).suffix
    # handle .tar.gz double extension
    if path.endswith(".tar.gz") or path.endswith(".tar.bz2"):
        suffix = ".gz"
    return in_results_dir and suffix in _RESULT_EXTS

FILTER_RESULTS = dict(
    name="results",
    description="binary result/output files (.pkl, .tar.gz, .png …) under results/ dirs",
    match=_is_result,
)

BUILTIN_FILTERS = {f["name"]: f for f in [FILTER_GIT, FILTER_RESULTS]}


# ── Scanning / loading ────────────────────────────────────────────────────────

def load_versioned(args) -> dict[str, VersionedFile]:
    if args.from_json:
        with open(args.from_json) as fh:
            records = json.load(fh)
        out = {}
        for r in records:
            from analyze_versions import OldVersion
            vf = VersionedFile(
                path=r["path"], name=r["name"],
                current_size=r["current_size"], current_mtime=r["current_mtime"],
                total_versions=r["old_count"] + 1,
                old_versions=[
                    OldVersion(size=v["size"], mtime=v["mtime"], version_num=v["version_num"])
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

    # Built-in flags
    if not args.no_git:
        active.append(FILTER_GIT["match"])
    if not args.no_results:
        active.append(FILTER_RESULTS["match"])

    # Generic flags
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

    # A file is selected if ANY filter matches (OR logic)
    selected = [vf for vf in versioned.values() if any(f(vf) for f in active)]

    # Optional minimum version-space threshold
    if args.min_version_size:
        threshold = parse_size(args.min_version_size)
        selected = [vf for vf in selected if vf.version_size >= threshold]

    return selected


def parse_size(s: str) -> int:
    """Parse human size string like '10MB', '500KB', '1GB' into bytes."""
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(B|KB|MB|GB|TB)?", s.strip(), re.IGNORECASE)
    if not m:
        raise ValueError(f"Cannot parse size: {s!r}")
    value = float(m.group(1))
    unit = (m.group(2) or "B").upper()
    return int(value * {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3, "TB": 1024**4}[unit])


# ── Dry-run report ────────────────────────────────────────────────────────────

def print_dry_run(selected: list[VersionedFile], all_version_bytes: int) -> None:
    total = sum(vf.version_size for vf in selected)
    count = sum(vf.old_count for vf in selected)

    print()
    print("=" * 72)
    print("DRY RUN — nothing deleted")
    print("=" * 72)
    print(f"  Files selected:              {len(selected)}")
    print(f"  Old versions to delete:      {count}")
    print(f"  Space to recover:            {fmt_size(total)}")
    if all_version_bytes:
        print(f"  % of total version space:   {total / all_version_bytes * 100:.1f}%")
    print()
    print(f"{'VER SPACE':>10}  {'VERS':>5}  PATH")
    print("-" * 72)
    for vf in sorted(selected, key=lambda f: f.version_size, reverse=True):
        print(f"{fmt_size(vf.version_size):>10}  {vf.old_count:>5}  {vf.path}")
    print()
    print("Re-run with --execute to permanently delete these version histories.")


# ── Execution ─────────────────────────────────────────────────────────────────

BATCH_SIZE = 50   # paths per mega-deleteversions call

def execute_prune(selected: list[VersionedFile]) -> None:
    total = sum(vf.version_size for vf in selected)
    print()
    print(f"Deleting versions for {len(selected)} files "
          f"({fmt_size(total)} to recover) …")

    paths = [vf.path for vf in selected]
    errors = []

    for i in range(0, len(paths), BATCH_SIZE):
        batch = paths[i:i + BATCH_SIZE]
        end = min(i + BATCH_SIZE, len(paths))
        print(f"  [{i + 1}–{end} / {len(paths)}] …", end=" ", flush=True)
        r = subprocess.run(
            ["mega-deleteversions", "-f"] + batch,
            capture_output=True, text=True,
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
            for p in batch:
                print(f"    {p}")
    else:
        print(f"Done. Deleted old versions for {len(selected)} files.")
        print(f"Recovered approximately {fmt_size(total)}.")


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Prune MEGA file version histories (requires MEGAcmd). "
                    "Dry-run by default — pass --execute to delete.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
filters (combinable, OR logic — git and results are on by default):
  --no-git           disable the .git/ filter
  --no-results       disable the binary result/output files filter
  --path-contains S  path contains the given string (repeatable)
  --ext EXT          file extension, e.g. .pkl  (repeatable)

examples:
  # Preview default filters (git + results)
  python3 prune_versions.py

  # Delete with default filters
  python3 prune_versions.py --execute

  # Delete, reusing a previously saved scan
  python3 prune_versions.py --from-json results.json --execute

  # Delete versions of all .csv files too
  python3 prune_versions.py --ext .csv --execute

  # Only git, skip results
  python3 prune_versions.py --no-results --execute
""",
    )

    # Source
    src = parser.add_argument_group("source")
    src.add_argument("path", nargs="?", default="/",
                     help="Cloud path to scan (default: /)")
    src.add_argument("--from-json", metavar="FILE",
                     help="Load versioned-file list from analyze_versions.py --json output "
                          "(skips re-scanning)")

    # Filters
    flt = parser.add_argument_group("filters")
    flt.add_argument("--no-git", action="store_true",
                     help="Exclude files inside .git/ directories (git filter is on by default)")
    flt.add_argument("--no-results", action="store_true",
                     help="Exclude binary result/output files under results/ or sandbox/ dirs (on by default)")
    flt.add_argument("--path-contains", metavar="STR", action="append",
                     help="Select files whose path contains STR (repeatable)")
    flt.add_argument("--ext", metavar="EXT", action="append",
                     help="Select files with this extension, e.g. .pkl (repeatable)")
    flt.add_argument("--min-version-size", metavar="SIZE",
                     help="Only select files where version space >= SIZE (e.g. 10MB)")

    # Mode
    mode = parser.add_argument_group("mode")
    mode.add_argument("--execute", action="store_true",
                      help="Actually delete. Without this flag, runs as dry-run.")

    args = parser.parse_args()

    check_logged_in()
    versioned = load_versioned(args)
    selected  = apply_filters(versioned, args)

    all_version_bytes = sum(vf.version_size for vf in versioned.values())

    if not selected:
        print("No files matched the given filters.")
        return

    if args.execute:
        execute_prune(selected)
    else:
        print_dry_run(selected, all_version_bytes)


if __name__ == "__main__":
    main()

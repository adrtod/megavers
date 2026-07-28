#!/usr/bin/env python3
"""
MEGA Versioning Space Analyzer

Uses MEGAcmd (mega-ls) to enumerate all file versions and report
which files consume the most space through their version history.
"""

import re
import sys
import json
import argparse
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from importlib.metadata import version as _pkg_version, PackageNotFoundError

try:
    __version__ = _pkg_version("megavers")
except PackageNotFoundError:
    __version__ = "0.1.0"


# ── Output line patterns ──────────────────────────────────────────────────────

# FLAGS VERS SIZE DATE [H:HANDLE] NAME
# Handle column is present when --show-handles is passed to mega-ls.
# Version names have a MEGA-internal #timestamp suffix that we strip.
NODE_RE = re.compile(
    r'^([a-z-]{4})\s+(\d+|-)\s+(\d+|-)\s+(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})'
    r'\s+(?:(H:[A-Za-z0-9]+)\s+)?(.+)$'
)
VERSIONS_OF_RE = re.compile(r'^Versions of (.+):$')
SECTION_RE     = re.compile(r'^(/?.+):$')


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class OldVersion:
    size:        int
    mtime:       str
    version_num: int
    handle:      str = ""   # H:XXXXXXXX, populated when scanned with --show-handles


@dataclass
class VersionedFile:
    path:           str
    name:           str
    current_size:   int
    current_mtime:  str
    total_versions: int
    old_versions:   list[OldVersion] = field(default_factory=list)

    @property
    def version_size(self) -> int:
        return sum(v.size for v in self.old_versions)

    @property
    def old_count(self) -> int:
        return len(self.old_versions)

    @property
    def oldest_mtime(self) -> str | None:
        return min((v.mtime for v in self.old_versions), default=None)

    @property
    def churn_rate(self) -> float | None:
        """Versions per day, measured from oldest version to now."""
        if not self.old_versions or not self.oldest_mtime:
            return None
        oldest = datetime.fromisoformat(self.oldest_mtime)
        days = (datetime.now() - oldest).total_seconds() / 86400
        if days < 1:
            return None
        return self.old_count / days


# ── MEGAcmd interaction ───────────────────────────────────────────────────────

def check_logged_in() -> None:
    r = subprocess.run(["mega-whoami"], capture_output=True, text=True)
    if "Not logged in" in r.stderr or "Not logged in" in r.stdout:
        print("Not logged into MEGAcmd. Run:  mega-login <email> <password>",
              file=sys.stderr)
        sys.exit(1)


def fetch_raw(path: str) -> list[str]:
    r = subprocess.run(
        ["mega-ls", "-l", "-r", "--versions", "--show-handles",
         "--time-format=ISO6081_WITH_TIME", path],
        capture_output=True, text=True,
    )
    if r.returncode != 0 and not r.stdout.strip():
        print(f"mega-ls failed:\n{r.stderr}", file=sys.stderr)
        sys.exit(1)
    return r.stdout.splitlines()


# ── Parsing ───────────────────────────────────────────────────────────────────

def normalize_path(p: str) -> str:
    p = p.strip()
    return p if p.startswith("/") else "/" + p


def is_decoration(line: str) -> bool:
    """Skip banner boxes and blank lines."""
    s = line.strip()
    return not s or s.startswith("|") or all(c in "- " for c in s)


def parse(lines: list[str]) -> dict[str, VersionedFile]:
    """
    Parse mega-ls -l -r --versions --show-handles output.

    Structure per directory:
      section_header:
        file lines  (FLAGS VERS SIZE DATE [H:HANDLE] NAME)
      Versions of <path>:
        version lines (current first, then old in descending order)
      [next section header]
    """
    versioned: dict[str, VersionedFile] = {}
    current_dir = ""
    versions_of_path: str | None = None   # path whose version block we're in
    version_line_idx = 0                      # 0 = current version (skip)

    for line in lines:
        if is_decoration(line):
            continue

        stripped = line.strip()

        if stripped.startswith("FLAGS "):
            continue

        # "Versions of <path>:" block header
        m = VERSIONS_OF_RE.match(stripped)
        if m:
            versions_of_path = normalize_path(m.group(1))
            version_line_idx = 0
            continue

        # Directory section header "path:"  (not a node line, not a "Versions of")
        m = SECTION_RE.match(stripped)
        if m and not NODE_RE.match(stripped):
            current_dir = normalize_path(m.group(1))
            versions_of_path = None
            continue

        # File / version node line
        m = NODE_RE.match(stripped)
        if not m:
            versions_of_path = None
            continue

        flags, vers_s, size_s, date, handle, name = m.groups()
        handle = handle or ""
        # Strip MEGA's internal version timestamp suffix (e.g. filename#1783436394)
        name = re.sub(r'#\d+$', '', name)
        size = int(size_s) if size_s != "-" else 0
        vers = int(vers_s) if vers_s != "-" else 0
        is_dir = flags[0] == "d"

        if versions_of_path:
            # Inside a "Versions of" block
            if version_line_idx == 0:
                # First line = current version, already recorded — skip
                version_line_idx += 1
                continue
            vf = versioned.get(versions_of_path)
            if vf:
                vf.old_versions.append(OldVersion(
                    size=size, mtime=date, version_num=vers, handle=handle,
                ))
            version_line_idx += 1

        else:
            # Regular directory listing — only care about files with versions
            if is_dir or vers <= 1:
                continue
            full_path = current_dir.rstrip("/") + "/" + name
            versioned[full_path] = VersionedFile(
                path=full_path,
                name=name,
                current_size=size,
                current_mtime=date,
                total_versions=vers,
            )

    return versioned


# ── Formatting ────────────────────────────────────────────────────────────────

def fmt_size(b: int) -> str:
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if b < 1024.0:
            return f"{b:.1f} {unit}"
        b /= 1024.0
    return f"{b:.1f} PB"


def fmt_date(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return iso


# ── Report ────────────────────────────────────────────────────────────────────

def print_report(versioned: dict[str, VersionedFile], top_n: int) -> None:
    files = list(versioned.values())
    total_ver_bytes = sum(f.version_size for f in files)
    total_cur_bytes = sum(f.current_size  for f in files)
    total_old_count = sum(f.old_count     for f in files)

    W = 76
    print()
    print("=" * W)
    print("MEGA VERSIONING SPACE REPORT")
    print("=" * W)
    print(f"  Files with old versions:         {len(files)}")
    print(f"  Total old version count:         {total_old_count}")
    print(f"  Space used by old versions:      {fmt_size(total_ver_bytes)}")
    if total_cur_bytes:
        pct = total_ver_bytes / total_cur_bytes * 100
        print(f"  Overhead vs. current file size:  {pct:.1f}%")
    print()

    # By version space
    print(f"TOP {top_n} FILES BY VERSION SPACE")
    print("-" * W)
    print(f"{'VER SPACE':>10}  {'VERS':>5}  {'CUR SIZE':>10}  PATH")
    print("-" * W)
    for vf in sorted(files, key=lambda f: f.version_size, reverse=True)[:top_n]:
        oldest = fmt_date(vf.oldest_mtime) if vf.oldest_mtime else "-"
        print(f"{fmt_size(vf.version_size):>10}  {vf.old_count:>5}  "
              f"{fmt_size(vf.current_size):>10}  {vf.path}")
        print(f"{'':>10}  {'':>5}  {'oldest:':>10}  {oldest}")
        print()

    # By version count
    print()
    print(f"TOP {top_n} FILES BY VERSION COUNT")
    print("-" * W)
    print(f"{'VERS':>5}  {'VER SPACE':>10}  {'CUR SIZE':>10}  PATH")
    print("-" * W)
    for vf in sorted(files, key=lambda f: f.old_count, reverse=True)[:top_n]:
        print(f"{vf.old_count:>5}  {fmt_size(vf.version_size):>10}  "
              f"{fmt_size(vf.current_size):>10}  {vf.path}")

    # By churn rate
    with_rate = [f for f in files if f.churn_rate is not None]
    print()
    print(f"TOP {top_n} FILES BY CHURN RATE (versions/day)")
    print("-" * W)
    print(f"{'V/DAY':>7}  {'VERS':>5}  {'SINCE':>12}  PATH")
    print("-" * W)
    for vf in sorted(with_rate, key=lambda f: f.churn_rate, reverse=True)[:top_n]:
        since = fmt_date(vf.oldest_mtime)
        print(f"{vf.churn_rate:>7.2f}  {vf.old_count:>5}  {since:>12}  {vf.path}")


# ── JSON export ───────────────────────────────────────────────────────────────

def save_json(versioned: dict[str, VersionedFile], out_path: str) -> None:
    data = [
        {
            "path":          vf.path,
            "name":          vf.name,
            "current_size":  vf.current_size,
            "current_mtime": vf.current_mtime,
            "old_count":     vf.old_count,
            "version_size":  vf.version_size,
            "versions": [
                {
                    "size":        v.size,
                    "mtime":       v.mtime,
                    "version_num": v.version_num,
                    "handle":      v.handle,
                }
                for v in sorted(vf.old_versions, key=lambda v: v.mtime, reverse=True)
            ],
        }
        for vf in sorted(versioned.values(), key=lambda f: f.version_size, reverse=True)
    ]
    with open(out_path, "w") as fh:
        json.dump(data, fh, indent=2)
    print(f"\nFull results saved to: {out_path}")


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Analyze MEGA versioning space usage (requires MEGAcmd)."
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "path", nargs="?", default="/",
        help="Cloud path to analyze (default: /)",
    )
    parser.add_argument("--top",      type=int, default=20, metavar="N",
                        help="Number of top files to display (default: 20)")
    parser.add_argument("--json",     metavar="FILE",
                        help="Save full results as JSON")
    parser.add_argument("--raw-dump", metavar="FILE",
                        help="Save raw mega-ls output for debugging")
    args = parser.parse_args()

    check_logged_in()

    print(f"Scanning {args.path!r} …", flush=True)
    lines = fetch_raw(args.path)
    print(f"  {len(lines)} lines received.", flush=True)

    if args.raw_dump:
        with open(args.raw_dump, "w") as fh:
            fh.write("\n".join(lines))
        print(f"Raw output saved to: {args.raw_dump}")

    versioned = parse(lines)
    print(f"  {len(versioned)} files have old versions.\n")

    print_report(versioned, top_n=args.top)

    if args.json:
        save_json(versioned, args.json)


if __name__ == "__main__":
    main()

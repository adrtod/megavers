"""Tests for megavers.prune filter logic: build_filter_fn(), apply_filters(), versions_to_delete()."""

import types
from datetime import datetime, timedelta, timezone

import pytest

from megavers.analyze import OldVersion, VersionedFile
from megavers.prune import (
    build_filter_fn, apply_filters, versions_to_delete, parse_size,
    validate_filters, _non_negative_int, extension_suffix,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_vf(path, old_versions=None, current_size=1000):
    name = path.rsplit("/", 1)[-1]
    old_versions = old_versions or []
    return VersionedFile(
        path=path,
        name=name,
        current_size=current_size,
        current_mtime="2025-07-01T09:00:00",
        total_versions=len(old_versions) + 1,
        old_versions=old_versions,
    )

def make_ov(size=1000, mtime="2025-01-01T00:00:00", handle="H:Aa"):
    return OldVersion(size=size, mtime=mtime, version_num=1, handle=handle)

def make_args(filter=None, path_contains=None, ext=None, min_version_size=None):
    """Build a minimal argparse-like namespace for apply_filters."""
    ns = types.SimpleNamespace()
    ns.filter = filter
    ns.path_contains = path_contains
    ns.ext = ext
    ns.min_version_size = min_version_size
    return ns


# ── build_filter_fn ───────────────────────────────────────────────────────────

def test_build_filter_fn_path_contains_matches():
    fn = build_filter_fn({"path_contains": ["/.git/"]})
    assert fn(make_vf("/repo/.git/FETCH_HEAD"))

def test_build_filter_fn_path_contains_no_match():
    fn = build_filter_fn({"path_contains": ["/.git/"]})
    assert not fn(make_vf("/docs/notes.txt"))

def test_build_filter_fn_path_contains_case_sensitive():
    # MEGA paths are case-sensitive; a differently-cased pattern must not match.
    fn = build_filter_fn({"path_contains": ["/.GIT/"]})
    assert not fn(make_vf("/repo/.git/FETCH_HEAD"))
    assert fn(make_vf("/repo/.GIT/FETCH_HEAD"))

def test_build_filter_fn_extensions_only_pkl():
    fn = build_filter_fn({"extensions": [".pkl"]})
    assert fn(make_vf("/results/model.pkl"))
    assert not fn(make_vf("/results/model.pt"))

def test_build_filter_fn_extensions_gz():
    fn = build_filter_fn({"extensions": [".gz"]})
    assert fn(make_vf("/data/dump.gz"))

def test_build_filter_fn_extensions_tar_gz():
    fn = build_filter_fn({"extensions": [".gz"]})
    assert fn(make_vf("/data/archive.tar.gz"))

def test_build_filter_fn_extensions_tar_bz2():
    fn = build_filter_fn({"extensions": [".bz2"]})
    assert fn(make_vf("/data/archive.tar.bz2"))

def test_build_filter_fn_extensions_tar_xz():
    fn = build_filter_fn({"extensions": [".xz"]})
    assert fn(make_vf("/data/archive.tar.xz"))

def test_build_filter_fn_tar_bz2_does_not_match_gz():
    fn = build_filter_fn({"extensions": [".gz"]})
    assert not fn(make_vf("/data/archive.tar.bz2"))

def test_build_filter_fn_both_and_logic_match():
    fn = build_filter_fn({"path_contains": ["/results/"], "extensions": [".pkl"]})
    assert fn(make_vf("/results/model.pkl"))

def test_build_filter_fn_both_and_logic_path_fails():
    fn = build_filter_fn({"path_contains": ["/results/"], "extensions": [".pkl"]})
    assert not fn(make_vf("/other/model.pkl"))

def test_build_filter_fn_both_and_logic_ext_fails():
    fn = build_filter_fn({"path_contains": ["/results/"], "extensions": [".pkl"]})
    assert not fn(make_vf("/results/model.pt"))

def test_build_filter_fn_empty_matches_everything():
    # build_filter_fn() itself stays permissive; validate_filters() is the guard
    # that rejects such a filter before it ever reaches here.
    fn = build_filter_fn({})
    assert fn(make_vf("/any/file.xyz"))

def test_build_filter_fn_multiple_path_contains_or():
    fn = build_filter_fn({"path_contains": ["/results/", "/sandbox/"]})
    assert fn(make_vf("/results/out.pkl"))
    assert fn(make_vf("/sandbox/tmp.pkl"))
    assert not fn(make_vf("/other/file.pkl"))


# ── apply_filters ─────────────────────────────────────────────────────────────

def test_apply_filters_or_logic():
    vf_git = make_vf("/repo/.git/FETCH_HEAD", [make_ov()])
    vf_pkl = make_vf("/results/model.pkl", [make_ov(size=2000)])
    vf_other = make_vf("/docs/notes.txt", [make_ov()])
    versioned = {vf.path: vf for vf in [vf_git, vf_pkl, vf_other]}

    config_filters = [
        {"name": "git", "path_contains": ["/.git/"]},
        {"name": "results", "path_contains": ["/results/"], "extensions": [".pkl"]},
    ]
    args = make_args()
    selected = apply_filters(versioned, args, config_filters)
    paths = {vf.path for vf in selected}
    assert "/repo/.git/FETCH_HEAD" in paths
    assert "/results/model.pkl" in paths
    assert "/docs/notes.txt" not in paths

def test_apply_filters_named_filter_subset():
    vf_git = make_vf("/repo/.git/HEAD", [make_ov()])
    vf_pkl = make_vf("/results/model.pkl", [make_ov()])
    versioned = {vf.path: vf for vf in [vf_git, vf_pkl]}

    config_filters = [
        {"name": "git", "path_contains": ["/.git/"]},
        {"name": "results", "path_contains": ["/results/"]},
    ]
    args = make_args(filter=["git"])
    selected = apply_filters(versioned, args, config_filters)
    paths = {vf.path for vf in selected}
    assert "/repo/.git/HEAD" in paths
    assert "/results/model.pkl" not in paths

def test_apply_filters_min_version_size():
    vf_small = make_vf("/repo/.git/HEAD", [make_ov(size=500)])
    vf_large = make_vf("/repo/.git/index", [make_ov(size=2 * 1024 * 1024)])
    versioned = {vf.path: vf for vf in [vf_small, vf_large]}

    config_filters = [{"name": "git", "path_contains": ["/.git/"]}]
    args = make_args(min_version_size="1MB")
    selected = apply_filters(versioned, args, config_filters)
    paths = {vf.path for vf in selected}
    assert "/repo/.git/index" in paths
    assert "/repo/.git/HEAD" not in paths

def test_apply_filters_adhoc_path_contains():
    vf_backup = make_vf("/backup/file.zip", [make_ov()])
    vf_other = make_vf("/docs/notes.txt", [make_ov()])
    versioned = {vf.path: vf for vf in [vf_backup, vf_other]}

    args = make_args(path_contains=["backup"])
    selected = apply_filters(versioned, args, [])
    assert len(selected) == 1
    assert selected[0].path == "/backup/file.zip"

def test_apply_filters_adhoc_ext():
    vf_pkl = make_vf("/data/model.pkl", [make_ov()])
    vf_pt = make_vf("/data/model.pt", [make_ov()])
    versioned = {vf.path: vf for vf in [vf_pkl, vf_pt]}

    args = make_args(ext=["pkl"])
    selected = apply_filters(versioned, args, [])
    assert len(selected) == 1
    assert selected[0].path == "/data/model.pkl"

def test_apply_filters_adhoc_ext_with_dot():
    vf_pkl = make_vf("/data/model.pkl", [make_ov()])
    versioned = {vf_pkl.path: vf_pkl}
    args = make_args(ext=[".pkl"])
    selected = apply_filters(versioned, args, [])
    assert len(selected) == 1


# ── versions_to_delete ────────────────────────────────────────────────────────

def _vf_with_versions(mtimes):
    """Build a VersionedFile with old versions at given ISO mtime strings."""
    old_versions = [
        OldVersion(size=1000, mtime=m, version_num=i + 1, handle=f"H:{i:08X}")
        for i, m in enumerate(mtimes)
    ]
    return make_vf("/some/file.txt", old_versions)

def test_versions_to_delete_neither_returns_all():
    vf = _vf_with_versions(["2025-01-01T00:00:00", "2025-02-01T00:00:00"])
    result = versions_to_delete(vf, None, None)
    assert len(result) == 2

def test_versions_to_delete_keep_n_only():
    vf = _vf_with_versions([
        "2025-07-01T00:00:00",
        "2025-06-01T00:00:00",
        "2025-05-01T00:00:00",
        "2025-04-01T00:00:00",
    ])
    result = versions_to_delete(vf, 2, None)
    assert len(result) == 2
    # deleted ones are the older tail (index 2 and 3)
    deleted_mtimes = {v.mtime for v in result}
    assert "2025-05-01T00:00:00" in deleted_mtimes
    assert "2025-04-01T00:00:00" in deleted_mtimes

def test_versions_to_delete_keep_n_gte_count_returns_empty():
    vf = _vf_with_versions(["2025-01-01T00:00:00", "2025-02-01T00:00:00"])
    assert versions_to_delete(vf, 5, None) == []

def test_versions_to_delete_keep_n_zero_returns_all():
    vf = _vf_with_versions(["2025-01-01T00:00:00", "2025-02-01T00:00:00"])
    result = versions_to_delete(vf, 0, None)
    assert len(result) == 2

def test_versions_to_delete_older_than_only(monkeypatch):
    now = datetime(2025, 8, 1, 12, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("megavers.prune.datetime", type("dt", (), {
        "now": staticmethod(lambda tz=None: now),
    }))
    vf = _vf_with_versions([
        "2025-07-25T00:00:00",  # 7 days old — keep (< 30)
        "2025-06-01T00:00:00",  # 61 days old — delete
        "2025-01-01T00:00:00",  # 212 days old — delete
    ])
    result = versions_to_delete(vf, None, 30)
    assert len(result) == 2
    deleted_mtimes = {v.mtime for v in result}
    assert "2025-06-01T00:00:00" in deleted_mtimes
    assert "2025-01-01T00:00:00" in deleted_mtimes

def test_versions_to_delete_all_newer_than_cutoff_returns_empty(monkeypatch):
    now = datetime(2025, 8, 1, 12, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("megavers.prune.datetime", type("dt", (), {
        "now": staticmethod(lambda tz=None: now),
    }))
    vf = _vf_with_versions(["2025-07-30T00:00:00", "2025-07-29T00:00:00"])
    result = versions_to_delete(vf, None, 30)
    assert result == []

def test_versions_to_delete_both_or_logic(monkeypatch):
    now = datetime(2025, 8, 1, 12, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("megavers.prune.datetime", type("dt", (), {
        "now": staticmethod(lambda tz=None: now),
    }))
    # keep_n=2, older_than=30 days
    # versions (newest first): v0=recent, v1=recent, v2=old
    # v0 and v1 are in top 2, but v1 might be old anyway
    vf = _vf_with_versions([
        "2025-07-30T00:00:00",  # v0: top-2, recent → KEEP
        "2025-07-29T00:00:00",  # v1: top-2, recent → KEEP
        "2025-01-01T00:00:00",  # v2: outside top-2, old → DELETE
    ])
    result = versions_to_delete(vf, 2, 30)
    assert len(result) == 1
    assert result[0].mtime == "2025-01-01T00:00:00"

def test_versions_to_delete_both_or_logic_old_in_top_n(monkeypatch):
    now = datetime(2025, 8, 1, 12, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("megavers.prune.datetime", type("dt", (), {
        "now": staticmethod(lambda tz=None: now),
    }))
    # keep_n=2, older_than=30: v1 is in top-2 but older than 30 days → DELETE (OR logic)
    vf = _vf_with_versions([
        "2025-07-30T00:00:00",  # v0: top-2, recent → KEEP
        "2025-06-01T00:00:00",  # v1: top-2, but 61 days old → DELETE
        "2025-01-01T00:00:00",  # v2: outside top-2, old → DELETE
    ])
    result = versions_to_delete(vf, 2, 30)
    assert len(result) == 2
    deleted_mtimes = {v.mtime for v in result}
    assert "2025-06-01T00:00:00" in deleted_mtimes
    assert "2025-01-01T00:00:00" in deleted_mtimes


# ── parse_size ────────────────────────────────────────────────────────────────

def test_parse_size_bytes():
    assert parse_size("1024") == 1024

def test_parse_size_kb():
    assert parse_size("1KB") == 1024

def test_parse_size_mb():
    assert parse_size("10MB") == 10 * 1024 ** 2

def test_parse_size_gb():
    assert parse_size("1GB") == 1024 ** 3

def test_parse_size_float():
    assert parse_size("1.5MB") == int(1.5 * 1024 ** 2)

def test_parse_size_case_insensitive():
    assert parse_size("10mb") == 10 * 1024 ** 2


# ── extension_suffix ────────────────────────────────────────────────────────────

def test_extension_suffix_plain():
    assert extension_suffix("/data/model.pkl") == ".pkl"

def test_extension_suffix_tar_gz_compound():
    assert extension_suffix("/data/archive.tar.gz") == ".gz"

def test_extension_suffix_case_insensitive():
    assert extension_suffix("/data/MODEL.PKL") == ".pkl"

def test_extension_suffix_no_extension():
    assert extension_suffix("/data/README") == ""


# ── validate_filters ─────────────────────────────────────────────────────────

def test_validate_filters_accepts_path_contains():
    validate_filters([{"name": "git", "path_contains": ["/.git/"]}])

def test_validate_filters_accepts_extensions():
    validate_filters([{"name": "pkl", "extensions": [".pkl"]}])

def test_validate_filters_rejects_empty_filter():
    with pytest.raises(SystemExit):
        validate_filters([{"name": "oops"}])

def test_validate_filters_rejects_unknown_key():
    with pytest.raises(SystemExit):
        validate_filters([{"name": "typo", "path_contain": ["/.git/"]}])


# ── _non_negative_int ─────────────────────────────────────────────────────────

def test_non_negative_int_accepts_zero_and_positive():
    assert _non_negative_int("0") == 0
    assert _non_negative_int("5") == 5

def test_non_negative_int_rejects_negative():
    with pytest.raises(Exception):
        _non_negative_int("-1")

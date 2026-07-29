"""Tests for CLI argument parsing, config file lookup, and the deletion path
(execute_prune / _run_batched) — the pieces that actually talk to MEGAcmd."""

import json

import pytest

from megavers.analyze import OldVersion, VersionedFile
from megavers.prune import (
    build_parser, find_user_config, init_config, load_config, load_versioned,
    execute_prune, BUNDLED_CONFIG_LABEL,
)


def make_vf(path, old_versions=None, current_size=1000, handle=""):
    name = path.rsplit("/", 1)[-1]
    old_versions = old_versions or []
    return VersionedFile(
        path=path, name=name, current_size=current_size,
        current_mtime="2025-07-01T09:00:00",
        total_versions=len(old_versions) + 1,
        handle=handle, old_versions=old_versions,
    )


def make_ov(size=1000, mtime="2025-01-01T00:00:00", version_num=1, handle="H:Aa"):
    return OldVersion(size=size, mtime=mtime, version_num=version_num, handle=handle)


# ── CLI argument parsing ──────────────────────────────────────────────────────

def test_build_parser_defaults():
    args = build_parser().parse_args([])
    assert args.path == "/"
    assert args.yes is False
    assert args.dry_run is False
    assert args.keep_n is None
    assert args.older_than is None

def test_build_parser_rejects_negative_keep_n():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--keep-n", "-1"])

def test_build_parser_rejects_negative_older_than():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--older-than", "-10"])

def test_build_parser_accepts_zero_keep_n():
    args = build_parser().parse_args(["--keep-n", "0"])
    assert args.keep_n == 0

def test_build_parser_yes_flag():
    args = build_parser().parse_args(["--yes"])
    assert args.yes is True

def test_build_parser_repeatable_filter():
    args = build_parser().parse_args(["--filter", "git", "--filter", "results"])
    assert args.filter == ["git", "results"]

def test_build_parser_path_positional():
    args = build_parser().parse_args(["/some/path"])
    assert args.path == "/some/path"


# ── Config file lookup precedence ─────────────────────────────────────────────

def test_find_user_config_none_when_absent(tmp_path, monkeypatch):
    monkeypatch.setattr("megavers.prune.USER_CONFIG_SEARCH_PATH", [
        tmp_path / ".megavers.toml", tmp_path / "nonexistent-home" / "config.toml",
    ])
    assert find_user_config() is None

def test_find_user_config_prefers_cwd_over_home(tmp_path, monkeypatch):
    cwd = tmp_path / "cwd"
    home = tmp_path / "home"
    cwd.mkdir()
    home.mkdir()
    (cwd / ".megavers.toml").write_text("[[filter]]\nname='cwd'\n")
    (home / ".config" / "megavers").mkdir(parents=True)
    (home / ".config" / "megavers" / "config.toml").write_text("[[filter]]\nname='home'\n")

    monkeypatch.chdir(cwd)
    monkeypatch.setattr("megavers.prune.Path.home", lambda: home)
    monkeypatch.setattr("megavers.prune.USER_CONFIG_SEARCH_PATH", [
        cwd / ".megavers.toml", home / ".config" / "megavers" / "config.toml",
    ])
    found = find_user_config()
    assert found == cwd / ".megavers.toml"

def test_load_config_bundled_fallback_when_path_is_none():
    # The bundled default ships with generally-applicable filters active;
    # more workflow-specific examples (e.g. "results") are commented out.
    filters = load_config(None)
    names = {f["name"] for f in filters}
    assert names == {
        "git", "os-junk", "editor-swap", "office-locks",
        "python-cache-dirs", "python-bytecode",
    }

def test_load_config_from_explicit_path(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text('[[filter]]\nname = "custom"\npath_contains = ["/x/"]\n')
    filters = load_config(cfg)
    assert filters == [{"name": "custom", "path_contains": ["/x/"]}]

def test_bundled_config_label_used_when_no_user_config():
    assert BUNDLED_CONFIG_LABEL == "<bundled default>"


# ── --init-config ──────────────────────────────────────────────────────────────

def test_init_config_writes_bundled_default(tmp_path):
    dest = tmp_path / "nested" / "config.toml"
    init_config(dest)
    filters = load_config(dest)
    assert filters == load_config(None)

def test_init_config_refuses_to_overwrite(tmp_path):
    dest = tmp_path / "config.toml"
    dest.write_text("[[filter]]\nname = 'mine'\npath_contains = ['/x/']\n")
    with pytest.raises(SystemExit):
        init_config(dest)
    # Original content must survive the refused overwrite.
    assert "mine" in dest.read_text()


# ── --from-json round-trip ────────────────────────────────────────────────────

def test_from_json_round_trip(tmp_path):
    data = [{
        "path": "/docs/notes.txt", "name": "notes.txt",
        "current_size": 1000, "current_mtime": "2025-07-01T09:00:00",
        "flags": "----", "handle": "H:CUR",
        "old_count": 2, "version_size": 300,
        "versions": [
            {"size": 100, "mtime": "2025-06-01T00:00:00", "version_num": 2, "handle": "H:V2"},
            {"size": 200, "mtime": "2025-05-01T00:00:00", "version_num": 1, "handle": "H:V1"},
        ],
    }]
    json_path = tmp_path / "scan.json"
    json_path.write_text(json.dumps(data), encoding="utf-8")

    class Args:
        from_json = str(json_path)

    versioned = load_versioned(Args())
    assert "/docs/notes.txt" in versioned
    vf = versioned["/docs/notes.txt"]
    assert vf.handle == "H:CUR"
    assert vf.flags == "----"
    assert [v.version_num for v in vf.old_versions] == [2, 1]

def test_from_json_missing_file_exits(tmp_path):
    class Args:
        from_json = str(tmp_path / "does-not-exist.json")

    with pytest.raises(SystemExit):
        load_versioned(Args())

def test_from_json_malformed_exits(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text('[{"path": "/x"}]', encoding="utf-8")  # missing required keys

    class Args:
        from_json = str(bad)

    with pytest.raises(SystemExit):
        load_versioned(Args())


# ── execute_prune / _run_batched ──────────────────────────────────────────────

def test_execute_prune_calls_mega_rm_with_handles_and_force(monkeypatch):
    calls = []

    def fake_run_mega(cmd, **kwargs):
        calls.append(cmd)
        class R:
            returncode = 0
            stderr = ""
        return R()

    monkeypatch.setattr("megavers.prune.run_mega", fake_run_mega)

    vf = make_vf("/docs/notes.txt", handle="H:CURRENT", old_versions=[
        make_ov(version_num=2, handle="H:OLD2"),
        make_ov(version_num=1, handle="H:OLD1"),
    ])
    ok = execute_prune([vf], None, None)

    assert ok is True
    assert len(calls) == 1
    cmd = calls[0]
    assert cmd[0] == "mega-rm"
    assert "-f" in cmd
    assert "H:OLD2" in cmd and "H:OLD1" in cmd
    assert "H:CURRENT" not in cmd

def test_execute_prune_refuses_when_old_version_matches_current_handle(monkeypatch):
    calls = []
    monkeypatch.setattr("megavers.prune.run_mega", lambda cmd, **kw: calls.append(cmd))

    vf = make_vf("/docs/bad.txt", handle="H:SAME", old_versions=[
        make_ov(version_num=1, handle="H:SAME"),
    ])
    ok = execute_prune([vf], None, None)

    assert ok is False
    assert calls == []  # nothing was ever executed

def test_execute_prune_returns_false_on_batch_error(monkeypatch):
    def fake_run_mega(cmd, **kwargs):
        class R:
            returncode = 1
            stderr = "some MEGAcmd error"
        return R()

    monkeypatch.setattr("megavers.prune.run_mega", fake_run_mega)

    vf = make_vf("/docs/notes.txt", handle="H:CURRENT", old_versions=[
        make_ov(version_num=1, handle="H:OLD1"),
    ])
    ok = execute_prune([vf], None, None)
    assert ok is False

def test_execute_prune_skips_versions_without_handles(monkeypatch):
    calls = []

    def fake_run_mega(cmd, **kwargs):
        calls.append(cmd)
        class R:
            returncode = 0
            stderr = ""
        return R()

    monkeypatch.setattr("megavers.prune.run_mega", fake_run_mega)

    vf = make_vf("/docs/notes.txt", handle="H:CURRENT", old_versions=[
        make_ov(version_num=1, handle=""),  # no handle — can't be deleted
    ])
    ok = execute_prune([vf], None, None)

    assert ok is True
    assert calls == []  # nothing to delete


# ── dry-run and execute agree on what's selected ──────────────────────────────

def test_dry_run_and_execute_use_the_same_row_computation(monkeypatch):
    from megavers.prune import compute_rows

    vf1 = make_vf("/a.txt", handle="H:A", old_versions=[make_ov(version_num=1, handle="H:A1")])
    vf2 = make_vf("/b.txt", handle="H:B", old_versions=[])  # nothing to delete

    rows_for_preview = compute_rows([vf1, vf2], None, None)
    calls = []

    def fake_run_mega(cmd, **kwargs):
        calls.append(cmd)
        class R:
            returncode = 0
            stderr = ""
        return R()

    monkeypatch.setattr("megavers.prune.run_mega", fake_run_mega)
    execute_prune([vf1, vf2], None, None)

    # Only vf1 has anything to delete in both the preview and the real run.
    assert len(rows_for_preview) == 1
    assert rows_for_preview[0][0] is vf1
    assert calls == [["mega-rm", "-f", "H:A1"]]

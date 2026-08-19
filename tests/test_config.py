"""Tests for megavers.config: config file lookup/loading/validation, the
init-config bootstrap, and the megavers-config-init/megavers-config-list
argument parsers."""

from pathlib import Path

import pytest

from megavers.config import (
    find_user_config, init_config, load_config, load_defaults,
    validate_defaults, resolve_config,
    build_config_init_parser, build_config_list_parser,
    BUNDLED_CONFIG_LABEL, DEFAULT_USER_CONFIG_PATH,
)


# ── Config file lookup precedence ─────────────────────────────────────────────

def test_find_user_config_none_when_absent(tmp_path, monkeypatch):
    monkeypatch.setattr("megavers.config.USER_CONFIG_SEARCH_PATH", [
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
    monkeypatch.setattr("megavers.config.Path.home", lambda: home)
    monkeypatch.setattr("megavers.config.USER_CONFIG_SEARCH_PATH", [
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


# ── load_defaults / validate_defaults ─────────────────────────────────────────

def test_load_defaults_empty_when_absent():
    # The bundled default ships with no [defaults] table (commented out).
    assert load_defaults(None) == {}

def test_load_defaults_from_explicit_path(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text("[defaults]\nkeep_n = 5\nolder_than = 90\n")
    assert load_defaults(cfg) == {"keep_n": 5, "older_than": 90}

def test_validate_defaults_accepts_empty():
    validate_defaults({})  # must not raise

def test_validate_defaults_accepts_valid_values():
    validate_defaults({"keep_n": 5, "older_than": 90})  # must not raise

def test_validate_defaults_accepts_zero():
    validate_defaults({"keep_n": 0})  # must not raise

def test_validate_defaults_rejects_unknown_key():
    with pytest.raises(SystemExit):
        validate_defaults({"keep_n": 5, "typo_key": 1})

def test_validate_defaults_rejects_negative():
    with pytest.raises(SystemExit):
        validate_defaults({"keep_n": -1})

def test_validate_defaults_rejects_non_integer():
    with pytest.raises(SystemExit):
        validate_defaults({"older_than": "90"})

def test_validate_defaults_rejects_bool():
    # TOML `true`/`false` parses as Python bool, a subclass of int - must be
    # rejected explicitly rather than silently accepted as 0/1.
    with pytest.raises(SystemExit):
        validate_defaults({"keep_n": True})


# ── init_config ──────────────────────────────────────────────────────────────

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

def test_init_config_writes_into_existing_directory(tmp_path):
    # megavers-config-init . should write .megavers.toml inside the directory,
    # not treat the directory itself as an existing target and refuse.
    init_config(tmp_path)
    dest = tmp_path / ".megavers.toml"
    assert dest.exists()
    assert load_config(dest) == load_config(None)

def test_init_config_recognizes_relative_path_in_search_path(tmp_path, monkeypatch, capsys):
    # dest is relative (as typed on the CLI) but denotes the same file as the
    # (absolute) search path entry - must still be recognized as auto-picked-up.
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("megavers.config.USER_CONFIG_SEARCH_PATH", [
        tmp_path / ".megavers.toml", tmp_path / "home" / "config.toml",
    ])
    init_config(Path(".megavers.toml"))
    assert "pick it up automatically" in capsys.readouterr().out


# ── resolve_config ─────────────────────────────────────────────────────────────

def test_resolve_config_uses_bundled_label_when_none_found(monkeypatch):
    monkeypatch.setattr("megavers.config.find_user_config", lambda: None)
    path, filters, label = resolve_config(None)
    assert path is None
    assert filters == load_config(None)
    assert label == BUNDLED_CONFIG_LABEL

def test_resolve_config_prefers_explicit_over_search_path(tmp_path, monkeypatch):
    other = tmp_path / "other.toml"
    other.write_text('[[filter]]\nname = "other"\npath_contains = ["/y/"]\n')
    monkeypatch.setattr("megavers.config.find_user_config", lambda: other)

    cfg = tmp_path / "config.toml"
    cfg.write_text('[[filter]]\nname = "custom"\npath_contains = ["/x/"]\n')
    path, filters, label = resolve_config(cfg)
    assert path == cfg
    assert label == str(cfg)
    assert filters == [{"name": "custom", "path_contains": ["/x/"]}]


# ── megavers-config-init parser ─────────────────────────────────────────────────

def test_build_config_init_parser_defaults():
    args = build_config_init_parser().parse_args([])
    assert args.path == DEFAULT_USER_CONFIG_PATH

def test_build_config_init_parser_explicit_path():
    args = build_config_init_parser().parse_args(["/tmp/x.toml"])
    assert args.path == Path("/tmp/x.toml")


# ── megavers-config-list parser ─────────────────────────────────────────────────

def test_build_config_list_parser_defaults():
    args = build_config_list_parser().parse_args([])
    assert args.config is None

def test_build_config_list_parser_explicit_config():
    args = build_config_list_parser().parse_args(["--config", "/tmp/c.toml"])
    assert args.config == Path("/tmp/c.toml")

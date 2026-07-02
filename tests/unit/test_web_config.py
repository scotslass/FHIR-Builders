"""Tests for web UI config loading (src/web/config.py)."""

from __future__ import annotations

from web.config import load_web_config


def test_defaults_when_file_absent(tmp_path):
    cfg = load_web_config(tmp_path / "nope.cfg")
    assert (cfg.port, cfg.default_cap, cfg.log_level) == (8000, 500, "info")


def test_reads_values_from_file(tmp_path):
    p = tmp_path / "web.cfg"
    p.write_text("[web]\nport = 9091\ndefault_cap = 250\nlog_level = debug\n")
    cfg = load_web_config(p)
    assert cfg.port == 9091
    assert cfg.default_cap == 250
    assert cfg.log_level == "debug"


def test_env_overrides_cap(tmp_path, monkeypatch):
    p = tmp_path / "web.cfg"
    p.write_text("[web]\ndefault_cap = 250\n")
    monkeypatch.setenv("WEB_DEFAULT_CAP", "42")
    assert load_web_config(p).default_cap == 42


def test_project_config_file_loads():
    """The shipped config/web.cfg parses and yields sane values."""
    cfg = load_web_config()
    assert cfg.port > 0
    assert cfg.default_cap >= 0

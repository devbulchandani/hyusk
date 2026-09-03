"""Configuration tests."""

from __future__ import annotations

import importlib
from pathlib import Path


def test_config_load_with_env(monkeypatch, tmp_path: Path):
    # Force an isolated user-config directory.
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("HYUSK_LLM_PROVIDER", "openai")
    monkeypatch.setenv("HYUSK_LLM_MODEL", "test-model")
    monkeypatch.setenv("HYUSK_LLM_API_KEY", "test-key")
    cfg_mod = importlib.import_module("hyusk.config.config")
    cfg = cfg_mod.Config.load()
    assert cfg.llm.provider == "openai"
    assert cfg.llm.model == "test-model"
    assert cfg.llm.api_key == "test-key"


def test_user_config_dir_creates(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    cfg_mod = importlib.import_module("hyusk.config.config")
    d = cfg_mod.user_config_dir()
    assert d.exists()
    assert d.name == "hyusk"

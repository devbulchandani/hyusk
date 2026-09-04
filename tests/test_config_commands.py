"""Tests for the `hyusk config` CLI (V4.1)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _isolated_config_env(tmp_path: Path) -> dict:
    env = os.environ.copy()
    env["HYUSK_CONFIG_DIR"] = str(tmp_path)
    # Unset any existing API keys so we test the config file path.
    for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "HYUSK_LLM_API_KEY"):
        env.pop(k, None)
    return env


def _run(env: dict, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "hyusk", *args],
        capture_output=True,
        text=True,
        env=env,
        cwd="/Users/devbulchandani/hyusk",
        timeout=15,
    )


def test_config_path(tmp_path: Path):
    env = _isolated_config_env(tmp_path)
    r = _run(env, "config", "path")
    assert r.returncode == 0
    expected = Path(tmp_path) / "hyusk" / "config.toml"
    assert r.stdout.strip() == str(expected)


def test_config_set_and_show(tmp_path: Path):
    env = _isolated_config_env(tmp_path)
    r = _run(env, "config", "set", "llm.api_key", "sk-test-12345")
    assert r.returncode == 0, r.stderr
    r = _run(env, "config", "set", "llm.model", "gpt-4o-mini")
    assert r.returncode == 0
    r = _run(env, "config", "set", "llm.base_url", "https://openrouter.ai/api/v1")
    assert r.returncode == 0
    r = _run(env, "config", "set", "llm.provider", "openai")
    assert r.returncode == 0

    # show should mask the api_key but show everything else.
    r = _run(env, "config", "show")
    assert r.returncode == 0
    out = r.stdout
    assert "sk-t" in out  # masked prefix
    assert "2345" in out  # masked suffix
    assert "gpt-4o-mini" in out
    assert "https://openrouter.ai/api/v1" in out
    # And NOT the full key in plaintext.
    assert "sk-test-12345" not in out


def test_config_unset(tmp_path: Path):
    env = _isolated_config_env(tmp_path)
    _run(env, "config", "set", "llm.model", "gpt-4o-mini")
    r = _run(env, "config", "unset", "llm.model")
    assert r.returncode == 0
    # The persisted section should no longer have llm.model.
    cfg_path = Path(tmp_path) / "hyusk" / "config.toml"
    text = cfg_path.read_text() if cfg_path.exists() else ""
    assert "llm.model" not in text


def test_config_unset_missing_is_ok(tmp_path: Path):
    env = _isolated_config_env(tmp_path)
    r = _run(env, "config", "unset", "llm.nonexistent")
    assert r.returncode == 0


def test_api_key_via_config_works(tmp_path: Path, monkeypatch):
    """A key stored via `config set` should be picked up by Config.load()."""
    from hyusk.config.config import Config

    monkeypatch.setenv("HYUSK_CONFIG_DIR", str(tmp_path))
    for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "HYUSK_LLM_API_KEY"):
        monkeypatch.delenv(k, raising=False)

    # Write a config file directly.
    cfg_dir = Path(tmp_path) / "hyusk"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.toml").write_text(
        '[llm]\nprovider = "openai"\nmodel = "gpt-4o-mini"\n'
        'api_key = "sk-from-config-file"\n'
        'base_url = "https://openrouter.ai/api/v1"\n'
    )

    cfg = Config.load()
    assert cfg.llm.api_key == "sk-from-config-file"
    assert cfg.llm.base_url == "https://openrouter.ai/api/v1"
    assert cfg.llm.provider == "openai"
    assert cfg.llm.model == "gpt-4o-mini"


def test_api_key_via_cli_flag_does_not_persist(tmp_path: Path, monkeypatch):
    """The --api-key flag should not be saved to the config file."""
    from hyusk.config.config import Config

    monkeypatch.setenv("HYUSK_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("HYUSK_LLM_API_KEY", raising=False)

    # No config file yet.
    cfg = Config.load()
    assert cfg.llm.api_key == ""

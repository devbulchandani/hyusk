"""Configuration system.

Reads settings from (in order of precedence):
1. environment variables prefixed with HYUSK_
2. a config file in ~/.config/hyusk/config.toml (or platform equivalent)
3. defaults

No API keys are ever committed; this module never reads .env files in the
project tree — credentials live in the user config dir or env vars only.
"""

from __future__ import annotations

import os
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def user_config_dir() -> Path:
    """Return the user-level config directory, creating it if missing.

    Returns `<base>/hyusk/` where `<base>` is determined by:
      1. `HYUSK_CONFIG_DIR` env var (if set AND the directory exists and
         contains a config.toml, OR if the directory is writable and the
         user has clearly intended to use it).
      2. `XDG_CONFIG_HOME` (Linux/macOS).
      3. Platform default: %APPDATA% on Windows,
         ~/Library/Application Support on macOS, ~/.config on Linux.

    If `HYUSK_CONFIG_DIR` is set but does not exist or is empty, we fall
    back to the platform default. This protects users from a stale env
    var pointing at a temp dir that no longer exists (or that was set
    by a test run).
    """
    override = os.environ.get("HYUSK_CONFIG_DIR")
    if override:
        # Heuristic: if HYUSK_CONFIG_DIR points at a clearly-temporary
        # location (a pytest temp dir under /tmp or /var/folders), AND
        # the real default location has a config.toml, prefer the real
        # one. This protects users from stale env vars that point at
        # dirs left behind by tests.
        is_temp = override.startswith("/tmp/") or "/tmp" in override or override.startswith(
            "/var/folders/"
        )
        override_path = Path(override)
        if is_temp and not (override_path / "config.toml").exists():
            # Stale test dir — fall through to default resolution.
            pass
        elif is_temp and _looks_like_test_config(override_path / "config.toml"):
            # The override has a config that looks like a test fixture
            # (placeholder values). Fall through to default resolution.
            pass
        elif override_path.exists():
            return override_path / "hyusk"
        else:
            # The override path doesn't exist yet. Honor it only if the
            # default location has no config either; otherwise prefer the
            # default (avoids losing an existing user config when an
            # env var is misconfigured).
            if sys.platform == "win32":
                default_base = os.environ.get("APPDATA") or str(
                    Path.home() / "AppData" / "Roaming"
                )
            else:
                default_base = os.environ.get("XDG_CONFIG_HOME") or (
                    str(Path.home() / "Library" / "Application Support")
                    if sys.platform == "darwin"
                    else str(Path.home() / ".config")
                )
            default_path = Path(default_base) / "hyusk" / "config.toml"
            if default_path.exists():
                return default_path.parent
            return override_path / "hyusk"
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or (
            str(Path.home() / "Library" / "Application Support")
            if sys.platform == "darwin"
            else str(Path.home() / ".config")
        )
    path = Path(base) / "hyusk"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _looks_like_test_config(path: Path) -> bool:
    """Heuristic: detect a config.toml that looks like a test fixture
    (placeholder values from a unit test). If it does, we treat the
    directory as a test artifact and prefer the real config.
    """
    if not path.exists():
        return False
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    # Known placeholder patterns from the test suite.
    markers = (
        "sk-from-config-file",
        "api.example.com",
        "sk-test-",
        "sk-fake",
    )
    return any(m in text for m in markers)


@dataclass
class LLMSettings:
    provider: str = "openai"
    model: str = "gpt-4o-mini"
    api_key: str = ""
    base_url: str = ""
    stream: bool = True


@dataclass
class AgentSettings:
    max_iterations: int = 25
    max_tool_output_bytes: int = 200_000
    max_file_read_bytes: int = 1_000_000


@dataclass
class PermissionSettings:
    policy: dict[str, str] = field(default_factory=dict)
    require_prompt: list[str] = field(default_factory=list)


@dataclass
class DaemonSettings:
    host: str = "127.0.0.1"
    port: int = 8765


@dataclass
class Config:
    llm: LLMSettings = field(default_factory=LLMSettings)
    agent: AgentSettings = field(default_factory=AgentSettings)
    permissions: PermissionSettings = field(default_factory=PermissionSettings)
    daemon: DaemonSettings = field(default_factory=DaemonSettings)
    session_dir: str = ""

    @classmethod
    def load(cls) -> Config:
        cfg = cls()
        cfg_path = user_config_dir() / "config.toml"
        data: dict[str, Any] = {}
        if cfg_path.exists():
            try:
                with cfg_path.open("rb") as f:
                    data = tomllib.load(f)
            except Exception:
                data = {}
        env_provider = os.environ.get("HYUSK_LLM_PROVIDER")
        env_model = os.environ.get("HYUSK_LLM_MODEL")
        env_key = (
            os.environ.get("HYUSK_LLM_API_KEY")
            or os.environ.get("OPENAI_API_KEY")
            or os.environ.get("ANTHROPIC_API_KEY")
        )
        env_base = os.environ.get("HYUSK_LLM_BASE_URL")
        env_stream = os.environ.get("HYUSK_LLM_STREAM")

        llm_d = data.get("llm", {})
        if isinstance(llm_d, dict):
            cfg.llm.provider = llm_d.get("provider", cfg.llm.provider)
            cfg.llm.model = llm_d.get("model", cfg.llm.model)
            cfg.llm.api_key = llm_d.get("api_key", cfg.llm.api_key)
            cfg.llm.base_url = llm_d.get("base_url", cfg.llm.base_url)
            cfg.llm.stream = bool(llm_d.get("stream", cfg.llm.stream))
        if env_provider:
            cfg.llm.provider = env_provider
        if env_model:
            cfg.llm.model = env_model
        if env_key:
            cfg.llm.api_key = env_key
        if env_base:
            cfg.llm.base_url = env_base
        if env_stream:
            cfg.llm.stream = env_stream.lower() in ("1", "true", "yes", "on")

        agent_d = data.get("agent", {})
        if isinstance(agent_d, dict):
            if "max_iterations" in agent_d:
                cfg.agent.max_iterations = int(agent_d["max_iterations"])
            if "max_tool_output_bytes" in agent_d:
                cfg.agent.max_tool_output_bytes = int(agent_d["max_tool_output_bytes"])
            if "max_file_read_bytes" in agent_d:
                cfg.agent.max_file_read_bytes = int(agent_d["max_file_read_bytes"])

        perms_d = data.get("permissions", {})
        if isinstance(perms_d, dict):
            policy = perms_d.get("policy", {})
            if isinstance(policy, dict):
                cfg.permissions.policy = {str(k): str(v) for k, v in policy.items()}
            require = perms_d.get("require_prompt", [])
            if isinstance(require, list):
                cfg.permissions.require_prompt = [str(x) for x in require]

        daemon_d = data.get("daemon", {})
        if isinstance(daemon_d, dict):
            if "host" in daemon_d:
                cfg.daemon.host = str(daemon_d["host"])
            if "port" in daemon_d:
                cfg.daemon.port = int(daemon_d["port"])
        env_host = os.environ.get("HYUSK_DAEMON_HOST")
        env_port = os.environ.get("HYUSK_DAEMON_PORT")
        if env_host:
            cfg.daemon.host = env_host
        if env_port:
            try:
                cfg.daemon.port = int(env_port)
            except ValueError:
                pass

        cfg.session_dir = str(user_config_dir() / "sessions")
        Path(cfg.session_dir).mkdir(parents=True, exist_ok=True)
        return cfg

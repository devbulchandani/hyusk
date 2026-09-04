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
    """Return the user-level config directory, creating it if missing."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = str(Path.home() / "Library" / "Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    path = Path(base) / "hyusk"
    path.mkdir(parents=True, exist_ok=True)
    return path


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

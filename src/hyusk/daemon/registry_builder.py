"""Shared builders for the registry, policy, and provider.

Lives in the daemon package because the daemon needs them, but the CLI
imports them from here too so V1 and V2 build the agent the same way.
"""

from __future__ import annotations

from ..config.config import Config
from ..llm.anthropic import AnthropicProvider
from ..llm.openai_compat import OpenAICompatProvider
from ..llm.provider import LLMProvider
from ..permissions.policy import PermissionPolicy
from ..plugins.loader import load_plugins
from ..tools.filesystem.tools import register_filesystem_tools
from ..tools.git.tools import register_git_tools
from ..tools.process.tools import register_process_tools
from ..tools.registry import ToolRegistry
from ..tools.shell.tools import register_shell_tools


def build_registry(load_user_plugins: bool = True) -> ToolRegistry:
    """Build the standard tool registry and (optionally) load user plugins."""
    reg = ToolRegistry()
    register_filesystem_tools(reg)
    register_shell_tools(reg)
    register_process_tools(reg)
    register_git_tools(reg)
    if load_user_plugins:
        load_plugins(reg)
    return reg


def build_policy(cfg: Config) -> PermissionPolicy:
    require = set(cfg.permissions.require_prompt)
    require.update({"kill_process"})
    return PermissionPolicy(require_prompt=sorted(require))


def build_provider(cfg: Config) -> LLMProvider:
    provider = (cfg.llm.provider or "openai").lower()
    if provider == "anthropic":
        return AnthropicProvider(
            api_key=cfg.llm.api_key,
            base_url=cfg.llm.base_url,
            default_model=cfg.llm.model,
        )
    # Default + OpenAI-compatible (also covers OpenRouter, Together, etc.)
    return OpenAICompatProvider(
        api_key=cfg.llm.api_key,
        base_url=cfg.llm.base_url,
        default_model=cfg.llm.model,
    )

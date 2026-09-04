"""Plugin loader.

A Hyusk plugin is a Python file in `~/.config/hyusk/plugins/` (or the path
in `HYUSK_PLUGINS_DIR`) that exposes a `register(registry)` function. At
daemon startup, we import every such module and call its `register`
function with the ToolRegistry.

Example plugin file (`~/.config/hyusk/plugins/hello.py`):

    from hyusk.tools.base import Tool, READ

    def register(registry):
        registry.register(Tool(
            name="hello",
            description="Say hello to the given name.",
            input_schema={
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
            permission=READ,
            execute=lambda a: {"greeting": f"hello, {a["name"]}"},
        ))

Errors in user plugins (bad imports, missing `register`, etc.) are
logged and skipped — one broken plugin should not prevent the daemon
from starting.
"""

from __future__ import annotations

import importlib.util
import logging
import sys
from collections.abc import Callable
from pathlib import Path

from ..tools.registry import ToolRegistry

logger = logging.getLogger("hyusk.plugins")


def default_plugin_dir() -> Path:
    """Return the user plugin directory, creating it if needed."""
    from ..config.config import user_config_dir
    d = user_config_dir() / "plugins"
    d.mkdir(parents=True, exist_ok=True)
    return d


def load_plugins(registry: ToolRegistry, plugin_dir: Path | None = None) -> int:
    """Discover and load all plugins in `plugin_dir` (default: user config dir).

    Returns the number of plugins successfully loaded.
    """
    d = plugin_dir or default_plugin_dir()
    if not d.exists():
        return 0
    loaded = 0
    for path in sorted(d.glob("*.py")):
        if path.name.startswith("_"):
            continue
        try:
            if load_plugin(registry, path):
                loaded += 1
        except Exception as exc:
            logger.warning("failed to load plugin %s: %s", path, exc)
    return loaded


def load_plugin(registry: ToolRegistry, path: Path) -> bool:
    """Load a single plugin file and call its `register(registry)`.

    Returns True if a `register` callable was found and called.
    """
    spec = importlib.util.spec_from_file_location(f"hyusk_plugin_{path.stem}", path)
    if spec is None or spec.loader is None:
        return False
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        logger.warning("error importing %s: %s", path, exc)
        return False
    register: Callable | None = getattr(module, "register", None)
    if not callable(register):
        logger.warning("plugin %s has no callable `register`", path)
        return False
    try:
        register(registry)
    except Exception as exc:
        logger.warning("register() raised in %s: %s", path, exc)
        return False
    return True

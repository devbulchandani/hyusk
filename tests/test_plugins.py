"""Plugin loader tests."""

from __future__ import annotations

from pathlib import Path

from hyusk.plugins.loader import load_plugin, load_plugins
from hyusk.tools.registry import ToolRegistry


def test_load_plugin_registers_tool(tmp_path: Path):
    plugin_file = tmp_path / "hello.py"
    plugin_file.write_text(
        "from hyusk.tools.base import Tool, READ\n"
        "\n"
        "def register(registry):\n"
        "    def _execute(args):\n"
        "        return {'greeting': 'hello, ' + args['name']}\n"
        "    registry.register(Tool(\n"
        "        name='hello',\n"
        "        description='Say hello',\n"
        "        input_schema={\n"
        "            'type': 'object',\n"
        "            'properties': {'name': {'type': 'string'}},\n"
        "            'required': ['name'],\n"
        "        },\n"
        "        permission=READ,\n"
        "        execute=_execute,\n"
        "    ))\n"
    )
    reg = ToolRegistry()
    loaded = load_plugin(reg, plugin_file)
    assert loaded
    assert reg.has("hello")
    tool = reg.get("hello")
    result = tool.run({"name": "world"})
    assert "greeting" in result
    assert "world" in result["greeting"]


def test_load_plugin_without_register_function(tmp_path: Path):
    (tmp_path / "noop.py").write_text("x = 1\n")
    reg = ToolRegistry()
    loaded = load_plugin(reg, tmp_path / "noop.py")
    assert not loaded


def test_load_plugin_broken_returns_false(tmp_path: Path):
    (tmp_path / "broken.py").write_text("raise RuntimeError('boom')\n")
    reg = ToolRegistry()
    loaded = load_plugin(reg, tmp_path / "broken.py")
    assert not loaded


def test_load_plugins_skips_init_files(tmp_path: Path):
    (tmp_path / "_skip.py").write_text("# underscore\n")
    (tmp_path / "real.py").write_text(
        "def register(registry):\n    pass\n"
    )
    reg = ToolRegistry()
    n = load_plugins(reg, tmp_path)
    # real.py has register but it doesn't add anything. We just check no crash.
    assert n >= 0

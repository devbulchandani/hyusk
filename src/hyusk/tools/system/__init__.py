"""System information tool.

Surfaces OS, hardware, and runtime specs to the LLM so it can adapt.
This is one of the first tools the agent should call on a new session
to know what it's working with.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
from typing import Any


def _safe_run(cmd: list[str], timeout: float = 2.0) -> str | None:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout.strip()
    except Exception:
        return None


def _macos_info() -> dict[str, Any]:
    out: dict[str, Any] = {"family": "Darwin"}
    # macOS version (e.g. "14.5")
    out["version"] = _safe_run(["sw_vers", "-productVersion"]) or platform.release()
    out["build"] = _safe_run(["sw_vers", "-buildVersion"]) or ""
    out["arch"] = platform.machine()  # arm64 / x86_64
    # Hardware: model name via sysctl
    model = _safe_run(["sysctl", "-n", "hw.model"])
    if model:
        out["hardware_model"] = model
    # CPU: brand string
    cpu_brand = _safe_run(["sysctl", "-n", "machdep.cpu.brand_string"])
    if cpu_brand:
        out["cpu_brand"] = cpu_brand
    out["cpu_count_logical"] = os.cpu_count()
    out["cpu_count_physical"] = os.cpu_count()  # macOS doesn't easily expose this
    # Memory
    mem_bytes = _safe_run(["sysctl", "-n", "hw.memsize"])
    if mem_bytes and mem_bytes.isdigit():
        out["memory_bytes"] = int(mem_bytes)
        out["memory_human"] = _human_bytes(int(mem_bytes))
    # Disk (root volume)
    try:
        usage = shutil.disk_usage("/")
        out["disk_total_bytes"] = usage.total
        out["disk_free_bytes"] = usage.free
    except Exception:
        pass
    # GPU (Metal)
    chip = _safe_run(["system_profiler", "SPDisplaysDataType"], timeout=4.0)
    if chip and "Chipset Model" in chip:
        for line in chip.splitlines():
            if "Chipset Model" in line:
                out["gpu"] = line.split(":", 1)[1].strip()
                break
    # Python
    out["python_version"] = platform.python_version()
    out["python_executable"] = sys.executable
    return out


def _linux_info() -> dict[str, Any]:
    out: dict[str, Any] = {"family": "Linux"}
    out["version"] = _safe_run(["uname", "-r"]) or platform.release()
    out["arch"] = platform.machine()
    # /etc/os-release is the standard place for distro info
    try:
        with open("/etc/os-release") as f:
            data = {}
            for line in f:
                if "=" in line:
                    k, v = line.strip().split("=", 1)
                    data[k] = v.strip('"')
        out["distro"] = data.get("PRETTY_NAME", "")
        out["distro_id"] = data.get("ID", "")
    except FileNotFoundError:
        pass
    # CPU
    out["cpu_count_logical"] = os.cpu_count()
    cpu_info = _safe_run(["lscpu"])
    if cpu_info:
        for line in cpu_info.splitlines():
            if line.startswith("Model name:"):
                out["cpu_brand"] = line.split(":", 1)[1].strip()
            elif line.startswith("CPU(s):"):
                try:
                    out["cpu_count_physical"] = int(line.split(":", 1)[1].strip())
                except ValueError:
                    pass
    # Memory
    meminfo = _safe_run(["cat", "/proc/meminfo"])
    if meminfo:
        for line in meminfo.splitlines():
            if line.startswith("MemTotal:"):
                try:
                    kb = int(line.split()[1])
                    out["memory_bytes"] = kb * 1024
                    out["memory_human"] = _human_bytes(kb * 1024)
                except (ValueError, IndexError):
                    pass
                break
    # Disk
    try:
        usage = shutil.disk_usage("/")
        out["disk_total_bytes"] = usage.total
        out["disk_free_bytes"] = usage.free
    except Exception:
        pass
    # GPU (try nvidia-smi first)
    gpu = _safe_run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"], timeout=2.0)
    if gpu:
        out["gpu"] = gpu
    # Python
    out["python_version"] = platform.python_version()
    out["python_executable"] = sys.executable
    return out


def _windows_info() -> dict[str, Any]:
    out: dict[str, Any] = {"family": "Windows"}
    out["version"] = platform.release()  # e.g. "10", "11"
    out["arch"] = platform.machine()
    out["cpu_count_logical"] = os.cpu_count()
    # CPU brand
    cpu_brand = _safe_run(["wmic", "cpu", "get", "name"], timeout=3.0)
    if cpu_brand:
        out["cpu_brand"] = cpu_brand.splitlines()[-1].strip()
    # Memory
    mem = _safe_run(["wmic", "OS", "get", "TotalVisibleMemorySize", "/VALUE"], timeout=3.0)
    if mem:
        for line in mem.splitlines():
            if line.strip().isdigit():
                kb = int(line.strip())
                out["memory_bytes"] = kb * 1024
                out["memory_human"] = _human_bytes(kb * 1024)
                break
    # Disk
    try:
        usage = shutil.disk_usage("/")
        out["disk_total_bytes"] = usage.total
        out["disk_free_bytes"] = usage.free
    except Exception:
        pass
    out["python_version"] = platform.python_version()
    out["python_executable"] = sys.executable
    return out


def _human_bytes(n: int) -> str:
    """Convert bytes to a human-readable string."""
    f = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if f < 1024:
            return f"{f:.1f} {unit}"
        f /= 1024
    return f"{f:.1f} PB"


def collect() -> dict[str, Any]:
    """Return a dict describing the current system."""
    sysname = platform.system()
    if sysname == "Darwin":
        info = _macos_info()
    elif sysname == "Linux":
        info = _linux_info()
    elif sysname == "Windows":
        info = _windows_info()
    else:
        info = {"family": sysname, "arch": platform.machine()}
    # Common fields
    info["hostname"] = platform.node()
    info["python_implementation"] = platform.python_implementation()
    info["uname"] = platform.uname()._asdict()
    return info


def system_info_tool():
    """Return a Tool that reports the current system configuration."""
    from ..base import READ, Tool

    def execute(_args: dict) -> dict:
        return collect()

    return Tool(
        name="system_info",
        description=(
            "Report the host system's OS, CPU, memory, disk, Python, "
            "and GPU. Call this early in a session to learn what "
            "platform you're running on and what packages are available."
        ),
        input_schema={
            "type": "object",
            "properties": {},
        },
        permission=READ,
        execute=execute,
    )


def register_system_info_tools(registry) -> None:
    registry.register(system_info_tool())

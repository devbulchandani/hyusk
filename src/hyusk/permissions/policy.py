"""Permission policy.

V1 implements a simple rule-based policy:
  - read-only tools (READ) are auto-allowed
  - tools marked EXECUTE/DESTRUCTIVE that are NOT in `require_prompt`
    are auto-allowed
  - tools in `require_prompt` MUST receive an explicit grant() call
    from the host (the CLI prompts the user)
  - tools whose category is in the deny list are always refused

The goal is that future clients can supply different policies
(`yolo`, `paranoid`, `tiered`) without touching the agent core.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from ..core.errors import PermissionDenied
from ..tools.base import Tool

ALLOW = "allow"
DENY = "deny"
ASK = "ask"


@dataclass
class Decision:
    action: str  # one of ALLOW, DENY, ASK
    reason: str = ""


@dataclass
class PermissionPolicy:
    """Configurable policy.

    - deny_categories: list of permission categories that are always denied
    - require_prompt: list of tool names that always ask
    - allow_tools: optional allow-list; if non-empty, only these tools run
    """

    deny_categories: list[str] = field(default_factory=list)
    require_prompt: list[str] = field(default_factory=list)
    allow_tools: list[str] = field(default_factory=list)
    auto_allow_categories: list[str] = field(default_factory=list)

    def decide(self, tool: Tool) -> Decision:
        if self.allow_tools and tool.name not in self.allow_tools:
            return Decision(DENY, f"tool '{tool.name}' not in allow-list")
        if tool.permission in self.deny_categories:
            return Decision(DENY, f"category '{tool.permission}' is denied by policy")
        if tool.name in self.require_prompt:
            return Decision(ASK, "tool requires interactive confirmation")
        # Sensible default: DESTRUCTIVE category tools always require prompt
        # unless explicitly auto-allowed via auto_allow_categories.
        if tool.permission == "DESTRUCTIVE" and "DESTRUCTIVE" not in self.auto_allow_categories:
            return Decision(ASK, "destructive tool requires interactive confirmation")
        return Decision(ALLOW, "allowed by policy")

    def enforce(self, tool: Tool, *, grants: Iterable[str] | None = None) -> None:
        decision = self.decide(tool)
        if decision.action == DENY:
            raise PermissionDenied(tool.name, decision.reason)
        if decision.action == ASK:
            granted = set(grants or [])
            if tool.name not in granted:
                raise PermissionDenied(tool.name, "interactive approval required")

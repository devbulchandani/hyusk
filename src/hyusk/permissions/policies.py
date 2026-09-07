"""Permission policy evaluation."""

from dataclasses import dataclass
from enum import Enum

from hyusk.models import PermissionLevel


class PolicyAction(str, Enum):
    """Action to take for a permission request."""

    ALLOW = "allow"  # Automatically allow
    CONFIRM = "confirm"  # Require user confirmation
    DENY = "deny"  # Automatically deny
    

@dataclass
class PolicyDecision:
    """Decision from policy evaluation."""

    action: PolicyAction
    reason: str
    auto_approve: bool = False
    

class PermissionPolicy:
    """Evaluates permission requests against policies."""

    def __init__(self, auto_approve_safe: bool = True) -> None:
        """Initialize permission policy.
        
        Args:
            auto_approve_safe: Whether to auto-approve SAFE tools
        """
        self.auto_approve_safe = auto_approve_safe

    def evaluate(
        self,
        tool_name: str,
        permission_level: PermissionLevel,
        arguments: dict,
    ) -> PolicyDecision:
        """Evaluate a permission request.
        
        Args:
            tool_name: Name of the tool
            permission_level: Permission level of the tool
            arguments: Arguments being passed to the tool
            
        Returns:
            PolicyDecision indicating what to do
        """
        # BLOCKED tools are always denied
        if permission_level == PermissionLevel.BLOCKED:
            return PolicyDecision(
                action=PolicyAction.DENY,
                reason=f"Tool '{tool_name}' is blocked",
                auto_approve=False,
            )

        # SAFE tools can be auto-approved if configured
        if permission_level == PermissionLevel.SAFE:
            if self.auto_approve_safe:
                return PolicyDecision(
                    action=PolicyAction.ALLOW,
                    reason=f"Tool '{tool_name}' is safe and auto-approval is enabled",
                    auto_approve=True,
                )
            else:
                return PolicyDecision(
                    action=PolicyAction.CONFIRM,
                    reason=f"Tool '{tool_name}' requires confirmation (auto-approval disabled)",
                    auto_approve=False,
                )

        # CONFIRM tools always require confirmation
        if permission_level == PermissionLevel.CONFIRM:
            return PolicyDecision(
                action=PolicyAction.CONFIRM,
                reason=f"Tool '{tool_name}' requires user confirmation",
                auto_approve=False,
            )

        # SENSITIVE tools require confirmation
        if permission_level == PermissionLevel.SENSITIVE:
            return PolicyDecision(
                action=PolicyAction.CONFIRM,
                reason=f"Tool '{tool_name}' is sensitive and requires confirmation",
                auto_approve=False,
            )

        # Unknown permission level - be safe and require confirmation
        return PolicyDecision(
            action=PolicyAction.CONFIRM,
            reason=f"Tool '{tool_name}' has unknown permission level: {permission_level}",
            auto_approve=False,
        )

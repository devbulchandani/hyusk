"""Permission engine for controlling tool access."""

from uuid import UUID

from hyusk.logging import get_logger
from hyusk.models import PermissionDecision, PermissionLevel
from hyusk.permissions.manager import get_manager
from hyusk.permissions.policies import PermissionPolicy, PolicyAction

logger = get_logger(__name__)


class PermissionEngine:
    """Central permission engine for evaluating and enforcing permissions."""

    def __init__(self, policy: PermissionPolicy | None = None) -> None:
        """Initialize permission engine.
        
        Args:
            policy: Permission policy to use (creates default if None)
        """
        if policy is None:
            from hyusk.config import get_config

            config = get_config()
            policy = PermissionPolicy(auto_approve_safe=config.permissions.auto_approve_safe)

        self.policy = policy
        self.manager = get_manager()

    async def check_permission(
        self,
        tool_name: str,
        permission_level: PermissionLevel,
        arguments: dict,
        task_id: UUID | None = None,
        reason: str = "",
        timeout: int | None = None,
    ) -> PermissionDecision:
        """Check if a tool execution is permitted.
        
        This is the main entry point for permission checking. It:
        1. Evaluates the request against the policy
        2. Auto-approves if policy allows
        3. Requests user approval if needed
        4. Returns the final decision
        
        Args:
            tool_name: Name of the tool
            permission_level: Permission level of the tool
            arguments: Arguments being passed to the tool
            task_id: Optional task ID making the request
            reason: Optional reason for the request
            
        Returns:
            PermissionDecision with approval status
        """
        logger.info(
            f"Checking permission for tool",
            tool=tool_name,
            permission_level=permission_level.value,
            task_id=str(task_id) if task_id else None,
        )

        # Evaluate against policy
        policy_decision = self.policy.evaluate(tool_name, permission_level, arguments)

        # If policy says DENY, reject immediately
        if policy_decision.action == PolicyAction.DENY:
            logger.warning(
                f"Permission denied by policy",
                tool=tool_name,
                reason=policy_decision.reason,
            )

            return PermissionDecision(
                request_id=None,
                approved=False,
                reason=policy_decision.reason,
            )

        # If policy says ALLOW and auto-approve is enabled, approve immediately
        if policy_decision.action == PolicyAction.ALLOW and policy_decision.auto_approve:
            logger.info(
                f"Permission auto-approved",
                tool=tool_name,
                reason=policy_decision.reason,
            )

            return PermissionDecision(
                request_id=None,
                approved=True,
                reason=policy_decision.reason,
            )

        # Otherwise, request user approval
        logger.info(
            f"Requesting user approval",
            tool=tool_name,
            reason=policy_decision.reason,
        )

        decision = await self.manager.request_approval(
            task_id=task_id,
            tool_name=tool_name,
            arguments=arguments,
            reason=reason or policy_decision.reason,
            timeout=timeout,
        )

        return decision

    async def approve_request(self, request_id: UUID, reason: str = "") -> PermissionDecision:
        """Approve a pending permission request.
        
        Args:
            request_id: ID of the request to approve
            reason: Optional reason for approval
            
        Returns:
            PermissionDecision
        """
        return await self.manager.approve(request_id, reason)

    async def reject_request(self, request_id: UUID, reason: str = "") -> PermissionDecision:
        """Reject a pending permission request.
        
        Args:
            request_id: ID of the request to reject
            reason: Optional reason for rejection
            
        Returns:
            PermissionDecision
        """
        return await self.manager.reject(request_id, reason)

    async def list_pending_requests(self):
        """List all pending permission requests.
        
        Returns:
            List of pending requests
        """
        return await self.manager.list_pending()


# Global permission engine instance
_engine: PermissionEngine | None = None


def get_engine() -> PermissionEngine:
    """Get the global permission engine instance."""
    global _engine
    if _engine is None:
        _engine = PermissionEngine()
    return _engine


def set_engine(engine: PermissionEngine) -> None:
    """Set the global permission engine instance."""
    global _engine
    _engine = engine

"""Approval manager for permission requests."""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Callable
from uuid import UUID, uuid4

from hyusk.database import get_database
from hyusk.logging import get_logger
from hyusk.models import PermissionDecision, PermissionRequest, PermissionRequestStatus

logger = get_logger(__name__)


class ApprovalManager:
    """Manages permission approval requests."""

    def __init__(self, default_timeout: int = 300) -> None:
        """Initialize approval manager.
        
        Args:
            default_timeout: Default timeout for approvals in seconds
        """
        self.default_timeout = default_timeout
        self._pending: dict[UUID, PermissionRequest] = {}
        self._callbacks: dict[UUID, Callable[[PermissionDecision], None]] = {}

    async def request_approval(
        self,
        task_id: UUID | None,
        tool_name: str,
        arguments: dict,
        reason: str,
        timeout: int | None = None,
    ) -> PermissionDecision:
        """Request approval for a tool execution.
        
        Args:
            task_id: ID of the task requesting permission
            tool_name: Name of the tool
            arguments: Arguments to pass to the tool
            reason: Reason for the request
            timeout: Timeout in seconds (uses default if None)
            
        Returns:
            PermissionDecision with the user's decision
        """
        timeout = timeout or self.default_timeout
        expires_at = datetime.now(UTC) + timedelta(seconds=timeout)

        # Create request
        request = PermissionRequest(
            id=uuid4(),
            task_id=task_id,
            tool=tool_name,
            arguments=arguments,
            reason=reason,
            created_at=datetime.now(UTC),
            expires_at=expires_at,
            status=PermissionRequestStatus.PENDING,
        )

        # Store in memory
        self._pending[request.id] = request

        # Persist to database
        try:
            from hyusk.database import PermissionRequestDB

            db = get_database()
            async with db.get_session() as session:
                db_request = PermissionRequestDB(
                    id=request.id,
                    task_id=request.task_id,
                    tool=request.tool,
                    arguments=request.arguments,
                    reason=request.reason,
                    status=request.status,
                    created_at=request.created_at,
                    expires_at=request.expires_at,
                    meta=request.metadata,
                )
                session.add(db_request)
                await session.commit()
        except Exception as e:
            logger.error(f"Failed to persist permission request: {e}")

        logger.info(
            f"Permission request created",
            request_id=str(request.id),
            tool=tool_name,
            timeout=timeout,
        )

        # Wait for decision or timeout
        try:
            decision = await asyncio.wait_for(
                self._wait_for_decision(request.id),
                timeout=timeout,
            )
            return decision
        except asyncio.TimeoutError:
            # Timeout - mark as expired
            request.status = PermissionRequestStatus.EXPIRED
            await self._update_request(request)
            
            logger.warning(
                f"Permission request expired",
                request_id=str(request.id),
            )

            return PermissionDecision(
                request_id=request.id,
                approved=False,
                reason="Request expired due to timeout",
                decided_at=datetime.now(UTC),
            )

    async def _wait_for_decision(self, request_id: UUID) -> PermissionDecision:
        """Wait for a decision on a request.
        
        Args:
            request_id: ID of the request
            
        Returns:
            PermissionDecision when available
        """
        # Create a future to wait on
        future: asyncio.Future[PermissionDecision] = asyncio.Future()

        # Register callback
        def callback(decision: PermissionDecision) -> None:
            if not future.done():
                future.set_result(decision)

        self._callbacks[request_id] = callback

        # Wait for decision
        return await future

    async def approve(self, request_id: UUID, reason: str = "") -> PermissionDecision:
        """Approve a permission request.
        
        Args:
            request_id: ID of the request to approve
            reason: Optional reason for approval
            
        Returns:
            PermissionDecision
            
        Raises:
            ValueError: If request not found or already decided
        """
        request = self._pending.get(request_id)
        if not request:
            raise ValueError(f"Permission request {request_id} not found")

        if request.status != PermissionRequestStatus.PENDING:
            raise ValueError(f"Request {request_id} is not pending (status: {request.status})")

        # Check if expired
        if datetime.now(UTC) > request.expires_at:
            request.status = PermissionRequestStatus.EXPIRED
            await self._update_request(request)
            raise ValueError(f"Request {request_id} has expired")

        # Update request
        request.status = PermissionRequestStatus.APPROVED
        await self._update_request(request)

        # Create decision
        decision = PermissionDecision(
            request_id=request_id,
            approved=True,
            reason=reason or "Approved by user",
            decided_at=datetime.now(UTC),
        )

        logger.info(
            f"Permission request approved",
            request_id=str(request_id),
            tool=request.tool,
        )

        # Notify waiting task
        if request_id in self._callbacks:
            self._callbacks[request_id](decision)
            del self._callbacks[request_id]

        # Cleanup
        if request_id in self._pending:
            del self._pending[request_id]

        return decision

    async def reject(self, request_id: UUID, reason: str = "") -> PermissionDecision:
        """Reject a permission request.
        
        Args:
            request_id: ID of the request to reject
            reason: Optional reason for rejection
            
        Returns:
            PermissionDecision
            
        Raises:
            ValueError: If request not found or already decided
        """
        request = self._pending.get(request_id)
        if not request:
            raise ValueError(f"Permission request {request_id} not found")

        if request.status != PermissionRequestStatus.PENDING:
            raise ValueError(f"Request {request_id} is not pending (status: {request.status})")

        # Update request
        request.status = PermissionRequestStatus.REJECTED
        await self._update_request(request)

        # Create decision
        decision = PermissionDecision(
            request_id=request_id,
            approved=False,
            reason=reason or "Rejected by user",
            decided_at=datetime.now(UTC),
        )

        logger.info(
            f"Permission request rejected",
            request_id=str(request_id),
            tool=request.tool,
        )

        # Notify waiting task
        if request_id in self._callbacks:
            self._callbacks[request_id](decision)
            del self._callbacks[request_id]

        # Cleanup
        if request_id in self._pending:
            del self._pending[request_id]

        return decision

    async def list_pending(self) -> list[PermissionRequest]:
        """List all pending permission requests.
        
        Returns:
            List of pending requests
        """
        # Clean up expired requests first
        now = datetime.now(UTC)
        expired_ids = [
            req_id
            for req_id, req in self._pending.items()
            if req.expires_at < now and req.status == PermissionRequestStatus.PENDING
        ]

        for req_id in expired_ids:
            request = self._pending[req_id]
            request.status = PermissionRequestStatus.EXPIRED
            await self._update_request(request)
            del self._pending[req_id]

        return [req for req in self._pending.values() if req.status == PermissionRequestStatus.PENDING]

    async def cancel(self, request_id: UUID) -> None:
        """Cancel a pending request.
        
        Args:
            request_id: ID of the request to cancel
            
        Raises:
            ValueError: If request not found
        """
        request = self._pending.get(request_id)
        if not request:
            raise ValueError(f"Permission request {request_id} not found")

        request.status = PermissionRequestStatus.CANCELLED
        await self._update_request(request)

        # Notify waiting task with rejection
        if request_id in self._callbacks:
            decision = PermissionDecision(
                request_id=request_id,
                approved=False,
                reason="Request cancelled",
                decided_at=datetime.now(UTC),
            )
            self._callbacks[request_id](decision)
            del self._callbacks[request_id]

        # Cleanup
        if request_id in self._pending:
            del self._pending[request_id]

        logger.info(
            f"Permission request cancelled",
            request_id=str(request_id),
        )

    async def _update_request(self, request: PermissionRequest) -> None:
        """Update a request in the database.
        
        Args:
            request: Request to update
        """
        try:
            from hyusk.database import PermissionRequestDB

            db = get_database()
            async with db.get_session() as session:
                # Fetch existing record
                db_request = await session.get(PermissionRequestDB, request.id)
                if db_request:
                    db_request.status = request.status
                    db_request.resolved_at = request.resolved_at
                    await session.commit()
        except Exception as e:
            logger.error(f"Failed to update permission request: {e}")


# Global approval manager instance
_manager: ApprovalManager | None = None


def get_manager() -> ApprovalManager:
    """Get the global approval manager instance."""
    global _manager
    if _manager is None:
        from hyusk.config import get_config

        config = get_config()
        _manager = ApprovalManager(default_timeout=config.permissions.approval_timeout)
    return _manager


def set_manager(manager: ApprovalManager) -> None:
    """Set the global approval manager instance."""
    global _manager
    _manager = manager

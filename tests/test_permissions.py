"""Tests for permission system."""

import asyncio
from datetime import datetime, timedelta
from uuid import uuid4

import pytest

from hyusk.models import PermissionRequestStatus, PermissionLevel
from hyusk.permissions.engine import PermissionEngine
from hyusk.permissions.manager import ApprovalManager
from hyusk.permissions.policies import PermissionPolicy, PolicyAction, PolicyDecision


def test_permission_policy_blocked():
    """Test policy blocks BLOCKED tools."""
    policy = PermissionPolicy(auto_approve_safe=True)

    decision = policy.evaluate(
        tool_name="dangerous_tool",
        permission_level=PermissionLevel.BLOCKED,
        arguments={},
    )

    assert decision.action == PolicyAction.DENY
    assert "blocked" in decision.reason.lower()
    assert not decision.auto_approve


def test_permission_policy_safe_auto_approve():
    """Test policy auto-approves SAFE tools when enabled."""
    policy = PermissionPolicy(auto_approve_safe=True)

    decision = policy.evaluate(
        tool_name="read_file",
        permission_level=PermissionLevel.SAFE,
        arguments={},
    )

    assert decision.action == PolicyAction.ALLOW
    assert decision.auto_approve


def test_permission_policy_safe_no_auto_approve():
    """Test policy requires confirmation for SAFE tools when disabled."""
    policy = PermissionPolicy(auto_approve_safe=False)

    decision = policy.evaluate(
        tool_name="read_file",
        permission_level=PermissionLevel.SAFE,
        arguments={},
    )

    assert decision.action == PolicyAction.CONFIRM
    assert not decision.auto_approve


def test_permission_policy_confirm():
    """Test policy requires confirmation for CONFIRM tools."""
    policy = PermissionPolicy(auto_approve_safe=True)

    decision = policy.evaluate(
        tool_name="write_file",
        permission_level=PermissionLevel.CONFIRM,
        arguments={},
    )

    assert decision.action == PolicyAction.CONFIRM
    assert not decision.auto_approve


def test_permission_policy_sensitive():
    """Test policy requires confirmation for SENSITIVE tools."""
    policy = PermissionPolicy(auto_approve_safe=True)

    decision = policy.evaluate(
        tool_name="terminal_execute",
        permission_level=PermissionLevel.SENSITIVE,
        arguments={},
    )

    assert decision.action == PolicyAction.CONFIRM
    assert not decision.auto_approve


@pytest.mark.asyncio
async def test_approval_manager_approve():
    """Test approval manager approval flow."""
    manager = ApprovalManager(default_timeout=1)

    # Start approval request in background
    task = asyncio.create_task(
        manager.request_approval(
            task_id=uuid4(),
            tool_name="write_file",
            arguments={"path": "/test.txt", "content": "hello"},
            reason="Test write",
            timeout=5,
        )
    )

    # Give it time to create the request
    await asyncio.sleep(0.1)

    # Get pending requests
    pending = await manager.list_pending()
    assert len(pending) == 1

    request = pending[0]
    assert request.tool == "write_file"
    assert request.status == PermissionRequestStatus.PENDING

    # Approve it
    decision = await manager.approve(request.id, reason="Test approval")

    # Wait for task to complete
    result = await task

    assert decision.approved
    assert result.approved
    assert result.reason  # Has a reason


@pytest.mark.asyncio
async def test_approval_manager_reject():
    """Test approval manager rejection flow."""
    manager = ApprovalManager(default_timeout=1)

    # Start approval request in background
    task = asyncio.create_task(
        manager.request_approval(
            task_id=uuid4(),
            tool_name="delete_file",
            arguments={"path": "/important.txt"},
            reason="Test delete",
            timeout=5,
        )
    )

    # Give it time to create the request
    await asyncio.sleep(0.1)

    # Get pending requests
    pending = await manager.list_pending()
    assert len(pending) == 1

    request = pending[0]

    # Reject it
    decision = await manager.reject(request.id, reason="Test rejection")

    # Wait for task to complete
    result = await task

    assert not decision.approved
    assert not result.approved
    assert "reject" in result.reason.lower()


@pytest.mark.asyncio
async def test_approval_manager_timeout():
    """Test approval manager timeout."""
    manager = ApprovalManager(default_timeout=1)

    # Request with short timeout
    decision = await manager.request_approval(
        task_id=uuid4(),
        tool_name="test_tool",
        arguments={},
        reason="Test timeout",
        timeout=1,
    )

    assert not decision.approved
    assert "expired" in decision.reason.lower() or "timeout" in decision.reason.lower()


@pytest.mark.asyncio
async def test_approval_manager_list_pending():
    """Test listing pending approvals."""
    manager = ApprovalManager(default_timeout=1)

    # Create multiple requests
    tasks = []
    for i in range(3):
        task = asyncio.create_task(
            manager.request_approval(
                task_id=uuid4(),
                tool_name=f"tool_{i}",
                arguments={"index": i},
                reason=f"Test {i}",
                timeout=10,
            )
        )
        tasks.append(task)

    # Give time to create requests
    await asyncio.sleep(0.1)

    # List pending
    pending = await manager.list_pending()
    assert len(pending) == 3

    # Approve one
    await manager.approve(pending[0].id)

    # Should have 2 pending
    pending = await manager.list_pending()
    assert len(pending) == 2

    # Cleanup - cancel remaining tasks
    for task in tasks:
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


@pytest.mark.asyncio
async def test_permission_engine_auto_approve():
    """Test permission engine auto-approves safe tools."""
    policy = PermissionPolicy(auto_approve_safe=True)
    engine = PermissionEngine(policy=policy)

    decision = await engine.check_permission(
        tool_name="get_time",
        permission_level=PermissionLevel.SAFE,
        arguments={},
    )

    assert decision.approved
    assert "auto-approval" in decision.reason.lower()


@pytest.mark.asyncio
async def test_permission_engine_deny_blocked():
    """Test permission engine denies blocked tools."""
    policy = PermissionPolicy(auto_approve_safe=True)
    engine = PermissionEngine(policy=policy)

    decision = await engine.check_permission(
        tool_name="dangerous_tool",
        permission_level=PermissionLevel.BLOCKED,
        arguments={},
    )

    assert not decision.approved
    assert "blocked" in decision.reason.lower()


@pytest.mark.asyncio
async def test_permission_engine_request_approval():
    """Test permission engine requests approval for confirm tools."""
    policy = PermissionPolicy(auto_approve_safe=True)
    manager = ApprovalManager(default_timeout=1)
    engine = PermissionEngine(policy=policy)
    engine.manager = manager

    # Start check in background
    task = asyncio.create_task(
        engine.check_permission(
            tool_name="write_file",
            permission_level=PermissionLevel.CONFIRM,
            arguments={"path": "/test.txt"},
            timeout=5,
        )
    )

    # Give time to create request
    await asyncio.sleep(0.1)

    # Find and approve the request
    pending = await manager.list_pending()
    assert len(pending) == 1

    await manager.approve(pending[0].id)

    # Get result
    decision = await task

    assert decision.approved


@pytest.mark.asyncio
async def test_permission_engine_integration():
    """Test full permission engine integration."""
    policy = PermissionPolicy(auto_approve_safe=False)  # No auto-approve
    manager = ApprovalManager(default_timeout=1)
    engine = PermissionEngine(policy=policy)
    engine.manager = manager

    # Test different permission levels
    test_cases = [
        (PermissionLevel.BLOCKED, False, "blocked"),
        (PermissionLevel.SAFE, None, "confirmation"),  # Will need approval
        (PermissionLevel.CONFIRM, None, "confirmation"),
        (PermissionLevel.SENSITIVE, None, "confirmation"),
    ]

    for level, expected_approved, expected_reason_keyword in test_cases:
        if expected_approved is None:
            # Need to approve/reject
            task = asyncio.create_task(
                engine.check_permission(
                    tool_name=f"test_tool_{level.value}",
                    permission_level=level,
                    arguments={},
                    timeout=5,
                )
            )

            await asyncio.sleep(0.1)

            pending = await manager.list_pending()
            if pending:
                # Approve the first, reject others
                if level == PermissionLevel.SAFE:
                    await manager.approve(pending[0].id)
                else:
                    await manager.reject(pending[0].id)

            decision = await task
            if level == PermissionLevel.SAFE:
                assert decision.approved
            else:
                assert not decision.approved
        else:
            # Direct decision
            decision = await engine.check_permission(
                tool_name=f"test_tool_{level.value}",
                permission_level=level,
                arguments={},
            )

            assert decision.approved == expected_approved
            assert expected_reason_keyword.lower() in decision.reason.lower()


def test_policy_decision_creation():
    """Test PolicyDecision creation."""
    decision = PolicyDecision(
        action=PolicyAction.ALLOW,
        reason="Test reason",
        auto_approve=True,
    )

    assert decision.action == PolicyAction.ALLOW
    assert decision.reason == "Test reason"
    assert decision.auto_approve


@pytest.mark.asyncio
async def test_approval_manager_cancel():
    """Test cancelling a pending approval."""
    manager = ApprovalManager(default_timeout=1)

    # Create request
    task = asyncio.create_task(
        manager.request_approval(
            task_id=uuid4(),
            tool_name="test_tool",
            arguments={},
            reason="Test cancel",
            timeout=10,
        )
    )

    await asyncio.sleep(0.1)

    pending = await manager.list_pending()
    assert len(pending) == 1

    # Cancel it
    await manager.cancel(pending[0].id)

    # Wait for task
    decision = await task

    assert not decision.approved
    assert "cancel" in decision.reason.lower()

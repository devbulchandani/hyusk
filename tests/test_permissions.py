"""Permission policy tests."""

from __future__ import annotations

import pytest

from hyusk.core.errors import PermissionDenied
from hyusk.permissions.policy import ALLOW, ASK, DENY, PermissionPolicy
from hyusk.tools.base import DESTRUCTIVE, READ, WRITE, Tool


def _t(name: str, perm: str) -> Tool:
    return Tool(
        name=name,
        description="",
        input_schema={"type": "object", "properties": {}, "required": []},
        permission=perm,
        execute=lambda a: {},
    )


def test_read_allowed_by_default():
    p = PermissionPolicy()
    assert p.decide(_t("read_x", READ)).action == ALLOW


def test_destructive_requires_prompt_by_default():
    p = PermissionPolicy()
    assert p.decide(_t("kill_x", DESTRUCTIVE)).action == ASK


def test_deny_category_always_denied():
    p = PermissionPolicy(deny_categories=[WRITE])
    assert p.decide(_t("write_x", WRITE)).action == DENY


def test_allow_list_filters():
    p = PermissionPolicy(allow_tools=["only_this"])
    assert p.decide(_t("only_this", READ)).action == ALLOW
    assert p.decide(_t("other", READ)).action == DENY


def test_enforce_raises_when_denied():
    p = PermissionPolicy(deny_categories=[WRITE])
    with pytest.raises(PermissionDenied):
        p.enforce(_t("write_x", WRITE))


def test_enforce_ask_without_grant_raises():
    p = PermissionPolicy(require_prompt=["kill_x"])
    with pytest.raises(PermissionDenied):
        p.enforce(_t("kill_x", DESTRUCTIVE))


def test_enforce_ask_with_grant_passes():
    p = PermissionPolicy(require_prompt=["kill_x"])
    p.enforce(_t("kill_x", DESTRUCTIVE), grants=["kill_x"])  # no raise

"""Session abstraction.

A session owns a list of messages, a unique id, and lightweight metadata.
Sessions are persisted as JSON so the CLI (or future daemon) can resume
them. Mobile clients will rely on this.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from ..core.errors import FileNotFound
from ..llm.provider import Message, ToolCallRequest


@dataclass
class Session:
    id: str
    messages: list[Message] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    metadata: dict[str, str] = field(default_factory=dict)

    @classmethod
    def create(cls) -> Session:
        return cls(id=str(uuid.uuid4()))

    def add(self, message: Message) -> None:
        self.messages.append(message)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "created_at": self.created_at,
            "metadata": self.metadata,
            "messages": [_msg_to_dict(m) for m in self.messages],
        }

    @classmethod
    def from_dict(cls, data: dict) -> Session:
        return cls(
            id=data["id"],
            created_at=data.get("created_at", time.time()),
            metadata=data.get("metadata", {}),
            messages=[_dict_to_msg(d) for d in data.get("messages", [])],
        )

    def save(self, base_dir: str) -> Path:
        p = Path(base_dir)
        p.mkdir(parents=True, exist_ok=True)
        path = p / f"{self.id}.json"
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        return path

    @classmethod
    def load(cls, base_dir: str, session_id: str) -> Session:
        path = Path(base_dir) / f"{session_id}.json"
        if not path.exists():
            raise FileNotFound(f"no such session: {session_id}")
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls.from_dict(data)

    @staticmethod
    def list_sessions(base_dir: str) -> list[dict]:
        p = Path(base_dir)
        if not p.exists():
            return []
        out: list[dict] = []
        for f in sorted(p.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
                out.append(
                    {
                        "id": d.get("id"),
                        "created_at": d.get("created_at"),
                        "metadata": d.get("metadata", {}),
                    }
                )
            except Exception:
                continue
        return out


def _msg_to_dict(m: Message) -> dict:
    return {
        "role": m.role,
        "content": m.content,
        "tool_calls": [
            {"id": tc.id, "name": tc.name, "arguments": tc.arguments} for tc in m.tool_calls
        ],
        "tool_call_id": m.tool_call_id,
        "name": m.name,
    }


def _dict_to_msg(d: dict) -> Message:
    tcs = d.get("tool_calls") or []
    return Message(
        role=d.get("role", "user"),
        content=d.get("content"),
        tool_calls=[
            ToolCallRequest(name=tc.get("name") or "", arguments=tc.get("arguments") or {}, id=tc.get("id"))
            for tc in tcs
        ],
        tool_call_id=d.get("tool_call_id"),
        name=d.get("name"),
    )

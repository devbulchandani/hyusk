"""Session store: knows where sessions are persisted.

A thin wrapper that gives a Session its base directory so it can be
saved without the caller passing the path each time.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .session import Session


@dataclass
class SessionStore:
    base_dir: str

    def new(self) -> Session:
        s = Session.create()
        s.metadata["_store_dir"] = self.base_dir
        return s

    def load(self, session_id: str) -> Session:
        s = Session.load(self.base_dir, session_id)
        s.metadata["_store_dir"] = self.base_dir
        return s

    def save(self, session: Session) -> Path:
        return session.save(self.base_dir)

    def list(self) -> list[dict]:
        return Session.list_sessions(self.base_dir)

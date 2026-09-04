"""V4 task store tests."""

from __future__ import annotations

from pathlib import Path

from hyusk.agent.tasks import TaskInfo, TaskState, TaskStore


def test_save_and_load(tmp_path: Path):
    store = TaskStore(base_dir=str(tmp_path))
    info = TaskInfo(
        id="abc123",
        session_id="sess1",
        state=TaskState.DONE,
        input="hello",
        created_at=100.0,
        text="done",
        iterations=3,
        transcript=[{"role": "user", "content": "hi"}],
    )
    store.save(info)
    loaded = store.load("abc123")
    assert loaded is not None
    assert loaded.id == "abc123"
    assert loaded.state == TaskState.DONE
    assert loaded.text == "done"
    assert loaded.transcript == [{"role": "user", "content": "hi"}]


def test_list_returns_sorted(tmp_path: Path):
    store = TaskStore(base_dir=str(tmp_path))
    for i, ts in enumerate([100.0, 50.0, 200.0, 75.0]):
        store.save(
            TaskInfo(
                id=f"id{i}",
                session_id="sess",
                state=TaskState.DONE,
                input="x",
                created_at=ts,
            )
        )
    listed = store.list()
    assert len(listed) == 4
    # newest first
    assert [t.id for t in listed] == ["id2", "id0", "id3", "id1"]


def test_delete(tmp_path: Path):
    store = TaskStore(base_dir=str(tmp_path))
    store.save(
        TaskInfo(id="z", session_id="s", state=TaskState.DONE, input="", created_at=1.0)
    )
    assert store.load("z") is not None
    store.delete("z")
    assert store.load("z") is None


def test_load_missing_returns_none(tmp_path: Path):
    store = TaskStore(base_dir=str(tmp_path))
    assert store.load("does-not-exist") is None


def test_taskinfo_round_trip_with_interrupted_state(tmp_path: Path):
    store = TaskStore(base_dir=str(tmp_path))
    info = TaskInfo(
        id="x1",
        session_id="s",
        state=TaskState.INTERRUPTED,
        input="x",
        created_at=10.0,
        ended_at=20.0,
        text="partial",
        iterations=2,
        error="interrupted by daemon restart",
    )
    store.save(info)
    loaded = store.load("x1")
    assert loaded is not None
    assert loaded.state == TaskState.INTERRUPTED
    assert loaded.error == "interrupted by daemon restart"

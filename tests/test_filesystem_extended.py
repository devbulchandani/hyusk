"""Tests for extended filesystem tools."""

import pytest

from hyusk.tools.filesystem import (
    CopyFileTool,
    CreateDirectoryTool,
    DeleteFileTool,
    MoveFileTool,
    SearchFilesTool,
)


@pytest.mark.asyncio
async def test_copy_file(tmp_path):
    """Test copying a file."""
    tool = CopyFileTool()

    # Create source file
    source = tmp_path / "source.txt"
    source.write_text("test content")

    dest = tmp_path / "dest.txt"

    # Copy file
    result = await tool.execute(
        source=str(source),
        destination=str(dest),
    )

    assert result["type"] == "file"
    assert dest.exists()
    assert dest.read_text() == "test content"


@pytest.mark.asyncio
async def test_copy_directory(tmp_path):
    """Test copying a directory."""
    tool = CopyFileTool()

    # Create source directory with files
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "file1.txt").write_text("content1")
    (source_dir / "file2.txt").write_text("content2")

    dest_dir = tmp_path / "dest"

    # Copy directory
    result = await tool.execute(
        source=str(source_dir),
        destination=str(dest_dir),
    )

    assert result["type"] == "directory"
    assert dest_dir.exists()
    assert (dest_dir / "file1.txt").exists()
    assert (dest_dir / "file2.txt").exists()


@pytest.mark.asyncio
async def test_move_file(tmp_path):
    """Test moving a file."""
    tool = MoveFileTool()

    # Create source file
    source = tmp_path / "source.txt"
    source.write_text("test content")

    dest = tmp_path / "dest.txt"

    # Move file
    result = await tool.execute(
        source=str(source),
        destination=str(dest),
    )

    assert result["type"] == "file"
    assert not source.exists()
    assert dest.exists()
    assert dest.read_text() == "test content"


@pytest.mark.asyncio
async def test_move_rename(tmp_path):
    """Test renaming a file."""
    tool = MoveFileTool()

    # Create source file
    source = tmp_path / "old_name.txt"
    source.write_text("test content")

    dest = tmp_path / "new_name.txt"

    # Rename
    result = await tool.execute(
        source=str(source),
        destination=str(dest),
    )

    assert not source.exists()
    assert dest.exists()


@pytest.mark.asyncio
async def test_delete_file(tmp_path):
    """Test deleting a file."""
    tool = DeleteFileTool()

    # Create file
    test_file = tmp_path / "test.txt"
    test_file.write_text("test content")

    # Delete it
    result = await tool.execute(path=str(test_file))

    assert result["deleted"] is True
    assert result["type"] == "file"
    assert not test_file.exists()


@pytest.mark.asyncio
async def test_delete_directory(tmp_path):
    """Test deleting a directory."""
    tool = DeleteFileTool()

    # Create directory with files
    test_dir = tmp_path / "test_dir"
    test_dir.mkdir()
    (test_dir / "file.txt").write_text("content")

    # Delete with recursive
    result = await tool.execute(path=str(test_dir), recursive=True)

    assert result["deleted"] is True
    assert result["type"] == "directory"
    assert not test_dir.exists()


@pytest.mark.asyncio
async def test_delete_directory_requires_recursive(tmp_path):
    """Test that directory deletion requires recursive flag."""
    tool = DeleteFileTool()

    # Create directory
    test_dir = tmp_path / "test_dir"
    test_dir.mkdir()

    # Try to delete without recursive
    with pytest.raises(Exception) as exc_info:
        await tool.execute(path=str(test_dir), recursive=False)

    assert "recursive" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_search_files(tmp_path):
    """Test searching for files."""
    tool = SearchFilesTool()

    # Create test files
    (tmp_path / "test1.py").write_text("python file 1")
    (tmp_path / "test2.py").write_text("python file 2")
    (tmp_path / "readme.txt").write_text("text file")

    # Search for Python files
    result = await tool.execute(
        directory=str(tmp_path),
        pattern="*.py",
        recursive=False,
    )

    assert result["count"] == 2
    paths = [r["path"] for r in result["results"]]
    assert any("test1.py" in p for p in paths)
    assert any("test2.py" in p for p in paths)


@pytest.mark.asyncio
async def test_search_files_recursive(tmp_path):
    """Test recursive file search."""
    tool = SearchFilesTool()

    # Create nested structure
    subdir = tmp_path / "subdir"
    subdir.mkdir()
    (tmp_path / "top.py").write_text("top level")
    (subdir / "nested.py").write_text("nested file")

    # Search recursively
    result = await tool.execute(
        directory=str(tmp_path),
        pattern="*.py",
        recursive=True,
    )

    assert result["count"] == 2
    paths = [r["path"] for r in result["results"]]
    assert any("top.py" in p for p in paths)
    assert any("nested.py" in p for p in paths)


@pytest.mark.asyncio
async def test_search_files_max_results(tmp_path):
    """Test max results limit."""
    tool = SearchFilesTool()

    # Create many files
    for i in range(20):
        (tmp_path / f"file{i}.txt").write_text(f"content {i}")

    # Search with limit
    result = await tool.execute(
        directory=str(tmp_path),
        pattern="*.txt",
        max_results=10,
    )

    assert result["count"] == 10
    assert result["truncated"] is True


@pytest.mark.asyncio
async def test_create_directory(tmp_path):
    """Test creating a directory."""
    tool = CreateDirectoryTool()

    new_dir = tmp_path / "new_directory"

    # Create directory
    result = await tool.execute(path=str(new_dir))

    assert result["created"] is True
    assert new_dir.exists()
    assert new_dir.is_dir()


@pytest.mark.asyncio
async def test_create_directory_nested(tmp_path):
    """Test creating nested directories."""
    tool = CreateDirectoryTool()

    nested_dir = tmp_path / "parent" / "child" / "grandchild"

    # Create with parents
    result = await tool.execute(path=str(nested_dir))

    assert result["created"] is True
    assert nested_dir.exists()


@pytest.mark.asyncio
async def test_create_directory_already_exists(tmp_path):
    """Test creating a directory that already exists."""
    tool = CreateDirectoryTool()

    existing_dir = tmp_path / "existing"
    existing_dir.mkdir()

    # Try to create again
    result = await tool.execute(path=str(existing_dir))

    assert result["created"] is False
    assert "already exists" in result["message"]

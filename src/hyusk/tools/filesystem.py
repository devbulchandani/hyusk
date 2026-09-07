"""Filesystem tools."""

import os
from pathlib import Path
from typing import Any

from hyusk.tools.base import ConfirmTool, SafeTool, ToolExecutionError


class ReadFileTool(SafeTool):
    """Read contents of a file."""

    @property
    def name(self) -> str:
        return "read_file"

    @property
    def description(self) -> str:
        return "Read the contents of a file. Returns the file content as text."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the file to read",
                },
                "encoding": {
                    "type": "string",
                    "description": "File encoding (default: utf-8)",
                },
            },
            "required": ["path"],
        }

    @property
    def category(self) -> str:
        return "filesystem"

    async def execute(self, path: str, encoding: str = "utf-8") -> dict[str, Any]:
        """Read file contents."""
        file_path = Path(path).expanduser().resolve()

        # Security: Check path traversal
        if not self._is_safe_path(file_path):
            raise ToolExecutionError("Path traversal detected")

        if not file_path.exists():
            raise ToolExecutionError(f"File not found: {path}")

        if not file_path.is_file():
            raise ToolExecutionError(f"Not a file: {path}")

        try:
            content = file_path.read_text(encoding=encoding)

            return {
                "path": str(file_path),
                "content": content,
                "size_bytes": file_path.stat().st_size,
                "lines": len(content.splitlines()),
            }

        except UnicodeDecodeError:
            raise ToolExecutionError(f"Failed to decode file with encoding: {encoding}")
        except Exception as e:
            raise ToolExecutionError(f"Failed to read file: {str(e)}")

    def _is_safe_path(self, path: Path) -> bool:
        """Check if path is safe (no traversal outside allowed areas).

        Args:
            path: Path to check

        Returns:
            True if safe
        """
        # For now, allow any path
        # TODO: Implement configurable allowed directories
        return True


class ListDirectoryTool(SafeTool):
    """List contents of a directory."""

    @property
    def name(self) -> str:
        return "list_directory"

    @property
    def description(self) -> str:
        return "List files and directories in a given path. Returns file names, types, and sizes."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Directory path to list",
                },
                "show_hidden": {
                    "type": "boolean",
                    "description": "Include hidden files (default: false)",
                },
            },
            "required": ["path"],
        }

    @property
    def category(self) -> str:
        return "filesystem"

    async def execute(self, path: str, show_hidden: bool = False) -> dict[str, Any]:
        """List directory contents."""
        dir_path = Path(path).expanduser().resolve()

        if not dir_path.exists():
            raise ToolExecutionError(f"Directory not found: {path}")

        if not dir_path.is_dir():
            raise ToolExecutionError(f"Not a directory: {path}")

        try:
            entries = []

            for item in sorted(dir_path.iterdir()):
                # Skip hidden files if requested
                if not show_hidden and item.name.startswith("."):
                    continue

                entry = {
                    "name": item.name,
                    "type": "directory" if item.is_dir() else "file",
                    "path": str(item),
                }

                if item.is_file():
                    entry["size_bytes"] = item.stat().st_size

                entries.append(entry)

            return {
                "path": str(dir_path),
                "entries": entries,
                "count": len(entries),
            }

        except PermissionError:
            raise ToolExecutionError(f"Permission denied: {path}")
        except Exception as e:
            raise ToolExecutionError(f"Failed to list directory: {str(e)}")


class FileExistsTool(SafeTool):
    """Check if a file or directory exists."""

    @property
    def name(self) -> str:
        return "file_exists"

    @property
    def description(self) -> str:
        return "Check if a file or directory exists at the given path."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to check",
                },
            },
            "required": ["path"],
        }

    @property
    def category(self) -> str:
        return "filesystem"

    async def execute(self, path: str) -> dict[str, Any]:
        """Check if path exists."""
        file_path = Path(path).expanduser().resolve()

        exists = file_path.exists()

        result = {
            "path": str(file_path),
            "exists": exists,
        }

        if exists:
            result["type"] = "directory" if file_path.is_dir() else "file"

            if file_path.is_file():
                result["size_bytes"] = file_path.stat().st_size

        return result


class WriteFileTool(ConfirmTool):
    """Write content to a file."""

    @property
    def name(self) -> str:
        return "write_file"

    @property
    def description(self) -> str:
        return (
            "Write content to a file. Creates the file if it doesn't exist, overwrites if it does."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the file to write",
                },
                "content": {
                    "type": "string",
                    "description": "Content to write to the file",
                },
                "encoding": {
                    "type": "string",
                    "description": "File encoding (default: utf-8)",
                },
            },
            "required": ["path", "content"],
        }

    @property
    def category(self) -> str:
        return "filesystem"

    async def execute(self, path: str, content: str, encoding: str = "utf-8") -> dict[str, Any]:
        """Write file contents."""
        file_path = Path(path).expanduser().resolve()

        # Security: Check path traversal
        if not self._is_safe_path(file_path):
            raise ToolExecutionError("Path traversal detected")

        try:
            # Create parent directories if needed
            file_path.parent.mkdir(parents=True, exist_ok=True)

            # Write file
            file_path.write_text(content, encoding=encoding)

            return {
                "path": str(file_path),
                "size_bytes": file_path.stat().st_size,
                "lines_written": len(content.splitlines()),
            }

        except Exception as e:
            raise ToolExecutionError(f"Failed to write file: {str(e)}")

    def _is_safe_path(self, path: Path) -> bool:
        """Check if path is safe for writing.

        Args:
            path: Path to check

        Returns:
            True if safe
        """
        # For now, allow any path
        # TODO: Implement configurable allowed directories
        return True


class CopyFileTool(ConfirmTool):
    """Copy a file or directory."""

    @property
    def name(self) -> str:
        return "copy_file"

    @property
    def description(self) -> str:
        return "Copy a file or directory to a new location."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "description": "Source path to copy from",
                },
                "destination": {
                    "type": "string",
                    "description": "Destination path to copy to",
                },
            },
            "required": ["source", "destination"],
        }

    @property
    def category(self) -> str:
        return "filesystem"

    async def execute(self, source: str, destination: str) -> dict[str, Any]:
        """Copy file or directory."""
        import shutil

        source_path = Path(source).expanduser().resolve()
        dest_path = Path(destination).expanduser().resolve()

        if not source_path.exists():
            raise ToolExecutionError(f"Source not found: {source}")

        try:
            if source_path.is_file():
                # Copy file
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_path, dest_path)
                result_type = "file"
                size = dest_path.stat().st_size
            else:
                # Copy directory
                shutil.copytree(source_path, dest_path)
                result_type = "directory"
                # Count files
                size = sum(1 for _ in dest_path.rglob("*") if _.is_file())

            return {
                "source": str(source_path),
                "destination": str(dest_path),
                "type": result_type,
                "size": size,
            }

        except Exception as e:
            raise ToolExecutionError(f"Failed to copy: {str(e)}")


class MoveFileTool(ConfirmTool):
    """Move or rename a file or directory."""

    @property
    def name(self) -> str:
        return "move_file"

    @property
    def description(self) -> str:
        return "Move or rename a file or directory."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "description": "Source path to move from",
                },
                "destination": {
                    "type": "string",
                    "description": "Destination path to move to",
                },
            },
            "required": ["source", "destination"],
        }

    @property
    def category(self) -> str:
        return "filesystem"

    async def execute(self, source: str, destination: str) -> dict[str, Any]:
        """Move/rename file or directory."""
        import shutil

        source_path = Path(source).expanduser().resolve()
        dest_path = Path(destination).expanduser().resolve()

        if not source_path.exists():
            raise ToolExecutionError(f"Source not found: {source}")

        try:
            # Create parent directory if needed
            dest_path.parent.mkdir(parents=True, exist_ok=True)

            # Move
            shutil.move(str(source_path), str(dest_path))

            return {
                "source": str(source_path),
                "destination": str(dest_path),
                "type": "directory" if dest_path.is_dir() else "file",
            }

        except Exception as e:
            raise ToolExecutionError(f"Failed to move: {str(e)}")


class DeleteFileTool(ConfirmTool):
    """Delete a file or directory."""

    @property
    def name(self) -> str:
        return "delete_file"

    @property
    def description(self) -> str:
        return "Delete a file or directory. Use with caution - this is permanent!"

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to delete",
                },
                "recursive": {
                    "type": "boolean",
                    "description": "Delete directory recursively (required for directories)",
                },
            },
            "required": ["path"],
        }

    @property
    def category(self) -> str:
        return "filesystem"

    async def execute(self, path: str, recursive: bool = False) -> dict[str, Any]:
        """Delete file or directory."""
        import shutil

        file_path = Path(path).expanduser().resolve()

        if not file_path.exists():
            raise ToolExecutionError(f"Path not found: {path}")

        try:
            if file_path.is_file():
                file_path.unlink()
                result_type = "file"
            elif file_path.is_dir():
                if not recursive:
                    raise ToolExecutionError(
                        "Directory deletion requires recursive=true"
                    )
                shutil.rmtree(file_path)
                result_type = "directory"
            else:
                raise ToolExecutionError(f"Unknown path type: {path}")

            return {
                "path": str(file_path),
                "deleted": True,
                "type": result_type,
            }

        except ToolExecutionError:
            raise
        except Exception as e:
            raise ToolExecutionError(f"Failed to delete: {str(e)}")


class SearchFilesTool(SafeTool):
    """Search for files matching a pattern."""

    @property
    def name(self) -> str:
        return "search_files"

    @property
    def description(self) -> str:
        return "Search for files matching a pattern in a directory."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "directory": {
                    "type": "string",
                    "description": "Directory to search in",
                },
                "pattern": {
                    "type": "string",
                    "description": "File name pattern (supports glob: *.py, test*.txt)",
                },
                "recursive": {
                    "type": "boolean",
                    "description": "Search recursively in subdirectories",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results to return (default: 100)",
                },
            },
            "required": ["directory", "pattern"],
        }

    @property
    def category(self) -> str:
        return "filesystem"

    async def execute(
        self,
        directory: str,
        pattern: str,
        recursive: bool = False,
        max_results: int = 100,
    ) -> dict[str, Any]:
        """Search for files."""
        dir_path = Path(directory).expanduser().resolve()

        if not dir_path.exists():
            raise ToolExecutionError(f"Directory not found: {directory}")

        if not dir_path.is_dir():
            raise ToolExecutionError(f"Not a directory: {directory}")

        try:
            # Use glob for pattern matching
            if recursive:
                matches = dir_path.rglob(pattern)
            else:
                matches = dir_path.glob(pattern)

            results = []
            count = 0

            for match in matches:
                if count >= max_results:
                    break

                results.append({
                    "path": str(match),
                    "name": match.name,
                    "type": "directory" if match.is_dir() else "file",
                    "size_bytes": match.stat().st_size if match.is_file() else None,
                })
                count += 1

            return {
                "directory": str(dir_path),
                "pattern": pattern,
                "results": results,
                "count": len(results),
                "truncated": count >= max_results,
            }

        except Exception as e:
            raise ToolExecutionError(f"Search failed: {str(e)}")


class CreateDirectoryTool(ConfirmTool):
    """Create a new directory."""

    @property
    def name(self) -> str:
        return "create_directory"

    @property
    def description(self) -> str:
        return "Create a new directory (and parent directories if needed)."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Directory path to create",
                },
            },
            "required": ["path"],
        }

    @property
    def category(self) -> str:
        return "filesystem"

    async def execute(self, path: str) -> dict[str, Any]:
        """Create directory."""
        dir_path = Path(path).expanduser().resolve()

        if dir_path.exists():
            if dir_path.is_dir():
                return {
                    "path": str(dir_path),
                    "created": False,
                    "message": "Directory already exists",
                }
            else:
                raise ToolExecutionError(f"Path exists but is not a directory: {path}")

        try:
            dir_path.mkdir(parents=True, exist_ok=True)

            return {
                "path": str(dir_path),
                "created": True,
            }

        except Exception as e:
            raise ToolExecutionError(f"Failed to create directory: {str(e)}")

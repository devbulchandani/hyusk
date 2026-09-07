"""macOS computer control tools."""

import subprocess
from pathlib import Path
from typing import Any

from hyusk.logging import get_logger
from hyusk.models import PermissionLevel
from hyusk.tools.base import ConfirmTool, SafeTool, SensitiveTool, ToolError

logger = get_logger(__name__)


class OpenApplicationTool(SafeTool):
    """Open a macOS application."""

    name = "open_application"
    description = "Open a macOS application by name or path. Works with any installed app."
    category = "computer"
    permission_level = PermissionLevel.SAFE

    @property
    def input_schema(self) -> dict[str, Any]:
        """Get input schema."""
        return {
            "type": "object",
            "properties": {
                "application": {
                    "type": "string",
                    "description": "Application name (e.g., 'Safari', 'Brave Browser') or path",
                },
                "url": {
                    "type": "string",
                    "description": "Optional URL to open with the application",
                },
            },
            "required": ["application"],
        }

    async def execute(self, application: str, url: str | None = None) -> dict[str, Any]:
        """Open an application.

        Args:
            application: App name or path
            url: Optional URL to open

        Returns:
            Dictionary with result
        """
        logger.info(f"Opening application", app=application, url=url)

        try:
            if url:
                # Open URL with specific application
                cmd = ["open", "-a", application, url]
            else:
                # Just open the application
                cmd = ["open", "-a", application]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10,
            )

            if result.returncode == 0:
                return {
                    "success": True,
                    "application": application,
                    "url": url,
                    "message": f"Opened {application}",
                }
            else:
                error_msg = result.stderr.strip() or "Failed to open application"
                raise ToolError(f"Failed to open {application}: {error_msg}")

        except subprocess.TimeoutExpired:
            raise ToolError(f"Timeout opening {application}")
        except Exception as e:
            raise ToolError(f"Error opening application: {str(e)}")


class CloseApplicationTool(ConfirmTool):
    """Close a macOS application."""

    name = "close_application"
    description = "Close a running macOS application gracefully or force quit."
    category = "computer"
    permission_level = PermissionLevel.CONFIRM

    @property
    def input_schema(self) -> dict[str, Any]:
        """Get input schema."""
        return {
            "type": "object",
            "properties": {
                "application": {
                    "type": "string",
                    "description": "Application name to close",
                },
                "force": {
                    "type": "boolean",
                    "description": "Force quit if true (default: false)",
                },
            },
            "required": ["application"],
        }

    async def execute(self, application: str, force: bool = False) -> dict[str, Any]:
        """Close an application.

        Args:
            application: App name
            force: Force quit

        Returns:
            Dictionary with result
        """
        logger.info(f"Closing application", app=application, force=force)

        try:
            if force:
                # Force quit using killall
                cmd = ["killall", application]
            else:
                # Graceful quit using osascript
                script = f'tell application "{application}" to quit'
                cmd = ["osascript", "-e", script]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10,
            )

            return {
                "success": result.returncode == 0,
                "application": application,
                "method": "force" if force else "graceful",
                "message": f"Closed {application}",
            }

        except Exception as e:
            raise ToolError(f"Error closing application: {str(e)}")


class TakeScreenshotTool(SafeTool):
    """Take a screenshot on macOS."""

    name = "take_screenshot"
    description = "Take a screenshot and save it to a file. Can capture entire screen or specific window."
    category = "computer"
    permission_level = PermissionLevel.SAFE

    @property
    def input_schema(self) -> dict[str, Any]:
        """Get input schema."""
        return {
            "type": "object",
            "properties": {
                "filepath": {
                    "type": "string",
                    "description": "Path where to save the screenshot (default: ~/Desktop/screenshot_TIMESTAMP.png)",
                },
                "window": {
                    "type": "boolean",
                    "description": "Capture specific window interactively (default: false, captures entire screen)",
                },
                "selection": {
                    "type": "boolean",
                    "description": "Allow user to select area interactively (default: false)",
                },
            },
        }

    async def execute(
        self,
        filepath: str | None = None,
        window: bool = False,
        selection: bool = False,
    ) -> dict[str, Any]:
        """Take a screenshot.

        Args:
            filepath: Output file path
            window: Capture specific window
            selection: Select area interactively

        Returns:
            Dictionary with result
        """
        import time

        # Generate default filename if not provided
        if not filepath:
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            filepath = f"~/Desktop/screenshot_{timestamp}.png"

        # Expand path
        output_path = Path(filepath).expanduser().resolve()

        # Create parent directory if needed
        output_path.parent.mkdir(parents=True, exist_ok=True)

        logger.info(f"Taking screenshot", output=str(output_path))

        try:
            # Build screencapture command
            cmd = ["screencapture"]

            # Add -x flag to prevent sound
            cmd.append("-x")

            if window:
                cmd.append("-w")  # Window mode
            elif selection:
                cmd.append("-s")  # Selection mode

            cmd.append(str(output_path))

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,  # Longer timeout for interactive selection
            )

            # Check if file was created (screencapture might return 0 even on permission failure)
            if output_path.exists() and output_path.stat().st_size > 0:
                size_bytes = output_path.stat().st_size
                return {
                    "success": True,
                    "filepath": str(output_path),
                    "size_bytes": size_bytes,
                    "message": f"Screenshot saved to {output_path}",
                }
            else:
                # Check stderr for permission issues
                stderr = result.stderr.strip()
                if stderr:
                    raise ToolError(f"Screenshot failed: {stderr}. May need Screen Recording permission in System Preferences > Privacy & Security")
                raise ToolError("Screenshot failed - file not created. May need Screen Recording permission in System Preferences > Privacy & Security")

        except subprocess.TimeoutExpired:
            raise ToolError("Screenshot timeout (may have been cancelled)")
        except ToolError:
            raise
        except Exception as e:
            raise ToolError(f"Error taking screenshot: {str(e)}")


class TypeTextTool(SensitiveTool):
    """Type text using keyboard simulation."""

    name = "type_text"
    description = "Type text into the currently focused application using keyboard simulation."
    category = "computer"
    permission_level = PermissionLevel.SENSITIVE

    @property
    def input_schema(self) -> dict[str, Any]:
        """Get input schema."""
        return {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Text to type",
                },
                "delay": {
                    "type": "number",
                    "description": "Delay between keystrokes in seconds (default: 0.01)",
                },
            },
            "required": ["text"],
        }

    async def execute(self, text: str, delay: float = 0.01) -> dict[str, Any]:
        """Type text using keyboard simulation.

        Args:
            text: Text to type
            delay: Delay between keystrokes

        Returns:
            Dictionary with result
        """
        logger.info(f"Typing text", length=len(text))

        try:
            # Use osascript to type text (more reliable than other methods)
            # Escape special characters for AppleScript
            escaped_text = text.replace('"', '\\"').replace("\\", "\\\\")

            script = f'''
tell application "System Events"
    keystroke "{escaped_text}"
end tell
'''

            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode == 0:
                return {
                    "success": True,
                    "characters_typed": len(text),
                    "message": f"Typed {len(text)} characters",
                }
            else:
                error_msg = result.stderr.strip() or "Failed to type text"
                raise ToolError(f"Keyboard simulation failed: {error_msg}")

        except subprocess.TimeoutExpired:
            raise ToolError("Typing timeout")
        except Exception as e:
            raise ToolError(f"Error typing text: {str(e)}")


class PressKeyTool(SensitiveTool):
    """Press a specific key or key combination."""

    name = "press_key"
    description = "Press a keyboard key or combination (e.g., 'return', 'command+c', 'option+tab')."
    category = "computer"
    permission_level = PermissionLevel.SENSITIVE

    @property
    def input_schema(self) -> dict[str, Any]:
        """Get input schema."""
        return {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "Key or combination to press (e.g., 'return', 'command+s', 'tab')",
                },
            },
            "required": ["key"],
        }

    async def execute(self, key: str) -> dict[str, Any]:
        """Press a key or key combination.

        Args:
            key: Key or combination

        Returns:
            Dictionary with result
        """
        logger.info(f"Pressing key", key=key)

        # Map common key names
        key_mapping = {
            "return": "return",
            "enter": "return",
            "tab": "tab",
            "space": "space",
            "escape": "escape",
            "esc": "escape",
            "delete": "delete",
            "backspace": "delete",
            "up": "up arrow",
            "down": "down arrow",
            "left": "left arrow",
            "right": "right arrow",
            "command": "command",
            "cmd": "command",
            "option": "option",
            "alt": "option",
            "control": "control",
            "ctrl": "control",
            "shift": "shift",
        }

        try:
            # Parse key combination
            parts = [p.strip().lower() for p in key.split("+")]

            # Build AppleScript
            if len(parts) == 1:
                # Single key
                key_name = key_mapping.get(parts[0], parts[0])
                script = f'''
tell application "System Events"
    key code {self._get_key_code(key_name)}
end tell
'''
            else:
                # Key combination
                modifiers = [key_mapping.get(p, p) for p in parts[:-1]]
                main_key = key_mapping.get(parts[-1], parts[-1])

                modifier_str = " using {" + ", ".join(f"{m} down" for m in modifiers) + "}"

                script = f'''
tell application "System Events"
    keystroke "{main_key}" {modifier_str}
end tell
'''

            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=10,
            )

            if result.returncode == 0:
                return {
                    "success": True,
                    "key": key,
                    "message": f"Pressed {key}",
                }
            else:
                error_msg = result.stderr.strip() or "Failed to press key"
                raise ToolError(f"Key press failed: {error_msg}")

        except Exception as e:
            raise ToolError(f"Error pressing key: {str(e)}")

    def _get_key_code(self, key: str) -> int:
        """Get key code for a key name."""
        # Common key codes for macOS
        codes = {
            "return": 36,
            "tab": 48,
            "space": 49,
            "delete": 51,
            "escape": 53,
        }
        return codes.get(key, 0)


class GetWindowListTool(SafeTool):
    """Get list of open windows."""

    name = "get_window_list"
    description = "Get a list of all open windows and applications."
    category = "computer"
    permission_level = PermissionLevel.SAFE

    @property
    def input_schema(self) -> dict[str, Any]:
        """Get input schema."""
        return {"type": "object", "properties": {}}

    async def execute(self) -> dict[str, Any]:
        """Get list of windows.

        Returns:
            Dictionary with window list
        """
        logger.info("Getting window list")

        try:
            # Use osascript to get window info
            script = '''
tell application "System Events"
    set appList to {}
    repeat with theProcess in (every process whose visible is true)
        set appName to name of theProcess
        try
            set windowList to (name of every window of theProcess)
            if (count of windowList) > 0 then
                set end of appList to {appName:appName, windows:windowList}
            end if
        end try
    end repeat
    return appList
end tell
'''

            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=10,
            )

            if result.returncode == 0:
                # Parse output (simplified)
                output = result.stdout.strip()

                return {
                    "success": True,
                    "raw_output": output,
                    "message": "Retrieved window list",
                }
            else:
                raise ToolError("Failed to get window list")

        except Exception as e:
            raise ToolError(f"Error getting window list: {str(e)}")


class ClickMouseTool(SensitiveTool):
    """Click the mouse at current position or coordinates."""

    name = "click_mouse"
    description = "Click the mouse at the current position or specified coordinates."
    category = "computer"
    permission_level = PermissionLevel.SENSITIVE

    @property
    def input_schema(self) -> dict[str, Any]:
        """Get input schema."""
        return {
            "type": "object",
            "properties": {
                "x": {
                    "type": "integer",
                    "description": "X coordinate (optional, clicks current position if not specified)",
                },
                "y": {
                    "type": "integer",
                    "description": "Y coordinate (optional)",
                },
                "button": {
                    "type": "string",
                    "description": "Mouse button: 'left', 'right', or 'middle' (default: left)",
                },
                "clicks": {
                    "type": "integer",
                    "description": "Number of clicks (default: 1, use 2 for double-click)",
                },
            },
        }

    async def execute(
        self,
        x: int | None = None,
        y: int | None = None,
        button: str = "left",
        clicks: int = 1,
    ) -> dict[str, Any]:
        """Click the mouse.

        Args:
            x: X coordinate
            y: Y coordinate
            button: Mouse button
            clicks: Number of clicks

        Returns:
            Dictionary with result
        """
        logger.info(f"Clicking mouse", x=x, y=y, button=button, clicks=clicks)

        try:
            # Build cliclick command
            # Note: Requires cliclick to be installed (brew install cliclick)
            cmd = ["cliclick"]

            if x is not None and y is not None:
                # Move to position first
                cmd.extend(["m:" + f"{x},{y}"])

            # Click
            click_cmd = "c:."  # Click at current position
            if clicks == 2:
                click_cmd = "dc:."  # Double click

            cmd.append(click_cmd)

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=5,
            )

            if result.returncode == 0:
                return {
                    "success": True,
                    "position": f"({x},{y})" if x and y else "current",
                    "button": button,
                    "clicks": clicks,
                    "message": f"Clicked {button} button {clicks} time(s)",
                }
            else:
                # cliclick might not be installed
                error_msg = result.stderr.strip()
                if "command not found" in error_msg:
                    raise ToolError(
                        "cliclick not installed. Install with: brew install cliclick"
                    )
                raise ToolError(f"Click failed: {error_msg}")

        except FileNotFoundError:
            raise ToolError("cliclick not found. Install with: brew install cliclick")
        except Exception as e:
            raise ToolError(f"Error clicking mouse: {str(e)}")

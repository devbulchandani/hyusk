"""Tests for computer control tools."""

import pytest

from hyusk.computer.macos import (
    CloseApplicationTool,
    GetWindowListTool,
    OpenApplicationTool,
    PressKeyTool,
    TakeScreenshotTool,
    TypeTextTool,
)


@pytest.mark.asyncio
async def test_open_application():
    """Test opening an application."""
    tool = OpenApplicationTool()

    # Open Calculator (should be available on all macOS)
    result = await tool.execute(application="Calculator")

    assert result["success"] is True
    assert result["application"] == "Calculator"
    assert "opened" in result["message"].lower()


@pytest.mark.asyncio
async def test_open_application_with_url():
    """Test opening an application with URL."""
    tool = OpenApplicationTool()

    # Open Safari with a URL
    result = await tool.execute(
        application="Safari",
        url="https://www.example.com"
    )

    assert result["success"] is True
    assert result["url"] == "https://www.example.com"


@pytest.mark.asyncio
async def test_open_nonexistent_application():
    """Test opening a non-existent application."""
    tool = OpenApplicationTool()

    with pytest.raises(Exception) as exc_info:
        await tool.execute(application="NonExistentApp123456")

    assert "failed" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_close_application():
    """Test closing an application."""
    # First open an app
    open_tool = OpenApplicationTool()
    await open_tool.execute(application="Calculator")

    # Small delay to ensure app is open
    import asyncio
    await asyncio.sleep(1)

    # Now close it
    close_tool = CloseApplicationTool()
    result = await close_tool.execute(application="Calculator")

    assert result["application"] == "Calculator"
    assert result["method"] == "graceful"


@pytest.mark.asyncio
async def test_take_screenshot(tmp_path):
    """Test taking a screenshot."""
    tool = TakeScreenshotTool()

    output_file = tmp_path / "test_screenshot.png"

    try:
        result = await tool.execute(filepath=str(output_file))

        assert result["success"] is True
        assert output_file.exists()
        assert result["size_bytes"] > 0
    except Exception as e:
        if "Screen Recording permission" in str(e):
            pytest.skip("Screen Recording permission not granted")
        raise


@pytest.mark.asyncio
async def test_take_screenshot_default_location():
    """Test screenshot with default location."""
    tool = TakeScreenshotTool()

    try:
        result = await tool.execute()

        assert result["success"] is True
        assert "Desktop" in result["filepath"]

        # Cleanup
        import os
        if os.path.exists(result["filepath"]):
            os.remove(result["filepath"])
    except Exception as e:
        if "Screen Recording permission" in str(e):
            pytest.skip("Screen Recording permission not granted")
        raise


@pytest.mark.asyncio
async def test_get_window_list():
    """Test getting window list."""
    tool = GetWindowListTool()

    result = await tool.execute()

    assert result["success"] is True
    assert "raw_output" in result


@pytest.mark.asyncio
async def test_type_text_schema():
    """Test type text tool schema."""
    tool = TypeTextTool()

    schema = tool.input_schema

    assert "properties" in schema
    assert "text" in schema["properties"]
    assert "required" in schema
    assert "text" in schema["required"]


@pytest.mark.asyncio
async def test_press_key_schema():
    """Test press key tool schema."""
    tool = PressKeyTool()

    schema = tool.input_schema

    assert "properties" in schema
    assert "key" in schema["properties"]
    assert "required" in schema
    assert "key" in schema["required"]


def test_tool_properties():
    """Test tool properties are correctly set."""
    tools = [
        (OpenApplicationTool(), "open_application", "computer"),
        (CloseApplicationTool(), "close_application", "computer"),
        (TakeScreenshotTool(), "take_screenshot", "computer"),
        (TypeTextTool(), "type_text", "computer"),
        (PressKeyTool(), "press_key", "computer"),
        (GetWindowListTool(), "get_window_list", "computer"),
    ]

    for tool, expected_name, expected_category in tools:
        assert tool.name == expected_name
        assert tool.category == expected_category
        assert tool.description  # Has description
        assert tool.input_schema  # Has schema

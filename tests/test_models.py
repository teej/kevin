from __future__ import annotations

import json
from unittest.mock import Mock, patch

import pytest

from kevin.models.claude import ClaudeClient
from kevin.models.types import ModelContext, Patch, Plan, Reflection


def test_plan_validation():
    """Test Plan model validation."""
    # Valid plan
    plan = Plan(
        files_to_read=["main.py", "test.py"],
        commands_to_run=["uv run python main.py", "uv run pytest"],
        rationale="Test the main functionality",
    )
    assert plan.files_to_read == ["main.py", "test.py"]
    assert plan.commands_to_run == ["uv run python main.py", "uv run pytest"]

    # Invalid plan - empty files
    with pytest.raises(ValueError, match="Must specify at least one file"):
        Plan(files_to_read=[], commands_to_run=["ls"], rationale="test")

    # Invalid plan - empty commands
    with pytest.raises(ValueError, match="Must specify at least one command"):
        Plan(files_to_read=["main.py"], commands_to_run=[], rationale="test")


def test_patch_validation():
    """Test Patch model validation."""
    # Valid patch
    valid_diff = """--- a/main.py
+++ b/main.py
@@ -1,3 +1,3 @@
 def hello():
-    print("hello")
+    print("Hello, World!")
"""
    patch = Patch(unified_diff=valid_diff)
    assert "--- a/main.py" in patch.unified_diff
    assert "+++ b/main.py" in patch.unified_diff

    # Invalid patch - empty
    with pytest.raises(ValueError, match="Patch cannot be empty"):
        Patch(unified_diff="")

    # Invalid patch - missing markers
    with pytest.raises(ValueError, match="Patch must contain"):
        Patch(unified_diff="just some text")


def test_reflection_validation():
    """Test Reflection model validation."""
    reflection = Reflection(
        next_action="Try a different approach",
        lessons_learned="The API endpoint was incorrect",
        should_retry=True,
    )
    assert reflection.should_retry is True


def test_model_context():
    """Test ModelContext creation."""
    context = ModelContext(
        task="Fix the bug",
        repo_path="/tmp/repo",
        file_contents={"main.py": "print('hello')"},
        command_results=[{"command": "ls", "returncode": 0}],
        test_command="uv run pytest",
    )
    assert context.task == "Fix the bug"
    assert context.repo_path == "/tmp/repo"
    assert "main.py" in context.file_contents


@patch("kevin.models.claude.Anthropic")
def test_claude_client_plan(mock_anthropic):
    """Test ClaudeClient plan generation."""
    # Mock the API response
    mock_response = Mock()
    mock_response.content = [Mock()]
    mock_response.content[0].text = json.dumps(
        {
            "files_to_read": ["main.py"],
            "commands_to_run": ["python main.py"],
            "rationale": "Test the main file",
        }
    )

    mock_client = Mock()
    mock_client.messages.create.return_value = mock_response
    mock_anthropic.return_value = mock_client

    client = ClaudeClient()
    context = ModelContext(task="test", repo_path="/tmp")

    plan = client.plan(context)
    assert plan.files_to_read == ["main.py"]
    assert plan.commands_to_run == ["python main.py"]
    assert plan.rationale == "Test the main file"


@patch("kevin.models.claude.Anthropic")
def test_claude_client_patch(mock_anthropic):
    """Test ClaudeClient patch generation."""
    # Mock the API response
    mock_response = Mock()
    mock_response.content = [Mock()]
    mock_response.content[0].text = """--- a/main.py
+++ b/main.py
@@ -1,3 +1,3 @@
 def hello():
-    print("hello")
+    print("Hello, World!")
"""

    mock_client = Mock()
    mock_client.messages.create.return_value = mock_response
    mock_anthropic.return_value = mock_client

    client = ClaudeClient()
    context = ModelContext(task="test", repo_path="/tmp")
    plan = Plan(files_to_read=["main.py"], commands_to_run=["ls"], rationale="test")

    patch = client.propose_patch(context, plan)
    assert "--- a/main.py" in patch.unified_diff
    assert "+++ b/main.py" in patch.unified_diff


@patch("kevin.models.claude.Anthropic")
def test_claude_client_reflection(mock_anthropic):
    """Test ClaudeClient reflection."""
    # Mock the API response
    mock_response = Mock()
    mock_response.content = [Mock()]
    mock_response.content[0].text = json.dumps(
        {
            "next_action": "Try a different approach",
            "lessons_learned": "The API was wrong",
            "should_retry": True,
        }
    )

    mock_client = Mock()
    mock_client.messages.create.return_value = mock_response
    mock_anthropic.return_value = mock_client

    client = ClaudeClient()
    context = ModelContext(task="test", repo_path="/tmp")

    reflection = client.reflect(context, "Failed to connect to API")
    assert reflection.next_action == "Try a different approach"
    assert reflection.lessons_learned == "The API was wrong"
    assert reflection.should_retry is True


def test_auto_repair_on_bad_json():
    """Test that ClaudeClient auto-repairs bad JSON responses."""
    client = ClaudeClient()

    # Test bad plan JSON
    bad_plan_response = "This is not JSON at all"
    plan = client._parse_plan_response(bad_plan_response)
    assert plan.files_to_read == ["README.md", "main.py"]  # Auto-repair default
    assert "Auto-generated" in plan.rationale

    # Test bad reflection JSON
    bad_reflection_response = "Also not JSON"
    reflection = client._parse_reflection_response(bad_reflection_response)
    assert "Auto-generated" in reflection.next_action
    assert "Auto-generated" in reflection.lessons_learned

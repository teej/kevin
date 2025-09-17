from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

from kevin.models import ClaudeClient, ModelContext
from kevin.sandbox.local import LocalSandbox


def create_toy_repo() -> Path:
    """Create a simple toy repository for testing."""
    temp_dir = Path(tempfile.mkdtemp())

    # Create a simple Python file with a bug
    main_py = temp_dir / "main.py"
    main_py.write_text("""
def add_numbers(a, b):
    return a + b

def multiply_numbers(a, b):
    return a * b

def main():
    result = add_numbers(5, 3)
    print(f"5 + 3 = {result}")
    
    # This has a bug - should be multiply_numbers
    result2 = add_numbers(2, 4)  # Should be multiply_numbers(2, 4)
    print(f"2 * 4 = {result2}")

if __name__ == "__main__":
    main()
""")

    # Create a test file
    test_py = temp_dir / "test_main.py"
    test_py.write_text("""
import main

def test_add_numbers():
    assert main.add_numbers(2, 3) == 5
    assert main.add_numbers(0, 0) == 0
    assert main.add_numbers(-1, 1) == 0

def test_multiply_numbers():
    assert main.multiply_numbers(2, 3) == 6
    assert main.multiply_numbers(0, 5) == 0
    assert main.multiply_numbers(-2, 3) == -6

def test_main_output():
    # This test will fail because of the bug in main()
    import io
    import sys
    from contextlib import redirect_stdout
    
    f = io.StringIO()
    with redirect_stdout(f):
        main.main()
    
    output = f.getvalue()
    assert "2 * 4 = 8" in output  # This will fail because it prints 6
""")

    # Create a simple README
    readme = temp_dir / "README.md"
    readme.write_text("""
# Toy Calculator

A simple calculator with addition and multiplication.

## Usage

```bash
python main.py
```

## Testing

```bash
uv run pytest test_main.py -v
```
""")

    return temp_dir


@patch("kevin.models.claude.Anthropic")
def test_toy_repo_integration(mock_anthropic):
    """Test the full integration with a toy repository."""
    # Create toy repo
    toy_repo = create_toy_repo()

    # Mock Claude responses
    mock_response_plan = Mock()
    mock_response_plan.content = [Mock()]
    mock_response_plan.content[0].text = """{
        "files_to_read": ["main.py", "test_main.py", "README.md"],
        "commands_to_run": ["uv run python main.py", "uv run pytest test_main.py -v"],
        "rationale": "I need to read the main files to understand the bug, then run the code and tests to see the failure"
    }"""

    mock_response_patch = Mock()
    mock_response_patch.content = [Mock()]
    mock_response_patch.content[0].text = """--- a/main.py
+++ b/main.py
@@ -10,7 +10,7 @@ def main():
     print(f"5 + 3 = {result}")
 
-    # This has a bug - should be multiply_numbers
-    result2 = add_numbers(2, 4)  # Should be multiply_numbers(2, 4)
+    # Fixed: now using multiply_numbers
+    result2 = multiply_numbers(2, 4)
     print(f"2 * 4 = {result2}")
 
 if __name__ == "__main__":
"""

    mock_client = Mock()
    mock_client.messages.create.side_effect = [mock_response_plan, mock_response_patch]
    mock_anthropic.return_value = mock_client

    # Initialize components
    client = ClaudeClient()
    sandbox = LocalSandbox(workdir=toy_repo)

    # Create context
    context = ModelContext(
        task="Fix the bug in main.py where 2*4 should equal 8 but currently shows 6",
        repo_path=str(toy_repo),
        test_command="uv run pytest test_main.py -v",
    )

    # Test plan generation
    plan = client.plan(context)
    assert "main.py" in plan.files_to_read
    assert "test_main.py" in plan.files_to_read
    assert "uv run python main.py" in plan.commands_to_run

    # Execute plan - read files
    for filepath in plan.files_to_read:
        content = sandbox.read_file(filepath)
        context.file_contents[filepath] = content

    # Execute plan - run commands
    for cmd in plan.commands_to_run:
        result = sandbox.exec(cmd, timeout=30)
        context.command_results.append(
            {
                "command": cmd,
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "duration_s": result.duration_s,
            }
        )

    # Test patch generation
    patch = client.propose_patch(context, plan)
    assert "multiply_numbers(2, 4)" in patch.unified_diff
    assert "--- a/main.py" in patch.unified_diff
    assert "+++ b/main.py" in patch.unified_diff

    # Test patch application - this should fail due to corrupt patch
    apply_result = sandbox.apply_patch(patch.unified_diff)
    assert apply_result.returncode != 0  # Patch should fail
    assert "corrupt patch" in apply_result.stderr

    # This demonstrates our enhanced patch failure handling
    # In a real scenario, the reflection step would analyze this failure
    # and suggest a recovery strategy like regenerating the patch

    # Clean up
    import shutil

    shutil.rmtree(toy_repo)


def test_sandbox_file_operations():
    """Test sandbox file read/write operations."""
    with tempfile.TemporaryDirectory() as temp_dir:
        sandbox = LocalSandbox(workdir=temp_dir)

        # Test write and read
        content = "print('hello world')"
        sandbox.write_file("test.py", content)

        read_content = sandbox.read_file("test.py")
        assert read_content == content

        # Test command execution
        result = sandbox.exec("uv run python test.py", timeout=30)
        assert result.returncode == 0
        assert "hello world" in result.stdout

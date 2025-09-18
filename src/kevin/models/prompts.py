from __future__ import annotations

from typing import Dict, List, Optional


class FilePreviewManager:
    """Manages file previews with configurable limits and expansion capabilities."""

    def __init__(self, default_max_lines: int = 50, default_context_lines: int = 5):
        self.default_max_lines = default_max_lines
        self.default_context_lines = default_context_lines
        self.expanded_files: Dict[str, int] = {}  # filepath -> expanded line count

    def truncate_file_content(
        self,
        content: str,
        filepath: str,
        max_lines: Optional[int] = None,
        context_lines: Optional[int] = None,
    ) -> str:
        """
        Truncate file content with smart preview and expansion tracking.

        Args:
            content: File content to truncate
            filepath: Path to the file (for expansion tracking)
            max_lines: Maximum lines to show (uses default if None)
            context_lines: Number of context lines around changes (uses default if None)

        Returns:
            Truncated content with expansion hints
        """
        if max_lines is None:
            max_lines = self.default_max_lines
        if context_lines is None:
            context_lines = self.default_context_lines

        lines = content.split("\n")
        if len(lines) <= max_lines:
            return content

        # Check if this file has been expanded
        if filepath in self.expanded_files:
            expanded_lines = self.expanded_files[filepath]
            if len(lines) <= expanded_lines:
                return content
            max_lines = expanded_lines

        first_half = max_lines // 2
        last_half = max_lines - first_half

        truncated = (
            lines[:first_half]
            + [f"... ({len(lines) - max_lines} lines omitted) ..."]
            + [f"[SHOW_MORE:{filepath}:{len(lines)}]"]  # Expansion hint
            + lines[-last_half:]
        )
        return "\n".join(truncated)

    def expand_file_preview(self, filepath: str, target_lines: int) -> None:
        """Mark a file for expanded preview."""
        self.expanded_files[filepath] = target_lines

    def reset_expansions(self) -> None:
        """Reset all file expansions."""
        self.expanded_files.clear()

    def get_expansion_hints(self, content: str) -> List[str]:
        """Extract expansion hints from content."""
        import re

        pattern = r"\[SHOW_MORE:([^:]+):(\d+)\]"
        matches = re.findall(pattern, content)
        return [f"{filepath}:{lines}" for filepath, lines in matches]


def truncate_file_content(content: str, max_lines: int = 50) -> str:
    """Legacy function for backward compatibility."""
    lines = content.split("\n")
    if len(lines) <= max_lines:
        return content

    first_half = max_lines // 2
    last_half = max_lines - first_half

    truncated = (
        lines[:first_half]
        + [f"... ({len(lines) - max_lines} lines omitted) ..."]
        + lines[-last_half:]
    )
    return "\n".join(truncated)


def format_file_contents(
    file_contents: dict[str, str],
    max_lines: int = 50,
    preview_manager: Optional[FilePreviewManager] = None,
) -> str:
    """Format file contents for model consumption with enhanced truncation and expansion hints."""
    if not file_contents:
        return "No files read yet."

    formatted = []
    for filepath, content in file_contents.items():
        if preview_manager:
            truncated = preview_manager.truncate_file_content(content, filepath, max_lines)
        else:
            truncated = truncate_file_content(content, max_lines)
        formatted.append(f"=== {filepath} ===\n{truncated}\n")

    return "\n".join(formatted)


def format_file_contents_with_expansion(
    file_contents: dict[str, str], preview_manager: FilePreviewManager, max_lines: int = 50
) -> str:
    """Format file contents with expansion management and hints."""
    if not file_contents:
        return "No files read yet."

    formatted = []
    expansion_hints = []

    for filepath, content in file_contents.items():
        truncated = preview_manager.truncate_file_content(content, filepath, max_lines)
        formatted.append(f"=== {filepath} ===\n{truncated}\n")

        # Collect expansion hints
        hints = preview_manager.get_expansion_hints(truncated)
        expansion_hints.extend(hints)

    result = "\n".join(formatted)

    # Add expansion summary if there are hints
    if expansion_hints:
        result += "\n\n[EXPANSION_HINTS]\n"
        for hint in expansion_hints:
            result += f"- {hint}\n"
        result += "\nUse 'show me more of <filepath>' to expand file previews.\n"

    return result


def format_command_results(command_results: list[dict]) -> str:
    """Format command execution results for model consumption."""
    if not command_results:
        return "No commands executed yet."

    formatted = []
    for i, result in enumerate(command_results, 1):
        cmd = result.get("command", "unknown")
        rc = result.get("returncode", -1)
        stdout = result.get("stdout", "").strip()
        stderr = result.get("stderr", "").strip()

        formatted.append(f"Command {i}: {cmd}")
        formatted.append(f"Exit code: {rc}")
        if stdout:
            formatted.append(f"Output: {stdout}")
        if stderr:
            formatted.append(f"Error: {stderr}")
        formatted.append("")

    return "\n".join(formatted)


PLAN_PROMPT = """You are an AI engineer working on a software task. Your job is to create a plan for approaching this task.

Task: {task}
Repository: {repo_path}
Test command: {test_command}

Project Information:
- Has src/ layout: {has_src_layout}
- Has tests/ directory: {has_tests_dir}
- Has pyproject.toml: {has_pyproject}
- Has setup.py: {has_setup_py}
- Package directories found: {package_dirs}
- Test files found: {test_files}

Based on the task description and project information above, create a plan that includes:
1. Which files you need to read to understand the codebase
2. Which commands you need to run to gather information or test your changes
3. Your reasoning for this approach

IMPORTANT: Only suggest files that actually exist based on the project information above. 
Common files to consider:
- Configuration: pyproject.toml, setup.py, README.md
- Package code: Use the package_dirs list above
- Tests: Use the test_files list above
- Main entry points: Look for main.py, __main__.py, or similar

Respond with a JSON object in this exact format:
{{
    "files_to_read": ["path/to/file1.py", "path/to/file2.js"],
    "commands_to_run": ["ls -la", "git status", "uv run pytest"],
    "rationale": "I need to read the main files to understand the structure, then run tests to see current state"
}}

Be specific about file paths and commands. Focus on understanding the codebase first before making changes."""


PATCH_PROMPT = """You are an AI engineer implementing a fix for a software task. Based on the context below, propose a unified diff patch.

Task: {task}

File Contents:
{file_contents}

Command Results:
{command_results}

Create a unified diff patch that implements the requested changes. The patch MUST:
1. Start with "diff --git a/path b/path" (git-style) OR "--- a/path" and "+++ b/path" (unified)
2. Use repo-relative paths only (no absolute paths)
3. Have LF line endings (no CRLF)
4. Include sufficient context lines for reliable application
5. Be minimal and focused on the specific changes needed

CRITICAL: Output ONLY the patch content. No markdown fences, no prose, no explanations.
The patch must be immediately applicable with git apply.

Example format:
diff --git a/src/file.py b/src/file.py
index 1234567..abcdefg 100644
--- a/src/file.py
+++ b/src/file.py
@@ -10,7 +10,7 @@ def function():
     existing_code()
 
-    old_code()
+    new_code()
     more_code()
"""


REFLECT_PROMPT = """You are an AI engineer reflecting on a failed attempt to complete a task. Analyze what went wrong and determine the next steps.

Task: {task}

What happened:
{fail_logs}

Context:
{context}

Based on the failure, provide:
1. What you learned from this attempt
2. What the next action should be
3. Whether you should retry or take a different approach
4. If this was a patch application failure, suggest a recovery strategy

Respond with a JSON object in this exact format:
{{
    "next_action": "specific action to take next",
    "lessons_learned": "what you learned from the failure",
    "should_retry": true,
    "recovery_strategy": "regenerate_patch|direct_edit|incremental_patches|reread_files|file_edits|null"
}}

Recovery strategies for patch failures:
- "regenerate_patch": Patch format is correct but context lines don't match - regenerate with more context
- "direct_edit": Patch format is malformed or too complex - switch to direct file editing
- "incremental_patches": Change is too complex - break into smaller, targeted patches
- "reread_files": Files may have changed - re-read current file state and regenerate
- "file_edits": Switch to JSON file edits format for maximum reliability
- null: Not a patch failure or no specific strategy needed"""


REFLECT_PATCH_FAILURE_PROMPT = """You are an AI engineer reflecting on a failed patch application. Analyze the patch failure and determine the best recovery strategy.

Task: {task}

Patch Application Failed:
{error_details}

Context:
{context}

Common patch failure causes and solutions:
1. Context line mismatch: The file has changed since patch was generated
   → Solution: "reread_files" - re-read current file state and regenerate patch
2. Insufficient context lines: Patch doesn't have enough context to match
   → Solution: "regenerate_patch" - generate new patch with more context lines
3. Malformed patch format: Patch syntax is incorrect
   → Solution: "direct_edit" - switch to direct file editing instead of patches
4. Complex changes: Patch tries to change too much at once
   → Solution: "incremental_patches" - break into smaller, focused patches
5. File path issues: Incorrect file paths in the patch
   → Solution: "regenerate_patch" - fix file paths and regenerate
6. Persistent patch failures: Multiple strategies have failed
   → Solution: "file_edits" - switch to JSON file edits format for maximum reliability

Analyze the specific error and determine the best recovery strategy.

Respond with a JSON object in this exact format:
{{
    "next_action": "specific recovery action to take",
    "lessons_learned": "what caused the patch failure",
    "should_retry": true,
    "recovery_strategy": "regenerate_patch|direct_edit|incremental_patches|reread_files|file_edits"
}}"""

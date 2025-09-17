from __future__ import annotations

from anthropic import Anthropic

from .prompts import (
    PATCH_PROMPT,
    PLAN_PROMPT,
    REFLECT_PATCH_FAILURE_PROMPT,
    REFLECT_PROMPT,
    FilePreviewManager,
    format_command_results,
    format_file_contents_with_expansion,
)
from .types import ModelContext, Patch, Plan, Reflection
from .validation import DiffValidator, JSONValidator


class ClaudeClient:
    """Claude Sonnet client for AI engineering tasks."""

    def __init__(self, api_key: str | None = None, model: str = "claude-3-5-sonnet-20241022"):
        self.client = Anthropic(api_key=api_key)
        self.model = model
        self.json_validator = JSONValidator()
        self.diff_validator = DiffValidator()
        self.preview_manager = FilePreviewManager()

    def plan(self, context: ModelContext) -> Plan:
        """Generate a plan for approaching the task."""
        prompt = PLAN_PROMPT.format(
            task=context.task,
            repo_path=context.repo_path,
            test_command=context.test_command or "none detected",
            has_src_layout=context.has_src_layout,
            has_tests_dir=context.has_tests_dir,
            has_pyproject=context.has_pyproject,
            has_setup_py=context.has_setup_py,
            package_dirs=", ".join(context.package_dirs) if context.package_dirs else "none found",
            test_files=", ".join(context.test_files) if context.test_files else "none found",
        )

        response = self._call_claude(prompt, max_tokens=1000)
        return self._parse_plan_response(response)

    def propose_patch(self, context: ModelContext, plan: Plan) -> Patch:
        """Propose a unified diff patch based on context and plan."""
        # Use enhanced file formatting with expansion support
        file_contents = format_file_contents_with_expansion(
            context.file_contents, self.preview_manager, context.preview_max_lines
        )
        command_results = format_command_results(context.command_results)

        prompt = PATCH_PROMPT.format(
            task=context.task, file_contents=file_contents, command_results=command_results
        )

        response = self._call_claude(prompt, max_tokens=context.max_tokens)
        return self._parse_patch_response(response)

    def reflect(self, context: ModelContext, fail_logs: str) -> Reflection:
        """Reflect on failures and determine next steps."""
        context_str = (
            f"Files: {list(context.file_contents.keys())}\n"
            f"Commands: {len(context.command_results)} executed"
        )

        prompt = REFLECT_PROMPT.format(task=context.task, fail_logs=fail_logs, context=context_str)

        response = self._call_claude(prompt, max_tokens=1000)
        return self._parse_reflection_response(response)

    def reflect_on_patch_failure(
        self, context: ModelContext, error_details: str, context_str: str
    ) -> Reflection:
        """Reflect specifically on patch application failures."""
        prompt = REFLECT_PATCH_FAILURE_PROMPT.format(
            task=context.task, error_details=error_details, context=context_str
        )

        response = self._call_claude(prompt, max_tokens=1000)
        return self._parse_reflection_response(response)

    def _call_claude(self, prompt: str, max_tokens: int = 1000) -> str:
        """Make a call to Claude API with error handling."""
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text
        except Exception as e:
            raise RuntimeError(f"Claude API call failed: {e}") from e

    def _parse_plan_response(self, response: str) -> Plan:
        """Parse and validate plan response from Claude with enhanced validation and auto-repair."""
        return self.json_validator.validate_and_repair_json(response, "plan", Plan)

    def _parse_patch_response(self, response: str) -> Patch:
        """Parse and validate patch response with enhanced diff validation and auto-repair."""
        repaired_diff = self.diff_validator.validate_and_repair_diff(response)
        return Patch(unified_diff=repaired_diff)

    def _parse_reflection_response(self, response: str) -> Reflection:
        """Parse and validate reflection response with enhanced validation and auto-repair."""
        return self.json_validator.validate_and_repair_json(response, "reflection", Reflection)

    def expand_file_preview(self, filepath: str, target_lines: int = 1000) -> None:
        """Expand preview for a specific file."""
        self.preview_manager.expand_file_preview(filepath, target_lines)

    def reset_preview_expansions(self) -> None:
        """Reset all file preview expansions."""
        self.preview_manager.reset_expansions()

    def get_expansion_hints(self, file_contents: dict[str, str]) -> list[str]:
        """Get expansion hints for all files."""
        hints = []
        for filepath, content in file_contents.items():
            file_hints = self.preview_manager.get_expansion_hints(content)
            hints.extend([f"{filepath}: {hint}" for hint in file_hints])
        return hints

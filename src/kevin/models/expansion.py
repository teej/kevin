from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from .prompts import FilePreviewManager


class ExpansionProcessor:
    """Processes expansion requests and manages file preview state."""

    def __init__(self, preview_manager: FilePreviewManager):
        self.preview_manager = preview_manager
        self.expansion_patterns = [
            r"show me more of (.+)",
            r"expand (.+)",
            r"show more (.+)",
            r"full content of (.+)",
            r"complete (.+)",
        ]

    def process_expansion_request(
        self, request: str, available_files: List[str]
    ) -> Tuple[bool, str, Optional[str]]:
        """
        Process an expansion request.

        Args:
            request: User request text
            available_files: List of available file paths

        Returns:
            Tuple of (is_expansion_request, response_message, expanded_file)
        """
        request_lower = request.lower().strip()

        for pattern in self.expansion_patterns:
            match = re.search(pattern, request_lower)
            if match:
                file_reference = match.group(1).strip()

                # Try to find matching file
                matched_file = self._find_matching_file(file_reference, available_files)

                if matched_file:
                    # Expand the file preview
                    self.preview_manager.expand_file_preview(
                        matched_file, 1000
                    )  # Large number for "full" content
                    return True, f"Expanded preview for {matched_file}", matched_file
                else:
                    return (
                        True,
                        f"File '{file_reference}' not found. Available files: {', '.join(available_files)}",
                        None,
                    )

        return False, "", None

    def _find_matching_file(self, file_reference: str, available_files: List[str]) -> Optional[str]:
        """Find the best matching file for a given reference."""
        file_reference = file_reference.strip("\"'")

        # Exact match
        if file_reference in available_files:
            return file_reference

        # Filename match (without path)
        filename = file_reference.split("/")[-1]
        for file_path in available_files:
            if file_path.endswith(filename):
                return file_path

        # Partial match (more strict)
        for file_path in available_files:
            if (
                file_reference.lower() in file_path.lower() and len(file_reference) > 3
            ):  # Avoid matching very short strings
                return file_path

        # Extension match (only if filename part matches)
        if "." in file_reference:
            ext = file_reference.split(".")[-1]
            filename_part = file_reference.split(".")[0]
            for file_path in available_files:
                if file_path.endswith(f".{ext}") and filename_part in file_path.split("/")[-1]:
                    return file_path

        # No match found
        return None

    def get_expansion_summary(self, file_contents: Dict[str, str]) -> str:
        """Get a summary of expansion opportunities."""
        summary_lines = []

        for filepath, content in file_contents.items():
            lines = content.split("\n")
            if len(lines) > self.preview_manager.default_max_lines:
                summary_lines.append(
                    f"- {filepath}: {len(lines)} lines (showing {self.preview_manager.default_max_lines})"
                )

        if summary_lines:
            return "Files with truncated content:\n" + "\n".join(summary_lines)
        else:
            return "All files are fully displayed."

    def reset_expansions(self) -> str:
        """Reset all expansions and return confirmation message."""
        self.preview_manager.reset_expansions()
        return "All file previews reset to default size."

    def set_file_preview_size(self, filepath: str, max_lines: int) -> str:
        """Set specific preview size for a file."""
        self.preview_manager.expand_file_preview(filepath, max_lines)
        return f"Set preview size for {filepath} to {max_lines} lines."

    def get_current_expansions(self) -> Dict[str, int]:
        """Get current expansion state."""
        return self.preview_manager.expanded_files.copy()


class SmartTruncation:
    """Smart truncation that preserves important content."""

    def __init__(self, preview_manager: FilePreviewManager):
        self.preview_manager = preview_manager

    def truncate_with_context(
        self,
        content: str,
        filepath: str,
        max_lines: int = 50,
        preserve_imports: bool = True,
        preserve_functions: bool = True,
        preserve_classes: bool = True,
    ) -> str:
        """
        Smart truncation that preserves important code structures.

        Args:
            content: File content
            filepath: File path
            max_lines: Maximum lines to show
            preserve_imports: Whether to preserve import statements
            preserve_functions: Whether to preserve function definitions
            preserve_classes: Whether to preserve class definitions

        Returns:
            Smartly truncated content
        """
        lines = content.split("\n")
        if len(lines) <= max_lines:
            return content

        # Identify important lines
        important_lines = set()

        if preserve_imports:
            for i, line in enumerate(lines):
                if line.strip().startswith(("import ", "from ")):
                    important_lines.add(i)

        if preserve_functions:
            for i, line in enumerate(lines):
                if re.match(r"^\s*def\s+\w+", line):
                    important_lines.add(i)

        if preserve_classes:
            for i, line in enumerate(lines):
                if re.match(r"^\s*class\s+\w+", line):
                    important_lines.add(i)

        # If we have too many important lines, fall back to regular truncation
        if len(important_lines) > max_lines * 0.8:
            return self.preview_manager.truncate_file_content(content, filepath, max_lines)

        # Build truncated content with important lines
        result_lines = []
        added_lines = set()

        # Add important lines with context
        for line_idx in sorted(important_lines):
            if line_idx not in added_lines:
                # Add context before
                start = max(0, line_idx - 2)
                end = min(len(lines), line_idx + 3)

                for i in range(start, end):
                    if i not in added_lines:
                        result_lines.append(lines[i])
                        added_lines.add(i)

        # If we still have room, add more content
        if len(result_lines) < max_lines:
            remaining_lines = max_lines - len(result_lines)
            # Add from the beginning and end
            first_half = remaining_lines // 2
            last_half = remaining_lines - first_half

            for i in range(min(first_half, len(lines))):
                if i not in added_lines:
                    result_lines.insert(i, lines[i])
                    added_lines.add(i)

            for i in range(max(0, len(lines) - last_half), len(lines)):
                if i not in added_lines:
                    result_lines.append(lines[i])
                    added_lines.add(i)

        # Sort lines by original order
        result_lines = [lines[i] for i in sorted(added_lines)]

        # Add truncation indicator if needed
        if len(result_lines) < len(lines):
            truncated = (
                result_lines[: len(result_lines) // 2]
                + [f"... ({len(lines) - len(result_lines)} lines omitted) ..."]
                + [f"[SHOW_MORE:{filepath}:{len(lines)}]"]
                + result_lines[len(result_lines) // 2 :]
            )
            return "\n".join(truncated)

        return "\n".join(result_lines)

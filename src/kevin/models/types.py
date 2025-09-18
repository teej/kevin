from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, validator


class RecoveryStrategy(str, Enum):
    """Recovery strategies for patch application failures."""

    REGENERATE_PATCH = "regenerate_patch"
    DIRECT_EDIT = "direct_edit"
    INCREMENTAL_PATCHES = "incremental_patches"
    REREAD_FILES = "reread_files"
    FILE_EDITS = "file_edits"


class Plan(BaseModel):
    """Model's plan for approaching a task."""

    files_to_read: list[str] = Field(description="List of file paths to read")
    commands_to_run: list[str] = Field(description="List of shell commands to execute")
    rationale: str = Field(description="Explanation of the approach and reasoning")

    @validator("files_to_read")
    def validate_files(cls, v):
        if not v:
            raise ValueError("Must specify at least one file to read")
        return v

    @validator("commands_to_run")
    def validate_commands(cls, v):
        if not v:
            raise ValueError("Must specify at least one command to run")
        return v


class FileEdit(BaseModel):
    """A single file edit operation."""

    path: str = Field(description="File path relative to repo root")
    mode: str = Field(description="Edit mode: 'replace', 'create', 'delete'")
    content: str = Field(default="", description="New file content (for replace/create)")


class Patch(BaseModel):
    """Unified diff patch proposed by the model."""

    unified_diff: str = Field(description="Unified diff format patch")

    @validator("unified_diff")
    def validate_diff_format(cls, v):
        # Basic validation for unified diff format
        if not v.strip():
            raise ValueError("Patch cannot be empty")

        # Check for unified diff markers
        lines = v.strip().split("\n")
        if not any(line.startswith("---") for line in lines):
            raise ValueError("Patch must contain '---' markers for unified diff format")
        if not any(line.startswith("+++") for line in lines):
            raise ValueError("Patch must contain '+++' markers for unified diff format")

        return v


class FileEdits(BaseModel):
    """Alternative to patches: direct file edits."""

    edits: list[FileEdit] = Field(description="List of file edits to apply")

    @validator("edits")
    def validate_edits(cls, v):
        if not v:
            raise ValueError("Must specify at least one file edit")
        return v


class Reflection(BaseModel):
    """Model's reflection on what went wrong and next steps."""

    next_action: str = Field(description="What to do next")
    lessons_learned: str = Field(description="What was learned from the failure")
    should_retry: bool = Field(default=True, description="Whether to retry the task")
    recovery_strategy: Optional[RecoveryStrategy] = Field(
        default=None, description="Specific recovery strategy for patch failures"
    )


class ModelContext(BaseModel):
    """Context passed to the model for decision making."""

    task: str = Field(description="The task description")
    repo_path: str = Field(description="Path to the repository")
    file_contents: dict[str, str] = Field(
        default_factory=dict, description="Contents of read files"
    )
    command_results: list[dict] = Field(
        default_factory=list, description="Results of executed commands"
    )
    test_command: str | None = Field(default=None, description="Detected test command")
    has_src_layout: bool = Field(default=False, description="Whether src/ directory exists")
    has_tests_dir: bool = Field(default=False, description="Whether tests/ directory exists")
    has_pyproject: bool = Field(default=False, description="Whether pyproject.toml exists")
    has_setup_py: bool = Field(default=False, description="Whether setup.py exists")
    package_dirs: list[str] = Field(default_factory=list, description="Package directories found")
    test_files: list[str] = Field(default_factory=list, description="Test files found")
    max_tokens: int = Field(default=4000, description="Maximum tokens for model response")
    preview_max_lines: int = Field(default=50, description="Maximum lines to show in file previews")
    enable_smart_truncation: bool = Field(
        default=True, description="Whether to use smart truncation"
    )


class CmdResult(BaseModel):
    """Result of a command execution."""

    command: str = Field(description="The command that was executed")
    returncode: int = Field(description="Exit code of the command")
    stdout: str = Field(description="Standard output")
    stderr: str = Field(description="Standard error")
    duration_s: float = Field(description="Execution time in seconds")

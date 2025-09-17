from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class StepType(str, Enum):
    """Types of steps in the agent workflow."""

    PLAN = "plan"
    FETCH_FILES = "fetch_files"
    PROPOSE_PATCH = "propose_patch"
    APPLY = "apply"
    RUN_TESTS = "run_tests"
    REFLECT = "reflect"


class StepStatus(str, Enum):
    """Status of a step execution."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class StepResult(BaseModel):
    """Result of a single step execution."""

    step_type: StepType
    status: StepStatus
    output: Optional[str] = None
    error: Optional[str] = None
    duration_s: Optional[float] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class LoopState(BaseModel):
    """State management for the agent execution loop."""

    # Loop configuration
    max_steps: int = Field(default=15, description="Maximum number of steps allowed")
    current_step: int = Field(default=0, description="Current step number (0-based)")
    dry_run: bool = Field(default=False, description="Whether to run in dry-run mode")

    # Execution state
    is_completed: bool = Field(
        default=False, description="Whether the loop has completed successfully"
    )
    is_failed: bool = Field(default=False, description="Whether the loop has failed permanently")
    should_stop: bool = Field(default=False, description="Whether to stop the loop")

    # Step history
    step_results: List[StepResult] = Field(
        default_factory=list, description="History of step results"
    )

    # Current iteration state
    current_plan: Optional[Any] = None  # Will be Plan object
    current_patch: Optional[Any] = None  # Will be Patch object
    test_output: Optional[str] = None  # Last test output for reflection

    # Metrics
    total_duration_s: float = Field(default=0.0, description="Total execution time")
    tokens_used: int = Field(default=0, description="Total tokens consumed")

    def can_continue(self) -> bool:
        """Check if the loop can continue."""
        return (
            not self.is_completed
            and not self.is_failed
            and not self.should_stop
            and self.current_step < self.max_steps
        )

    def add_step_result(self, result: StepResult) -> None:
        """Add a step result to the history."""
        self.step_results.append(result)
        if result.duration_s:
            self.total_duration_s += result.duration_s

    def get_last_step_result(self) -> Optional[StepResult]:
        """Get the last step result."""
        return self.step_results[-1] if self.step_results else None

    def get_last_failed_step(self) -> Optional[StepResult]:
        """Get the last failed step."""
        for result in reversed(self.step_results):
            if result.status == StepStatus.FAILED:
                return result
        return None

    def get_test_output_tail(self, lines: int = 200) -> str:
        """Get the last N lines of test output."""
        if not self.test_output:
            return ""

        output_lines = self.test_output.split("\n")
        if len(output_lines) <= lines:
            return self.test_output

        return "\n".join(output_lines[-lines:])

    def mark_completed(self) -> None:
        """Mark the loop as completed successfully."""
        self.is_completed = True
        self.should_stop = True

    def mark_failed(self, error: str) -> None:
        """Mark the loop as failed."""
        self.is_failed = True
        self.should_stop = True
        # Add a final failed step result
        self.add_step_result(
            StepResult(step_type=StepType.REFLECT, status=StepStatus.FAILED, error=error)
        )

    def increment_step(self) -> None:
        """Increment the current step counter."""
        self.current_step += 1

    def get_step_type_for_iteration(self) -> StepType:
        """Get the step type for the current iteration based on step number."""
        step_in_cycle = self.current_step % 6
        step_types = [
            StepType.PLAN,
            StepType.FETCH_FILES,
            StepType.PROPOSE_PATCH,
            StepType.APPLY,
            StepType.RUN_TESTS,
            StepType.REFLECT,
        ]
        return step_types[step_in_cycle]

    def get_iteration_number(self) -> int:
        """Get the current iteration number (0-based)."""
        return self.current_step // 6

    def is_first_iteration(self) -> bool:
        """Check if this is the first iteration."""
        return self.get_iteration_number() == 0

    def get_summary(self) -> str:
        """Get a summary of the current loop state."""
        iteration = self.get_iteration_number()
        step_in_cycle = self.current_step % 6
        step_type = self.get_step_type_for_iteration()

        return (
            f"Iteration {iteration + 1}, Step {step_in_cycle + 1}/6 ({step_type.value}) - "
            f"Total steps: {self.current_step}/{self.max_steps}"
        )

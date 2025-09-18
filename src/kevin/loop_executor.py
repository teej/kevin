from __future__ import annotations

import time

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from .models.claude import ClaudeClient
from .models.loop_state import LoopState, StepResult, StepStatus, StepType
from .models.types import ModelContext
from .sandbox.local import LocalSandbox


class LoopExecutor:
    """Executes the agent workflow loop with state management."""

    def __init__(
        self,
        client: ClaudeClient,
        sandbox: LocalSandbox,
        context: ModelContext,
        loop_state: LoopState,
        console: Console | None = None,
    ):
        self.client = client
        self.sandbox = sandbox
        self.context = context
        self.loop_state = loop_state
        self.console = console or Console()

    def execute_loop(self) -> LoopState:
        """Execute the complete agent workflow loop."""
        self.console.rule("[bold]Starting Agent Loop")
        self.console.print(f"[bold]Max steps:[/bold] {self.loop_state.max_steps}")
        self.console.print(f"[bold]Dry run:[/bold] {self.loop_state.dry_run}")

        while self.loop_state.can_continue():
            try:
                self._execute_single_iteration()
            except Exception as e:
                self.console.print(f"[red]Fatal error in iteration:[/red] {e}")
                self.loop_state.mark_failed(str(e))
                break

        self._print_final_summary()
        return self.loop_state

    def _execute_single_iteration(self) -> None:
        """Execute a single iteration of the 6-step workflow."""
        iteration = self.loop_state.get_iteration_number()
        self.console.print(f"\n[bold blue]=== Iteration {iteration + 1} ===[/bold blue]")

        # Execute each step in the workflow
        self._execute_step(StepType.PLAN)
        if not self.loop_state.can_continue():
            return

        self._execute_step(StepType.FETCH_FILES)
        if not self.loop_state.can_continue():
            return

        self._execute_step(StepType.PROPOSE_PATCH)
        if not self.loop_state.can_continue():
            return

        self._execute_step(StepType.APPLY)
        if not self.loop_state.can_continue():
            return

        self._execute_step(StepType.RUN_TESTS)
        if not self.loop_state.can_continue():
            return

        self._execute_step(StepType.REFLECT)

        self.loop_state.increment_step()

    def _execute_step(self, step_type: StepType) -> None:
        """Execute a single step of the workflow."""
        start_time = time.time()

        with Progress(
            SpinnerColumn(),
            TextColumn(f"[bold]{step_type.value}..."),
            console=self.console,
            transient=True,
        ) as progress:
            progress.add_task("executing", total=None)

            try:
                if step_type == StepType.PLAN:
                    result = self._execute_plan_step()
                elif step_type == StepType.FETCH_FILES:
                    result = self._execute_fetch_files_step()
                elif step_type == StepType.PROPOSE_PATCH:
                    result = self._execute_propose_patch_step()
                elif step_type == StepType.APPLY:
                    result = self._execute_apply_step()
                elif step_type == StepType.RUN_TESTS:
                    result = self._execute_run_tests_step()
                elif step_type == StepType.REFLECT:
                    result = self._execute_reflect_step()
                else:
                    raise ValueError(f"Unknown step type: {step_type}")

                duration = time.time() - start_time
                result.duration_s = duration
                self.loop_state.add_step_result(result)

                self._print_step_result(result)

            except Exception as e:
                duration = time.time() - start_time
                error_result = StepResult(
                    step_type=step_type, status=StepStatus.FAILED, error=str(e), duration_s=duration
                )
                self.loop_state.add_step_result(error_result)
                self._print_step_result(error_result)

                # Decide whether to continue or fail
                if step_type in [StepType.PLAN, StepType.PROPOSE_PATCH]:
                    # Critical steps - fail the loop
                    self.loop_state.mark_failed(f"Critical step failed: {step_type.value}")
                # Other steps can be retried in next iteration

    def _execute_plan_step(self) -> StepResult:
        """Execute the plan step."""
        try:
            plan = self.client.plan(self.context)
            self.loop_state.current_plan = plan

            output = f"Plan generated: {plan.rationale}\n"
            output += f"Files to read: {', '.join(plan.files_to_read)}\n"
            output += f"Commands to run: {', '.join(plan.commands_to_run)}"

            return StepResult(step_type=StepType.PLAN, status=StepStatus.COMPLETED, output=output)
        except Exception as e:
            return StepResult(step_type=StepType.PLAN, status=StepStatus.FAILED, error=str(e))

    def _execute_fetch_files_step(self) -> StepResult:
        """Execute the fetch files step."""
        if not self.loop_state.current_plan:
            return StepResult(
                step_type=StepType.FETCH_FILES, status=StepStatus.FAILED, error="No plan available"
            )

        try:
            plan = self.loop_state.current_plan
            fetched_files = []
            failed_files = []

            for filepath in plan.files_to_read:
                try:
                    content = self.sandbox.read_file(filepath)
                    self.context.file_contents[filepath] = content
                    fetched_files.append(filepath)
                except Exception as e:
                    failed_files.append(f"{filepath}: {e}")

            # Also run any commands from the plan
            for cmd in plan.commands_to_run:
                try:
                    result = self.sandbox.exec(cmd, timeout=120)
                    self.context.command_results.append(
                        {
                            "command": cmd,
                            "returncode": result.returncode,
                            "stdout": result.stdout,
                            "stderr": result.stderr,
                            "duration_s": result.duration_s,
                        }
                    )
                except Exception as e:
                    self.context.command_results.append(
                        {
                            "command": cmd,
                            "returncode": -1,
                            "stdout": "",
                            "stderr": str(e),
                            "duration_s": 0.0,
                        }
                    )

            output = f"Fetched {len(fetched_files)} files successfully"
            if failed_files:
                output += f"\nFailed to fetch: {', '.join(failed_files)}"

            status = StepStatus.COMPLETED if fetched_files else StepStatus.FAILED
            return StepResult(step_type=StepType.FETCH_FILES, status=status, output=output)
        except Exception as e:
            return StepResult(
                step_type=StepType.FETCH_FILES, status=StepStatus.FAILED, error=str(e)
            )

    def _execute_propose_patch_step(self) -> StepResult:
        """Execute the propose patch step."""
        try:
            if not self.loop_state.current_plan:
                return StepResult(
                    step_type=StepType.PROPOSE_PATCH,
                    status=StepStatus.FAILED,
                    error="No plan available",
                )

            patch = self.client.propose_patch(self.context, self.loop_state.current_plan)
            self.loop_state.current_patch = patch

            output = f"Patch generated ({len(patch.unified_diff)} chars)"
            if len(patch.unified_diff) > 200:
                output += f"\nPreview: {patch.unified_diff[:200]}..."
            else:
                output += f"\nPatch: {patch.unified_diff}"

            return StepResult(
                step_type=StepType.PROPOSE_PATCH, status=StepStatus.COMPLETED, output=output
            )
        except Exception as e:
            return StepResult(
                step_type=StepType.PROPOSE_PATCH, status=StepStatus.FAILED, error=str(e)
            )

    def _execute_apply_step(self) -> StepResult:
        """Execute the apply patch step with enhanced error handling."""
        if not self.loop_state.current_patch:
            return StepResult(
                step_type=StepType.APPLY, status=StepStatus.FAILED, error="No patch available"
            )

        if self.loop_state.dry_run:
            return StepResult(
                step_type=StepType.APPLY,
                status=StepStatus.COMPLETED,
                output="[DRY RUN] Patch would be applied here",
            )

        try:
            # Apply the patch using the sandbox
            patch = self.loop_state.current_patch
            result = self.sandbox.apply_patch(patch.unified_diff)

            if result.returncode == 0:
                return StepResult(
                    step_type=StepType.APPLY,
                    status=StepStatus.COMPLETED,
                    output="Patch applied successfully",
                )
            else:
                # Enhanced error information for reflection
                first_20_lines = "\n".join(patch.unified_diff.split("\n")[:20])
                stderr_tail = result.stderr[-2000:] if len(result.stderr) > 2000 else result.stderr

                error_details = {
                    "git_stderr": stderr_tail,
                    "git_exit_code": result.returncode,
                    "patch_first_20_lines": first_20_lines,
                    "patch_total_length": len(patch.unified_diff),
                    "stdout": result.stdout,
                }

                # Create detailed error message for reflection
                detailed_error = "PATCH APPLICATION FAILED\n"
                detailed_error += f"Git exit code: {result.returncode}\n"
                detailed_error += f"Git stderr (last 2000 chars): {stderr_tail}\n"
                detailed_error += f"Patch preview (first 20 lines):\n{first_20_lines}\n"
                if result.stdout:
                    detailed_error += f"Git stdout: {result.stdout}\n"

                return StepResult(
                    step_type=StepType.APPLY,
                    status=StepStatus.FAILED,
                    error=detailed_error,
                    output=f"Error details: {error_details}",  # Pass to reflection
                )
        except Exception as e:
            return StepResult(step_type=StepType.APPLY, status=StepStatus.FAILED, error=str(e))

    def _execute_run_tests_step(self) -> StepResult:
        """Execute the run tests step."""
        if not self.context.test_command:
            return StepResult(
                step_type=StepType.RUN_TESTS,
                status=StepStatus.SKIPPED,
                output="No test command available",
            )

        try:
            result = self.sandbox.exec(self.context.test_command, timeout=300)
            self.loop_state.test_output = result.stdout + result.stderr

            if result.returncode == 0:
                return StepResult(
                    step_type=StepType.RUN_TESTS,
                    status=StepStatus.COMPLETED,
                    output="All tests passed",
                )
            else:
                return StepResult(
                    step_type=StepType.RUN_TESTS,
                    status=StepStatus.FAILED,
                    output=f"Tests failed (rc={result.returncode})",
                )
        except Exception as e:
            return StepResult(step_type=StepType.RUN_TESTS, status=StepStatus.FAILED, error=str(e))

    def _execute_reflect_step(self) -> StepResult:
        """Execute the reflect step with enhanced patch failure handling."""
        try:
            # Check if there was a patch application failure in this iteration
            apply_failure = None
            for result in reversed(self.loop_state.step_results):
                if result.step_type == StepType.APPLY and result.status == StepStatus.FAILED:
                    apply_failure = result
                    break

            if apply_failure:
                # Use patch failure specific reflection
                error_details = apply_failure.output or apply_failure.error
                patch_preview = (
                    self.loop_state.current_patch.unified_diff[:200]
                    if self.loop_state.current_patch
                    else "None"
                )
                context_str = (
                    f"Files: {list(self.context.file_contents.keys())}\n"
                    f"Commands: {len(self.context.command_results)} executed\n"
                    f"Last patch preview: {patch_preview}..."
                )

                reflection = self.client.reflect_on_patch_failure(
                    self.context, error_details, context_str
                )
            else:
                # Use standard reflection with test output
                test_output_tail = self.loop_state.get_test_output_tail(200)

                if not test_output_tail:
                    return StepResult(
                        step_type=StepType.REFLECT,
                        status=StepStatus.COMPLETED,
                        output="No test output to reflect on",
                    )

                reflection = self.client.reflect(self.context, test_output_tail)

            # Format output with recovery strategy if available
            output = f"Reflection: {reflection.next_action}\n"
            output += f"Lessons learned: {reflection.lessons_learned}\n"
            output += f"Should retry: {reflection.should_retry}"
            if reflection.recovery_strategy:
                output += f"\nRecovery strategy: {reflection.recovery_strategy.value}"

            # Check if we should stop based on reflection
            if not reflection.should_retry:
                self.loop_state.should_stop = True
                if (
                    self.loop_state.get_last_step_result()
                    and self.loop_state.get_last_step_result().step_type == StepType.RUN_TESTS
                    and self.loop_state.get_last_step_result().status == StepStatus.COMPLETED
                ):
                    self.loop_state.mark_completed()

            return StepResult(
                step_type=StepType.REFLECT, status=StepStatus.COMPLETED, output=output
            )
        except Exception as e:
            return StepResult(step_type=StepType.REFLECT, status=StepStatus.FAILED, error=str(e))

    def _print_step_result(self, result: StepResult) -> None:
        """Print the result of a step execution."""
        status_color = {
            StepStatus.COMPLETED: "green",
            StepStatus.FAILED: "red",
            StepStatus.SKIPPED: "yellow",
            StepStatus.PENDING: "blue",
            StepStatus.IN_PROGRESS: "blue",
        }.get(result.status, "white")

        status_icon = {
            StepStatus.COMPLETED: "✓",
            StepStatus.FAILED: "✗",
            StepStatus.SKIPPED: "⊘",
            StepStatus.PENDING: "○",
            StepStatus.IN_PROGRESS: "⟳",
        }.get(result.status, "?")

        duration_str = f" ({result.duration_s:.1f}s)" if result.duration_s else ""

        self.console.print(
            f"[{status_color}]{status_icon}[/{status_color}] "
            f"[bold]{result.step_type.value}[/bold]{duration_str}"
        )

        if result.output:
            self.console.print(f"  [dim]{result.output}[/dim]")

        if result.error:
            self.console.print(f"  [red]Error: {result.error}[/red]")

    def _print_final_summary(self) -> None:
        """Print the final summary of the loop execution."""
        self.console.rule("[bold]Loop Summary")

        if self.loop_state.is_completed:
            self.console.print("[green]✓ Task completed successfully![/green]")
        elif self.loop_state.is_failed:
            self.console.print("[red]✗ Task failed[/red]")
        else:
            self.console.print("[yellow]⊘ Task stopped (max steps reached or manual stop)[/yellow]")

        self.console.print(
            f"Total steps: {self.loop_state.current_step}/{self.loop_state.max_steps}"
        )
        self.console.print(f"Total duration: {self.loop_state.total_duration_s:.1f}s")

        # Show step summary
        completed_steps = sum(
            1 for r in self.loop_state.step_results if r.status == StepStatus.COMPLETED
        )
        failed_steps = sum(1 for r in self.loop_state.step_results if r.status == StepStatus.FAILED)
        skipped_steps = sum(
            1 for r in self.loop_state.step_results if r.status == StepStatus.SKIPPED
        )

        self.console.print(
            f"Steps: {completed_steps} completed, {failed_steps} failed, {skipped_steps} skipped"
        )

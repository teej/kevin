from __future__ import annotations

from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel

from . import __version__
from .config import settings
from .loop_executor import LoopExecutor
from .models import ClaudeClient, ModelContext
from .models.loop_state import LoopState
from .repo import detect_project_info, detect_test_command, prepare_repo
from .sandbox.local import LocalSandbox

console = Console()


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(__version__, prog_name="kevin")
def cli() -> None:
    """kevin-like minimal CLI scaffold."""
    pass


@cli.command()
@click.option("--repo", "repo_input", required=True, help="Path or git URL of the target project.")
@click.option("--task", required=True, help="Goal/issue description for the agent.")
@click.option(
    "--sandbox",
    type=click.Choice(["local", "docker"]),
    default="local",
    show_default=True,
    help="Execution environment for commands/tests.",
)
@click.option(
    "--max-steps",
    type=int,
    default=15,
    show_default=True,
    help="Maximum number of steps in the loop.",
)
@click.option(
    "--timeout", type=int, default=120, show_default=True, help="Per-command timeout (s)."
)
@click.option(
    "--model",
    type=click.Choice(["claude"]),
    default="claude",
    show_default=True,
    help="AI model to use for planning and patching.",
)
@click.option("--api-key", help="API key for the model (or set ANTHROPIC_API_KEY env var).")
@click.option(
    "--dry-run", is_flag=True, help="Run the loop without applying patches (for testing)."
)
def run(
    repo_input: str,
    task: str,
    sandbox: str,
    max_steps: int,
    timeout: int,
    model: str,
    api_key: str,
    dry_run: bool,
) -> None:
    """Scaffold 'run' that prepares a workspace and executes a sandbox smoke test."""
    console.rule("[bold]kevin")
    console.print(Panel.fit(task, title="Task"))

    workspace: Path = prepare_repo(repo_input)
    console.print(f"[bold]Workspace:[/bold] {workspace}")

    test_cmd = detect_test_command(workspace)
    if test_cmd:
        console.print(f"[bold]Detected tests:[/bold] {test_cmd}")
    else:
        console.print("[yellow]No test command detected yet.[/yellow]")

    if sandbox == "local":
        sb = LocalSandbox(workdir=workspace)
    else:
        console.print("[red]Docker sandbox not implemented yet. Falling back to local.[/red]")
        sb = LocalSandbox(workdir=workspace)

    # Smoke test that proves basic sandbox command execution works
    result = sb.exec("echo hello from sandbox", timeout=15)
    console.print(
        f"[bold]Sandbox check:[/bold] rc={result.returncode} out='{result.stdout.strip()}'"
    )

    # Initialize model client
    if model == "claude":
        # Use CLI arg, then env var, then settings
        effective_api_key = api_key or settings.anthropic_api_key
        if not effective_api_key:
            console.print(
                "[red]Error:[/red] No Anthropic API key provided. "
                "Set --api-key or ANTHROPIC_API_KEY env var."
            )
            raise click.ClickException("Missing API key")
        client = ClaudeClient(api_key=effective_api_key)
    else:
        raise ValueError(f"Unsupported model: {model}")

    # Create model context
    project_info = detect_project_info(workspace)
    context = ModelContext(
        task=task,
        repo_path=str(workspace),
        test_command=test_cmd,
        has_src_layout=project_info["has_src_layout"],
        has_tests_dir=project_info["has_tests_dir"],
        has_pyproject=project_info["has_pyproject"],
        has_setup_py=project_info["has_setup_py"],
        package_dirs=project_info["package_dirs"],
        test_files=project_info["test_files"],
    )

    # Create loop state
    loop_state = LoopState(max_steps=max_steps, dry_run=dry_run)

    # Create and execute the loop
    executor = LoopExecutor(
        client=client, sandbox=sb, context=context, loop_state=loop_state, console=console
    )

    final_state = executor.execute_loop()

    # Print final status
    if final_state.is_completed:
        console.print("[green]✓ Task completed successfully![/green]")
    elif final_state.is_failed:
        console.print("[red]✗ Task failed[/red]")
        raise click.ClickException("Task execution failed")
    else:
        console.print("[yellow]⊘ Task stopped (max steps reached)[/yellow]")

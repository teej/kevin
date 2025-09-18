from __future__ import annotations

import os
import subprocess
import tempfile
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path


@dataclass
class CmdResult:
    returncode: int
    stdout: str
    stderr: str
    duration_s: float


class LocalSandbox:
    """
    Minimal sandbox that runs commands in a working directory on the host.
    Future: add DockerSandbox with same interface.
    """

    def __init__(self, workdir: str | Path) -> None:
        self.workdir = str(Path(workdir).resolve())

    def exec(self, cmd: str | Sequence[str], timeout: int = 120) -> CmdResult:
        start = time.perf_counter()
        proc = subprocess.run(
            cmd,
            cwd=self.workdir,
            shell=isinstance(cmd, str),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            check=False,
        )
        return CmdResult(
            returncode=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
            duration_s=time.perf_counter() - start,
        )

    def read_file(self, path: str, max_bytes: int = 100_000) -> str:
        p = Path(self.workdir) / path
        data = p.read_bytes()
        return data[:max_bytes].decode("utf-8", errors="replace")

    def write_file(self, path: str, content: str) -> None:
        p = Path(self.workdir) / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")

    def apply_patch(self, unified_diff: str) -> CmdResult:
        """Apply a patch with multiple fallback strategies for robustness."""
        # Step 1: Log the real failure details
        diff_preview = unified_diff[:1000] + "..." if len(unified_diff) > 1000 else unified_diff
        first_20_lines = "\n".join(unified_diff.split("\n")[:20])

        # Step 2: Strip wrappers and normalize
        diff = self._strip_diff_wrappers(unified_diff)
        diff = diff.replace("\r\n", "\n").strip()

        # Step 3: Validate diff format
        if not self._is_valid_diff_format(diff):
            return CmdResult(
                returncode=1,
                stdout="",
                stderr=f"Invalid diff format. Expected unified diff (---/+++) or git-style (diff --git). Got: {first_20_lines}",
                duration_s=0.0,
            )

        # Step 4: Normalize paths and check files
        diff = self._normalize_diff_paths(diff)

        # Step 5: Try multiple apply strategies
        strategies = [
            # Preflight check
            ["git", "apply", "--check"],
            # Standard apply with whitespace fixes
            ["git", "apply", "--whitespace=fix", "--ignore-whitespace"],
            # Try with -p0 (no prefix stripping)
            ["git", "apply", "-p0", "--whitespace=fix", "--ignore-whitespace"],
            # Try with -p1 (strip one directory level)
            ["git", "apply", "-p1", "--whitespace=fix", "--ignore-whitespace"],
            # Try with -p2 (strip two directory levels)
            ["git", "apply", "-p2", "--whitespace=fix", "--ignore-whitespace"],
        ]

        # Only try 3-way merge if we have git-style diff with index lines
        if "diff --git" in diff and "index " in diff:
            strategies.append(["git", "apply", "-3"])

        last_error = ""
        for strategy in strategies:
            result = self._try_apply_strategy(strategy, diff)
            if result.returncode == 0 and "apply" in " ".join(strategy):
                return result
            last_error = result.stderr

        # Step 6: Fallback to patch utility with different prefix levels
        patch_strategies = ["-p0", "-p1", "-p2"]
        for prefix in patch_strategies:
            patch_result = self._try_patch_fallback(diff, prefix)
            if patch_result.returncode == 0:
                return patch_result

        # Step 7: Return detailed error with all context
        error_msg = f"All patch strategies failed.\n"
        error_msg += f"Last git error: {last_error}\n"
        error_msg += f"Patch utility error: {patch_result.stderr}\n"
        error_msg += f"Diff preview (first 20 lines):\n{first_20_lines}"

        return CmdResult(returncode=1, stdout="", stderr=error_msg, duration_s=0.0)

    def _strip_diff_wrappers(self, diff: str) -> str:
        """Remove code fences, markdown, and prose from diff."""
        # Remove triple backticks and language specifiers
        lines = diff.split("\n")
        stripped_lines = []
        in_code_block = False

        for line in lines:
            # Skip markdown code fences
            if line.strip().startswith("```"):
                in_code_block = not in_code_block
                continue
            if in_code_block:
                continue

            # Skip prose lines that don't look like diff content
            if not any(
                line.startswith(prefix) for prefix in ["---", "+++", "diff", "@@", "+", "-", " "]
            ):
                # Skip lines that are clearly prose
                if not line.strip() or line.strip().startswith(("Here", "This", "The", "I", "We")):
                    continue

            stripped_lines.append(line)

        return "\n".join(stripped_lines)

    def _is_valid_diff_format(self, diff: str) -> bool:
        """Check if diff has valid format markers."""
        lines = diff.split("\n")
        has_unified = any(line.startswith("---") for line in lines) and any(
            line.startswith("+++") for line in lines
        )
        has_git_style = any(line.startswith("diff --git") for line in lines)
        return has_unified or has_git_style

    def _normalize_diff_paths(self, diff: str) -> str:
        """Normalize paths in diff to be repo-relative."""
        lines = diff.split("\n")
        normalized_lines = []

        for line in lines:
            # Handle unified diff headers
            if line.startswith("--- a/") or line.startswith("+++ b/"):
                # Keep a/ and b/ prefixes for git apply -p0
                normalized_lines.append(line)
            elif line.startswith("--- ") or line.startswith("+++ "):
                # Convert to git-style with a/ and b/ prefixes
                prefix = line[:4]
                path = line[4:].strip()
                if prefix == "--- ":
                    normalized_lines.append(f"--- a/{path}")
                else:
                    normalized_lines.append(f"+++ b/{path}")
            else:
                normalized_lines.append(line)

        return "\n".join(normalized_lines)

    def _try_apply_strategy(self, strategy: list[str], diff: str) -> CmdResult:
        """Try a specific git apply strategy."""
        with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8") as tf:
            tf.write(diff)
            tf.flush()
            path = tf.name

        try:
            # Use subprocess directly for better control
            start_time = time.perf_counter()
            cmd = strategy + [path]
            proc = subprocess.run(
                cmd,
                cwd=self.workdir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=60,
                check=False,
            )
            duration = time.perf_counter() - start_time

            return CmdResult(
                returncode=proc.returncode,
                stdout=proc.stdout,
                stderr=proc.stderr,
                duration_s=duration,
            )
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

    def _try_patch_fallback(self, diff: str, prefix: str = "-p0") -> CmdResult:
        """Try patch utility as fallback with specified prefix level."""
        with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8") as tf:
            tf.write(diff)
            tf.flush()
            path = tf.name

        try:
            # Use subprocess directly to handle input redirection properly
            start_time = time.perf_counter()
            proc = subprocess.run(
                ["patch", "--batch", prefix],
                cwd=self.workdir,
                input=diff,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=60,
                check=False,
            )
            duration = time.perf_counter() - start_time

            return CmdResult(
                returncode=proc.returncode,
                stdout=proc.stdout,
                stderr=proc.stderr,
                duration_s=duration,
            )
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

    def apply_file_edits(self, edits: list[dict]) -> CmdResult:
        """Apply file edits directly (robust fallback to patches)."""
        try:
            applied_files = []
            errors = []

            for edit in edits:
                path = edit["path"]
                mode = edit["mode"]
                content = edit.get("content", "")

                file_path = Path(self.workdir) / path

                try:
                    if mode == "replace":
                        # Ensure parent directory exists
                        file_path.parent.mkdir(parents=True, exist_ok=True)
                        file_path.write_text(content, encoding="utf-8")
                        applied_files.append(f"replaced {path}")
                    elif mode == "create":
                        # Ensure parent directory exists
                        file_path.parent.mkdir(parents=True, exist_ok=True)
                        file_path.write_text(content, encoding="utf-8")
                        applied_files.append(f"created {path}")
                    elif mode == "delete":
                        if file_path.exists():
                            file_path.unlink()
                            applied_files.append(f"deleted {path}")
                        else:
                            errors.append(f"file {path} does not exist for deletion")
                    else:
                        errors.append(f"unknown mode '{mode}' for {path}")

                except Exception as e:
                    errors.append(f"failed to {mode} {path}: {e}")

            if errors:
                return CmdResult(
                    returncode=1,
                    stdout="\n".join(applied_files),
                    stderr="\n".join(errors),
                    duration_s=0.0,
                )
            else:
                return CmdResult(
                    returncode=0,
                    stdout=f"Successfully applied {len(applied_files)} edits: "
                    + ", ".join(applied_files),
                    stderr="",
                    duration_s=0.0,
                )

        except Exception as e:
            return CmdResult(
                returncode=1, stdout="", stderr=f"File edits failed: {e}", duration_s=0.0
            )

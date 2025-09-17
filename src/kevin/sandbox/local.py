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
        # Applies a unified diff using git; requires repo to be a git worktree.
        with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8") as tf:
            tf.write(unified_diff)
            tf.flush()
            path = tf.name
        try:
            return self.exec(f"git apply --whitespace=fix {path}", timeout=60)
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

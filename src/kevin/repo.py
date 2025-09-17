from __future__ import annotations

import re
import subprocess
from pathlib import Path


def _is_git_url(s: str) -> bool:
    return bool(re.match(r"^(?:https?://|git@|ssh://)", s))


def _slugify(url: str) -> str:
    s = re.sub(r"[^\w.-]+", "-", url.strip().lower())
    return s.strip("-")[:80] or "repo"


def prepare_repo(repo_input: str) -> Path:
    """
    If `repo_input` is a local path, return its absolute Path.
    If it's a git URL, clone shallow into ./.kevin/workspaces/<slug>/ (create if missing).
    """
    p = Path(repo_input)
    if p.exists():
        return p.resolve()

    if not _is_git_url(repo_input):
        raise ValueError(f"Not a path or git URL: {repo_input!r}")

    base = Path(".kevin/workspaces")
    base.mkdir(parents=True, exist_ok=True)
    dest = (base / _slugify(repo_input)).resolve()

    if not dest.exists():
        try:
            subprocess.run(
                ["git", "clone", "--depth=1", repo_input, str(dest)],
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"git clone failed: {e.stderr}") from e

    return dest


def detect_test_command(repo_path: Path) -> str | None:
    """
    Heuristics to guess a test command. Keep simple for now.
    Always use uv for Python projects.
    """
    if (repo_path / "tests").exists():
        return "uv run pytest -q"
    if (repo_path / "pytest.ini").exists():
        return "uv run pytest -q"
    pyproject = repo_path / "pyproject.toml"
    if pyproject.exists() and "pytest" in pyproject.read_text(encoding="utf-8", errors="ignore"):
        return "uv run pytest -q"
    package_json = repo_path / "package.json"
    if package_json.exists():
        try:
            import json

            scripts = json.loads(package_json.read_text()).get("scripts", {})
            if "test" in scripts:
                return "npm test --silent"
        except Exception:
            pass
    return None


def detect_project_info(repo_path: Path) -> dict:
    """
    Detect flexible project information to help the AI understand the layout.
    Returns a dictionary with boolean flags and lists of found items.
    """
    info = {
        "has_src_layout": (repo_path / "src").exists(),
        "has_tests_dir": (repo_path / "tests").exists(),
        "has_pyproject": (repo_path / "pyproject.toml").exists(),
        "has_setup_py": (repo_path / "setup.py").exists(),
        "package_dirs": [],
        "test_files": [],
    }

    # Find package directories
    if info["has_src_layout"]:
        # Look for packages in src/
        src_dir = repo_path / "src"
        for item in src_dir.iterdir():
            if item.is_dir() and (item / "__init__.py").exists():
                info["package_dirs"].append(f"src/{item.name}")
    else:
        # Look for packages in root
        for item in repo_path.iterdir():
            if (
                item.is_dir()
                and (item / "__init__.py").exists()
                and item.name not in ["tests", "__pycache__", ".git"]
            ):
                info["package_dirs"].append(item.name)

    # Find test files
    if info["has_tests_dir"]:
        tests_dir = repo_path / "tests"
        for item in tests_dir.iterdir():
            if item.is_file() and item.suffix == ".py" and item.name.startswith("test_"):
                info["test_files"].append(f"tests/{item.name}")
    else:
        # Look for test files in root
        for item in repo_path.iterdir():
            if item.is_file() and item.suffix == ".py" and item.name.startswith("test_"):
                info["test_files"].append(item.name)

    return info

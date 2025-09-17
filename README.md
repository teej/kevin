# kevin

Minimal Python CLI scaffold for a kevin-like "AI engineer".

## Quickstart (uv):

```bash
uv venv
source .venv/bin/activate
uv pip install -e .
uv pip install pytest ruff
uv run kevin --help
uv run kevin run --repo . --task "echo hello"
```

## Next steps:

- Implement DockerSandbox in `src/kevin/sandbox/docker.py` and wire `--sandbox docker`.
- Add model client + agent loop (plan -> read files -> propose patch -> apply -> run tests).
- Add JSONL run logs and a unified diff apply tool.

## License: MIT
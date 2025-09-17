# kevin

Minimal Python CLI scaffold for a kevin-like "AI engineer".

## Quickstart (uv):

```bash
uv venv
source .venv/bin/activate
uv pip install -e .
uv pip install pytest ruff
uv run kevin --help

# Option 1: Environment variable
export ANTHROPIC_API_KEY="your-api-key-here"

# Option 2: .env file (recommended for development)
cp .env.example .env
# Edit .env with your actual API key

# Run kevin on a simple task
uv run kevin run --repo . --task "Add a hello world function to main.py"
```

## Next steps:

- Implement DockerSandbox in `src/kevin/sandbox/docker.py` and wire `--sandbox docker`.
- Add model client + agent loop (plan -> read files -> propose patch -> apply -> run tests).
- Add JSONL run logs and a unified diff apply tool.

## License: Apache
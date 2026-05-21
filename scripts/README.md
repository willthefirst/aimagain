# Scripts

This directory holds the project's developer CLI plus a handful of standalone scripts used by Docker, deployment, and lint checks.

## The `dev` command

`dev_cli.py` is the source of truth for `dev <command>`. It's installed as a console script via `pip install -e .` and auto-detects the current project root by walking up to `pyproject.toml`, so it operates on the worktree you're sitting in.

Run `dev --help` for the command list and `dev <command> --help` for per-command details. Help strings are co-located with the argparse definitions in [`dev_cli.py`](dev_cli.py), so they cannot drift from the implementation.

CLAUDE.md and other docs that want to mention a command link to `dev --help` rather than restating it.

## Layout

- `dev_cli.py` — the `dev` CLI entry point (argparse).
- `dev/` — one file per `dev <command>` implementation, each with a colocated `test_*.py`.
- `dev/title_case_check.py` / `dev/template_imports_check.py` / `dev/python_cluster_imports_check.py` — lint checks invoked by `dev lint`.
- `runtime/` — container-entrypoint scripts: `start.sh` (production CMD: runs migrations, starts uvicorn) and `start-dev.sh` (dev: adds LiveReload + hot reload).
- `check_doc_test_coupling.py` — Claude Code `Stop` hook; reminds the agent when `src/` code changed without touching colocated README/tests. Wired via [`.claude/settings.json`](../.claude/settings.json).
- `session_start_branch_check.py` — Claude Code `SessionStart` hook; prints the real branch, dirty state, and stash list at session start, and warns loudly when the agent lands on `main`/`master` in the shared working tree. Wired via [`.claude/settings.json`](../.claude/settings.json).
- `test_dev_cli.py` — tests for `dev_cli.py` itself.

Deployment-specific scripts live in `deployment/scripts/` (see [`deployment/README.md`](../deployment/README.md)).

## Tests

Tests for `scripts/dev/*` live colocated as `scripts/dev/test_*.py`. Tests for `dev_cli.py` itself live as `scripts/test_dev_cli.py`. Pytest discovers them via the `scripts` entry in `pyproject.toml`'s `testpaths`. Run only the CLI tests with `dev test scripts/`.

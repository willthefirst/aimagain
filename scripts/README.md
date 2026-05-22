# Scripts

This directory holds the project's developer CLI plus a handful of standalone scripts used by Docker, deployment, and lint checks.

## The `dev` command

`dev_cli.py` is the source of truth for `dev <command>`. It's installed as a console script via `pip install -e .` and auto-detects the current project root by walking up to `pyproject.toml`, so it operates on the worktree you're sitting in.

Each worktree also runs under its own `docker compose` project name (derived from the project-root directory), so `dev up` / `dev seed` / `dev logs` in a worktree never collide with the main checkout. Export `COMPOSE_PROJECT_NAME` to override.

Run `dev --help` for the command list and `dev <command> --help` for per-command details. Help strings are co-located with the argparse definitions in [`dev_cli.py`](dev_cli.py), so they cannot drift from the implementation.

CLAUDE.md and other docs that want to mention a command link to `dev --help` rather than restating it.

## Layout

- `dev_cli.py` — the `dev` CLI entry point (argparse).
- `dev/` — one file per `dev <command>` implementation, each with a colocated `test_*.py`.
- `dev/title_case_check.py` / `dev/template_imports_check.py` / `dev/python_cluster_imports_check.py` — lint checks invoked by `dev lint`.
- `runtime/` — container-entrypoint scripts: `start.sh` (production CMD: runs migrations, starts uvicorn) and `start-dev.sh` (dev: adds LiveReload + hot reload).
- `check_doc_test_coupling.py` — Claude Code `Stop` hook; reminds the agent when `src/` code changed without touching colocated README/tests. Wired via [`.claude/settings.json`](../.claude/settings.json).
- `session_start_branch_check.py` — Claude Code `SessionStart` hook; prints the real branch, dirty state, and stash list at session start, and warns loudly when the agent lands on `main`/`master` in the shared working tree. Wired via [`.claude/settings.json`](../.claude/settings.json).
- `preflight_worktree_check.py` — Claude Code `PreToolUse` hook for `Edit`/`Write`/`NotebookEdit`; the enforcement leg of the session-start warning. Refuses edits when the agent is in the main checkout on `main`/`master` so new work has to start on a worktree branched off main (`dev worktree add <slug>`). Allows edits in any worktree, and on the main checkout from a feature branch (so an in-flight session continuing on a feature branch isn't disrupted). Wired via [`.claude/settings.json`](../.claude/settings.json); colocated test pins the allow-vs-block matrix.
- `test_dev_cli.py` — tests for `dev_cli.py` itself.

Deployment-specific scripts live in `deployment/scripts/` (see [`deployment/README.md`](../deployment/README.md)).

## Merging PRs

PRs land via [Mergify](https://mergify.com) on `main`. The full flow requires no manual steps beyond `dev push`:

**Flow:**

1. `dev push` opens (or updates) a PR off your worktree branch.
2. Mergify immediately registers the PR for the queue (triggered on PR open, not on CI completion).
3. CI runs on the PR head (`pull_request` event). Mergify watches the `queue_conditions` and waits for all four checks to go green.
4. Once CI is green, Mergify admits the PR to the active queue — batching with any other waiting PRs (up to 3).
5. Mergify creates a speculative branch combining the batch rebased onto current `main`, runs CI on that branch, and squash-merges when green.
6. `dev merge [<pr>]` is optional — use it to watch and get notified when the PR lands or a check fails.

**Queue config:**

Config lives in [`.mergify.yml`](../.mergify.yml) at the repo root. Key knobs:

- `merge_method: squash` — matches `required_linear_history: true` on the branch rule.
- `batch_size: 3` — up to 3 PRs share one speculative CI run. Raise if throughput increases.
- `batch_max_wait_time: 2 minutes` — a lone PR in the queue won't wait more than 2 min for siblings before merging solo.

**Recovery:**

- See what's queued: Mergify dashboard at [app.mergify.com](https://app.mergify.com) or the "Mergify" check on any PR.
- Pull a PR out of the queue: comment `@mergifyio dequeue` on the PR. Re-add by pushing a new commit (re-triggering CI) or commenting `@mergifyio queue`.
- If Mergify is dequeuing PRs unexpectedly, check the "Checks" tab on the speculative merge commit Mergify created — that's where the failing CI run lives.

## Tests

Tests for `scripts/dev/*` live colocated as `scripts/dev/test_*.py`. Tests for `dev_cli.py` itself live as `scripts/test_dev_cli*.py`. Pytest discovers them via the `scripts` entry in `pyproject.toml`'s `testpaths`. Run only the CLI tests with `dev test scripts/`.

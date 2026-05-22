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

<!-- title-case-ignore: PRs is an acronym -->
## Merging PRs

PRs land via [GitHub Merge Queue](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/configuring-pull-request-merges/managing-a-merge-queue) on `main`. The flow is:

1. `dev push` opens (or updates) a PR off your worktree branch.
2. `dev merge [<pr>]` enables auto-merge via `gh pr merge --auto --squash`, then polls until the queue lands the PR or a required check fails.
3. The queue rebases the PR onto current `main` itself, runs CI in `merge_group` context against the speculative merge commit, and merges when green. No manual `gh pr update-branch --rebase`.

**When CI runs in each context:**

- `pull_request` event — runs against the PR head, on every push. Required checks for the PR-ready state.
- `merge_group` event — runs against the queue's speculative merge commit (PR rebased onto current `main`). Same four required checks (`tests`, `contract-tests`, `linting`, `docker-health-check`); see [`.github/workflows/ci.yml`](../.github/workflows/ci.yml).

The required-check names are identical across both contexts, so branch protection is satisfied by either.

**Queue config and tuning:**

The queue config lives on the `main` branch protection rule, not in this repo. Inspect with:

```bash
gh api /repos/willthefirst/bedlam-connect/branches/main/protection/required_merge_queue
```

Knobs worth knowing:

- `merge_method=squash` — matches `required_linear_history: true` on the branch rule.
- `max_entries_to_build` — how many PRs the queue speculatively rebases and tests in parallel. Start small (3); raise once CI is stable.
- `min_entries_to_merge_wait_minutes` — how long the queue waits for siblings before merging a lone entry. Set low for solo work, higher to amortize CI across batches.

**Recovery:**

- See what's queued: `gh api /repos/willthefirst/bedlam-connect/actions/runs?event=merge_group --jq '.workflow_runs[] | {id, status, head_branch}'`.
- Pull a PR out of the queue: `gh pr merge --disable-auto <pr>`. Re-queue with `dev merge <pr>` when ready.
- If the queue is jammed (stuck PR with no clear failure), GitHub UI → Settings → Branches → `main` → "Merge queue" exposes the queue dashboard.

## Tests

Tests for `scripts/dev/*` live colocated as `scripts/dev/test_*.py`. Tests for `dev_cli.py` itself live as `scripts/test_dev_cli*.py`. Pytest discovers them via the `scripts` entry in `pyproject.toml`'s `testpaths`. Run only the CLI tests with `dev test scripts/`.

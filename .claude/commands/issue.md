---
description: Work on a GitHub issue end-to-end — pull, worktree, plan, implement, PR, merge
allowed-tools: Bash, Read, Edit, Write, Agent, EnterWorktree, ExitWorktree
---

# Issue $arguments

## Issue details

!`gh issue view $ARGUMENTS 2>/dev/null || echo "⚠ Could not fetch issue — verify the number and run 'gh auth status'"`

## Workflow

Work through this end-to-end. Pause only for irreversible actions or genuine decision points — do not ask "shall I proceed?" on non-risky steps.

1. **Pull main** — run `git pull` from the main checkout to get the latest before branching.

2. **Claim** — `dev claim $ARGUMENTS`. If exit code 1 (already claimed by someone else), stop and report. Exit code 0 means you won the claim.

3. **Worktree** — `dev worktree add $ARGUMENTS` to create `.claude/worktrees/issue-$ARGUMENTS`. Then use `EnterWorktree` to switch into it so all subsequent file edits and commands run there.

4. **Plan** — read `CLAUDE.md`, then the relevant source files. Use `/plan` for any change touching multiple layers or introducing new resources/routes; skip it for single-file changes. Do not write code until the plan is clear.

5. **Implement** — follow `CLAUDE.md` definition of done: code change + README accuracy + colocated tests + `dev test` passes + `dev lint` passes.

6. **Push** — `dev push` to open the PR.

7. **Merge** — `dev merge` to watch CI and land it.

8. **Retro** — deliver the per-PR retrospective unprompted as your final message (per `CLAUDE.md`). Then propose the next open issue.

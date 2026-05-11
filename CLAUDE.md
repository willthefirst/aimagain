# Working in this repo

This file is the contract between you (the AI agent) and this codebase. Read it before any code change.

## Architecture in one line

The code under `src/` is organized into three top-level buckets: **`specs/`** (entity declarations — the business surface), **`framework/`** (domain-agnostic library), and **`domain/<entity>/`** (per-entity bespoke helpers — handlers + repository + schema collocated). A new entity adds one spec file and one domain cluster. See [`src/README.md`](src/README.md) for how the buckets relate and the import discipline between them.

## Definition of done

For any code change in `src/`, the change is **not done** until all four are true:

1. The code change itself is in.
2. The relevant README reflects new/changed/removed behavior — or you have explicitly verified it is still accurate. (Top-level: [`src/README.md`](src/README.md). Per-bucket: [`src/framework/README.md`](src/framework/README.md). Per-entity: [`src/domain/<entity>/README.md`](src/domain/) when one exists.)
3. The change has test coverage that pins what changed — colocated `test_*.py` in the same directory as the changed code (framework changes get `src/framework/test_*.py`; domain changes get `src/domain/<entity>/test_*.py`; route-level smoke tests under `src/api/routes/test_*.py` for thin pass-through.)
4. `dev test` passes and `dev lint` passes.

If a relevant README or test file doesn't exist yet, **create it as part of the change**. Don't defer.

A Stop hook checks the diff at end-of-turn and surfaces a reminder when source files change without their README/test. The hook is a soft prompt, not a hard block — but ignoring it should be a deliberate decision (e.g. typo fix, log message tweak), not an oversight.

**Contract tests are not run by default.** `tests/test_contract` is excluded from the default `dev test` collection (see [`tests/test_contract/README.md`](tests/test_contract/README.md)). If you change templates, route response shapes, or anything mock data factories in `tests/test_contract` assume, also run `dev test contract` before pushing — otherwise CI is the first place the breakage surfaces.

## One source of truth — link, don't copy

Each fact has exactly **one home**: the README closest to the code or config that the fact describes. Other docs link to it; they never restate it.

- The CLI's command list is exposed by `dev --help` and `dev <command> --help`, generated from the argparse definitions in [`scripts/dev_cli.py`](scripts/dev_cli.py). Every other doc that wants to mention a command links to `dev --help`, not a hand-maintained restatement.
- The three-bucket architecture lives in [`src/README.md`](src/README.md). Other READMEs link there, not duplicate it.
- Framework behavior, conventions, and tests live in [`src/framework/README.md`](src/framework/README.md). Cross-references go upward via links.
- Per-entity facts (cardinality decisions, polymorphism, audit quirks) live in `src/domain/<entity>/README.md` when an entity has something non-obvious to say.
- Migrations live in [`alembic/README.md`](alembic/README.md). Deployment in [`deployment/README.md`](deployment/README.md). Testing conventions in [`tests/README.md`](tests/README.md).

If you find a fact stated in two places, **one of them is wrong** — even if both currently agree, they will drift. Pick the one closest to the code, leave it there, and replace the other with a link. The Stop hook only catches drift between code and its colocated README/test; cross-cutting drift (e.g. CLI commands documented in the root README) can only be prevented by not duplicating in the first place.

## Grammar, not alphabet

A parent README expresses the **grammar** of what's in the directory below it — the shape, the rules, the contract every child must follow. It does not enumerate the **alphabet** — the specific entities, files, or counts that exist today.

A grammar is stable across churn: "every `domain/<entity>/` directory holds the per-entity helpers (handlers + repository + schema) for one domain entity; specs and the framework read from but do not depend on per-entity code." An alphabet drifts every time you add or rename an entity: "currently we have posts, providers, users, auth, favorites." The directory listing IS the alphabet — `ls src/specs/` and `ls src/domain/` are the source of truth for what entities exist.

A useful tell: when you write "currently X" in a parent README, you're describing alphabet. Replace with the grammar (what role X plays for *any* entity) and a pointer to the directory. When you write "always", "must", or "may", you're describing grammar — keep it.

The same rule applies recursively. An entity's own README (`domain/<entity>/README.md`) is the right home for facts about that specific entity — there, the entity *is* the subject, not part of an alphabet. The parent points down to entities; entities describe themselves; the parent doesn't restate them.

This complements the [single-source-of-truth rule](#one-source-of-truth--link-dont-copy): that rule says facts have one home; this rule says parent READMEs prefer rules over rosters.

**Default to not creating a new README.** A README earns its existence by documenting something `ls` and the code can't:

- A non-obvious pattern (registry-driven dispatch, polymorphic discriminator, cardinality decision).
- A deliberate deviation from the bucket's grammar.
- A constraint or contract that spans files in non-obvious ways.

If the only thing a candidate README would say is enumerate-what-`ls`-shows or restate-the-bucket-rules, don't write it. Empty or aspirational READMEs are net-negative — they tell the next reader to expect content that isn't load-bearing.

## Where to look

| Topic | Where it lives |
| --- | --- |
| Architecture, three-bucket layout, import discipline | [`src/README.md`](src/README.md) |
| Framework behavior (EntitySpec, mount helpers, generic handlers) | [`src/framework/README.md`](src/framework/README.md) |
| Resource URL grammar, lifecycle, subresource conventions | [`src/api/routes/RESOURCE_GRAMMAR.md`](src/api/routes/RESOURCE_GRAMMAR.md) |
| CLI commands (`dev ...`) | `dev --help` (source: [`scripts/dev_cli.py`](scripts/dev_cli.py)) |
| Testing conventions, fixtures | [`tests/README.md`](tests/README.md) |
| Database migrations | [`alembic/README.md`](alembic/README.md) |
| Deployment | [`deployment/README.md`](deployment/README.md) |
| Per-entity quirks | `src/domain/<entity>/README.md` when one exists |

Pre-commit hooks run lint automatically — don't bypass with `--no-verify`.

## When in doubt

1. Read [`src/README.md`](src/README.md) for the three-bucket layout and what may import what.
2. Read [`src/framework/README.md`](src/framework/README.md) if you're touching the dispatch helpers, generic handlers, or audit framework.
3. If a single change adds a new entity, follow the entity checklist in [`src/README.md`](src/README.md#adding-a-new-domain-entity) — one spec file + one domain cluster + one route file.
4. **Before adding or modifying a resource type**, read [`src/api/routes/RESOURCE_GRAMMAR.md`](src/api/routes/RESOURCE_GRAMMAR.md) first. It's the prescriptive contract for URL shape, lifecycle states, and subresource conventions.
5. **Before adding or moving a route**, run `dev routes [prefix]` to see every handler currently mounted. Catches router shadowing before tests do. Full CLI list: `dev --help` (source: [`scripts/dev_cli.py`](scripts/dev_cli.py)).
6. **Before changing a wire or storage contract**, do the contract-surface check below.

## Before implementing a multi-layer change: contract-surface check

Bucket-by-bucket planning catches "did I update every file?" — it does *not* catch "did I just break every existing client?" That second question is what this section is for.

Before writing code on any change that modifies a schema, route, template, or persisted format, write a short pre-implementation note that answers three questions. Five minutes; no plan-mode session needed.

1. **Which contract surfaces does this touch?** For each, classify as **compatible** (existing producers/consumers keep working) or **breaking** (someone has to change). Surfaces include:
   - HTTP request body shape (route schemas)
   - HTTP response body shape (route schemas, template-context dicts consumed by HTMX)
   - URL shape (added paths, renamed paths, new query parameters that change selection)
   - Persisted JSON shape (`audit_log.before`/`after`, settings blobs, anything stored as JSON)
   - Database CHECK/UNIQUE constraints whose universe of valid values is shrinking

2. **Is there a strictly smaller PR you could ship first?** Specifically: a 1-file or 1-layer change that makes the main PR's diff smaller, more reversible, or stop introducing two concepts at once. The canonical example: when adding a discriminator-based feature, ship "make the discriminator field required on the wire (single value allowed)" first, then "add a second value" as a separate PR. The prep PR is a no-op functionally; the feature PR is then a textbook discriminated union.

3. **For each breaking surface, who decides?** If the breakage is scoped (only internal callers, only your tests) you can absorb it. If it leaks past your boundary (HTML forms, external API consumers, persisted data already in production) **surface the choice to the user explicitly** before implementing — *"this changes X for existing clients; OK, or do you want me to prep first?"* Don't decide silently inside the implementation.

4. **Which other READMEs reference symbols, files, or paths I'm renaming, deleting, or changing?** Bucket-by-bucket planning catches *which buckets a change touches*; it doesn't catch *which other READMEs reference the symbols being changed*. For each renamed or removed identifier, run:

   ```bash
   grep -rn "<old-name>" $(find . -name README.md -not -path './.claude/*' -not -path './.pytest_cache/*')
   ```

   Update or delete any matches as part of the same PR — neighbor-README drift is otherwise invisible until the next reader hits a stale claim.

The cost of skipping this check is one end-of-PR realization that you took the wrong shape — by which point unwinding is more work than the prep PR would have been.

## Plan mode

Use `/plan` when a change touches multiple buckets or introduces new resources/routes — the Explore + Plan overhead pays off when a wrong direction is expensive. Skip it for typo fixes, single-file refactors, README polish, and anything you can describe in one sentence.

## Per-PR retrospective

Before declaring a PR complete (after the final commit, before push), run a retro on the session and ship it as the final message — separately from the PR description. The user decides which entries become issues; this is how friction gets filed instead of re-discovered next session.

Each entry should be issue-shaped:

```
### <one-line title>
**Friction:** what slowed me down, with a concrete example.
**Fix:** the specific change that would prevent it (file, command, config).
**Why didn't existing patterns prevent this?** <one sentence — if an existing pattern *should* have prevented this and you didn't follow it, that's a class-of-bug signal>
**Could this class recur elsewhere?** <name the audit you'd run, or write "no, one-off" — forces the audit step *before* filing>
**Effort:** small / medium / large.
```

The two middle fields are sorting questions, not approval gates. Most entries will answer "no existing pattern applies" and "no, one-off" in ten words and move on. The *signal* is when the answer to the first is "an existing pattern applies and I didn't follow it" — that's the fork between filing a doc note and filing a structural-prevention issue. The second field forces an audit before generalizing, so retro entries don't imply current bugs that don't actually exist.

Cover the single biggest time sink, any missing/misleading tool or doc, and anything that worked unexpectedly well (so it gets repeated).

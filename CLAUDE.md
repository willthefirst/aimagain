# Working in this repo

The contract between you (the AI agent) and this codebase. Read it before any code change.

The architecture, layer responsibilities, and per-directory grammar live in [`src/README.md`](src/README.md) and the layer READMEs it points at. This file documents only the rules that wouldn't be discovered by reading the code or the per-layer READMEs.

## Definition of done

For any code change in `src/`, the change is **not done** until all four are true:

1. The code change itself is in.
2. The README closest to the changed code reflects new/changed/removed behavior — or you have explicitly verified it is still accurate.
3. There is colocated `test_*.py` coverage that pins what changed.
4. `dev test` passes and `dev lint` passes.

If a relevant README or test file doesn't exist yet, **create it as part of the change**. Don't defer.

A Stop hook checks the diff at end-of-turn and surfaces a reminder when source files change without their README/test. The hook is a soft prompt, not a hard block — but ignoring it should be a deliberate decision (e.g. typo fix, log message tweak), not an oversight.

**Contract tests are not run by default.** `tests/test_contract` is excluded from the default `dev test` collection (see [`tests/test_contract/README.md`](tests/test_contract/README.md)). If you change templates, route response shapes, or anything mock data factories in `tests/test_contract` assume, also run `dev test contract` before pushing — otherwise CI is the first place the breakage surfaces.

## One source of truth — link, don't copy

Each fact has exactly **one home**: the README closest to the code or config that the fact describes. Other docs link to it; they never restate it.

The CLI's command list is generated from [`scripts/dev_cli.py`](scripts/dev_cli.py); link to `dev --help`, never restate. The architecture lives in [`src/README.md`](src/README.md); other READMEs link there. Per-entity facts live in `src/domain/logic/<entity>/README.md` when an entity has something non-obvious to say.

If you find a fact stated in two places, **one of them is wrong** — even if both currently agree, they will drift. Pick the one closest to the code, leave it there, and replace the other with a link.

## Grammar, not alphabet

A parent README expresses the **grammar** of what's in the directory below it — the shape, the rules, the contract every child must follow. It does not enumerate the **alphabet** — the specific entities, files, or counts that exist today.

A useful tell: when you write "currently X" in a parent README, you're describing alphabet. Replace with the grammar (what role X plays for *any* entity) and a pointer to the directory. When you write "always", "must", or "may", you're describing grammar — keep it.

The same rule applies recursively. An entity's own README is the right home for facts about that specific entity — there, the entity *is* the subject. The parent points down to entities; entities describe themselves; the parent doesn't restate them.

**Default to not creating a new README.** A README earns its existence by documenting something `ls` and the code can't:

- A non-obvious pattern (registry-driven dispatch, polymorphic discriminator, cardinality decision).
- A deliberate deviation from the bucket's grammar.
- A constraint or contract that spans files in non-obvious ways.

If the only thing a candidate README would say is enumerate-what-`ls`-shows or restate-the-bucket-rules, don't write it. Empty or aspirational READMEs are net-negative — they tell the next reader to expect content that isn't load-bearing.

Pre-commit hooks run lint automatically — don't bypass with `--no-verify`.

## Before implementing a multi-layer change: contract-surface check

Layer-by-layer planning catches "did I update every file?" — it does *not* catch "did I just break every existing client?" That second question is what this section is for.

Before writing code on any change that modifies a schema, route, template, or persisted format, write a short pre-implementation note that answers four questions. Five minutes; no plan-mode session needed.

1. **Which contract surfaces does this touch?** For each, classify as **compatible** (existing producers/consumers keep working) or **breaking** (someone has to change). Surfaces include:
   - HTTP request body shape (route schemas)
   - HTTP response body shape (route schemas, template-context dicts consumed by HTMX)
   - URL shape (added paths, renamed paths, new query parameters that change selection)
   - Persisted JSON shape (`audit_log.before`/`after`, settings blobs, anything stored as JSON)
   - Database CHECK/UNIQUE constraints whose universe of valid values is shrinking

2. **Is there a strictly smaller PR you could ship first?** Specifically: a 1-file or 1-layer change that makes the main PR's diff smaller, more reversible, or stop introducing two concepts at once. The canonical example: when adding a discriminator-based feature, ship "make the discriminator field required on the wire (single value allowed)" first, then "add a second value" as a separate PR. The prep PR is a no-op functionally; the feature PR is then a textbook discriminated union.

3. **For each breaking surface, who decides?** If the breakage is scoped (only internal callers, only your tests) you can absorb it. If it leaks past your boundary (HTML forms, external API consumers, persisted data already in production) **surface the choice to the user explicitly** before implementing — *"this changes X for existing clients; OK, or do you want me to prep first?"* Don't decide silently inside the implementation.

4. **Which other READMEs reference symbols, files, or paths I'm renaming, deleting, or changing?** For each renamed or removed identifier, run:

   ```bash
   grep -rn "<old-name>" $(find . -name README.md -not -path './.claude/*' -not -path './.pytest_cache/*')
   ```

   Update or delete any matches as part of the same PR — neighbor-README drift is otherwise invisible until the next reader hits a stale claim.

Also, before adding or moving a route, run `dev routes [prefix]` to see every handler currently mounted — catches router shadowing before tests do. And before adding or modifying a resource type, read [`src/domain/routes/RESOURCE_GRAMMAR.md`](src/domain/routes/RESOURCE_GRAMMAR.md) — it's the prescriptive contract for URL shape, lifecycle states, and subresource conventions.

## Plan mode

Use `/plan` when a change touches multiple layers or introduces new resources/routes — the Explore + Plan overhead pays off when a wrong direction is expensive. Skip it for typo fixes, single-file refactors, README polish, and anything you can describe in one sentence.

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

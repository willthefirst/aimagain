# Working in this repo

This file is the contract between you (the AI agent) and this codebase. Read it before any code change.

## Architecture in one line

The code under `src/` is organized by **layer**, not by feature; each layer is a subdirectory of `src/`. A new entity typically touches every layer. See [`src/README.md`](src/README.md) for layer responsibilities, the dependency rules between layers, and the cluster pattern that organizes entities within each layer.

## Definition of done

For any code change in `src/<layer>/`, the change is **not done** until all four are true:

1. The code change itself is in.
2. The colocated `src/<layer>/README.md` reflects new/changed/removed behavior — or you have explicitly verified it is still accurate.
3. The colocated test file (`src/<layer>/test_*.py`) is updated or added to cover the change.
4. `dev test` passes and `dev lint` passes.

If a layer has no README or no test file yet, **create them as part of the change**. Don't defer.

A Stop hook checks the diff at end-of-turn and surfaces a reminder when source files change without their README/test. The hook is a soft prompt, not a hard block — but ignoring it should be a deliberate decision (e.g. typo fix, log message tweak), not an oversight.

**Contract tests are not run by default.** `tests/test_contract` is excluded from the default `dev test` collection (see [`tests/test_contract/README.md`](tests/test_contract/README.md)). If you change templates, route response shapes, or anything mock data factories in `tests/test_contract` assume, also run `dev test contract` before pushing — otherwise CI is the first place the breakage surfaces.

## One source of truth — link, don't copy

Each fact has exactly **one home**: the README closest to the code or config that the fact describes. Other docs link to it; they never restate it.

- The CLI's command list lives in [`scripts/README.md`](scripts/README.md). Every other doc that wants to mention a command links there.
- The layered architecture lives in [`src/README.md`](src/README.md). The root README and layer READMEs link there, not duplicate it.
- A layer's behavior, conventions, and tests live in `src/<layer>/README.md`. Cross-references go upward via links.
- Migrations live in [`alembic/README.md`](alembic/README.md). Deployment in [`deployment/README.md`](deployment/README.md). Testing conventions in [`tests/README.md`](tests/README.md).

If you find a fact stated in two places, **one of them is wrong** — even if both currently agree, they will drift. Pick the one closest to the code, leave it there, and replace the other with a link. The Stop hook only catches drift between code and its colocated README/test; cross-cutting drift (e.g. CLI commands documented in the root README) can only be prevented by not duplicating in the first place.

## Grammar, not alphabet

A parent README expresses the **grammar** of what's in the directory below it — the shape, the rules, the contract every child must follow. It does not enumerate the **alphabet** — the specific entities, files, or counts that exist today.

A grammar is stable across churn: "every cluster directory represents one domain entity; cluster files may import from same cluster + the layer's shared tier." An alphabet drifts every time you add or rename an entity: "currently we have posts, providers, users, auth, audit." The directory listing IS the alphabet — `ls src/<layer>/` is the source of truth for what entities exist.

A useful tell: when you write "currently X" in a parent README, you're describing alphabet. Replace with the grammar (what role X plays for *any* entity) and a pointer to the directory. When you write "always", "must", or "may", you're describing grammar — keep it.

The same rule applies recursively. A cluster's own README (`<layer>/<entity>/README.md`) is the right home for facts about that specific entity — there, the entity *is* the subject, not part of an alphabet. The parent points down to clusters; clusters describe themselves; the parent doesn't restate them.

This complements the [single-source-of-truth rule](#one-source-of-truth--link-dont-copy): that rule says facts have one home; this rule says parent READMEs prefer rules over rosters.

## Where to look

| Topic | Where it lives |
| --- | --- |
| Architecture, layer responsibilities, dependency rules | [`src/README.md`](src/README.md) |
| Resource URL grammar, lifecycle, subresource conventions | [`src/api/routes/RESOURCE_GRAMMAR.md`](src/api/routes/RESOURCE_GRAMMAR.md) |
| CLI commands (`dev ...`) | [`scripts/README.md`](scripts/README.md) |
| Testing conventions, fixtures | [`tests/README.md`](tests/README.md) |
| Database migrations | [`alembic/README.md`](alembic/README.md) |
| Deployment | [`deployment/README.md`](deployment/README.md) |
| A specific layer's behavior | `src/<layer>/README.md` |

Pre-commit hooks run lint automatically — don't bypass with `--no-verify`.

## When in doubt

1. Read [`src/README.md`](src/README.md) for layer responsibilities and what may import what.
2. Read the README of the layer you're changing, plus the layers it depends on.
3. If a single change forces edits across most layers (model + schema + repo + service + route), follow the entity checklist in [`src/README.md`](src/README.md#adding-a-new-domain-entity) — that's expected for new entities, not a smell.
4. **Before adding or modifying a resource type**, read [`src/api/routes/RESOURCE_GRAMMAR.md`](src/api/routes/RESOURCE_GRAMMAR.md) first. It's the prescriptive contract for URL shape, lifecycle states, and subresource conventions.
5. **Before adding or moving a route**, run `dev routes [prefix]` to see every handler currently mounted. Catches router shadowing before tests do. Full CLI list: [`scripts/README.md`](scripts/README.md).
6. **Before changing a wire or storage contract**, do the contract-surface check below. The layer matrix tells you *which layers* a change touches; this tells you *which contracts* it touches.

## Before implementing a multi-layer change: contract-surface check

Layer-by-layer planning catches "did I update every file?" — it does *not* catch "did I just break every existing client?" That second question is what this section is for.

Before writing code on any change that modifies a schema, route, template, or persisted format, write a short pre-implementation note that answers three questions. Five minutes; no plan-mode session needed.

1. **Which contract surfaces does this touch?** For each, classify as **compatible** (existing producers/consumers keep working) or **breaking** (someone has to change). Surfaces include:
   - HTTP request body shape (route schemas)
   - HTTP response body shape (route schemas, template-context dicts consumed by HTMX)
   - URL shape (added paths, renamed paths, new query parameters that change selection)
   - Persisted JSON shape (`audit_log.before`/`after`, settings blobs, anything stored as JSON)
   - Database CHECK/UNIQUE constraints whose universe of valid values is shrinking

2. **Is there a strictly smaller PR you could ship first?** Specifically: a 1-file or 1-layer change that makes the main PR's diff smaller, more reversible, or stop introducing two concepts at once. The canonical example: when adding a discriminator-based feature, ship "make the discriminator field required on the wire (single value allowed)" first, then "add a second value" as a separate PR. The prep PR is a no-op functionally; the feature PR is then a textbook discriminated union.

3. **For each breaking surface, who decides?** If the breakage is scoped (only internal callers, only your tests) you can absorb it. If it leaks past your boundary (HTML forms, external API consumers, persisted data already in production) **surface the choice to the user explicitly** before implementing — *"this changes X for existing clients; OK, or do you want me to prep first?"* Don't decide silently inside the implementation.

The cost of skipping this check is one end-of-PR realization that you took the wrong shape — by which point unwinding is more work than the prep PR would have been.

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

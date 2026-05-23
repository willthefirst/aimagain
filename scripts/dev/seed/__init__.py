"""Deterministic, introspection-driven seed for the dev database.

Entry points:
  - `scripts.dev.seed.main()`             — CLI entry (returns rc).
  - `scripts.dev.seed.seed_all()`         — async coroutine if you want
                                            to embed seeding in a test.

How extension works:

  - Add a new model: nothing here changes. The runner walks
    `metadata.sorted_tables` and the generic generator fills columns
    via introspection. Run `dev lint` — if the new model has free-text
    columns the generator can't cover, the drift lint
    (`lint_coverage.py`) tells you exactly which name to add to
    `vocab.COLUMN_VOCAB` or `vocab.PLACEHOLDER_OK`.

  - Add a new CHECK-constrained column: nothing changes. The constraint
    SQL is parsed at import time (`check_registry.py`) and the
    generator round-robins over the values.

  - Add a model with structural specials (constructor side effects,
    hierarchy, fan-out, M:N): create a new module under `overrides/`
    and `@register(YourModel)` an async function returning the rows
    it produced.

See `README.md` in this directory for the full contract.
"""

from .runner import main, seed_all  # noqa: F401

__all__ = ["main", "seed_all"]

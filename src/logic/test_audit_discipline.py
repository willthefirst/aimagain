"""Static check that mutation handlers obey the audit-log discipline.

Per `RESOURCE_GRAMMAR.md:135`, every mutation handler MUST write an audit
row in the same transaction as the mutation. The discipline is easy to
forget on a new handler — this test makes "forgot the audit call" a CI
failure instead of a code-review catch.

The check parses each `*_processing.py` in `src/logic/`, walks every
`async def handle_*` function, and fails the test if the function calls
`.commit()` without also calling `record_audit(...)`.

Opt-out: add `audit-discipline-ignore` to the function's docstring with a
brief reason. Use sparingly — the rule is the rule for a good reason.
"""

import ast
from pathlib import Path

import pytest

LOGIC_DIR = Path(__file__).parent
PROCESSING_FILES = sorted(LOGIC_DIR.glob("*_processing.py"))


def _has_call_named(node: ast.AST, name: str) -> bool:
    """True if the subtree rooted at `node` contains a call to `name`.

    Matches both bare names (`record_audit(...)`) and attribute calls
    (`audit_repo.session.commit()`).
    """
    for sub in ast.walk(node):
        if not isinstance(sub, ast.Call):
            continue
        func = sub.func
        if isinstance(func, ast.Name) and func.id == name:
            return True
        if isinstance(func, ast.Attribute) and func.attr == name:
            return True
    return False


def _is_opted_out(func: ast.AsyncFunctionDef) -> bool:
    docstring = ast.get_docstring(func) or ""
    return "audit-discipline-ignore" in docstring


def _mutation_handlers(path: Path) -> list[ast.AsyncFunctionDef]:
    """All `async def handle_*` definitions in a logic-layer file."""
    tree = ast.parse(path.read_text())
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name.startswith("handle_")
    ]


def _all_handlers() -> list[tuple[Path, ast.AsyncFunctionDef]]:
    pairs: list[tuple[Path, ast.AsyncFunctionDef]] = []
    for path in PROCESSING_FILES:
        for func in _mutation_handlers(path):
            pairs.append((path, func))
    return pairs


HANDLERS = _all_handlers()


@pytest.mark.parametrize(
    "path,func",
    HANDLERS,
    ids=[f"{p.name}::{f.name}" for p, f in HANDLERS],
)
def test_handler_obeys_audit_discipline(path: Path, func: ast.AsyncFunctionDef) -> None:
    """A `handle_*` that calls `.commit()` MUST also call `record_audit(...)`.

    The check is intentionally conservative — read-only handlers (no commit)
    pass trivially; mutation handlers without the audit call fail with a
    pointer to RESOURCE_GRAMMAR.md and the opt-out mechanism.
    """
    if _is_opted_out(func):
        pytest.skip(f"{func.name} opted out via audit-discipline-ignore")

    commits = _has_call_named(func, "commit")
    audits = _has_call_named(func, "record_audit")

    if commits and not audits:
        pytest.fail(
            f"{path.name}::{func.name} calls .commit() without record_audit. "
            "Mutation handlers MUST write an audit row in the same transaction "
            "(RESOURCE_GRAMMAR.md:135). Either add a `record_audit(...)` call "
            "before the commit, or — if this handler legitimately doesn't "
            "mutate — annotate its docstring with `audit-discipline-ignore: "
            "<reason>`."
        )


def test_check_finds_handlers() -> None:
    """Sanity: at least one mutation handler must be discovered, otherwise
    the parametrize collected nothing and the discipline check is silently
    a no-op."""
    assert len(HANDLERS) > 0, "no handle_* functions found in src/logic/"


def test_at_least_one_handler_actually_audits() -> None:
    """Sanity: at least one handler in the codebase calls record_audit.
    If this fails, the import-graph or AST walk is broken — not a discipline
    failure, a self-test failure.
    """
    auditing = [
        (path, func) for path, func in HANDLERS if _has_call_named(func, "record_audit")
    ]
    assert auditing, (
        "no handler calls record_audit — either the AST walk is broken or "
        "the audit retrofit hasn't shipped"
    )


# --- Self-tests: prove the check catches what it claims to catch ---------


def _parse_handler(source: str) -> ast.AsyncFunctionDef:
    tree = ast.parse(source)
    handler = tree.body[0]
    assert isinstance(handler, ast.AsyncFunctionDef)
    return handler


def test_check_flags_handler_that_commits_without_audit() -> None:
    """A regression in the check itself shows up here, not in production."""
    bad = _parse_handler("""
async def handle_bad(repo, user):
    await repo.do_thing()
    await repo.session.commit()
    return None
""")
    assert _has_call_named(bad, "commit")
    assert not _has_call_named(bad, "record_audit")


def test_check_approves_handler_that_audits_then_commits() -> None:
    good = _parse_handler("""
async def handle_good(repo, audit_repo, user):
    await record_audit(audit_repo, action=AuditAction.X)
    await repo.session.commit()
    return None
""")
    assert _has_call_named(good, "commit")
    assert _has_call_named(good, "record_audit")


def test_check_skips_handler_with_opt_out_in_docstring() -> None:
    opted_out = _parse_handler('''
async def handle_special(repo):
    """Read-only consistency commit.

    audit-discipline-ignore: this handler doesn't mutate; the .commit()
    is a savepoint release, no audit row warranted.
    """
    await repo.session.commit()
    return None
''')
    assert _is_opted_out(opted_out)

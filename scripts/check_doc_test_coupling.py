#!/usr/bin/env python3
"""Stop-hook reminder: surface src/ edits without README/test changes."""

from __future__ import annotations

import os
import subprocess
import sys
from collections import defaultdict
from pathlib import Path


def git_changed_files() -> list[str]:
    """Return paths changed vs HEAD, staged + unstaged, deduplicated."""
    try:
        out = subprocess.run(
            ["git", "diff", "HEAD", "--name-only"],
            capture_output=True,
            text=True,
            check=True,
        )
        return [line for line in out.stdout.splitlines() if line]
    except subprocess.CalledProcessError:
        out = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            capture_output=True,
            text=True,
            check=False,
        )
        return [line for line in out.stdout.splitlines() if line]


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    os.chdir(repo_root)

    changed = git_changed_files()
    if not changed:
        return 0

    # Group changes by their containing directory under src/.
    # Top-level files like src/main.py group under "src"; nested files
    # like src/domain/routes/auth.py group under "src/domain/routes".
    by_module: dict[str, set[str]] = defaultdict(set)
    for path in changed:
        if not path.startswith("src/"):
            continue
        parts = Path(path).parts
        module_dir = str(Path(*parts[:-1])) if len(parts) > 1 else "src"
        by_module[module_dir].add(parts[-1])

    reminders: list[str] = []
    for module_dir, files in sorted(by_module.items()):
        code_files = {
            f
            for f in files
            if f.endswith(".py") and not f.startswith("test_") and f != "__init__.py"
        }
        if not code_files:
            continue

        readme_touched = "README.md" in files
        test_touched = any(f.startswith("test_") and f.endswith(".py") for f in files)

        readme_exists = (Path(module_dir) / "README.md").exists()
        existing_tests = list(Path(module_dir).glob("test_*.py"))

        missing: list[str] = []
        if not readme_touched:
            if readme_exists:
                missing.append(f"  - README not updated: {module_dir}/README.md")
            else:
                missing.append(f"  - README missing: create {module_dir}/README.md")
        if not test_touched:
            if existing_tests:
                names = ", ".join(t.name for t in existing_tests)
                missing.append(f"  - tests not updated: {module_dir}/ ({names})")
            else:
                missing.append(
                    f"  - no tests for module: create {module_dir}/test_*.py"
                )

        if missing:
            edited = ", ".join(sorted(code_files))
            reminders.append(f"{module_dir}/ — edited: {edited}\n" + "\n".join(missing))

    if reminders:
        print(
            "\n[doc/test coupling reminder]\n"
            "You edited code in these modules without touching their colocated\n"
            "README/tests. If that was intentional (typo, log message, etc.) ignore\n"
            "this. Otherwise, update the docs and tests as part of this change.\n",
            file=sys.stderr,
        )
        for r in reminders:
            print(r + "\n", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Tests for scripts/dev/title_case_check.py.

These exercise the checker as a subprocess (the same way `dev lint` invokes
it) so we catch stdout/stderr noise that wouldn't show up in unit tests of
the class methods.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CHECKER = PROJECT_ROOT / "scripts" / "dev" / "title_case_check.py"


def test_title_case_check_silently_skips_binary_files(tmp_path):
    """A non-utf8 .db file must not produce 'Error reading' or 'can't decode' noise."""
    db_file = tmp_path / "fake.db"
    db_file.write_bytes(b"\x86\xff\x00binary")

    result = subprocess.run(
        [
            sys.executable,
            str(CHECKER),
            "--check-only",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
    )

    combined = result.stdout + result.stderr
    assert result.returncode == 0, combined
    assert "Error reading" not in combined, combined
    assert "can't decode" not in combined, combined

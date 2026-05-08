"""Tests for scripts/dev/python_cluster_imports_check.py."""

from __future__ import annotations

from pathlib import Path

from scripts.dev.python_cluster_imports_check import find_violations


def _write(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def _build_layer(
    src_root: Path,
    layer: str,
    clusters: list[str],
    parent_files: list[str] | None = None,
) -> None:
    """Create a fake layer with given cluster directories under src_root.

    Each cluster gets a placeholder file so it counts as a real cluster
    in the auto-discovery step.
    """
    layer_root = src_root / layer
    layer_root.mkdir(parents=True, exist_ok=True)
    for c in clusters:
        _write(layer_root / c / "_placeholder.py", "")
    for f in parent_files or []:
        _write(layer_root / f, "")


def test_same_cluster_absolute_import_is_allowed(tmp_path: Path) -> None:
    src = tmp_path / "src"
    _build_layer(src, "logic", ["posts", "providers"], parent_files=["audit.py"])
    f = _write(
        src / "logic" / "posts" / "post_processing.py",
        "from src.logic.posts._placeholder import x\n",
    )

    assert find_violations([f], src) == []


def test_shared_parent_file_import_is_allowed(tmp_path: Path) -> None:
    src = tmp_path / "src"
    _build_layer(src, "logic", ["posts", "providers"], parent_files=["audit.py"])
    f = _write(
        src / "logic" / "posts" / "post_processing.py",
        "from src.logic.audit import record_audit\n",
    )

    assert find_violations([f], src) == []


def test_cross_layer_import_is_out_of_scope(tmp_path: Path) -> None:
    """Cross-layer imports are not enforced by this check (only within-layer)."""
    src = tmp_path / "src"
    _build_layer(src, "logic", ["posts"])
    _build_layer(src, "repositories", ["providers"])
    f = _write(
        src / "logic" / "posts" / "post_processing.py",
        "from src.repositories.providers.repo import X\n",
    )

    assert find_violations([f], src) == []


def test_cross_cluster_absolute_import_is_flagged(tmp_path: Path) -> None:
    src = tmp_path / "src"
    _build_layer(src, "logic", ["posts", "providers"], parent_files=["audit.py"])
    f = _write(
        src / "logic" / "posts" / "post_processing.py",
        "from src.logic.providers.handler import x\n",
    )

    violations = find_violations([f], src)

    assert len(violations) == 1
    v = violations[0]
    assert v.importer_layer == "logic"
    assert v.importer_cluster == "posts"
    assert v.target_cluster == "providers"
    assert "posts/ → providers/" in v.message()


def test_relative_dot_import_is_same_cluster(tmp_path: Path) -> None:
    """`from .x import y` from inside a cluster resolves within the same cluster."""
    src = tmp_path / "src"
    _build_layer(src, "logic", ["posts"])
    f = _write(
        src / "logic" / "posts" / "post_processing.py",
        "from .helpers import h\n",
    )

    assert find_violations([f], src) == []


def test_relative_double_dot_import_to_sibling_cluster_is_flagged(
    tmp_path: Path,
) -> None:
    """`from ..providers.x import y` walks to a sibling cluster."""
    src = tmp_path / "src"
    _build_layer(src, "logic", ["posts", "providers"])
    f = _write(
        src / "logic" / "posts" / "post_processing.py",
        "from ..providers.handler import x\n",
    )

    violations = find_violations([f], src)

    assert len(violations) == 1
    assert violations[0].target_cluster == "providers"


def test_relative_double_dot_to_shared_is_allowed(tmp_path: Path) -> None:
    """`from ..base import` from a clustered file walks to the layer's parent — fine."""
    src = tmp_path / "src"
    _build_layer(src, "repositories", ["posts"], parent_files=["base.py"])
    f = _write(
        src / "repositories" / "posts" / "post_repository.py",
        "from ..base import BaseRepository\n",
    )

    assert find_violations([f], src) == []


def test_parent_level_file_is_not_lint_subject(tmp_path: Path) -> None:
    """Files at the layer's parent level have no cluster — they are the shared tier
    and may import anywhere in the layer (audit.py orchestrates across clusters)."""
    src = tmp_path / "src"
    _build_layer(src, "logic", ["posts", "providers"], parent_files=["audit.py"])
    f = _write(
        src / "logic" / "audit.py",
        "from src.logic.posts.handler import x\n"
        "from src.logic.providers.handler import y\n",
    )

    assert find_violations([f], src) == []


def test_unclustered_layer_is_skipped(tmp_path: Path) -> None:
    """Layers not in _CLUSTERED_LAYERS (e.g. api/, core/) aren't checked."""
    src = tmp_path / "src"
    api = src / "api" / "routes"
    api.mkdir(parents=True)
    f = _write(api / "posts.py", "from src.api.routes.providers import x\n")

    assert find_violations([f], src) == []


def test_module_starting_with_underscore_is_not_a_cluster(tmp_path: Path) -> None:
    """Auto-discovery skips dunder/underscore directories — `__pycache__` etc."""
    src = tmp_path / "src"
    layer_root = src / "schemas"
    layer_root.mkdir(parents=True)
    (layer_root / "__pycache__").mkdir()
    _write(layer_root / "_validators.py", "")
    _write(layer_root / "posts" / "_placeholder.py", "")

    f = _write(
        src / "schemas" / "posts" / "post.py",
        "from src.schemas._validators import StrippedText\n",
    )

    assert find_violations([f], src) == []


def test_multiple_violations_in_one_file(tmp_path: Path) -> None:
    src = tmp_path / "src"
    _build_layer(src, "logic", ["posts", "providers", "users"])
    body = "from src.logic.providers.x import a\n" "from src.logic.users.y import b\n"
    f = _write(src / "logic" / "posts" / "post_processing.py", body)

    violations = find_violations([f], src)

    assert len(violations) == 2
    assert {v.target_cluster for v in violations} == {"providers", "users"}

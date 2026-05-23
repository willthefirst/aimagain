"""Re-export shim for the route-mount machinery.

The implementation lives in :mod:`src.framework.dispatch.mounts` —
one file per verb (`mount_create`, `mount_list`, …) plus the
`mount_entity` orchestrator, with shared helpers in `_spec.py`,
`_synth.py`, and `_common.py`. See ``mounts/README.md`` for the
per-file layout.

This module exists to keep the long-standing import path
``src.framework.dispatch.resource_routes`` working for every external
caller (route files, ``filters.py``, tests, contract-test patches
against the private state-axis self-guard).
"""

from src.framework.dispatch.mounts._spec import QueryParam, ResourceSpec
from src.framework.dispatch.mounts._synth import MountError
from src.framework.dispatch.mounts.create import mount_create
from src.framework.dispatch.mounts.delete import mount_delete
from src.framework.dispatch.mounts.detail import mount_detail
from src.framework.dispatch.mounts.edge import mount_edge_routes
from src.framework.dispatch.mounts.entity import mount_entity
from src.framework.dispatch.mounts.form import mount_form
from src.framework.dispatch.mounts.list_ import mount_list
from src.framework.dispatch.mounts.related_list import mount_related_list
from src.framework.dispatch.mounts.search import mount_search
from src.framework.dispatch.mounts.state_axis import (
    _wrap_state_axis_with_self_guard,
    mount_state_axis,
)
from src.framework.dispatch.mounts.update import mount_update

# `APIResponse` is re-exported here so tests that monkeypatch
# ``src.framework.dispatch.resource_routes.APIResponse.html_response``
# keep resolving. The patches mutate the class (shared across all
# per-verb modules that import it), so a single re-export is enough.
from src.framework.http.responses import APIResponse  # noqa: F401

__all__ = [
    "MountError",
    "QueryParam",
    "ResourceSpec",
    "_wrap_state_axis_with_self_guard",
    "mount_create",
    "mount_delete",
    "mount_detail",
    "mount_edge_routes",
    "mount_entity",
    "mount_form",
    "mount_list",
    "mount_related_list",
    "mount_search",
    "mount_state_axis",
    "mount_update",
]

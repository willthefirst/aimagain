"""Generic registry for a polymorphic entity's discriminator values.

Posts is the only consumer today (`posts/post_kinds.py`). The registry
itself is post-agnostic: each polymorphic entity defines its own per-row
Spec dataclass with whatever fields it needs (detail model, templates,
labels, ...) and constructs a `DiscriminatorRegistry[<EntitySpec>]`
keyed by the discriminator value. Shared machinery — name lookup, names
tuple, CHECK SQL fragment, custom reverse indexes — lives here so a
second polymorphic entity is a clean import rather than a re-derivation.
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Generic, TypeVar

S = TypeVar("S")
K = TypeVar("K")


@dataclass(frozen=True)
class DiscriminatorRegistry(Generic[S]):
    column: str
    specs: dict[str, S]

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self.specs)

    def __getitem__(self, name: str) -> S:
        return self.specs[name]

    def get(self, name: str) -> S | None:
        return self.specs.get(name)

    def values(self) -> Iterable[S]:
        return self.specs.values()

    def items(self) -> Iterable[tuple[str, S]]:
        return self.specs.items()

    def __iter__(self):
        return iter(self.specs)

    def check_sql(self) -> str:
        """SQL fragment for a `<column> IN (...)` CHECK constraint."""
        return f"{self.column} IN (" + ", ".join(repr(n) for n in self.names) + ")"

    def reverse_index(self, key: Callable[[S], K]) -> dict[K, S]:
        """Build a `{key(spec): spec}` dict. Caller chooses the key
        function — e.g. `lambda s: s.detail_model` for the post pattern.
        Last-wins on collisions, matching plain dict-comprehension
        semantics; the post registry's detail-model values are unique by
        construction."""
        return {key(s): s for s in self.specs.values()}

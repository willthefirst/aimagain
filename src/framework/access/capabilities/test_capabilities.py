"""Tests for `src/framework/capabilities.py` — the framework-layer tree primitives.

Only the structural / evaluation logic is covered here. Domain predicates
(`check_can_read_feed`, etc.) are tested in
`src/domain/logic/test_capabilities.py`.
"""

from __future__ import annotations

import pytest

from src.framework.access.capabilities.capabilities import (
    Bundle,
    CapabilityCheck,
    Condition,
    Gate,
    Leaf,
    LeafRegistry,
)


def _met(label: str = "met") -> Condition:
    return Condition(label_active=label, label_done=label, met=True, fix_url="/fix")


def _unmet(label: str = "unmet") -> Condition:
    return Condition(label_active=label, label_done=label, met=False, fix_url="/fix")


# ---------- Bundle (AND) ---------------------------------------------------


def test_bundle_all_met_is_true():
    b = Bundle(label_active="b", label_done="b", children=(_met(), _met()))
    assert b.met is True


def test_bundle_any_unmet_is_false():
    b = Bundle(label_active="b", label_done="b", children=(_met(), _unmet()))
    assert b.met is False


def test_bundle_all_unmet_is_false():
    b = Bundle(label_active="b", label_done="b", children=(_unmet(), _unmet()))
    assert b.met is False


def test_bundle_empty_is_true():
    """Vacuous truth: an empty AND is True."""
    assert Bundle(label_active="empty", label_done="empty", children=()).met is True


# ---------- Gate (OR) ------------------------------------------------------


def test_gate_any_met_is_true():
    g = Gate(label_active="g", label_done="g", children=(_unmet(), _met()))
    assert g.met is True


def test_gate_all_unmet_is_false():
    g = Gate(label_active="g", label_done="g", children=(_unmet(), _unmet()))
    assert g.met is False


def test_gate_all_met_is_true():
    g = Gate(label_active="g", label_done="g", children=(_met(), _met()))
    assert g.met is True


def test_gate_empty_is_false():
    """Vacuous falsity: an empty OR is False."""
    assert Gate(label_active="empty", label_done="empty", children=()).met is False


# ---------- CapabilityCheck ------------------------------------------------


def test_capability_check_description_defaults_to_none():
    assert CapabilityCheck(name="x", tree=_met()).description is None


def test_capability_check_accepts_description():
    check = CapabilityCheck(name="x", tree=_met(), description="Some text")
    assert check.description == "Some text"


def test_capability_check_granted_delegates_to_tree_met():
    check_granted = CapabilityCheck(name="x", tree=_met())
    assert check_granted.granted is True

    check_denied = CapabilityCheck(name="x", tree=_unmet())
    assert check_denied.granted is False


def test_capability_check_granted_uses_bundle_met():
    tree = Bundle(label_active="root", label_done="root", children=(_met(), _met()))
    assert CapabilityCheck(name="x", tree=tree).granted is True

    tree_fail = Bundle(
        label_active="root", label_done="root", children=(_met(), _unmet())
    )
    assert CapabilityCheck(name="x", tree=tree_fail).granted is False


def test_capability_check_granted_uses_gate_met():
    tree = Gate(label_active="root", label_done="root", children=(_unmet(), _met()))
    assert CapabilityCheck(name="x", tree=tree).granted is True

    tree_fail = Gate(
        label_active="root", label_done="root", children=(_unmet(), _unmet())
    )
    assert CapabilityCheck(name="x", tree=tree_fail).granted is False


def test_capability_check_has_no_out_of_band_override():
    """`granted` is exactly the tree's met state — no bypass field.
    Administrative overrides are modeled INSIDE the tree by the domain
    (an OR `Gate` with the override condition), so the rendered tree
    can never contradict the granted verdict."""
    assert CapabilityCheck(name="x", tree=_met()).granted is True
    assert CapabilityCheck(name="x", tree=_unmet()).granted is False
    assert not hasattr(CapabilityCheck(name="x", tree=_met()), "bypass")


def test_override_modeled_as_gate_grants_with_unmet_requirements():
    """The in-tree override shape: Gate(requirements, override). An unmet
    requirements bundle with a met override condition grants — and the
    tree itself shows why."""
    tree = Gate(label_active="cap", label_done="cap", children=(_unmet(), _met()))
    check = CapabilityCheck(name="x", tree=tree)
    assert check.granted is True
    assert check.tree.children[0].met is False  # real requirements still unmet


# ---------- nested tree evaluation ----------------------------------------


def test_nested_bundle_inside_gate():
    """Gate OR (Bundle AND (met, unmet), met) → True because the second Gate
    child is met."""
    inner = Bundle(
        label_active="inner", label_done="inner", children=(_met(), _unmet())
    )
    g = Gate(label_active="root", label_done="root", children=(inner, _met()))
    assert g.met is True


def test_nested_gate_inside_bundle():
    """Bundle AND (met, Gate OR (unmet, unmet)) → False because the Gate
    fails."""
    inner = Gate(
        label_active="inner", label_done="inner", children=(_unmet(), _unmet())
    )
    b = Bundle(label_active="root", label_done="root", children=(_met(), inner))
    assert b.met is False


# ---------- Leaf -----------------------------------------------------------


def _leaf(
    name: str = "x",
    predicate=lambda a: True,
    requires: tuple[Leaf, ...] = (),
) -> Leaf:
    return Leaf(
        name=name,
        label_active=f"Do {name}",
        label_done=f"{name} done",
        fix_url=f"/fix/{name}",
        predicate=predicate,
        requires=requires,
    )


def test_leaf_evaluate_returns_condition_with_canonical_copy():
    """`evaluate(actor)` packages the leaf's `(label_active, label_done,
    fix_url)` into a `Condition` whose `met` reflects the predicate."""
    cond = _leaf(predicate=lambda a: True).evaluate(actor="anything")
    assert isinstance(cond, Condition)
    assert cond.label_active == "Do x"
    assert cond.label_done == "x done"
    assert cond.fix_url == "/fix/x"
    assert cond.met is True


def test_leaf_evaluate_predicate_receives_actor():
    """The predicate is invoked with the actor passed to `evaluate`."""
    seen: list = []

    def pred(actor):
        seen.append(actor)
        return False

    _leaf(predicate=pred).evaluate(actor="sentinel")
    assert seen == ["sentinel"]


def test_leaf_evaluate_coerces_truthy_predicate_to_bool():
    """A predicate that returns a non-bool truthy value (e.g. a list) still
    produces a bool `Condition.met` — Conditions hold strict bool."""
    cond = _leaf(predicate=lambda a: [1, 2, 3]).evaluate(actor=None)
    assert cond.met is True
    assert isinstance(cond.met, bool)


def test_leaf_evaluate_coerces_falsy_predicate_to_bool():
    cond = _leaf(predicate=lambda a: []).evaluate(actor=None)
    assert cond.met is False
    assert isinstance(cond.met, bool)


# ---------- Leaf.requires / evaluate_chain --------------------------------


def test_leaf_requires_defaults_to_empty_tuple():
    """Leaves with no upstream dependencies don't have to declare
    `requires` — the default matches the existing single-leaf shape."""
    assert _leaf().requires == ()


def test_leaf_evaluate_chain_no_requires_returns_self_only():
    """A leaf with no `requires` returns just its own `Condition` — same
    boolean as `evaluate()`, just wrapped in a one-tuple so callers can
    splat uniformly."""
    leaf = _leaf(name="x", predicate=lambda a: True)
    chain = leaf.evaluate_chain(actor=None)
    assert len(chain) == 1
    assert chain[0].label_active == "Do x"
    assert chain[0].met is True


def test_leaf_evaluate_chain_one_requires_emits_dep_first():
    """`A.requires = (B,)` → `A.evaluate_chain()` yields `(B_cond,
    A_cond)`. Dep-first order matches reading the UI top-to-bottom:
    prerequisites appear above the dependent step."""
    b = _leaf(name="b", predicate=lambda a: True)
    a = _leaf(name="a", predicate=lambda a: False, requires=(b,))
    chain = a.evaluate_chain(actor=None)
    assert [c.label_active for c in chain] == ["Do b", "Do a"]
    assert [c.met for c in chain] == [True, False]


def test_leaf_evaluate_chain_transitive_requires():
    """A→B→C: `A.evaluate_chain()` yields `(C, B, A)`. The chain is the
    full transitive closure so a consumer only ever names the top of
    the chain to pull in everything below it."""
    c = _leaf(name="c")
    b = _leaf(name="b", requires=(c,))
    a = _leaf(name="a", requires=(b,))
    chain = a.evaluate_chain(actor=None)
    assert [cnd.label_active for cnd in chain] == ["Do c", "Do b", "Do a"]


def test_leaf_evaluate_chain_dedupes_shared_dep():
    """A.requires=(C,), B.requires=(C,), and a Bundle wants both: each
    leaf's own chain still includes C. The chain dedupes within a
    single `evaluate_chain` call by leaf name — and tree-level dedup
    across siblings is the composer's responsibility (Bundle's
    children are listed once)."""
    c = _leaf(name="c")
    a = _leaf(name="a", requires=(c, c))  # accidental double-require
    chain = a.evaluate_chain(actor=None)
    assert [cnd.label_active for cnd in chain] == ["Do c", "Do a"]


def test_leaf_evaluate_chain_diamond_dedupes_by_name():
    """A.requires=(B, C); B.requires=(D,); C.requires=(D,): D is shared
    so it appears once. Order: D before B and C; A last."""
    d = _leaf(name="d")
    b = _leaf(name="b", requires=(d,))
    c = _leaf(name="c", requires=(d,))
    a = _leaf(name="a", requires=(b, c))
    chain = a.evaluate_chain(actor=None)
    labels = [cnd.label_active for cnd in chain]
    assert labels == ["Do d", "Do b", "Do c", "Do a"]


def test_leaf_evaluate_chain_passes_actor_to_every_predicate():
    """Every leaf in the chain — including transitive prereqs — sees
    the same actor passed to `evaluate_chain`."""
    seen: list = []

    def record(name):
        def pred(actor):
            seen.append((name, actor))
            return True

        return pred

    c = _leaf(name="c", predicate=record("c"))
    b = _leaf(name="b", predicate=record("b"), requires=(c,))
    a = _leaf(name="a", predicate=record("a"), requires=(b,))
    a.evaluate_chain(actor="sentinel")
    assert seen == [("c", "sentinel"), ("b", "sentinel"), ("a", "sentinel")]


# ---------- LeafRegistry --------------------------------------------------


def test_registry_register_and_get_roundtrip():
    reg = LeafRegistry()
    leaf = _leaf(name="email")
    assert reg.register(leaf) is leaf
    assert reg.get("email") is leaf


def test_registry_register_rejects_duplicate_name():
    """Re-registering the same name raises — a typo or accidental
    re-import can't silently shadow an existing fact."""
    reg = LeafRegistry()
    reg.register(_leaf(name="email"))
    with pytest.raises(ValueError, match="email"):
        reg.register(_leaf(name="email"))


def test_registry_get_unknown_raises_key_error():
    """Callers reference leaves by literal name, so a miss is a domain
    bug — surface it as KeyError, not None."""
    reg = LeafRegistry()
    with pytest.raises(KeyError):
        reg.get("nope")


def test_registry_all_returns_immutable_tuple_in_insertion_order():
    """`.all()` is the introspection surface — returns a tuple snapshot
    so a caller can't mutate the registry through it."""
    reg = LeafRegistry()
    a = reg.register(_leaf(name="a"))
    b = reg.register(_leaf(name="b"))
    c = reg.register(_leaf(name="c"))
    snapshot = reg.all()
    assert isinstance(snapshot, tuple)
    assert snapshot == (a, b, c)


def test_registry_all_snapshot_unaffected_by_later_register():
    """A snapshot taken before a new registration doesn't include the
    new leaf — tuples are immutable."""
    reg = LeafRegistry()
    reg.register(_leaf(name="a"))
    early = reg.all()
    reg.register(_leaf(name="b"))
    assert len(early) == 1
    assert len(reg.all()) == 2

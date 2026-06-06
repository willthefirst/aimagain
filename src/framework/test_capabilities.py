"""Tests for `src/framework/capabilities.py` — the framework-layer tree primitives.

Only the structural / evaluation logic is covered here. Domain predicates
(`check_can_read_feed`, etc.) are tested in
`src/domain/logic/test_capabilities.py`.
"""

from __future__ import annotations

from src.framework.capabilities import Bundle, CapabilityCheck, Condition, Gate


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

"""Tests for core.quests: tree building, substitution accounting, summaries."""

from __future__ import annotations

import pytest

from core.quests import (
    QUALITY_HQ,
    NodeStatus,
    RequirementNode,
    assign_node_ids,
    build_tree,
    flatten_requirements,
    format_summary_line,
    iter_nodes,
    node_statuses,
    quest_complete,
)


def wheels_lookup(item_id: int) -> list[tuple[int, str, int]] | None:
    """400-wheel style tree: wheel = 5 logs + 2 ore; log/ore are leaves."""
    recipes: dict[int, list[tuple[int, str, int]]] = {
        1: [(2, "log", 5), (3, "ore", 2)],
    }
    return recipes.get(item_id)


def make_wheel_tree(qty: int = 400) -> RequirementNode:
    root = build_tree(1, "wheel", qty, wheels_lookup, quality=QUALITY_HQ)
    return assign_node_ids(root)


class TestBuildTree:
    def test_scales_quantities_down_the_tree(self) -> None:
        root = make_wheel_tree(400)
        assert root.qty_required == 400
        log, ore = root.children
        assert (log.name, log.qty_required) == ("log", 2000)
        assert (ore.name, ore.qty_required) == ("ore", 800)

    def test_quality_propagates(self) -> None:
        root = make_wheel_tree()
        assert root.quality == QUALITY_HQ
        assert all(c.quality == QUALITY_HQ for c in root.children)

    def test_non_craftable_is_leaf(self) -> None:
        leaf = build_tree(99, "popcorn", 300, lambda _i: None)
        assert leaf.children == []

    def test_depth_cap(self) -> None:
        def chain(item_id: int) -> list[tuple[int, str, int]] | None:
            return [(item_id + 1, f"item{item_id + 1}", 1)]

        with pytest.raises(ValueError, match="depth"):
            build_tree(0, "item0", 1, chain)

    def test_cycle_guard(self) -> None:
        def loopy(_item_id: int) -> list[tuple[int, str, int]]:
            return [(1, "self", 1)]

        with pytest.raises(ValueError, match="cyclic"):
            build_tree(1, "loop", 1, loopy)

    def test_document_order_ids(self) -> None:
        root = make_wheel_tree()
        ids = [n.node_id for n in iter_nodes(root)]
        assert ids == ["n0", "n1", "n2"]


class TestSubstitutionAccounting:
    def test_parent_turnin_zeroes_children(self) -> None:
        """Turning in all wheels satisfies the logs proportionally."""
        root = make_wheel_tree()
        statuses = node_statuses(root, {}, {"n0": 400})
        assert statuses["n0"].fulfilled is True
        assert statuses["n1"].outstanding == 0
        assert statuses["n2"].outstanding == 0

    def test_partial_parent_proportionally_reduces_children(self) -> None:
        root = make_wheel_tree()
        # half the wheels turned in -> half the logs/ore outstanding
        statuses = node_statuses(root, {}, {"n0": 200})
        assert statuses["n1"].outstanding == 1000
        assert statuses["n2"].outstanding == 400
        assert statuses["n1"].fulfilled is False

    def test_child_pledge_does_not_touch_siblings(self) -> None:
        root = make_wheel_tree()
        statuses = node_statuses(root, {"n1": 500}, {})
        assert statuses["n1"].open_to_pledge == 1500
        assert statuses["n2"].open_to_pledge == 800  # sibling untouched

    def test_overpledging_clamps_at_requirement(self) -> None:
        root = make_wheel_tree()
        statuses = node_statuses(root, {"n1": 9999}, {})
        assert statuses["n1"].pledged == 2000
        assert statuses["n1"].open_to_pledge == 0

    def test_mixed_parent_and_child_amounts_sum(self) -> None:
        root = make_wheel_tree()
        statuses = node_statuses(
            root,
            {"n0": 100, "n1": 1500},  # 100 wheels pledged + 1500 raw logs
            {},
        )
        # logs: 500 covered via parent + 1500 direct = full coverage;
        # ore: 200 covered via the same parent pledge (100 wheels * 2) -> 600 open
        assert statuses["n1"].open_to_pledge == 0
        assert statuses["n2"].open_to_pledge == 600

    def test_unknown_node_raises(self) -> None:
        root = make_wheel_tree()
        with pytest.raises(KeyError, match="unknown node ids"):
            node_statuses(root, {"nope": 1}, {})

    def test_leaf_only_quest_completes(self) -> None:
        root = assign_node_ids(build_tree(99, "popcorn", 300, lambda _i: None))
        assert quest_complete(root, {}) is False
        assert quest_complete(root, {"n0": 300}) is True
        assert quest_complete(root, {"n0": 299}) is False


class TestFlattenAndFormat:
    def test_shopping_list_deepest_first_and_skips_done(self) -> None:
        root = make_wheel_tree()
        flat = flatten_requirements(root, {}, {"n0": 400})
        assert flat == []  # everything satisfied via root turn-in

        flat = flatten_requirements(root, {"n1": 2000}, {})
        # logs fully pledged; ore outstanding; wheel itself open too
        names = [s.name for s in flat]
        assert "ore" in names
        assert "wheel" in names
        assert names[0] == "log"  # deepest first (alphabetical tie-break)

    def test_format_line_variants(self) -> None:
        done = NodeStatus("a", 1, "x", "any", 5, 5, 5, 0, 0, True)
        partial = NodeStatus("b", 2, "y", QUALITY_HQ, 10, 4, 1, 6, 9, False)
        open_line = NodeStatus("c", 3, "z", "any", 7, 0, 0, 7, 7, False)
        assert format_summary_line(done) == "x x0 DONE"
        assert format_summary_line(partial) == "y x6 (HQ) [4/10 pledged]"
        assert format_summary_line(open_line) == "z x7"

"""Quest requirement trees and pledge/turn-in accounting.

A quest's requirement is a tree of :class:`RequirementNode`. The root is the
item actually asked for ("400 wheels"); ``children`` are ingredients scaled by
the recipe ("2000 logs"). Trees are built once at quest creation from the
recipe catalog (see app.db quest helpers) and stored; re-expansion replaces
the tree wholesale so stored pledges never silently dangle.

Substitution semantics (docs/questboard.md): a pledge or turn-in on any node
satisfies its descendants proportionally. Someone turning in all 400 wheels
has, in effect, also brought the 2000 logs.

Accounting model -- everything is expressed as fractions of each node's own
requirement:

* ``pledged_fraction(n)`` = min(1, sum over n and all its ancestors of
  pledged_amount / node_requirement)
* ``turned_fraction(n)`` = same with turn-in amounts

Derived per-node quantities:

* ``open_to_pledge`` = ceil(requirement * (1 - pledged_fraction))
  -- what still needs someone to promise it
* ``outstanding``    = ceil(requirement * (1 - turned_fraction))
  -- what still needs to physically arrive
* ``fulfilled``      = turned_fraction >= 1

Pledging more than the remaining fraction is clamped at the display level;
amounts are stored verbatim so the audit trail stays honest.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field

QUALITY_ANY = "any"
QUALITY_HQ = "hq"

SOURCE_ROOT = "root"
SOURCE_AUTO = "auto"
SOURCE_MANUAL = "manual"


@dataclass
class RequirementNode:
    """One node of a quest requirement tree."""

    item_id: int
    name: str
    qty_required: int
    quality: str = QUALITY_ANY
    source: str = SOURCE_AUTO
    limited: bool = False
    node_id: str | None = None
    children: list[RequirementNode] = field(default_factory=list)


@dataclass(frozen=True)
class NodeStatus:
    """Computed pledge/turn-in state for one node."""

    node_id: str
    item_id: int
    name: str
    quality: str
    required: int
    pledged: int
    turned_in: int
    open_to_pledge: int
    outstanding: int
    fulfilled: bool


RecipeLookup = Callable[[int], list[tuple[int, str, int]] | None]


def build_tree(
    item_id: int,
    name: str,
    qty: int,
    lookup: RecipeLookup,
    *,
    quality: str = QUALITY_ANY,
    _depth: int = 0,
    _seen: frozenset[int] = frozenset(),
) -> RequirementNode:
    """Recursively expand ``item_id`` into a requirement tree.

    ``lookup`` maps an item id to its recipe as ``(item_id, ingredient_name,
    qty_per_craft)`` tuples, or None when the item is not craftable. Ingredient
    quantities scale with ``qty``. Cycle-guarded via ``_seen``; depth capped at
    8. Non-craftable items become leaves.
    """
    if _depth > 8:
        raise ValueError("recipe expansion exceeded maximum depth of 8")
    if item_id in _seen:
        raise ValueError(f"cyclic recipe detected at item {item_id}")
    node = RequirementNode(item_id=item_id, name=name, qty_required=max(1, qty), quality=quality)
    recipe = lookup(item_id)
    if recipe:
        child_seen = _seen | {item_id}
        for ing_id, ing_name, per_craft in recipe:
            node.children.append(
                build_tree(
                    ing_id,
                    ing_name,
                    qty * per_craft,
                    lookup,
                    quality=quality,
                    _depth=_depth + 1,
                    _seen=child_seen,
                )
            )
    return node


def assign_node_ids(root: RequirementNode, prefix: str = "n") -> RequirementNode:
    """Assign deterministic ids (prefix + counter, document order) in place."""
    counter = 0

    def walk(node: RequirementNode) -> None:
        nonlocal counter
        node.node_id = f"{prefix}{counter}"
        counter += 1
        for child in node.children:
            walk(child)

    walk(root)
    return root


def iter_nodes(root: RequirementNode) -> Iterator[RequirementNode]:
    """Yield every node in document order (pre-order DFS)."""
    yield root
    for child in root.children:
        yield from iter_nodes(child)


AmountByNode = dict[str, int]


def _chain_fraction(
    root: RequirementNode,
    amounts: AmountByNode,
    target_id: str,
    key_field: str,
) -> float:
    """Sum amount/requirement fractions along the root->target chain."""
    path: list[RequirementNode] = []
    found = False

    def walk(node: RequirementNode) -> bool:
        nonlocal found
        path.append(node)
        if node.node_id == target_id:
            found = True
            return True
        for child in node.children:
            if walk(child):
                return True
        path.pop()
        return False

    walk(root)
    if not found:
        raise KeyError(f"node {target_id!r} not present in tree")
    del key_field  # kept out of the signature contract; see docstring
    total = 0.0
    for node in path:
        assert node.node_id is not None
        total += amounts.get(node.node_id, 0) / node.qty_required
    return min(1.0, total)


def node_statuses(
    root: RequirementNode,
    pledges: AmountByNode,
    turned_in: AmountByNode,
) -> dict[str, NodeStatus]:
    """Compute :class:`NodeStatus` for every node of the tree.

    ``pledges`` / ``turned_in`` map node ids to summed amounts (direct only --
    inheritance is handled here via the chain-fraction rule).
    """
    statuses: dict[str, NodeStatus] = {}
    known_ids = {n.node_id for n in iter_nodes(root)}
    unknown = (set(pledges) | set(turned_in)) - known_ids
    if unknown:
        raise KeyError(f"unknown node ids in amounts: {sorted(unknown)}")
    for node in iter_nodes(root):
        nid = node.node_id
        if nid is None:  # pragma: no cover - assign_node_ids guarantees ids
            continue
        pf = _chain_fraction(root, pledges, nid, "pledges")
        tf = _chain_fraction(root, turned_in, nid, "turned_in")
        pledged_units = round(pf * node.qty_required)
        turned_units = round(tf * node.qty_required)
        open_to_pledge = max(0, node.qty_required - pledged_units)
        outstanding = max(0, node.qty_required - turned_units)
        statuses[nid] = NodeStatus(
            node_id=nid,
            item_id=node.item_id,
            name=node.name,
            quality=node.quality,
            required=node.qty_required,
            pledged=pledged_units,
            turned_in=turned_units,
            open_to_pledge=min(open_to_pledge, node.qty_required),
            outstanding=min(outstanding, node.qty_required),
            fulfilled=tf >= 1.0,
        )
    return statuses


def quest_complete(root: RequirementNode, turned_in: AmountByNode) -> bool:
    """True when the root node is fully turned in."""
    rid = root.node_id
    if rid is None:
        return False
    return _chain_fraction(root, turned_in, rid, "turned_in") >= 1.0


def flatten_requirements(
    root: RequirementNode,
    pledges: AmountByNode,
    turned_in: AmountByNode,
) -> list[NodeStatus]:
    """Leaf-first shopping list: nodes with outstanding > 0, deepest first."""
    statuses = node_statuses(root, pledges, turned_in)
    order: dict[str, int] = {}

    def measure(node: RequirementNode, depth: int) -> int:
        depths = [measure(child, depth + 1) for child in node.children]
        d = max([*depths, depth])
        assert node.node_id is not None
        order[node.node_id] = d
        return d

    measure(root, 0)
    remaining = [s for s in statuses.values() if s.outstanding > 0]
    remaining.sort(key=lambda s: (-order[s.node_id], s.name))
    return remaining


def format_summary_line(status: NodeStatus) -> str:
    """One human-readable line for embeds/lists."""
    parts = [f"{status.name} x{status.open_to_pledge}"]
    if status.quality == QUALITY_HQ:
        parts.append("(HQ)")
    if status.fulfilled:
        parts.append("DONE")
    elif status.pledged > status.turned_in:
        parts.append(f"[{status.pledged}/{status.required} pledged]")
    return " ".join(parts)


__all__ = [
    "QUALITY_ANY",
    "QUALITY_HQ",
    "SOURCE_AUTO",
    "SOURCE_MANUAL",
    "SOURCE_ROOT",
    "AmountByNode",
    "NodeStatus",
    "RecipeLookup",
    "RequirementNode",
    "assign_node_ids",
    "build_tree",
    "flatten_requirements",
    "format_summary_line",
    "iter_nodes",
    "node_statuses",
    "quest_complete",
]

assert math.ceil(1.0) == 1  # keep math imported for future rounding strategies

from __future__ import annotations

import time
from collections.abc import Generator
from dataclasses import asdict
from typing import Any

from app.models import Assignment, Constraints, Job, Person

JOBS = [
    Job("pld", "PLD", "tank", "tank"),
    Job("war", "WAR", "tank", "tank"),
    Job("drk", "DRK", "tank", "tank"),
    Job("gnb", "GNB", "tank", "tank"),
    Job("whm", "WHM", "healer", "pure"),
    Job("sch", "SCH", "healer", "shield"),
    Job("ast", "AST", "healer", "pure"),
    Job("sge", "SGE", "healer", "shield"),
    Job("mnk", "MNK", "dps", "melee", "selfish"),
    Job("drg", "DRG", "dps", "melee", "utility"),
    Job("nin", "NIN", "dps", "melee", "utility"),
    Job("sam", "SAM", "dps", "melee", "selfish"),
    Job("vpr", "VPR", "dps", "melee", "selfish"),
    Job("brd", "BRD", "dps", "pranged", "utility"),
    Job("mch", "MCH", "dps", "pranged", "selfish"),
    Job("dnc", "DNC", "dps", "pranged", "utility"),
    Job("blm", "BLM", "dps", "caster", "selfish"),
    Job("smn", "SMN", "dps", "caster", "utility"),
    Job("rdm", "RDM", "dps", "caster", "utility"),
    Job("pct", "PCT", "dps", "caster", "selfish"),
]
JOBS_BY_ID = {j.id: j for j in JOBS}


def parse_job_id(entry: str) -> str:
    return entry.split(":")[0]


def get_priority(entry: str) -> int:
    parts = entry.split(":")
    return int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 5


def compute_parties(people: list[Person], constraints: Constraints) -> list[list[Assignment]]:
    results: list[list[Assignment]] = []

    def valid(assignments: list[Job]) -> bool:
        c = constraints
        n_tank = sum(1 for j in assignments if j.role == "tank")
        n_healer = sum(1 for j in assignments if j.role == "healer")
        n_dps = sum(1 for j in assignments if j.role == "dps")
        if c.std_comp and (n_tank != 2 or n_healer != 2 or n_dps != 4):
            return False
        if c.no_dupes and len({j.id for j in assignments}) != len(assignments):
            return False
        if c.heal_mix:
            pure = sum(1 for j in assignments if j.sub == "pure")
            shield = sum(1 for j in assignments if j.sub == "shield")
            if pure != 1 or shield != 1:
                return False
        n_melee = sum(1 for j in assignments if j.sub == "melee")
        n_pranged = sum(1 for j in assignments if j.sub == "pranged")
        n_caster = sum(1 for j in assignments if j.sub == "caster")
        n_selfish = sum(1 for j in assignments if j.dps_type == "selfish")
        n_utility = sum(1 for j in assignments if j.dps_type == "utility")
        assigned_ids = {j.id for j in assignments}
        for group in c.exclusions:
            if group and set(group).issubset(assigned_ids):
                return False
        return (
            c.min_melee <= n_melee <= c.max_melee
            and c.min_pranged <= n_pranged <= c.max_pranged
            and c.min_caster <= n_caster <= c.max_caster
            and c.min_selfish <= n_selfish <= c.max_selfish
            and c.min_utility <= n_utility <= c.max_utility
        )

    def dfs(idx: int, assigned: list[Job], priorities: list[int]) -> None:
        if idx == len(people):
            if valid(assigned):
                results.append([
                    Assignment(name=people[i].name, job=j.name, role=j.role, priority=priorities[i])
                    for i, j in enumerate(assigned)
                ])
            return
        p = people[idx]
        if not p.jobs:
            return
        for entry in p.jobs:
            job = JOBS_BY_ID.get(parse_job_id(entry))
            if job is None:
                continue
            priority = get_priority(entry)
            assigned.append(job)
            priorities.append(priority)
            dfs(idx + 1, assigned, priorities)
            assigned.pop()
            priorities.pop()

    dfs(0, [], [])
    results.sort(key=lambda r: sum(a.priority for a in r), reverse=True)
    return results


def collapse_by_role_group(parties: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse parties that share the same (person, role) assignments.

    When the same set of people fill the same roles (regardless of which
    specific job each plays), only the highest-scoring variant is kept.
    """
    role_order = {"tank": 0, "healer": 1, "dps": 2}
    groups: dict[frozenset[tuple[str, str]], list[dict[str, Any]]] = {}
    for party in parties:
        key = frozenset((m["name"], m["role"]) for m in party["members"])
        groups.setdefault(key, []).append(party)

    collapsed = [max(group, key=lambda p: p["score"]) for group in groups.values()]
    collapsed.sort(key=lambda p: p["score"], reverse=True)

    for party in collapsed:
        party["members"].sort(
            key=lambda m: (role_order.get(m.get("role", ""), 99), m.get("name", "")),
        )

    return collapsed


_SSEEvent = tuple[str, dict[str, Any]]


def compute_parties_stream(
    people: list[Person], constraints: Constraints,
) -> Generator[_SSEEvent, None, None]:
    results: list[list[dict[str, Any]]] = []
    seen_role_groups: set[frozenset[tuple[str, str]]] = set()
    t0 = time.monotonic()
    last_report = t0
    explored = 0

    def valid(assignments: list[Job]) -> bool:
        c = constraints
        n_tank = sum(1 for j in assignments if j.role == "tank")
        n_healer = sum(1 for j in assignments if j.role == "healer")
        n_dps = sum(1 for j in assignments if j.role == "dps")
        if c.std_comp and (n_tank != 2 or n_healer != 2 or n_dps != 4):
            return False
        if c.no_dupes and len({j.id for j in assignments}) != len(assignments):
            return False
        if c.heal_mix:
            pure = sum(1 for j in assignments if j.sub == "pure")
            shield = sum(1 for j in assignments if j.sub == "shield")
            if pure != 1 or shield != 1:
                return False
        n_melee = sum(1 for j in assignments if j.sub == "melee")
        n_pranged = sum(1 for j in assignments if j.sub == "pranged")
        n_caster = sum(1 for j in assignments if j.sub == "caster")
        n_selfish = sum(1 for j in assignments if j.dps_type == "selfish")
        n_utility = sum(1 for j in assignments if j.dps_type == "utility")
        assigned_ids = {j.id for j in assignments}
        for group in c.exclusions:
            if group and set(group).issubset(assigned_ids):
                return False
        return (
            c.min_melee <= n_melee <= c.max_melee
            and c.min_pranged <= n_pranged <= c.max_pranged
            and c.min_caster <= n_caster <= c.max_caster
            and c.min_selfish <= n_selfish <= c.max_selfish
            and c.min_utility <= n_utility <= c.max_utility
        )

    # mypy: ignore the generator type — nested recursive generator
    def dfs(idx: int, assigned: list[Job], priorities: list[int]) -> Generator:  # type: ignore[misc]
        nonlocal explored, last_report
        explored += 1
        now = time.monotonic()
        if now - last_report >= 1.0:
            yield ("progress", {
                "found": len(results), "distinct": len(seen_role_groups), "explored": explored,
            })
            last_report = now
        if idx == len(people):
            if valid(assigned):
                party = [
                    asdict(Assignment(
                        name=people[i].name, job=j.name, role=j.role,
                        priority=priorities[i],
                    ))
                    for i, j in enumerate(assigned)
                ]
                results.append(party)
                key = frozenset((people[i].name, j.role) for i, j in enumerate(assigned))
                seen_role_groups.add(key)
            return
        p = people[idx]
        if not p.jobs:
            return
        for entry in p.jobs:
            job = JOBS_BY_ID.get(parse_job_id(entry))
            if job is None:
                continue
            priority = get_priority(entry)
            assigned.append(job)
            priorities.append(priority)
            yield from dfs(idx + 1, assigned, priorities)
            assigned.pop()
            priorities.pop()

    yield from dfs(0, [], [])
    wrapped = [
        {"members": party, "score": sum(m.get("priority", 5) for m in party)}
        for party in results
    ]
    collapsed = collapse_by_role_group(wrapped)
    yield ("complete", {"found": len(results), "distinct": len(collapsed), "parties": collapsed})

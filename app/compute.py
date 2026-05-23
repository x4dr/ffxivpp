from __future__ import annotations

import time
from collections.abc import Generator
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


def analyze_constraints(people: list[Person], constraints: Constraints) -> list[str]:
    reasons = []
    c = constraints

    # 1. Total people check
    if len(people) < 8:
        reasons.append(f"Not enough people: have {len(people)}, need 8")
        return reasons # Stop here, can't form a party

    # 2. Check available jobs
    all_possible_jobs = set()
    for p in people:
        for entry in p.jobs:
            job = JOBS_BY_ID.get(parse_job_id(entry))
            if job:
                all_possible_jobs.add(job.id)

    # 3. Role availability
    available_tanks = sum(1 for j in JOBS if j.id in all_possible_jobs and j.role == 'tank')
    available_healers = sum(1 for j in JOBS if j.id in all_possible_jobs and j.role == 'healer')
    available_dps = sum(1 for j in JOBS if j.id in all_possible_jobs and j.role == 'dps')

    if c.std_comp:
        if available_tanks < 2:
            reasons.append("Not enough tanks possible (need 2)")
        if available_healers < 2:
            reasons.append("Not enough healers possible (need 2)")
        if available_dps < 4:
            reasons.append("Not enough DPS possible (need 4)")

    # 4. Check specific role/sub-role pools
    def get_count(role, sub=None, dps_type=None):
        return sum(
            1 for j in JOBS
            if j.role == role and (not sub or j.sub == sub) and (not dps_type or j.dps_type == dps_type)
        )

    if c.min_melee > get_count('dps', sub='melee'):
        reasons.append("Too many melee required")

    return reasons


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

    def dfs(idx: int, assigned: list[tuple[Person, Job]]) -> None:
        # If we have reached a party size of 8, check if valid
        if len(assigned) == 8:
            jobs_only = [job for p, job in assigned]
            if valid(jobs_only):
                results.append([Assignment(p.name, j.name, j.role) for p, j in assigned])
            # We don't return here because we want to find all valid parties of 8
            # BUT we have to be careful: if we already have 8, we can't assign more.
            # So if we have 8, we actually *should* return to avoid adding more people.
            return

        # If we ran out of people, stop
        if idx == len(people):
            return

        # Remaining people:
        remaining_people = len(people) - idx
        # Remaining needed:
        needed = 8 - len(assigned)

        # Option 1: Bench this person (if we have enough people left)
        if remaining_people > needed:
            dfs(idx + 1, assigned)

        # Option 2: Assign this person (if we still need more)
        if needed > 0:
            p = people[idx]
            for entry in p.jobs:
                job = JOBS_BY_ID.get(parse_job_id(entry))
                if job is None:
                    continue
                assigned.append((p, job))
                dfs(idx + 1, assigned)
                assigned.pop()

    dfs(0, [])
    return results


_SSEEvent = tuple[str, dict[str, Any]]


def compute_parties_stream(
    people: list[Person], constraints: Constraints,
) -> Generator[_SSEEvent, None, None]:
    results: list[list[Assignment]] = []
    t0 = time.monotonic()
    last_report = t0
    explored = 0
    total_space = 1
    for p in people:
        valid_jobs = sum(1 for e in p.jobs if JOBS_BY_ID.get(parse_job_id(e)))
        if valid_jobs:
            total_space *= valid_jobs

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
    def dfs(idx: int, assigned: list[tuple[Person, Job]]) -> Generator:  # type: ignore[misc]
        nonlocal explored, last_report
        explored += 1
        now = time.monotonic()
        if now - last_report >= 1.0:
            elapsed = now - t0
            remaining = None
            if explored > 0:
                rate = explored / elapsed
                remaining = int((total_space - explored) / rate)
            yield ("progress", {
                "found": len(results), "explored": explored,
                "total": total_space, "remaining": remaining,
            })
            last_report = now

        if len(assigned) == 8:
            jobs_only = [job for p, job in assigned]
            if valid(jobs_only):
                score = 0
                members: list[dict[str, str]] = []
                for p, j in assigned:
                    prio = 5
                    for entry in p.jobs:
                        if parse_job_id(entry) == j.id:
                            prio = get_priority(entry)
                            break
                    score += prio
                    members.append({"name": p.name, "job": j.name, "role": j.role})
                results.append({"score": score, "members": members})
            return

        if idx == len(people):
            return

        remaining_people = len(people) - idx
        needed = 8 - len(assigned)

        # Option 1: Bench
        if remaining_people > needed:
            yield from dfs(idx + 1, assigned)

        # Option 2: Assign
        if needed > 0:
            p = people[idx]
            for entry in p.jobs:
                job = JOBS_BY_ID.get(parse_job_id(entry))
                if job is None:
                    continue
                assigned.append((p, job))
                yield from dfs(idx + 1, assigned)
                assigned.pop()

    yield from dfs(0, [])
    results.sort(key=lambda r: r["score"], reverse=True)
    yield ("complete", {
        "found": len(results),
        "parties": results[:2000],
    })

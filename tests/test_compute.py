from __future__ import annotations

from typing import Any

from app.compute import collapse_by_role_group, compute_parties, compute_parties_stream
from app.models import Constraints, Person


def _p(name: str, *jobs: str) -> Person:
    return Person(name, list(jobs))


def _m(name: str, job: str, role: str, priority: int = 5) -> dict[str, Any]:
    return {"name": name, "job": job, "role": role, "priority": priority}


def test_compute_parties_stream() -> None:
    people = [_p("A", "pld"), _p("B", "war"), _p("C", "whm"), _p("D", "sch"),
              _p("E", "mnk"), _p("F", "brd"), _p("G", "blm"), _p("H", "nin")]

    stream = list(compute_parties_stream(people, Constraints()))

    # Check for at least one complete event
    assert any(event_type == "complete" for event_type, _ in stream)

    # Verify the complete event has parties and found count
    complete_event = next(data for event_type, data in stream if event_type == "complete")
    assert "found" in complete_event
    assert complete_event["found"] == 1
    assert "parties" in complete_event
    assert len(complete_event["parties"]) == 1


def test_one_exact_match() -> None:
    people = [_p("A", "pld"), _p("B", "war"), _p("C", "whm"), _p("D", "sch"),
              _p("E", "mnk"), _p("F", "brd"), _p("G", "blm"), _p("H", "nin")]
    r = compute_parties(people, Constraints())
    assert len(r) == 1


def test_multiple_combos() -> None:
    people = [_p("A", "pld", "war"), _p("B", "war", "gnb"), _p("C", "whm", "ast"),
              _p("D", "sch", "sge"), _p("E", "mnk", "drg"), _p("F", "brd", "dnc"),
              _p("G", "blm", "rdm"), _p("H", "nin", "sam")]
    r = compute_parties(people, Constraints())
    assert len(r) > 0


def test_no_dupes_blocked() -> None:
    people = [_p("A", "pld"), _p("B", "pld"), _p("C", "whm"), _p("D", "sch"),
              _p("E", "mnk"), _p("F", "brd"), _p("G", "blm"), _p("H", "nin")]
    assert len(compute_parties(people, Constraints(no_dupes=True))) == 0
    assert len(compute_parties(people, Constraints(no_dupes=False))) > 0


def test_heal_mix() -> None:
    people = [_p("A", "pld"), _p("B", "war"), _p("C", "whm"), _p("D", "whm"),
              _p("E", "mnk"), _p("F", "brd"), _p("G", "blm"), _p("H", "nin")]
    assert len(compute_parties(people, Constraints(heal_mix=True))) == 0

    people2 = [_p("A", "pld"), _p("B", "war"), _p("C", "whm"), _p("D", "sch"),
               _p("E", "mnk"), _p("F", "brd"), _p("G", "blm"), _p("H", "nin")]
    assert len(compute_parties(people2, Constraints(heal_mix=True))) == 1


def test_dps_subrole_max() -> None:
    people = [_p("A", "pld"), _p("B", "war"), _p("C", "whm"), _p("D", "sch"),
              _p("E", "mnk"), _p("F", "drg"), _p("G", "sam"), _p("H", "nin")]
    assert len(compute_parties(people, Constraints(max_melee=2))) == 0
    assert len(compute_parties(people, Constraints(max_melee=4))) > 0


def test_dps_subrole_min() -> None:
    people = [_p("A", "pld"), _p("B", "war"), _p("C", "whm"), _p("D", "sch"),
              _p("E", "mnk"), _p("F", "brd"), _p("G", "nin"), _p("H", "sam")]
    assert len(compute_parties(people, Constraints(min_caster=1))) == 0

    people[7] = _p("H", "blm")
    assert len(compute_parties(people, Constraints(min_caster=1))) > 0


def test_selfish_utility() -> None:
    people = [_p("A", "pld"), _p("B", "war"), _p("C", "whm"), _p("D", "sch"),
              _p("E", "sam"), _p("F", "drg"), _p("G", "nin"), _p("H", "brd")]
    assert len(compute_parties(people, Constraints(min_selfish=1))) > 0
    assert len(compute_parties(people, Constraints(max_selfish=0))) == 0
    assert len(compute_parties(people, Constraints(min_utility=3))) > 0
    assert len(compute_parties(people, Constraints(max_utility=2))) == 0


def test_std_comp_off() -> None:
    people = [_p("A", "pld"), _p("B", "war"), _p("C", "whm"), _p("D", "sch"),
              _p("E", "ast"), _p("F", "mnk"), _p("G", "blm"), _p("H", "nin")]
    assert len(compute_parties(people, Constraints(std_comp=False))) > 0
    assert len(compute_parties(people, Constraints(std_comp=True))) == 0


def test_exclusions() -> None:
    people = [_p("A", "pld"), _p("B", "war"), _p("C", "whm"), _p("D", "sch"),
              _p("E", "sam"), _p("F", "vpr"), _p("G", "brd"), _p("H", "blm")]
    assert len(compute_parties(people, Constraints(exclusions=[["sam", "vpr"]]))) == 0
    assert len(compute_parties(people, Constraints(exclusions=[["sam", "blm"]]))) == 0
    assert len(compute_parties(people, Constraints(exclusions=[["sam", "mnk"]]))) > 0


def test_empty_jobs() -> None:
    people = [_p("A", "pld"), _p("B", "war"), _p("C", "whm"), _p("D", "sch"),
              _p("E", "mnk"), _p("F", "brd"), _p("G", "blm"), _p("H")]
    assert len(compute_parties(people, Constraints())) == 0


def test_invalid_job_id_skipped() -> None:
    people = [_p("A", "pld"), _p("B", "war"), _p("C", "whm"), _p("D", "sch"),
              _p("E", "mnk"), _p("F", "brd"), _p("G", "blm"), _p("H", "invalid_job", "nin")]
    assert len(compute_parties(people, Constraints())) > 0


# ── collapse_by_role_group tests ────────────────────────────────────────

def test_collapse_same_people_same_roles() -> None:
    p1 = {"members": [_m("A", "PLD", "tank"), _m("B", "WAR", "tank"),
                      _m("C", "WHM", "healer"), _m("D", "SCH", "healer"),
                      _m("E", "MNK", "dps"), _m("F", "BRD", "dps"),
                      _m("G", "BLM", "dps"), _m("H", "NIN", "dps")],
          "score": 40}
    p2 = {"members": [_m("A", "DRK", "tank"), _m("B", "GNB", "tank"),
                      _m("C", "AST", "healer"), _m("D", "SGE", "healer"),
                      _m("E", "DRG", "dps"), _m("F", "DNC", "dps"),
                      _m("G", "RDM", "dps"), _m("H", "SAM", "dps")],
          "score": 38}
    result = collapse_by_role_group([p1, p2])
    assert len(result) == 1
    assert result[0]["score"] == 40


def test_collapse_different_people() -> None:
    p1 = {"members": [_m("A", "PLD", "tank"), _m("B", "WAR", "tank"),
                      _m("C", "WHM", "healer"), _m("D", "SCH", "healer"),
                      _m("E", "MNK", "dps"), _m("F", "BRD", "dps"),
                      _m("G", "BLM", "dps"), _m("H", "NIN", "dps")],
          "score": 40}
    p2 = {"members": [_m("A", "PLD", "tank"), _m("B", "WAR", "tank"),
                      _m("C", "WHM", "healer"), _m("D", "SCH", "healer"),
                      _m("E", "MNK", "dps"), _m("F", "BRD", "dps"),
                      _m("G", "BLM", "dps"), _m("I", "NIN", "dps")],
          "score": 38}
    result = collapse_by_role_group([p1, p2])
    assert len(result) == 2


def test_collapse_different_role_assignment() -> None:
    p1 = {"members": [_m("A", "PLD", "tank"), _m("B", "WAR", "tank"),
                      _m("C", "WHM", "healer"), _m("D", "SCH", "healer"),
                      _m("E", "MNK", "dps"), _m("F", "BRD", "dps"),
                      _m("G", "BLM", "dps"), _m("H", "NIN", "dps")],
          "score": 40}
    p2 = {"members": [_m("A", "PLD", "tank"), _m("C", "WHM", "tank"),
                      _m("B", "WAR", "healer"), _m("D", "SCH", "healer"),
                      _m("E", "MNK", "dps"), _m("F", "BRD", "dps"),
                      _m("G", "BLM", "dps"), _m("H", "NIN", "dps")],
          "score": 38}
    result = collapse_by_role_group([p1, p2])
    assert len(result) == 2


def test_collapse_empty() -> None:
    assert collapse_by_role_group([]) == []


def test_collapse_single() -> None:
    p = {"members": [_m("A", "PLD", "tank"), _m("B", "WAR", "tank"),
                     _m("C", "WHM", "healer"), _m("D", "SCH", "healer"),
                     _m("E", "MNK", "dps"), _m("F", "BRD", "dps"),
                     _m("G", "BLM", "dps"), _m("H", "NIN", "dps")],
         "score": 40}
    result = collapse_by_role_group([p])
    assert len(result) == 1
    assert result[0] == p


def test_collapse_picks_best_score() -> None:
    p1 = {"members": [_m("A", "PLD", "tank", priority=5), _m("B", "WAR", "tank", priority=5),
                      _m("C", "WHM", "healer", priority=5), _m("D", "SCH", "healer", priority=5),
                      _m("E", "MNK", "dps", priority=5), _m("F", "BRD", "dps", priority=5),
                      _m("G", "BLM", "dps", priority=5), _m("H", "NIN", "dps", priority=5)],
          "score": 40}
    p2 = {"members": [_m("A", "DRK", "tank", priority=3), _m("B", "GNB", "tank", priority=3),
                      _m("C", "AST", "healer", priority=3), _m("D", "SGE", "healer", priority=3),
                      _m("E", "DRG", "dps", priority=3), _m("F", "DNC", "dps", priority=3),
                      _m("G", "RDM", "dps", priority=3), _m("H", "SAM", "dps", priority=3)],
          "score": 24}
    result = collapse_by_role_group([p1, p2])
    assert len(result) == 1
    assert result[0]["score"] == 40
    # The winning variant should keep its specific job assignments
    assert result[0]["members"][0]["job"] == "PLD"


def test_collapse_member_sort_order() -> None:
    p = {"members": [_m("H", "NIN", "dps"), _m("B", "WAR", "tank"),
                     _m("F", "BRD", "dps"), _m("D", "SCH", "healer"),
                     _m("G", "BLM", "dps"), _m("C", "WHM", "healer"),
                     _m("E", "MNK", "dps"), _m("A", "PLD", "tank")],
         "score": 40}
    result = collapse_by_role_group([p])
    roles = [m["role"] for m in result[0]["members"]]
    names = [m["name"] for m in result[0]["members"]]
    assert roles == ["tank", "tank", "healer", "healer", "dps", "dps", "dps", "dps"]
    assert names == ["A", "B", "C", "D", "E", "F", "G", "H"]


# ── stream distinct count tests ─────────────────────────────────────────

def test_stream_distinct_in_progress() -> None:
    people = [_p("A", "pld", "drk"), _p("B", "war", "gnb"), _p("C", "whm", "ast"),
              _p("D", "sch", "sge"), _p("E", "mnk", "drg"), _p("F", "brd", "dnc"),
              _p("G", "blm", "rdm"), _p("H", "nin", "sam")]
    events = list(compute_parties_stream(people, Constraints()))
    for event_type, data in events:
        if event_type == "progress":
            distinct = data.get("distinct", 0)
            assert distinct <= data.get("found", 0)
        elif event_type == "complete":
            assert data.get("distinct", 0) == len(data.get("parties", []))
            assert data["distinct"] <= data["found"]


def test_stream_distinct_no_duplicates() -> None:
    people = [_p("A", "pld"), _p("B", "war"), _p("C", "whm"), _p("D", "sch"),
              _p("E", "mnk"), _p("F", "brd"), _p("G", "blm"), _p("H", "nin")]
    events = list(compute_parties_stream(people, Constraints()))
    complete = next(data for t, data in events if t == "complete")
    assert complete["found"] == 1
    assert complete["distinct"] == 1
    assert len(complete["parties"]) == 1


def test_stream_collapsed_count() -> None:
    people = [_p("A", "pld", "drk"), _p("B", "war", "gnb"), _p("C", "whm", "ast"),
              _p("D", "sch", "sge"), _p("E", "mnk", "drg"), _p("F", "brd", "dnc"),
              _p("G", "blm", "rdm"), _p("H", "nin", "sam")]
    events = list(compute_parties_stream(people, Constraints()))
    complete = next(data for t, data in events if t == "complete")
    assert complete["found"] > complete["distinct"]
    assert len(complete["parties"]) == complete["distinct"]

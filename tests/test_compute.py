from __future__ import annotations

from app.compute import compute_parties, compute_parties_stream
from app.models import Constraints, Person


def _p(name: str, *jobs: str) -> Person:
    return Person(name, list(jobs))


def test_compute_parties_stream() -> None:
    people = [_p("A", "pld"), _p("B", "war"), _p("C", "whm"), _p("D", "sch"),
              _p("E", "mnk"), _p("F", "brd"), _p("G", "blm"), _p("H", "nin")]
    
    stream = list(compute_parties_stream(people, Constraints()))
    
    # Check for at least one complete event
    assert any(event_type == "complete" for event_type, _ in stream)
    
    # Verify the complete event has results
    complete_event = next(data for event_type, data in stream if event_type == "complete")
    assert "results" in complete_event
    assert len(complete_event["results"]) == 1


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

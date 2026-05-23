from __future__ import annotations

from bot.commands import JOB_NAMES, ROLE_JOBS, VALID_JOBS, _build_job_list, parse_jobs


def test_parse_jobs_valid():
    assert parse_jobs("pld,war,whm") == ["pld", "war", "whm"]


def test_parse_jobs_with_spaces():
    assert parse_jobs(" pld , war ") == ["pld", "war"]


def test_parse_jobs_invalid_ignored():
    assert parse_jobs("pld,invalid_job,war") == ["pld", "war"]


def test_parse_jobs_all_invalid():
    assert parse_jobs("foo,bar") == []


def test_parse_jobs_empty():
    assert parse_jobs("") == []


def test_valid_jobs_contains_all():
    expected = {"pld", "war", "drk", "gnb", "whm", "sch", "ast", "sge",
                "mnk", "drg", "nin", "sam", "vpr", "brd", "mch", "dnc",
                "blm", "smn", "rdm", "pct"}
    assert VALID_JOBS == expected


def test_job_names_mapping():
    assert JOB_NAMES["pld"] == "PLD"
    assert JOB_NAMES["whm"] == "WHM"
    assert JOB_NAMES["blm"] == "BLM"
    assert len(JOB_NAMES) == 20


def test_parse_jobs_with_priority():
    assert parse_jobs("pld:7,war:3,whm") == ["pld:7", "war:3", "whm"]


def test_parse_jobs_invalid_priority_defaults():
    assert parse_jobs("pld:abc,war") == ["pld", "war"]


def test_role_jobs_tank():
    assert ROLE_JOBS["tank"] == ["pld", "war", "drk", "gnb"]


def test_role_jobs_healer():
    assert ROLE_JOBS["healer"] == ["whm", "sch", "ast", "sge"]


def test_role_jobs_melee():
    assert ROLE_JOBS["melee"] == ["mnk", "drg", "nin", "sam", "vpr"]


def test_role_jobs_pranged():
    assert ROLE_JOBS["pranged"] == ["brd", "mch", "dnc"]


def test_role_jobs_caster():
    assert ROLE_JOBS["caster"] == ["blm", "smn", "rdm", "pct"]


def test_role_jobs_all_keys_present():
    assert set(ROLE_JOBS) == {"tank", "healer", "melee", "pranged", "caster"}


def test_role_jobs_no_duplicates():
    all_jobs = []
    for jl in ROLE_JOBS.values():
        all_jobs.extend(jl)
    assert len(all_jobs) == len(VALID_JOBS)
    assert set(all_jobs) == VALID_JOBS


def test_build_job_list_empty():
    assert _build_job_list([]) == "*none*"


def test_build_job_list_some():
    result = _build_job_list(["pld:7", "whm"])
    assert "PLD[7]" in result
    assert "WHM[5]" in result

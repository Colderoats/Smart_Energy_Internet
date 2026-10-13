"""/testbed/* routes: read-only views of saved result files, admin-protected (the pinned unauthenticated-401 list lives in test_auth.py)."""

import json

import pytest


def test_status_reports_provenance(logged_in):
    r = logged_in.get("/testbed/status")
    assert r.status_code == 200
    body = r.json()
    assert body["provenance"] == "simulated_testbed"
    assert "never mixed" in body["note"]


@pytest.mark.parametrize("paper", ["journal", "conference"])
def test_results_tables_carry_measured_and_paper_target_separately(logged_in, paper):
    r = logged_in.get(f"/testbed/results?paper={paper}")
    assert r.status_code == 200
    body = r.json()
    assert body["provenance"] == "simulated_testbed"
    for t in body["tables"]:
        for row in t["rows"]:
            assert row["paper_name"] == paper
            # a paper value is only ever a separate "paper" field next to the measured one
            assert set(["measured", "paper", "within"]) <= set(row)


def test_results_rejects_unknown_paper(logged_in):
    assert logged_in.get("/testbed/results?paper=thesis").status_code == 422


def test_kelmarsh_is_labelled_real_not_simulated(logged_in):
    r = logged_in.get("/testbed/kelmarsh")
    assert r.status_code == 200
    assert r.json()["provenance"] == "real_kelmarsh_replayed"


@pytest.mark.parametrize("bad", ["..%2f..%2f.env", "a b", "x" * 80])
def test_run_id_is_validated(logged_in, bad):
    assert logged_in.get(f"/testbed/runs/{bad}").status_code in (400, 404, 422)


def test_unknown_topology_is_404(logged_in):
    assert logged_in.get("/testbed/topologies/Z/redistribution").status_code == 404
    assert logged_in.get("/testbed/topologies/Z/faults").status_code == 404


def test_missing_results_say_how_to_generate_them(logged_in):
    r = logged_in.get("/testbed/runs/does_not_exist")
    assert r.status_code == 404
    assert "run_all" in json.dumps(r.json())

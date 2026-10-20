"""Simulated-testbed endpoints (paper reproduction): read-only views of saved result files under experiments/results.

Everything served here is `provenance: "simulated_testbed"` EXCEPT /testbed/kelmarsh, which reads the existing Module 3/4 artifacts of the real
Kelmarsh replay, read-only, so the two kinds of evidence are never mixed. Paper values appear only as "paper" next to a measured value.
No pandapower / torch is imported here (the backend venv does not have pandapower): the heavy work happens offline in backend/testbed.
Every route is included with dependencies=protected in app/main.py.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from testbed import compare

router = APIRouter(prefix="/testbed")

REPO = Path(__file__).resolve().parents[3]
RES = REPO / "experiments" / "results"
AI_ART = REPO / "backend" / "ai" / "artifacts"
FED_RUNS = REPO / "backend" / "ai" / "federated" / "artifacts" / "runs"
PROVENANCE = "simulated_testbed"
RUN_ID = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")
TOPOLOGIES = ("A", "B", "C")


def _json(path: Path):
    if not path.exists():
        raise HTTPException(404, f"{path.name} not generated yet - run experiments/run_all.py")
    return json.loads(path.read_text(), parse_constant=lambda c: None)


@router.get("/status")
async def status():
    runs = []
    if RES.exists():
        for d in sorted(RES.iterdir()):
            f = d / "metrics.json"
            if f.exists():
                doc = json.loads(f.read_text(), parse_constant=lambda c: None)
                runs.append(dict(run_id=doc["run_id"], created_utc=doc["created_utc"], config_hash=doc["config_hash"], metrics=len(doc["metrics"])))
    return dict(provenance=PROVENANCE, runs=runs, has_comparison=(RES / "comparison.md").exists(), has_topologies=(RES / "topologies.json").exists(),
                has_graphs=(RES / "graphs.json").exists(), note="Simulated - never mixed with the real Kelmarsh results.")


_BLANK = re.compile(r"\b(journal|conference|testbed)\b\s*", re.I)


def _scrub(o):
    """Blank the words journal / conference / testbed out of every displayed string value (keys untouched)."""
    if isinstance(o, str):
        return _BLANK.sub("", o)
    if isinstance(o, dict):
        return {k: _scrub(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_scrub(v) for v in o]
    return o


def _clean(o):
    """NaN / inf (e.g. the std of a single-iteration metric) are not valid JSON: serve them as null."""
    if isinstance(o, float):
        return o if o == o and o not in (float("inf"), float("-inf")) else None
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    return o


@router.get("/results")
async def results(paper: str = Query("journal", pattern="^(journal|conference)$")):
    comp = _clean(compare.build_comparison())
    reasons = {}
    rf = RES / "reasons.json"
    if rf.exists():
        reasons = json.loads(rf.read_text())
    pipelines = {}
    pf = RES / "pipeline.json"
    if pf.exists():
        pipelines = json.loads(pf.read_text())
    tables: dict[str, dict] = {}
    for r in comp["rows"]:
        if r["paper_name"] != paper:
            continue
        t = tables.setdefault(r["table"], dict(table=r["table"], rows=[], within=0, outside=0, total=0))
        r["reason"] = reasons.get(r["target_id"]) if r["within"] is False else None
        t["rows"].append(r)
        t["total"] += 1
        if r["within"] is True:
            t["within"] += 1
        elif r["within"] is False:
            t["outside"] += 1
    return dict(provenance=PROVENANCE, paper=paper, tables=list(tables.values()), pipelines=pipelines.get(paper, {}), tolerance_rel=compare.TOL_REL)


@router.get("/runs/{run_id}")
async def run_metrics(run_id: str):
    if not RUN_ID.match(run_id):
        raise HTTPException(400, "bad run id")
    return _json(RES / run_id / "metrics.json")


@router.get("/comparison")
async def comparison_md():
    f = RES / "comparison.md"
    if not f.exists():
        raise HTTPException(404, "comparison.md not generated yet")
    return dict(markdown=f.read_text(), provenance=PROVENANCE)


@router.get("/kelmarsh")
async def kelmarsh():
    """REAL Kelmarsh SCADA replay results (Module 3 + Module 4), read-only. Not simulated, not part of the testbed."""
    out: dict = dict(provenance="real_kelmarsh_replayed", module3=None, module4=[])
    f = AI_ART / "results_exp013_tag.json"
    if f.exists():
        d = json.loads(f.read_text(), parse_constant=lambda c: None)
        runs = d["models"]["tag"]["runs"]
        det = [r["detection"] for r in runs]
        mean = lambda k: sum(x[k] for x in det) / len(det)
        out["module3"] = dict(source="results_exp013_tag.json (EXP-013)", split=d.get("split"), model=d["models"]["tag"].get("display_name"), seeds=len(runs),
                              detection=dict(f1=mean("f1"), precision=mean("precision"), recall=mean("recall"), roc_auc=mean("roc_auc"), pr_auc=mean("pr_auc")),
                              provenance_text=d.get("provenance"))
    if FED_RUNS.exists():
        for run in sorted(FED_RUNS.iterdir()):
            mf = run / "run_meta.json"
            if mf.exists():
                m = json.loads(mf.read_text(), parse_constant=lambda c: None)
                out["module4"].append(dict(run=run.name, mode=m.get("mode"), mu=m.get("mu"), rounds=m.get("rounds"), rounds_to_convergence=m.get("rounds_to_convergence"),
                                           best_val_pr_auc=m.get("best_mean_client_val_pr_auc"), megabytes_float32=(m.get("communication") or {}).get("total_megabytes_float32"),
                                           scenario=(m.get("scenario") or {}).get("scenario")))
    return out


@router.get("/topologies")
async def topologies():
    d = _json(RES / "topologies.json")
    kp = (RES / "topology_kpis.json")
    kpis = json.loads(kp.read_text(), parse_constant=lambda c: None) if kp.exists() else {}
    return dict(provenance=PROVENANCE, **_scrub(dict(topologies=d, kpis=kpis)))


def _topo(name: str) -> str:
    if name not in TOPOLOGIES:
        raise HTTPException(404, "unknown topology")
    return name


@router.get("/topologies/{name}/redistribution")
async def redistribution(name: str):
    return dict(provenance=PROVENANCE, **_scrub(_json(RES / f"redistribution_{_topo(name)}.json")))


@router.get("/topologies/{name}/faults")
async def fault_list(name: str):
    d = _json(RES / f"fault_replay_{_topo(name)}.json")
    return dict(provenance=PROVENANCE, scenarios=_scrub([dict(id=s["id"], title=s["title"], type=s["type"], start=s["start"], summary=s["summary"]) for s in d["scenarios"]]))


@router.get("/topologies/{name}/faults/{scenario_id}")
async def fault_scenario(name: str, scenario_id: str):
    if not RUN_ID.match(scenario_id):
        raise HTTPException(400, "bad scenario id")
    d = _json(RES / f"fault_replay_{_topo(name)}.json")
    for s in d["scenarios"]:
        if s["id"] == scenario_id:
            return dict(provenance=PROVENANCE, **_scrub(s))
    raise HTTPException(404, "unknown scenario")


@router.get("/graphs")
async def graphs():
    return dict(provenance=PROVENANCE, **_scrub(_json(RES / "graphs.json")))

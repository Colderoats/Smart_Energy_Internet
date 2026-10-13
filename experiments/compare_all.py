"""Build experiments/results/comparison.md (and comparison.json): per paper target, measured vs paper, absolute / relative difference,
within / outside the +-5 % tolerance (rounded to the paper's decimals). Within-tolerance count per table at the top."""
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from testbed import compare  # noqa: E402

RES = ROOT / "experiments" / "results"
ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8, "IX": 9, "X": 10, "XI": 11}


def order(t):
    import re
    m = re.search(r"Table ([IVX]+)", t or "")
    return (ROMAN.get(m.group(1), 90) if m else 95, t or "")


def main():
    comp = compare.build_comparison()
    (RES / "comparison.json").write_text(json.dumps(comp, default=float))
    reasons = json.loads((RES / "reasons.json").read_text()) if (RES / "reasons.json").exists() else {}
    rows = [r for r in comp["rows"] if r["target_id"] and r["paper"] is not None]
    by = defaultdict(list)
    for r in rows:
        by[(r["paper_name"], r["table"])].append(r)
    lines = ["# Measured (simulated testbed) vs paper targets", "",
             "Every measured value comes from a run on the **simulated testbed** (`provenance: simulated_testbed`); paper values are targets, never inputs.",
             f"Tolerance: +-{int(compare.TOL_REL * 100)} % relative (+-0.05 absolute when the paper value is 0); structural counts must match exactly.",
             "The measured value is rounded to the number of decimals the paper uses. Rows marked **outside** keep the measured number and give the most likely reason.", "",
             "## Within-tolerance count per table", "", "| Paper | Table | within | total |", "|---|---|---|---|"]
    tot_w = tot = 0
    for (paper, table), rs in sorted(by.items(), key=lambda kv: (kv[0][0], order(kv[0][1]))):
        w = sum(1 for r in rs if r["within"])
        tot_w += w
        tot += len(rs)
        lines.append(f"| {paper} | {table} | {w} | {len(rs)} |")
    lines += [f"| **all** | | **{tot_w}** | **{tot}** |", ""]
    for (paper, table), rs in sorted(by.items(), key=lambda kv: (kv[0][0], order(kv[0][1]))):
        lines += [f"## {paper.capitalize()} - {table}", "", "| target | topology | measured | paper | abs diff | rel diff | status |", "|---|---|---|---|---|---|---|"]
        for r in rs:
            m = r.get("measured_rounded", r["measured"])
            std = f" ± {r['std']:.3g}" if r.get("std") not in (None, 0) and (r.get("n") or 0) > 1 else ""
            lines.append(f"| {r['target_id']} | {r['topology'] or ''} | {m:g}{std} {r['unit'] if r['unit'] != '%' else '%'} | {r['paper']:g} | {r['abs_diff']:+.4g} | "
                         f"{'' if r['rel_diff'] is None else format(r['rel_diff'] * 100, '+.1f') + ' %'} | {r['status']}{' - ' + reasons[r['target_id']] if r['within'] is False and r['target_id'] in reasons else ''} |")
        lines.append("")
    unmatched = [t for t in compare.load_targets().values() if t["value"] is not None and not any(r["target_id"] == t["id"] for r in rows)]
    lines += ["## Paper targets with no measured counterpart", ""] + [f"- `{t['id']}` ({t['table_or_figure']}): {t['metric']} = {t['value']}" for t in unmatched] + [""]
    (RES / "comparison.md").write_text("\n".join(lines))
    print(f"{tot_w}/{tot} within tolerance; {len(unmatched)} targets without a measured value")


if __name__ == "__main__":
    main()

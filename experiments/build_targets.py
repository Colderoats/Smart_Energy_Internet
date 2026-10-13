"""Generates experiments/paper_targets.json: every number the papers report.

These are PAPER TARGETS, kept apart from measured results. Nothing here is read
by any simulator, trainer or evaluator; only comparison.py reads them, after the
runs are finished. Table IX and the abstract claims are targets too, but their
measured counterparts are always *derived* from measured Tables VI/VII/X.
"""
import json
from pathlib import Path

T = []


def add(id, paper, ref, module, metric, value, unit="", cond="", formula="", eq="", std=None):
    e = dict(id=id, paper=paper, table_or_figure=ref, module=module, metric=metric, value=value, unit=unit,
             conditions=cond, formula=formula, equation=eq)
    if std is not None:
        e["std"] = std
    T.append(e)


J, C = "journal", "conference"
# ---- Journal Table III (setup; checked structurally) ------------------------
for topo, n, l, s, w, k in (("A", 6, 5, 2, 1, 6), ("B", 14, 20, 4, 2, 14), ("C", 33, 37, 6, 3, 33)):
    for m, v in (("nodes", n), ("lines", l), ("solar_nodes", s), ("wind_hydro_sources", w), ("clients", k)):
        add(f"J.T3.{topo}.{m}", J, "Table III", "testbed", m, v, "count", f"topology {topo}", "structural")
    add(f"J.T3.{topo}.hours", J, "Table III", "testbed", "hours", 24, "h", f"topology {topo}")
    add(f"J.T3.{topo}.faults", J, "Table III", "testbed", "faults_per_iteration", 20, "count", "4 types x 5")
add("J.T3.samples", J, "Table III / Sec 5.1", "testbed", "samples", 17280, "count", "24 h at 5 s", "86400/5")
# ---- Journal Table IV -------------------------------------------------------
for o, (lr, k, h, m, tl, vl, f1) in {1: (0.01, 2, 128, 2, .0482, .0515, .882), 2: (0.001, 3, 64, 2, .0315, .0342, .915),
                                      3: (0.001, 2, 128, 3, .0248, .0271, .942), 4: (0.0001, 2, 128, 2, .0385, .0410, .901)}.items():
    c = f"Option {o}: LR={lr}, K={k}, H={h}, M={m}, 25 epochs"
    add(f"J.T4.o{o}.train_loss", J, "Table IV", "ta_gnn", "train_loss", tl, "", c, "Eq.14", "14")
    add(f"J.T4.o{o}.val_loss", J, "Table IV", "ta_gnn", "val_loss", vl, "", c, "Eq.14", "14")
    add(f"J.T4.o{o}.val_f1", J, "Table IV", "ta_gnn", "val_f1", f1, "", c, "F1 of fault head", "13")
# ---- Journal Table V --------------------------------------------------------
for n, (ep, tl, vl, f1) in {"3_LRS": (250, .0112, .0128, .978), "3_NLRS": (250, .0185, .0205, .954), "2_NLRS": (150, .0298, .0321, .923)}.items():
    c = f"Option {n}, {ep} epochs"
    add(f"J.T5.{n}.train_loss", J, "Table V", "ta_gnn", "train_loss", tl, "", c, "Eq.14", "14")
    add(f"J.T5.{n}.val_loss", J, "Table V", "ta_gnn", "val_loss", vl, "", c, "Eq.14", "14")
    add(f"J.T5.{n}.val_f1", J, "Table V", "ta_gnn", "val_f1", f1, "", c, "F1 of fault head", "13")
# ---- Journal Table VI -------------------------------------------------------
for t, (gm, gr, tm, tr) in {"A": (1.42, 1.95, 1.37, 1.88), "B": (3.85, 5.20, 3.44, 4.65), "C": (8.50, 11.40, 7.42, 9.95)}.items():
    for mdl, mae, rmse in (("gcn", gm, gr), ("ta_gnn", tm, tr)):
        add(f"J.T6.{t}.{mdl}.mae", J, "Table VI", "forecast", "mae", mae, "kW", f"topology {t}, {mdl}", "mean |Yhat-Y|", "20")
        add(f"J.T6.{t}.{mdl}.rmse", J, "Table VI", "forecast", "rmse", rmse, "kW", f"topology {t}, {mdl}", "sqrt(mean (Yhat-Y)^2)", "21")
# ---- Journal Table VII ------------------------------------------------------
for t, d, w in (("A", (.885, 42.0, 12.5), (.916, 38.5, 10.2)), ("B", (.862, 88.0, 38.4), (.948, 62.0, 25.6)), ("C", (.840, 145.0, 92.0), (.952, 96.0, 54.2))):
    for s, (f1, tr, eu) in (("default", d), ("twin", w)):
        c = f"topology {t}, {s} scheme"
        add(f"J.T7.{t}.{s}.detection_f1", J, "Table VII", "self_healing", "detection_f1", f1, "", c, "F1 of fault detection (twin/protection)")
        add(f"J.T7.{t}.{s}.t_rec", J, "Table VII", "self_healing", "t_rec", tr, "s", c, "t_restored - t_fault", "22")
        add(f"J.T7.{t}.{s}.e_uns", J, "Table VII", "self_healing", "e_uns", eu, "kWh", c, "unserved energy", "7")
# ---- Journal Table VIII -----------------------------------------------------
for k, v in {"open+close_tie": 8, "open+close_tie+island": 6, "open+close_tie+curtail": 4, "open+island": 2}.items():
    add(f"J.T8.C.{k}", J, "Table VIII", "self_healing", "action_sequence_count", v, "events", "topology C, line outage 12-13, 20 events", "count of chosen a*", "5")
add("J.T8.C.example_cost", J, "Table VIII", "self_healing", "lowest_J", 0.42, "", "example event: close tie switch 33", "J=w1 Euns+w2 Vviol+w3 Nsw", "7")
# ---- Journal Table IX (derived) --------------------------------------------
for t, (a, b, c_) in {"A": (3.52, 3.50, 8.33), "B": (10.65, 9.98, 29.55), "C": (12.71, 13.33, 33.79)}.items():
    add(f"J.T9.{t}.forecast_mae_improvement", J, "Table IX", "derived", "forecast_mae_reduction_pct", a, "%", f"topology {t}", "(GCN MAE - TA-GNN MAE)/GCN MAE", "derived from Table VI")
    add(f"J.T9.{t}.fault_f1_improvement", J, "Table IX", "derived", "fault_f1_gain_pct", b, "%", f"topology {t}", "(twin F1 - default F1)/default F1", "derived from Table VII")
    add(f"J.T9.{t}.recovery_improvement", J, "Table IX", "derived", "recovery_time_reduction_pct", c_, "%", f"topology {t}", "(T_default - T_twin)/T_default", "derived from Table VII")
# ---- Journal Table X --------------------------------------------------------
for m, (r, mb, vl, f1) in {"central": (None, None, .0118, .975), "fedavg": (85, 118.2, .0245, .921), "fedprox": (62, 86.2, .0182, .945), "adaptive_fedprox": (42, 58.5, .0128, .972)}.items():
    c = f"method {m}, target loss 0.0130"
    if r is not None:
        add(f"J.T10.{m}.rounds", J, "Table X", "federated", "rounds_to_target", r, "rounds", c, "first round with val loss <= 0.0130")
        add(f"J.T10.{m}.comm_mb", J, "Table X", "federated", "comm_volume", mb, "MB", c, "2 R K |w| beta", "18")
    add(f"J.T10.{m}.val_loss", J, "Table X", "federated", "val_loss", vl, "", c, "Eq.14", "14")
    add(f"J.T10.{m}.fault_f1", J, "Table X", "federated", "fault_f1", f1, "", c, "F1 of TA-GNN fault head", "13")
# ---- Journal Table XI -------------------------------------------------------
for op, (g, l) in {"register": (46250, .85), "sell_offer": (62100, 1.12), "buy_bid": (61800, 1.10), "match": (88400, 1.45), "settle": (105300, 1.82)}.items():
    add(f"J.T11.{op}.gas", J, "Table XI", "contract", "gas", g, "gas", f"operation {op}", "receipt.gasUsed")
    add(f"J.T11.{op}.latency", J, "Table XI", "contract", "latency", l, "s", f"operation {op}", "t_confirmed - t_submitted")
add("J.ABS.forecast", J, "Abstract", "derived", "max_forecast_error_reduction_pct", 12.7, "%", "max over topologies", "max of Table IX forecast", "derived")
add("J.ABS.recovery", J, "Abstract", "derived", "max_recovery_time_reduction_pct", 33.79, "%", "max over topologies", "max of Table IX recovery", "derived")
add("J.ABS.comm", J, "Abstract", "derived", "comm_reduction_pct", 32.13, "%", "FedProx -> adaptive FedProx", "(86.2-58.5)/86.2", "derived from Table X")
for f, d in {"Fig2": "initial validation loss (4 options)", "Fig3": "LRS training curves", "Fig4": "fine-tuned training loss", "Fig5": "fine-tuned validation loss",
             "Fig8": "node-wise RMSE", "Fig9": "ROC of fault head", "Fig10": "demand forecast vs actual"}.items():
    add(f"J.{f}", J, f, "figure", "figure", None, "", d)
# ---- Conference -------------------------------------------------------------
for s in ("solar", "wind", "hydro"):
    add(f"C.T2.{s}.nodes", C, "Table II", "testbed", "nodes", 4, "count", s)
    add(f"C.T2.{s}.samples", C, "Table II", "testbed", "samples", 140160, "count", f"{s}: 4 nodes x 35,040")
add("C.T2.total.samples", C, "Table II", "testbed", "samples_total", 420480, "count", "12 nodes x 35,040")
for s, (auc, p, r, f1, far) in {"solar": (.990, .88, .23, .36, .04), "wind": (.983, .83, .32, .44, .15), "hydro": (.999, .90, .89, .90, .24)}.items():
    c = f"{s}, test partition, mean of 5 datasets"
    for m, v, u in (("auc", auc, ""), ("precision", p, ""), ("recall", r, ""), ("f1", f1, ""), ("far_pct", far, "%")):
        add(f"C.T4.{s}.{m}", C, "Table IV", "twin_risk", m, v, u, c, "Eqs.1-4", "1-4")
add("C.T4.auc_std_max", C, "Sec IV-B", "twin_risk", "auc_std_upper_bound", 0.003, "", "AUC std < 0.003")
add("C.T4.mean_delay_intervals", C, "Sec IV-B", "twin_risk", "mean_detection_delay", 2.7, "intervals", "about 41 min at 15 min sampling")
add("C.T4.detected_before_end_pct", C, "Sec IV-B", "twin_risk", "faults_detected_before_end", 62, "%", "test faults")
for tau, vals in {0.3: (.48, .71, .63, .20, .69), 0.5: (.42, .72, .60, .25, .65), 0.7: (.36, .71, .56, .26, .61), 0.9: (.29, .70, .49, .30, .54)}.items():
    for cond, v in zip(("summer", "monsoon", "winter", "high_load", "low_load"), vals):
        add(f"C.T5.tau{tau}.{cond}", C, "Table V", "twin_risk", "f1", v, "", f"tau={tau}, {cond}, 5-fold blocked CV", "F1", "4")
for m, (iid, a5, a1, r) in {"fedavg": ((2.93, .02), (2.85, .08), (2.79, .02), 18.7), "fedprox_fixed": ((3.03, .06), (2.90, .06), (2.79, .05), 18.0),
                             "fedprox_adaptive": ((3.03, .06), (2.88, .08), (2.78, .04), 18.0)}.items():
    for sp, (v, sd) in (("iid", iid), ("alpha0.5", a5), ("alpha0.1", a1)):
        add(f"C.T6.{m}.{sp}.rmse", C, "Table VI", "federated", "test_rmse", v, "kW", f"{m}, {sp}, 3 seeds", "RMSE", "", std=sd)
    add(f"C.T6.{m}.rounds", C, "Table VI", "federated", "rounds_to_5pct_of_best", r, "rounds", f"{m}, alpha=0.1", "first round val RMSE <= 1.05 best")
for mu, v in zip((0.001, 0.01, 0.1, 1), (3.23, 3.33, 3.77, 6.33)):
    add(f"C.T6.mu{mu}.val_rmse", C, "Sec IV-D", "federated", "val_rmse", v, "kW", f"mu={mu}")
add("C.T6.central_rmse", C, "Sec IV-D", "forecast", "test_rmse", 2.65, "kW", "centralized TA-GNN")
for m, (rm, sd, ma, r2) in {"lstm": (2.66, .01, 1.38, .979), "gru": (2.65, .00, 1.36, .979), "gcn_fixed": (2.74, .02, 1.51, .977), "tgnn": (2.75, .06, 1.56, .977),
                             "ta_gnn_no_adapt": (2.66, .02, 1.39, .979), "ta_gnn": (2.65, .02, 1.35, .979)}.items():
    c = f"{m}, 3 seeds"
    add(f"C.T7.{m}.rmse", C, "Table VII", "forecast", "rmse", rm, "kW", c, "RMSE", "", std=sd)
    add(f"C.T7.{m}.mae", C, "Table VII", "forecast", "mae", ma, "kW", c, "MAE")
    add(f"C.T7.{m}.r2", C, "Table VII", "forecast", "r2", r2, "", c, "R^2")
for n, (lat, gas, tps) in {5: (59, 53862, 21.7), 10: (53, 53863, 22.8), 20: (55, 53864, 22.4), 50: (58, 53864, 21.3)}.items():
    c = f"{n} nodes, 5 rounds x 3 repeats"
    add(f"C.T8.n{n}.latency_ms", C, "Table VIII", "contract", "settle_latency", lat, "ms", c)
    add(f"C.T8.n{n}.gas", C, "Table VIII", "contract", "settle_gas", gas, "gas", c)
    add(f"C.T8.n{n}.tps", C, "Table VIII", "contract", "throughput", tps, "tx/s", c)
for m, v in (("settle", 53900), ("offer_request", 118000), ("register", 65600)):
    add(f"C.GAS.{m}", C, "Sec IV-F", "contract", "gas", v, "gas", f"{m} (approx.)")
add("C.Fig2", C, "Fig 2", "figure", "figure", None, "", "ROC per source")

Path(__file__).with_name("paper_targets.json").write_text(json.dumps(T, indent=1))
print(len(T), "targets")

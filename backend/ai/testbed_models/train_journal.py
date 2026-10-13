"""Journal TA-GNN / GCN training runs (Tables IV, V; models for Tables VI, VII, X; Figs 2-5, 8-10).

  python -m ai.testbed_models.train_journal search <top> <it> <tag|gcn> <option 1-4>   # Table IV cell: 25 epochs
  python -m ai.testbed_models.train_journal final  <top> <it> <3_LRS|3_NLRS|2_NLRS|GCN># Table V row: 250 / 250 / 150 epochs (GCN: best search option, 250 epochs, LRS)
  python -m ai.testbed_models.train_journal collect <top> <it>                          # merge the per-job files into search.json / final.json
Each fit is an independent process (see experiments/train_farm.py). Everything is `simulated_testbed`.
Adam (fused), batch = BATCH snapshots (journal: "batch size equals the number of nodes"; BATCH = 32 ~ N of topology C, a compute-driven setting fixed
in PREREGISTRATION.md amendment 1), 80/20 chronological split, float32.
"""
from __future__ import annotations

import json
import sys
import time

import numpy as np
import torch
import torch.nn.functional as Fn

from ai.testbed_models import journal_model as JM
from ai.testbed_models.journal_core import BATCH
from ai.testbed_models.paths import ART as OUT_ROOT

torch.set_num_threads(1)
OPTIONS = {  # journal Table IV: LR, K, H, M
    1: dict(lr=0.01, K=2, H=128, M=2),
    2: dict(lr=0.001, K=3, H=64, M=2),
    3: dict(lr=0.001, K=2, H=128, M=3),
    4: dict(lr=0.0001, K=2, H=128, M=2),
}
EPOCH_SCALE = 0.4  # PREREGISTRATION amendment 4: all epoch counts and scheduler breakpoints scaled by 0.4 (compute)
SEARCH_EPOCHS = int(25 * EPOCH_SCALE)  # 10
FINALS = {"3_LRS": ("tag", 3, int(250 * EPOCH_SCALE), True), "3_NLRS": ("tag", 3, int(250 * EPOCH_SCALE), False), "2_NLRS": ("tag", 2, int(150 * EPOCH_SCALE), False)}


def fit(data: JM.Data, kind: str, cfg: dict, epochs: int, use_lrs: bool, seed: int, log=None) -> tuple[JM.JointGNN, dict]:
    torch.manual_seed(seed)
    np.random.seed(seed)
    model = JM.JointGNN(data.x.shape[-1], cfg["H"], cfg["K"], cfg["M"], kind)
    opt = torch.optim.Adam(model.parameters(), lr=cfg["lr"], fused=True)
    bs = BATCH
    n_tr = data.split
    rng = np.random.default_rng(seed)
    curves = dict(epoch=[], lr=[], train_loss=[], val_loss=[], val_f1=[], val_mae_kw=[], val_cos=[])
    t0 = time.time()
    mask = data.mask
    for ep in range(epochs):
        lr = JM.lr_schedule(ep, use_lrs, cfg["lr"], EPOCH_SCALE)
        for g in opt.param_groups:
            g["lr"] = lr
        model.train()
        perm = torch.from_numpy(rng.permutation(n_tr))
        xs, As, ys, cs = data.x[perm], data.A_table[data.A_id[perm]], data.y[perm], data.c[perm]  # one gather per epoch, then contiguous slices
        tl = torch.zeros(())
        nb = 0
        for i in range(0, n_tr - bs + 1, bs):
            yh, ch = model(xs[i:i + bs], As[i:i + bs])
            loss = ((yh - ys[i:i + bs]) ** 2)[:, mask].mean() + Fn.cross_entropy(ch, cs[i:i + bs])  # Eq. 14, lambda_F = lambda_C = 1
            opt.zero_grad(set_to_none=True)
            loss.backward()
            opt.step()
            tl += loss.detach()
            nb += 1
        va = JM.evaluate(model, data, slice(n_tr, None))
        for k, v in (("epoch", ep + 1), ("lr", lr), ("train_loss", float(tl) / nb), ("val_loss", va["loss"]), ("val_f1", va["f1_macro"]),
                     ("val_mae_kw", va["mae_kw"]), ("val_cos", va["cos_sim"])):
            curves[k].append(v)
        if log and (ep % 5 == 0 or ep == epochs - 1):
            print(f"  [{kind} {cfg} lrs={use_lrs}] ep {ep + 1}/{epochs} train {float(tl) / nb:.4f} val {va['loss']:.4f} f1 {va['f1_macro']:.3f} ({time.time() - t0:.0f}s)", flush=True)
    tr = JM.evaluate(model, data, slice(0, n_tr))  # final train-set evaluation (eval mode) for the tables
    return model, dict(curves=curves, train=tr, val=va, seconds=time.time() - t0, n_params=JM.n_params(model))


def _prep(top: str, it: int):
    d, man = JM.load_data(top, it)
    data, stats = JM.make_data(top, d)
    out = OUT_ROOT / f"journal_{top}" / f"it{it}"
    out.mkdir(parents=True, exist_ok=True)
    return data, stats, man, out


def search_one(top: str, it: int, kind: str, o: int) -> None:
    data, stats, man, out = _prep(top, it)
    _, r = fit(data, kind, OPTIONS[o], SEARCH_EPOCHS, False, seed=it, log=True)
    (out / f"search_{kind}_o{o}.json").write_text(json.dumps(dict(cfg=OPTIONS[o], config_hash=man["config_hash"], **r)))


def final_one(top: str, it: int, name: str) -> None:
    data, stats, man, out = _prep(top, it)
    if name == "GCN":
        best = min(range(1, 5), key=lambda o: json.loads((out / f"search_gcn_o{o}.json").read_text())["val"]["loss"])
        kind, cfg, ep, lrs, tag = "gcn", OPTIONS[best], int(250 * EPOCH_SCALE), True, f"gcn_o{best}_LRS"
    else:
        kind, o, ep, lrs = FINALS[name]
        cfg, tag = OPTIONS[o], name
    model, r = fit(data, kind, cfg, ep, lrs, seed=it, log=True)
    torch.save(dict(state=model.state_dict(), cfg=cfg, kind=kind, stats=stats, top=top), out / f"model_{tag}.pt")
    (out / f"final_{tag}.json").write_text(json.dumps(dict(cfg=cfg, kind=kind, epochs=ep, lrs=lrs, config_hash=man["config_hash"], **r)))


def collect(top: str, it: int) -> None:
    out = OUT_ROOT / f"journal_{top}" / f"it{it}"
    runs = {f"{k}_o{o}": json.loads((out / f"search_{k}_o{o}.json").read_text()) for k in ("tag", "gcn") for o in range(1, 5)}
    man_hash = runs["tag_o1"]["config_hash"]
    (out / "search.json").write_text(json.dumps(dict(provenance="simulated_testbed", topology=top, iteration=it, config_hash=man_hash, runs=runs), indent=1))
    ranked = sorted(((k, v["val"]["loss"]) for k, v in runs.items() if k.startswith("tag")), key=lambda kv: kv[1])
    fins = {n: json.loads((out / f"final_{n}.json").read_text()) for n in FINALS}
    g = next(p.stem.replace("final_", "") for p in out.glob("final_gcn_*.json"))
    fins[g] = json.loads((out / f"final_{g}.json").read_text())
    (out / "final.json").write_text(json.dumps(dict(provenance="simulated_testbed", topology=top, iteration=it, config_hash=man_hash, search_ranking_tag=ranked,
                                                    gcn_selected=g.split("_")[1], runs=fins), indent=1))
    print("collected", top, it)


if __name__ == "__main__":
    mode, top, it = sys.argv[1], sys.argv[2], int(sys.argv[3])
    if mode == "search":
        search_one(top, it, sys.argv[4], int(sys.argv[5]))
    elif mode == "final":
        final_one(top, it, sys.argv[4])
    else:
        collect(top, it)

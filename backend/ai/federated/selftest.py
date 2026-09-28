"""Fast self-checks for Module 4 building blocks (no Flower processes needed).
Run (Module 4 venv, from backend/):  ai\federated\venv\Scripts\python -m ai.federated.selftest
Takes ~40 s (three short local training epochs on one client's shard)."""
from __future__ import annotations

import warnings

warnings.filterwarnings("ignore")
import numpy as np  # noqa: E402

from ai.federated import local, partition, simulated, weighting, wire  # noqa: E402
from ai.models import get_weights  # noqa: E402


def test_weighting() -> None:
    ws = weighting.AdaptiveWeighter()
    w, d = ws.weights({1: 1.0, 2: 1.0, 3: 1.0, 4: 1.0}, {1: 1.0, 2: 1.0, 3: 1.0, 4: 1.0})
    assert all(abs(v - 0.25) < 1e-9 for v in w.values()), "identical clients must get equal weights"
    w, _ = weighting.AdaptiveWeighter().weights({1: 3.0, 2: 1.0, 3: 1.0, 4: 1.0}, {1: 1.0, 2: 1.0, 3: 1.0, 4: 1.0})
    assert abs(sum(w.values()) - 1) < 1e-9 and w[1] == min(w.values()) and w[1] >= weighting.FLOOR - 1e-12, "bad-loss client floored, not zeroed"
    w, _ = weighting.AdaptiveWeighter().weights({k: 1.0 for k in (1, 2, 3, 4)}, {1: 9.0, 2: 1.0, 3: 1.0, 4: 1.0})
    assert w[1] < 0.25 * 0.5, "a huge update norm must be penalised"
    w, _ = weighting.AdaptiveWeighter().weights({1: float("nan"), 2: 1.0}, {1: 1.0, 2: 1.0})
    assert w[1] >= weighting.FLOOR - 1e-12 and w[1] < w[2], "non-finite loss counts as bad, not as zero"
    assert abs(sum(weighting.apply_floor(np.array([0.97, 0.02, 0.01]), 0.05)) - 1) < 1e-9
    a = [np.ones((2, 2), dtype=np.float32)]
    b = [3 * np.ones((2, 2), dtype=np.float32)]
    out = weighting.aggregate({2: b, 1: a}, {1: 0.75, 2: 0.25})
    assert np.allclose(out[0], 1.5)
    # history: absent client keeps its EMA
    wt = weighting.AdaptiveWeighter()
    wt.weights({1: 1.0, 2: 1.0, 3: 1.0}, {1: 1, 2: 1, 3: 1})
    before = wt.ema[3]
    wt.weights({1: 1.0, 2: 1.0}, {1: 1, 2: 1})
    assert wt.ema[3] == before
    print("weighting OK")


def test_simulated() -> None:
    s1, s2 = simulated.dropout_schedule(0, 30), simulated.dropout_schedule(0, 30)
    assert s1 == s2 and all(4 - len(v) >= simulated.MIN_PRESENT for v in s1.values())
    assert any(v for v in s1.values()), "dropout schedule must actually drop someone"
    assert simulated.dropout_schedule(0, 30) != simulated.dropout_schedule(1, 30)
    print("simulated dropout OK (mean absent per round: %.2f)" % np.mean([len(v) for v in s1.values()]))


def test_wire() -> None:
    shapes = [(2, 3), (4,)]
    ok = [np.zeros(s, dtype=np.float32) for s in shapes]
    wire.check_payload(ok, {"val_loss": 0.1, "turbine": 1}, shapes)
    for bad_arrays, bad_metrics in (
        (ok + [np.zeros((5, 40), dtype=np.float32)], {}),  # an extra array (a data-shaped one) must be rejected
        ([np.zeros((2, 3), dtype=np.float64), ok[1]], {}),
        (ok, {"raw_readings": 1.0}),
        (ok, {"val_loss": [1.0, 2.0]}),
    ):
        try:
            wire.check_payload(bad_arrays, bad_metrics, shapes)
        except wire.WireViolation:
            continue
        raise AssertionError("wire violation not caught")
    print("wire audit OK")


def test_local() -> None:
    shard = partition.load_shard(4)
    data = local.local_data_from_shard(shard)
    # only own-turbine features are present in any client sample
    assert data.train_x.shape[1] == local.D_DYN and (data.train_own == shard.own_idx).all()
    w0 = get_weights(local.make_model(0))
    cfg = dict(epochs=1, seed=5)
    wa, _ = local.local_train(w0, data, mu=0.0, **cfg)
    wb, _ = local.local_train(w0, data, mu=0.0, **cfg)
    assert all(np.array_equal(x, y) for x, y in zip(wa, wb)), "same seed must reproduce local training exactly"
    wp, st = local.local_train(w0, data, mu=50.0, **cfg)
    dist = lambda w: float(np.sqrt(sum(((a - b) ** 2).sum() for a, b in zip(w, w0))))
    assert dist(wp) < dist(wa), "a strong proximal term must keep the local model closer to the global one"
    print(f"local training OK (reproducible; ||dw|| mu=0: {dist(wa):.3f}, mu=50: {dist(wp):.3f})")


if __name__ == "__main__":
    test_weighting()
    test_simulated()
    test_wire()
    test_local()
    print("ALL SELF-TESTS PASSED")

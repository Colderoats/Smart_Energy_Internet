"""SIMULATED fault-tolerance scenarios for the federated experiments.

Everything in this file is SIMULATED degradation, injected on purpose to see
how each aggregation rule reacts. None of it is real data, real client
behaviour, or a physically sensed fault. Every use is labelled "SIMULATED" in
log lines, run metadata (`simulated: true`) and result files, so it can never
be confused with the real Kelmarsh replay.

Scenarios (all parameters fixed a priori, NOT tuned on results):

  clean              no injected problem (the headline runs)
  dropout            SIMULATED client dropout: each round each client is
                     independently unavailable with probability DROPOUT_P
                     (seeded, so every strategy sees the identical schedule for
                     a given seed); at least MIN_PRESENT clients always remain.
  degraded_data      SIMULATED degraded client (turbine SIM_TURBINE): Gaussian
                     noise (sigma = NOISE_SIGMA, in z-score units) added to all
                     of that client's dynamic feature values, and a random
                     LABEL_DROP_FRAC of its positive labels turned into 0
                     ("missed fault labels"). Applied to that client's train and
                     validation shards; the global test set stays clean.
  corrupted_update   SIMULATED corrupted updates (turbine SIM_TURBINE): the
                     client trains honestly, then transmits
                     w_global - UPDATE_SCALE * (w_local - w_global), i.e. a
                     sign-flipped, scaled update (a standard model-poisoning
                     attack). Its reported local validation scalars are the
                     honest pre-corruption ones.

The server never sees which scenario a client is in: the scenario flag is a
client-launch argument, and the aggregation strategies only ever use the
metrics/weights that cross the wire (see strategies.py / weighting.py).
"""

from __future__ import annotations

import numpy as np

SCENARIOS = ("clean", "dropout", "degraded_data", "corrupted_update")

SIM_TURBINE = 3  # the turbine whose data/updates are degraded in the two client-side scenarios
DROPOUT_P = 0.3
MIN_PRESENT = 2
NOISE_SIGMA = 2.0
LABEL_DROP_FRAC = 0.5
UPDATE_SCALE = 3.0

LABEL = "SIMULATED"  # prefix used in every log line / result field for injected problems


def describe(scenario: str) -> dict:
    """Machine-readable description stored in every run's metadata."""
    base = {"scenario": scenario, "simulated": scenario != "clean", "label": LABEL if scenario != "clean" else "none"}
    if scenario == "dropout":
        base.update(dropout_probability=DROPOUT_P, min_clients_present=MIN_PRESENT)
    elif scenario == "degraded_data":
        base.update(turbine=SIM_TURBINE, feature_noise_sigma=NOISE_SIGMA, positive_label_drop_fraction=LABEL_DROP_FRAC)
    elif scenario == "corrupted_update":
        base.update(turbine=SIM_TURBINE, update_scale=UPDATE_SCALE, kind="sign-flipped scaled update")
    return base


def dropout_schedule(seed: int, rounds: int, turbines=(1, 2, 3, 4)) -> dict[int, list[int]]:
    """SIMULATED dropout: {round (1-based): [turbines ABSENT that round]}.
    Depends only on (seed, rounds) so it is identical across strategies."""
    rng = np.random.default_rng(10_000 + seed)
    out: dict[int, list[int]] = {}
    for r in range(1, rounds + 1):
        absent = [t for t in turbines if rng.random() < DROPOUT_P]
        while len(turbines) - len(absent) < MIN_PRESENT:
            absent.pop(int(rng.integers(0, len(absent))))
        out[r] = sorted(absent)
    return out


def degrade_shard_arrays(train_x, train_y, val_x, val_y, seed: int):
    """SIMULATED sensor degradation for one client (see module docstring).
    Returns new arrays; presence-flag columns are left untouched (only the
    value blocks last/mean/delta get noise)."""
    from ai import features as F

    rng = np.random.default_rng(20_000 + seed)
    n_val_cols = 3 * F.N_CHANNELS  # value blocks precede the presence block

    def noisy(x):
        x = x.copy()
        x[:, :n_val_cols] += rng.normal(0.0, NOISE_SIGMA, size=(len(x), n_val_cols)).astype(np.float32)
        return x

    def drop_positives(y):
        y = y.copy()
        pos = np.nonzero(y == 1)[0]
        y[rng.choice(pos, size=int(len(pos) * LABEL_DROP_FRAC), replace=False)] = 0
        return y

    return noisy(train_x), drop_positives(train_y), noisy(val_x), drop_positives(val_y)


def corrupt_update(global_w: list[np.ndarray], local_w: list[np.ndarray]) -> list[np.ndarray]:
    """SIMULATED model poisoning: transmit w_g - UPDATE_SCALE * (w_l - w_g)."""
    return [(g - UPDATE_SCALE * (l - g)).astype(np.float32) for g, l in zip(global_w, local_w)]

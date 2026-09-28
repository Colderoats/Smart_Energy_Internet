# Module 4 results — measured on the identical held-out Module 3 test split

Real Kelmarsh SCADA, REPLAYED (test = H2 2018: 98,392 valid node-samples, **27 positives from 5 independent events**; chance PR-AUC ≈ 0.0003, chance top-1 localization ≈ 0.26). Mean ± std over seeds 0-4. A federated client is a partition of the replay (one per turbine), not a separate site. Anything labelled SIMULATED is injected degradation, not real data.


## Clean scenario — FULL-VIEW test (all four turbines' features per snapshot = Module 3's input and the backend serving path)

| Configuration | Precision | Recall | F1 | ROC-AUC | PR-AUC | Accuracy | Loc. top-1 | Event recall | Val PR-AUC (optimistic) | Rounds to conv. | Rounds×params |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Centralized, Module 3 (pooled, full snapshots) — reused | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.338 ± 0.088 | 0.0002 ± 0.0000 | 0.9994 | 0.237 ± 0.195 | 0.000 ± 0.000 | n/a | n/a | n/a |
| FedAvg (equal weights) | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.256 ± 0.026 | 0.0002 ± 0.0000 | 0.9992 | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.052 ± 0.010 | 3.4 ± 0.5 | 96,400 |
| FedProx, mu=0.001 | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.228 ± 0.014 | 0.0002 ± 0.0000 | 0.9993 | 0.015 ± 0.018 | 0.000 ± 0.000 | 0.070 ± 0.018 | 3.2 ± 2.5 | 90,730 |
| FedProx, mu=0.01 | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.311 ± 0.057 | 0.0002 ± 0.0000 | 0.9989 | 0.156 ± 0.123 | 0.000 ± 0.000 | 0.074 ± 0.013 | 1.4 ± 0.5 | 39,694 |
| FedProx, mu=0.1 | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.275 ± 0.027 | 0.0002 ± 0.0000 | 0.9985 | 0.119 ± 0.028 | 0.000 ± 0.000 | 0.091 ± 0.010 | 3.8 ± 2.6 | 107,741 |
| FedProx, mu=1 | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.404 ± 0.072 | 0.0002 ± 0.0000 | 0.9985 | 0.104 ± 0.064 | 0.000 ± 0.000 | 0.096 ± 0.024 | 17.4 ± 9.0 | 493,342 |
| FedProx + adaptive, mu=0 (adaptive weighting alone) | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.261 ± 0.034 | 0.0002 ± 0.0000 | 0.9991 | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.055 ± 0.005 | 5.6 ± 4.3 | 158,777 |
| FedProx + adaptive, mu=1 | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.392 ± 0.058 | 0.0002 ± 0.0000 | 0.9984 | 0.104 ± 0.043 | 0.000 ± 0.000 | 0.119 ± 0.010 | 18.0 ± 4.0 | 510,354 |

## Clean scenario — OWN-VIEW test (each turbine scored from its own features only = the view federated clients trained on)

| Configuration | Precision | Recall | F1 | ROC-AUC | PR-AUC | Accuracy | Loc. top-1 | Event recall | Val PR-AUC (optimistic) | Rounds to conv. | Rounds×params |
|---|---|---|---|---|---|---|---|---|---|---|---|
| FedAvg (equal weights) | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.387 ± 0.015 | 0.0002 ± 0.0000 | 0.9996 | 0.474 ± 0.068 | 0.000 ± 0.000 | 0.091 ± 0.008 | 3.4 ± 0.5 | 96,400 |
| FedProx, mu=0.001 | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.344 ± 0.013 | 0.0002 ± 0.0000 | 0.9995 | 0.415 ± 0.064 | 0.000 ± 0.000 | 0.083 ± 0.007 | 3.2 ± 2.5 | 90,730 |
| FedProx, mu=0.01 | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.345 ± 0.044 | 0.0002 ± 0.0000 | 0.9981 | 0.370 ± 0.099 | 0.000 ± 0.000 | 0.080 ± 0.010 | 1.4 ± 0.5 | 39,694 |
| FedProx, mu=0.1 | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.348 ± 0.037 | 0.0002 ± 0.0000 | 0.9983 | 0.437 ± 0.043 | 0.000 ± 0.000 | 0.079 ± 0.014 | 3.8 ± 2.6 | 107,741 |
| FedProx, mu=1 | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.432 ± 0.023 | 0.0002 ± 0.0000 | 0.9984 | 0.274 ± 0.119 | 0.000 ± 0.000 | 0.089 ± 0.015 | 17.4 ± 9.0 | 493,342 |
| FedProx + adaptive, mu=0 (adaptive weighting alone) | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.357 ± 0.041 | 0.0002 ± 0.0000 | 0.9997 | 0.400 ± 0.043 | 0.000 ± 0.000 | 0.095 ± 0.003 | 5.6 ± 4.3 | 158,777 |
| FedProx + adaptive, mu=1 | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.422 ± 0.027 | 0.0003 ± 0.0000 | 0.9977 | 0.281 ± 0.090 | 0.000 ± 0.000 | 0.101 ± 0.010 | 18.0 ± 4.0 | 510,354 |

Val PR-AUC = pooled validation PR-AUC of the selected round. It was used to choose the round (and, in the sweep, mu), so it is OPTIMISTIC. It is the only column here that separates methods, and it is not a held-out result.


## Per-client test metrics (full view, val-selected round; T1 and T4 have ZERO test positives, so recall/AUCs are n/a)

| Configuration | Client | Precision | Recall | F1 | PR-AUC |
|---|---|---|---|---|---|
| FedAvg (equal weights) | T1 | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 | n/a |
| FedAvg (equal weights) | T2 | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 |
| FedAvg (equal weights) | T3 | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.001 ± 0.000 |
| FedAvg (equal weights) | T4 | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 | n/a |
| FedProx mu=0.001 | T1 | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 | n/a |
| FedProx mu=0.001 | T2 | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 |
| FedProx mu=0.001 | T3 | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 |
| FedProx mu=0.001 | T4 | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 | n/a |
| FedProx mu=0.01 | T1 | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 | n/a |
| FedProx mu=0.01 | T2 | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.001 ± 0.000 |
| FedProx mu=0.01 | T3 | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 |
| FedProx mu=0.01 | T4 | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 | n/a |
| FedProx mu=0.1 | T1 | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 | n/a |
| FedProx mu=0.1 | T2 | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.001 ± 0.000 |
| FedProx mu=0.1 | T3 | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 |
| FedProx mu=0.1 | T4 | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 | n/a |
| FedProx mu=1 | T1 | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 | n/a |
| FedProx mu=1 | T2 | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.001 ± 0.000 |
| FedProx mu=1 | T3 | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 |
| FedProx mu=1 | T4 | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 | n/a |
| FedProx + adaptive mu=0 | T1 | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 | n/a |
| FedProx + adaptive mu=0 | T2 | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 |
| FedProx + adaptive mu=0 | T3 | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.001 ± 0.000 |
| FedProx + adaptive mu=0 | T4 | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 | n/a |
| FedProx + adaptive mu=1 | T1 | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 | n/a |
| FedProx + adaptive mu=1 | T2 | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.001 ± 0.000 |
| FedProx + adaptive mu=1 | T3 | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 |
| FedProx + adaptive mu=1 | T4 | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 | n/a |

## SIMULATED fault tolerance (full view; degradation is injected, not real)

| Scenario | Strategy | Precision | Recall | F1 | ROC-AUC | PR-AUC | Accuracy | Loc. top-1 | Event recall |
|---|---|---|---|---|---|---|---|---|---|
| clean (real replay) | FedAvg (equal weights) | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.256 ± 0.026 | 0.0002 ± 0.0000 | 0.9992 | 0.000 ± 0.000 | 0.000 ± 0.000 |
| clean (real replay) | FedProx mu=1 | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.404 ± 0.072 | 0.0002 ± 0.0000 | 0.9985 | 0.104 ± 0.064 | 0.000 ± 0.000 |
| clean (real replay) | FedProx + adaptive mu=1 | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.392 ± 0.058 | 0.0002 ± 0.0000 | 0.9984 | 0.104 ± 0.043 | 0.000 ± 0.000 |

## Adaptive weights (mean aggregation weight per client over rounds and seeds; equal = 0.25)

| Scenario | mu | T1 | T2 | T3 | T4 |
|---|---|---|---|---|---|
| clean (real replay) | 0 | 0.230 | 0.316 | 0.246 | 0.208 |
| clean (real replay) | 1 | 0.113 | 0.322 | 0.236 | 0.329 |

# Measured (simulated testbed) vs paper targets

Every measured value comes from a run on the **simulated testbed** (`provenance: simulated_testbed`); paper values are targets, never inputs.
Tolerance: +-5 % relative (+-0.05 absolute when the paper value is 0); structural counts must match exactly.
The measured value is rounded to the number of decimals the paper uses. Rows marked **outside** keep the measured number and give the most likely reason.

## Within-tolerance count per table

| Paper | Table | within | total |
|---|---|---|---|
| conference | Table II | 7 | 7 |
| conference | Table IV | 4 | 15 |
| conference | Table V | 4 | 20 |
| conference | Table VI | 2 | 12 |
| conference | Table VII | 6 | 18 |
| conference | Table VIII | 7 | 12 |
| conference | Sec IV-B | 1 | 3 |
| conference | Sec IV-D | 0 | 4 |
| journal | Table III | 21 | 21 |
| journal | Table III / Sec 5.1 | 3 | 3 |
| journal | Table IV | 0 | 36 |
| journal | Table V | 0 | 27 |
| journal | Table VI | 0 | 12 |
| journal | Table VII | 1 | 18 |
| journal | Table VIII | 0 | 5 |
| journal | Table IX | 0 | 9 |
| journal | Table X | 0 | 42 |
| journal | Table XI | 1 | 15 |
| journal | Abstract | 0 | 3 |
| **all** | | **57** | **282** |

## Conference - Table II

| target | topology | measured | paper | abs diff | rel diff | status |
|---|---|---|---|---|---|---|
| C.T2.solar.nodes |  | 4  | 4 | +0 | +0.0 % | within tolerance |
| C.T2.solar.samples |  | 140160  | 140160 | +0 | +0.0 % | within tolerance |
| C.T2.wind.nodes |  | 4  | 4 | +0 | +0.0 % | within tolerance |
| C.T2.wind.samples |  | 140160  | 140160 | +0 | +0.0 % | within tolerance |
| C.T2.hydro.nodes |  | 4  | 4 | +0 | +0.0 % | within tolerance |
| C.T2.hydro.samples |  | 140160  | 140160 | +0 | +0.0 % | within tolerance |
| C.T2.total.samples |  | 420480  | 420480 | +0 | +0.0 % | within tolerance |

## Conference - Table IV

| target | topology | measured | paper | abs diff | rel diff | status |
|---|---|---|---|---|---|---|
| C.T4.solar.auc |  | 0.93 ± 0.0164  | 0.99 | -0.06 | -6.1 % | outside tolerance |
| C.T4.solar.precision |  | 0.4 ± 0.0588  | 0.88 | -0.48 | -54.5 % | outside tolerance |
| C.T4.solar.recall |  | 0.39 ± 0.0747  | 0.23 | +0.16 | +69.6 % | outside tolerance |
| C.T4.solar.f1 |  | 0.39 ± 0.0654  | 0.36 | +0.03 | +8.3 % | outside tolerance |
| C.T4.solar.far_pct |  | 1.33 ± 0.13 % | 0.04 | +1.29 | +3225.0 % | outside tolerance |
| C.T4.wind.auc |  | 0.974 ± 0.00417  | 0.983 | -0.009 | -0.9 % | within tolerance |
| C.T4.wind.precision |  | 0.22 ± 0.064  | 0.83 | -0.61 | -73.5 % | outside tolerance |
| C.T4.wind.recall |  | 0.24 ± 0.0344  | 0.32 | -0.08 | -25.0 % | outside tolerance |
| C.T4.wind.f1 |  | 0.23 ± 0.0474  | 0.44 | -0.21 | -47.7 % | outside tolerance |
| C.T4.wind.far_pct |  | 2.04 ± 0.286 % | 0.15 | +1.89 | +1260.0 % | outside tolerance |
| C.T4.hydro.auc |  | 0.999 ± 0.00031  | 0.999 | +0 | +0.0 % | within tolerance |
| C.T4.hydro.precision |  | 0.9 ± 0.0197  | 0.9 | +0 | +0.0 % | within tolerance |
| C.T4.hydro.recall |  | 0.94 ± 0.00803  | 0.89 | +0.05 | +5.6 % | outside tolerance |
| C.T4.hydro.f1 |  | 0.9 ± 0.0118  | 0.9 | +0 | +0.0 % | within tolerance |
| C.T4.hydro.far_pct |  | 0.3 ± 0.0624 % | 0.24 | +0.06 | +25.0 % | outside tolerance |

## Conference - Table V

| target | topology | measured | paper | abs diff | rel diff | status |
|---|---|---|---|---|---|---|
| C.T5.tau0.3.summer |  | 0.27 ± 0.0224  | 0.48 | -0.21 | -43.7 % | outside tolerance |
| C.T5.tau0.3.monsoon |  | 0.19 ± 0.00758  | 0.71 | -0.52 | -73.2 % | outside tolerance |
| C.T5.tau0.3.winter |  | 0.3 ± 0.00542  | 0.63 | -0.33 | -52.4 % | outside tolerance |
| C.T5.tau0.3.high_load |  | 0 ± 0.00203  | 0.2 | -0.2 | -100.0 % | outside tolerance |
| C.T5.tau0.3.low_load |  | 0.47 ± 0.0173  | 0.69 | -0.22 | -31.9 % | outside tolerance |
| C.T5.tau0.5.summer |  | 0.4 ± 0.018  | 0.42 | -0.02 | -4.8 % | within tolerance |
| C.T5.tau0.5.monsoon |  | 0.31 ± 0.0127  | 0.72 | -0.41 | -56.9 % | outside tolerance |
| C.T5.tau0.5.winter |  | 0.5 ± 0.00929  | 0.6 | -0.1 | -16.7 % | outside tolerance |
| C.T5.tau0.5.high_load |  | 0.01 ± 0.00402  | 0.25 | -0.24 | -96.0 % | outside tolerance |
| C.T5.tau0.5.low_load |  | 0.59 ± 0.00632  | 0.65 | -0.06 | -9.2 % | outside tolerance |
| C.T5.tau0.7.summer |  | 0.49 ± 0.00786  | 0.36 | +0.13 | +36.1 % | outside tolerance |
| C.T5.tau0.7.monsoon |  | 0.42 ± 0.0162  | 0.71 | -0.29 | -40.8 % | outside tolerance |
| C.T5.tau0.7.winter |  | 0.54 ± 0.0116  | 0.56 | -0.02 | -3.6 % | within tolerance |
| C.T5.tau0.7.high_load |  | 0.03 ± 0.00896  | 0.26 | -0.23 | -88.5 % | outside tolerance |
| C.T5.tau0.7.low_load |  | 0.61 ± 0.00646  | 0.61 | +0 | +0.0 % | within tolerance |
| C.T5.tau0.9.summer |  | 0.51 ± 0.0158  | 0.29 | +0.22 | +75.9 % | outside tolerance |
| C.T5.tau0.9.monsoon |  | 0.5 ± 0.0143  | 0.7 | -0.2 | -28.6 % | outside tolerance |
| C.T5.tau0.9.winter |  | 0.5 ± 0.00743  | 0.49 | +0.01 | +2.0 % | within tolerance |
| C.T5.tau0.9.high_load |  | 0.1 ± 0.0291  | 0.3 | -0.2 | -66.7 % | outside tolerance |
| C.T5.tau0.9.low_load |  | 0.62 ± 0.00727  | 0.54 | +0.08 | +14.8 % | outside tolerance |

## Conference - Table VI

| target | topology | measured | paper | abs diff | rel diff | status |
|---|---|---|---|---|---|---|
| C.T6.fedavg.iid.rmse |  | 1.22 ± 0.096 kW | 2.93 | -1.71 | -58.4 % | outside tolerance |
| C.T6.fedavg.alpha0.5.rmse |  | 1.17 ± 0.0712 kW | 2.85 | -1.68 | -58.9 % | outside tolerance |
| C.T6.fedavg.alpha0.1.rmse |  | 1.15 ± 0.113 kW | 2.79 | -1.64 | -58.8 % | outside tolerance |
| C.T6.fedavg.rounds |  | 19.3 ± 6.6 rounds | 18.7 | +0.6 | +3.2 % | within tolerance |
| C.T6.fedprox_fixed.iid.rmse |  | 1.12 ± 0.0381 kW | 3.03 | -1.91 | -63.0 % | outside tolerance |
| C.T6.fedprox_fixed.alpha0.5.rmse |  | 1.1 ± 0.0174 kW | 2.9 | -1.8 | -62.1 % | outside tolerance |
| C.T6.fedprox_fixed.alpha0.1.rmse |  | 1.09 ± 0.0896 kW | 2.79 | -1.7 | -60.9 % | outside tolerance |
| C.T6.fedprox_fixed.rounds |  | 21 ± 3.74 rounds | 18 | +3 | +16.7 % | outside tolerance |
| C.T6.fedprox_adaptive.iid.rmse |  | 1.12 ± 0.0118 kW | 3.03 | -1.91 | -63.0 % | outside tolerance |
| C.T6.fedprox_adaptive.alpha0.5.rmse |  | 1.07 ± 0.0515 kW | 2.88 | -1.81 | -62.8 % | outside tolerance |
| C.T6.fedprox_adaptive.alpha0.1.rmse |  | 1.06 ± 0.1 kW | 2.78 | -1.72 | -61.9 % | outside tolerance |
| C.T6.fedprox_adaptive.rounds |  | 18.3 ± 1.25 rounds | 18 | +0.3 | +1.7 % | within tolerance |

## Conference - Table VII

| target | topology | measured | paper | abs diff | rel diff | status |
|---|---|---|---|---|---|---|
| C.T7.lstm.rmse |  | 0.88 ± 0.00416 kW | 2.66 | -1.78 | -66.9 % | outside tolerance |
| C.T7.lstm.mae |  | 0.34 ± 0.00913 kW | 1.38 | -1.04 | -75.4 % | outside tolerance |
| C.T7.lstm.r2 |  | 0.995 ± 5.09e-05  | 0.979 | +0.016 | +1.6 % | within tolerance |
| C.T7.gru.rmse |  | 0.88 ± 0.00689 kW | 2.65 | -1.77 | -66.8 % | outside tolerance |
| C.T7.gru.mae |  | 0.34 ± 0.0137 kW | 1.36 | -1.02 | -75.0 % | outside tolerance |
| C.T7.gru.r2 |  | 0.995 ± 8.37e-05  | 0.979 | +0.016 | +1.6 % | within tolerance |
| C.T7.gcn_fixed.rmse |  | 0.88 ± 0.00337 kW | 2.74 | -1.86 | -67.9 % | outside tolerance |
| C.T7.gcn_fixed.mae |  | 0.34 ± 0.0121 kW | 1.51 | -1.17 | -77.5 % | outside tolerance |
| C.T7.gcn_fixed.r2 |  | 0.995 ± 4.1e-05  | 0.977 | +0.018 | +1.8 % | within tolerance |
| C.T7.tgnn.rmse |  | 0.95 ± 0.0288 kW | 2.75 | -1.8 | -65.5 % | outside tolerance |
| C.T7.tgnn.mae |  | 0.46 ± 0.0476 kW | 1.56 | -1.1 | -70.5 % | outside tolerance |
| C.T7.tgnn.r2 |  | 0.994 ± 0.000378  | 0.977 | +0.017 | +1.7 % | within tolerance |
| C.T7.ta_gnn_no_adapt.rmse |  | 0.89 ± 0.0131 kW | 2.66 | -1.77 | -66.5 % | outside tolerance |
| C.T7.ta_gnn_no_adapt.mae |  | 0.36 ± 0.0231 kW | 1.39 | -1.03 | -74.1 % | outside tolerance |
| C.T7.ta_gnn_no_adapt.r2 |  | 0.995 ± 0.000162  | 0.979 | +0.016 | +1.6 % | within tolerance |
| C.T7.ta_gnn.rmse |  | 0.89 ± 0.00664 kW | 2.65 | -1.76 | -66.4 % | outside tolerance |
| C.T7.ta_gnn.mae |  | 0.35 ± 0.0177 kW | 1.35 | -1 | -74.1 % | outside tolerance |
| C.T7.ta_gnn.r2 |  | 0.995 ± 8.15e-05  | 0.979 | +0.016 | +1.6 % | within tolerance |

## Conference - Table VIII

| target | topology | measured | paper | abs diff | rel diff | status |
|---|---|---|---|---|---|---|
| C.T8.n5.latency_ms |  | 58 ± 3.49 ms | 59 | -1 | -1.7 % | within tolerance |
| C.T8.n5.gas |  | 54031 ± 1.37e+04 gas | 53862 | +169 | +0.3 % | within tolerance |
| C.T8.n5.tps |  | 16.8 ± 0.693 tx/s | 21.7 | -4.9 | -22.6 % | outside tolerance |
| C.T8.n10.latency_ms |  | 54 ± 3.42 ms | 53 | +1 | +1.9 % | within tolerance |
| C.T8.n10.gas |  | 54032 ± 1.37e+04 gas | 53863 | +169 | +0.3 % | within tolerance |
| C.T8.n10.tps |  | 17.9 ± 0.691 tx/s | 22.8 | -4.9 | -21.5 % | outside tolerance |
| C.T8.n20.latency_ms |  | 53 ± 3.56 ms | 55 | -2 | -3.6 % | within tolerance |
| C.T8.n20.gas |  | 54032 ± 1.37e+04 gas | 53864 | +168 | +0.3 % | within tolerance |
| C.T8.n20.tps |  | 18.3 ± 0.748 tx/s | 22.4 | -4.1 | -18.3 % | outside tolerance |
| C.T8.n50.latency_ms |  | 53 ± 3.15 ms | 58 | -5 | -8.6 % | outside tolerance |
| C.T8.n50.gas |  | 54032 ± 1.37e+04 gas | 53864 | +168 | +0.3 % | within tolerance |
| C.T8.n50.tps |  | 18.4 ± 0.356 tx/s | 21.3 | -2.9 | -13.6 % | outside tolerance |

## Conference - Sec IV-B

| target | topology | measured | paper | abs diff | rel diff | status |
|---|---|---|---|---|---|---|
| C.T4.auc_std_max |  | 0.016  | 0.003 | +0.013 | +433.3 % | outside tolerance |
| C.T4.mean_delay_intervals |  | 2.5 ± 0.45 intervals | 2.7 | -0.2 | -7.4 % | outside tolerance |
| C.T4.detected_before_end_pct |  | 65 ± 7.17 % | 62 | +3 | +4.8 % | within tolerance |

## Conference - Sec IV-D

| target | topology | measured | paper | abs diff | rel diff | status |
|---|---|---|---|---|---|---|
| C.T6.mu0.001.val_rmse |  | 1.54 kW | 3.23 | -1.69 | -52.3 % | outside tolerance |
| C.T6.mu0.01.val_rmse |  | 1.55 kW | 3.33 | -1.78 | -53.5 % | outside tolerance |
| C.T6.mu0.1.val_rmse |  | 1.84 kW | 3.77 | -1.93 | -51.2 % | outside tolerance |
| C.T6.central_rmse |  | 0.89 kW | 2.65 | -1.76 | -66.4 % | outside tolerance |

## Journal - Table III

| target | topology | measured | paper | abs diff | rel diff | status |
|---|---|---|---|---|---|---|
| J.T3.A.nodes | A | 6  | 6 | +0 | +0.0 % | within tolerance |
| J.T3.A.lines | A | 5  | 5 | +0 | +0.0 % | within tolerance |
| J.T3.A.solar_nodes | A | 2  | 2 | +0 | +0.0 % | within tolerance |
| J.T3.A.wind_hydro_sources | A | 1  | 1 | +0 | +0.0 % | within tolerance |
| J.T3.A.clients | A | 6  | 6 | +0 | +0.0 % | within tolerance |
| J.T3.A.hours | A | 24  | 24 | +0 | +0.0 % | within tolerance |
| J.T3.A.faults | A | 20  | 20 | +0 | +0.0 % | within tolerance |
| J.T3.B.nodes | B | 14  | 14 | +0 | +0.0 % | within tolerance |
| J.T3.B.lines | B | 20  | 20 | +0 | +0.0 % | within tolerance |
| J.T3.B.solar_nodes | B | 4  | 4 | +0 | +0.0 % | within tolerance |
| J.T3.B.wind_hydro_sources | B | 2  | 2 | +0 | +0.0 % | within tolerance |
| J.T3.B.clients | B | 14  | 14 | +0 | +0.0 % | within tolerance |
| J.T3.B.hours | B | 24  | 24 | +0 | +0.0 % | within tolerance |
| J.T3.B.faults | B | 20  | 20 | +0 | +0.0 % | within tolerance |
| J.T3.C.nodes | C | 33  | 33 | +0 | +0.0 % | within tolerance |
| J.T3.C.lines | C | 37  | 37 | +0 | +0.0 % | within tolerance |
| J.T3.C.solar_nodes | C | 6  | 6 | +0 | +0.0 % | within tolerance |
| J.T3.C.wind_hydro_sources | C | 3  | 3 | +0 | +0.0 % | within tolerance |
| J.T3.C.clients | C | 33  | 33 | +0 | +0.0 % | within tolerance |
| J.T3.C.hours | C | 24  | 24 | +0 | +0.0 % | within tolerance |
| J.T3.C.faults | C | 20  | 20 | +0 | +0.0 % | within tolerance |

## Journal - Table III / Sec 5.1

| target | topology | measured | paper | abs diff | rel diff | status |
|---|---|---|---|---|---|---|
| J.T3.samples | A | 17280  | 17280 | +0 | +0.0 % | within tolerance |
| J.T3.samples | B | 17280  | 17280 | +0 | +0.0 % | within tolerance |
| J.T3.samples | C | 17280  | 17280 | +0 | +0.0 % | within tolerance |

## Journal - Table IV

| target | topology | measured | paper | abs diff | rel diff | status |
|---|---|---|---|---|---|---|
| J.T4.o1.train_loss | A | 0.0888 ± 0.0197  | 0.0482 | +0.0406 | +84.2 % | outside tolerance |
| J.T4.o1.val_loss | A | 1.4569 ± 1.09  | 0.0515 | +1.405 | +2728.9 % | outside tolerance |
| J.T4.o1.val_f1 | A | 0.594 ± 0.0956  | 0.882 | -0.288 | -32.7 % | outside tolerance |
| J.T4.o2.train_loss | A | 0.1137 ± 0.0137  | 0.0315 | +0.0822 | +261.0 % | outside tolerance |
| J.T4.o2.val_loss | A | 0.8718 ± 0.506  | 0.0342 | +0.8376 | +2449.1 % | outside tolerance |
| J.T4.o2.val_f1 | A | 0.628 ± 0.0862  | 0.915 | -0.287 | -31.4 % | outside tolerance |
| J.T4.o3.train_loss | A | 0.0821 ± 0.00781  | 0.0248 | +0.0573 | +231.0 % | outside tolerance |
| J.T4.o3.val_loss | A | 1.3198 ± 0.987  | 0.0271 | +1.293 | +4770.1 % | outside tolerance |
| J.T4.o3.val_f1 | A | 0.612 ± 0.0875  | 0.942 | -0.33 | -35.0 % | outside tolerance |
| J.T4.o4.train_loss | A | 0.2481 ± 0.0363  | 0.0385 | +0.2096 | +544.4 % | outside tolerance |
| J.T4.o4.val_loss | A | 0.396 ± 0.0866  | 0.041 | +0.355 | +865.9 % | outside tolerance |
| J.T4.o4.val_f1 | A | 0.583 ± 0.0719  | 0.901 | -0.318 | -35.3 % | outside tolerance |
| J.T4.o1.train_loss | B | 0.1158 ± 0.029  | 0.0482 | +0.0676 | +140.2 % | outside tolerance |
| J.T4.o1.val_loss | B | 1.6601 ± 0.801  | 0.0515 | +1.609 | +3123.5 % | outside tolerance |
| J.T4.o1.val_f1 | B | 0.382 ± 0.0834  | 0.882 | -0.5 | -56.7 % | outside tolerance |
| J.T4.o2.train_loss | B | 0.2102 ± 0.0422  | 0.0315 | +0.1787 | +567.3 % | outside tolerance |
| J.T4.o2.val_loss | B | 1.0905 ± 0.49  | 0.0342 | +1.056 | +3088.6 % | outside tolerance |
| J.T4.o2.val_f1 | B | 0.344 ± 0.0291  | 0.915 | -0.571 | -62.4 % | outside tolerance |
| J.T4.o3.train_loss | B | 0.1145 ± 0.0435  | 0.0248 | +0.0897 | +361.7 % | outside tolerance |
| J.T4.o3.val_loss | B | 1.7443 ± 1.1  | 0.0271 | +1.717 | +6336.5 % | outside tolerance |
| J.T4.o3.val_f1 | B | 0.37 ± 0.0663  | 0.942 | -0.572 | -60.7 % | outside tolerance |
| J.T4.o4.train_loss | B | 0.353 ± 0.0189  | 0.0385 | +0.3145 | +816.9 % | outside tolerance |
| J.T4.o4.val_loss | B | 0.487 ± 0.191  | 0.041 | +0.446 | +1087.8 % | outside tolerance |
| J.T4.o4.val_f1 | B | 0.343 ± 0.0283  | 0.901 | -0.558 | -61.9 % | outside tolerance |
| J.T4.o1.train_loss | C | 0.2141  | 0.0482 | +0.1659 | +344.2 % | outside tolerance |
| J.T4.o1.val_loss | C | 0.316  | 0.0515 | +0.2645 | +513.6 % | outside tolerance |
| J.T4.o1.val_f1 | C | 0.491  | 0.882 | -0.391 | -44.3 % | outside tolerance |
| J.T4.o2.train_loss | C | 0.2154  | 0.0315 | +0.1839 | +583.8 % | outside tolerance |
| J.T4.o2.val_loss | C | 0.2504  | 0.0342 | +0.2162 | +632.2 % | outside tolerance |
| J.T4.o2.val_f1 | C | 0.492  | 0.915 | -0.423 | -46.2 % | outside tolerance |
| J.T4.o3.train_loss | C | 0.2283  | 0.0248 | +0.2035 | +820.6 % | outside tolerance |
| J.T4.o3.val_loss | C | 0.3132  | 0.0271 | +0.2861 | +1055.7 % | outside tolerance |
| J.T4.o3.val_f1 | C | 0.483  | 0.942 | -0.459 | -48.7 % | outside tolerance |
| J.T4.o4.train_loss | C | 0.2845  | 0.0385 | +0.246 | +639.0 % | outside tolerance |
| J.T4.o4.val_loss | C | 0.263  | 0.041 | +0.222 | +541.5 % | outside tolerance |
| J.T4.o4.val_f1 | C | 0.489  | 0.901 | -0.412 | -45.7 % | outside tolerance |

## Journal - Table V

| target | topology | measured | paper | abs diff | rel diff | status |
|---|---|---|---|---|---|---|
| J.T5.3_LRS.train_loss | A | 0.0176 ± 0.00227  | 0.0112 | +0.0064 | +57.1 % | outside tolerance |
| J.T5.3_LRS.val_loss | A | 2.5929 ± 1.27  | 0.0128 | +2.58 | +20157.0 % | outside tolerance |
| J.T5.3_LRS.val_f1 | A | 0.51 ± 0.0368  | 0.978 | -0.468 | -47.9 % | outside tolerance |
| J.T5.3_NLRS.train_loss | A | 0.0276 ± 0.0173  | 0.0185 | +0.0091 | +49.2 % | outside tolerance |
| J.T5.3_NLRS.val_loss | A | 2.3436 ± 1.46  | 0.0205 | +2.323 | +11332.2 % | outside tolerance |
| J.T5.3_NLRS.val_f1 | A | 0.542 ± 0.03  | 0.954 | -0.412 | -43.2 % | outside tolerance |
| J.T5.2_NLRS.train_loss | A | 0.0372 ± 0.00742  | 0.0298 | +0.0074 | +24.8 % | outside tolerance |
| J.T5.2_NLRS.val_loss | A | 1.294 ± 1.1  | 0.0321 | +1.262 | +3931.2 % | outside tolerance |
| J.T5.2_NLRS.val_f1 | A | 0.615 ± 0.0898  | 0.923 | -0.308 | -33.4 % | outside tolerance |
| J.T5.3_LRS.train_loss | B | 0.0152 ± 0.0013  | 0.0112 | +0.004 | +35.7 % | outside tolerance |
| J.T5.3_LRS.val_loss | B | 3.8915 ± 2.19  | 0.0128 | +3.879 | +30302.3 % | outside tolerance |
| J.T5.3_LRS.val_f1 | B | 0.367 ± 0.0635  | 0.978 | -0.611 | -62.5 % | outside tolerance |
| J.T5.3_NLRS.train_loss | B | 0.0118 ± 0.00304  | 0.0185 | -0.0067 | -36.2 % | outside tolerance |
| J.T5.3_NLRS.val_loss | B | 2.8947 ± 1.42  | 0.0205 | +2.874 | +14020.5 % | outside tolerance |
| J.T5.3_NLRS.val_f1 | B | 0.395 ± 0.106  | 0.954 | -0.559 | -58.6 % | outside tolerance |
| J.T5.2_NLRS.train_loss | B | 0.0546 ± 0.0212  | 0.0298 | +0.0248 | +83.2 % | outside tolerance |
| J.T5.2_NLRS.val_loss | B | 5.1261 ± 3.09  | 0.0321 | +5.094 | +15869.2 % | outside tolerance |
| J.T5.2_NLRS.val_f1 | B | 0.341 ± 0.0308  | 0.923 | -0.582 | -63.1 % | outside tolerance |
| J.T5.3_LRS.train_loss | C | 0.022  | 0.0112 | +0.0108 | +96.4 % | outside tolerance |
| J.T5.3_LRS.val_loss | C | 0.741  | 0.0128 | +0.7282 | +5689.1 % | outside tolerance |
| J.T5.3_LRS.val_f1 | C | 0.487  | 0.978 | -0.491 | -50.2 % | outside tolerance |
| J.T5.3_NLRS.train_loss | C | 0.0044  | 0.0185 | -0.0141 | -76.2 % | outside tolerance |
| J.T5.3_NLRS.val_loss | C | 1.0679  | 0.0205 | +1.047 | +5109.3 % | outside tolerance |
| J.T5.3_NLRS.val_f1 | C | 0.464  | 0.954 | -0.49 | -51.4 % | outside tolerance |
| J.T5.2_NLRS.train_loss | C | 0.0462  | 0.0298 | +0.0164 | +55.0 % | outside tolerance |
| J.T5.2_NLRS.val_loss | C | 0.5242  | 0.0321 | +0.4921 | +1533.0 % | outside tolerance |
| J.T5.2_NLRS.val_f1 | C | 0.488  | 0.923 | -0.435 | -47.1 % | outside tolerance |

## Journal - Table VI

| target | topology | measured | paper | abs diff | rel diff | status |
|---|---|---|---|---|---|---|
| J.T6.A.ta_gnn.mae | A | 10.19 ± 1.61 kW | 1.37 | +8.82 | +643.8 % | outside tolerance |
| J.T6.A.ta_gnn.rmse | A | 26.87 ± 6.6 kW | 1.88 | +24.99 | +1329.3 % | outside tolerance |
| J.T6.A.gcn.mae | A | 20.47 ± 2.13 kW | 1.42 | +19.05 | +1341.5 % | outside tolerance |
| J.T6.A.gcn.rmse | A | 33.39 ± 6.69 kW | 1.95 | +31.44 | +1612.3 % | outside tolerance |
| J.T6.B.ta_gnn.mae | B | 5.47 ± 0.74 kW | 3.44 | +2.03 | +59.0 % | outside tolerance |
| J.T6.B.ta_gnn.rmse | B | 11.42 ± 4.82 kW | 4.65 | +6.77 | +145.6 % | outside tolerance |
| J.T6.B.gcn.mae | B | 32.22 ± 2.21 kW | 3.85 | +28.37 | +736.9 % | outside tolerance |
| J.T6.B.gcn.rmse | B | 41 ± 2.67 kW | 5.2 | +35.8 | +688.5 % | outside tolerance |
| J.T6.C.ta_gnn.mae | C | 7.81 kW | 7.42 | +0.39 | +5.3 % | outside tolerance |
| J.T6.C.ta_gnn.rmse | C | 15.39 kW | 9.95 | +5.44 | +54.7 % | outside tolerance |
| J.T6.C.gcn.mae | C | 22.5 kW | 8.5 | +14 | +164.7 % | outside tolerance |
| J.T6.C.gcn.rmse | C | 31.7 kW | 11.4 | +20.3 | +178.1 % | outside tolerance |

## Journal - Table VII

| target | topology | measured | paper | abs diff | rel diff | status |
|---|---|---|---|---|---|---|
| J.T7.A.default.detection_f1 | A | 0.588 ± 0.0173  | 0.885 | -0.297 | -33.6 % | outside tolerance |
| J.T7.A.default.t_rec | A | 601.6 ± 47.8 s | 42 | +559.6 | +1332.4 % | outside tolerance |
| J.T7.A.default.e_uns | A | 371.4 ± 73.1 kWh | 12.5 | +358.9 | +2871.2 % | outside tolerance |
| J.T7.A.twin.detection_f1 | A | 0.59 ± 0.0594  | 0.916 | -0.326 | -35.6 % | outside tolerance |
| J.T7.A.twin.t_rec | A | 130.4 ± 31 s | 38.5 | +91.9 | +238.7 % | outside tolerance |
| J.T7.A.twin.e_uns | A | 192.5 ± 31.6 kWh | 10.2 | +182.3 | +1787.3 % | outside tolerance |
| J.T7.B.default.detection_f1 | B | 0.378 ± 0.0532  | 0.862 | -0.484 | -56.1 % | outside tolerance |
| J.T7.B.default.t_rec | B | nan ± nan s | 88 | +nan | +nan % | outside tolerance |
| J.T7.B.default.e_uns | B | 2.1 ± 2.93 kWh | 38.4 | -36.3 | -94.5 % | outside tolerance |
| J.T7.B.twin.detection_f1 | B | 0.502 ± 0.0661  | 0.948 | -0.446 | -47.0 % | outside tolerance |
| J.T7.B.twin.t_rec | B | 672.2 ± 79.2 s | 62 | +610.2 | +984.2 % | outside tolerance |
| J.T7.B.twin.e_uns | B | 137 ± 114 kWh | 25.6 | +111.4 | +435.2 % | outside tolerance |
| J.T7.C.default.detection_f1 | C | 0.54  | 0.84 | -0.3 | -35.7 % | outside tolerance |
| J.T7.C.default.t_rec | C | 55.6 s | 145 | -89.4 | -61.7 % | outside tolerance |
| J.T7.C.default.e_uns | C | 90.8 kWh | 92 | -1.2 | -1.3 % | within tolerance |
| J.T7.C.twin.detection_f1 | C | 0.512  | 0.952 | -0.44 | -46.2 % | outside tolerance |
| J.T7.C.twin.t_rec | C | 135.3 s | 96 | +39.3 | +40.9 % | outside tolerance |
| J.T7.C.twin.e_uns | C | 148.9 kWh | 54.2 | +94.7 | +174.7 % | outside tolerance |

## Journal - Table VIII

| target | topology | measured | paper | abs diff | rel diff | status |
|---|---|---|---|---|---|---|
| J.T8.C.open+close_tie | C | 13 events | 8 | +5 | +62.5 % | outside tolerance |
| J.T8.C.open+close_tie+island | C | 0 events | 6 | -6 | -100.0 % | outside tolerance |
| J.T8.C.open+close_tie+curtail | C | 0 events | 4 | -4 | -100.0 % | outside tolerance |
| J.T8.C.open+island | C | 7 events | 2 | +5 | +250.0 % | outside tolerance |
| J.T8.C.example_cost | C | 0.05  | 0.42 | -0.37 | -88.1 % | outside tolerance |

## Journal - Table IX

| target | topology | measured | paper | abs diff | rel diff | status |
|---|---|---|---|---|---|---|
| J.T9.A.forecast_mae_improvement | A | 50.19 % | 3.52 | +46.67 | +1325.9 % | outside tolerance |
| J.T9.A.fault_f1_improvement | A | 0.3 % | 3.5 | -3.2 | -91.4 % | outside tolerance |
| J.T9.A.recovery_improvement | A | 78.32 % | 8.33 | +69.99 | +840.2 % | outside tolerance |
| J.T9.B.forecast_mae_improvement | B | 83.01 % | 10.65 | +72.36 | +679.4 % | outside tolerance |
| J.T9.B.fault_f1_improvement | B | 32.84 % | 9.98 | +22.86 | +229.1 % | outside tolerance |
| J.T9.B.recovery_improvement | B | nan % | 29.55 | +nan | +nan % | outside tolerance |
| J.T9.C.forecast_mae_improvement | C | 65.36 % | 12.71 | +52.65 | +414.2 % | outside tolerance |
| J.T9.C.fault_f1_improvement | C | -5.13 % | 13.33 | -18.46 | -138.5 % | outside tolerance |
| J.T9.C.recovery_improvement | C | -143.41 % | 33.79 | -177.2 | -524.4 % | outside tolerance |

## Journal - Table X

| target | topology | measured | paper | abs diff | rel diff | status |
|---|---|---|---|---|---|---|
| J.T10.central.val_loss | A | 2.5929 ± 1.27  | 0.0118 | +2.581 | +21873.7 % | outside tolerance |
| J.T10.central.fault_f1 | A | 0.51 ± 0.0368  | 0.975 | -0.465 | -47.7 % | outside tolerance |
| J.T10.fedavg.rounds | A | 1 rounds | 85 | -84 | -98.8 % | outside tolerance |
| J.T10.fedavg.comm_mb | A | 5.9 ± 8.88e-16 MB | 118.2 | -112.3 | -95.0 % | outside tolerance |
| J.T10.fedavg.val_loss | A | 1.0798 ± 0.85  | 0.0245 | +1.055 | +4307.3 % | outside tolerance |
| J.T10.fedavg.fault_f1 | A | 0.617 ± 0.0809  | 0.921 | -0.304 | -33.0 % | outside tolerance |
| J.T10.fedprox.rounds | A | 1 rounds | 62 | -61 | -98.4 % | outside tolerance |
| J.T10.fedprox.comm_mb | A | 5.9 ± 8.88e-16 MB | 86.2 | -80.3 | -93.2 % | outside tolerance |
| J.T10.fedprox.val_loss | A | 0.8688 ± 0.252  | 0.0182 | +0.8506 | +4673.6 % | outside tolerance |
| J.T10.fedprox.fault_f1 | A | 0.571 ± 0.0302  | 0.945 | -0.374 | -39.6 % | outside tolerance |
| J.T10.adaptive_fedprox.rounds | A | 1 rounds | 42 | -41 | -97.6 % | outside tolerance |
| J.T10.adaptive_fedprox.comm_mb | A | 5.9 ± 8.88e-16 MB | 58.5 | -52.6 | -89.9 % | outside tolerance |
| J.T10.adaptive_fedprox.val_loss | A | 0.6893 ± 0.192  | 0.0128 | +0.6765 | +5285.2 % | outside tolerance |
| J.T10.adaptive_fedprox.fault_f1 | A | 0.567 ± 0.025  | 0.972 | -0.405 | -41.7 % | outside tolerance |
| J.T10.central.val_loss | B | 3.8915 ± 2.19  | 0.0118 | +3.88 | +32878.8 % | outside tolerance |
| J.T10.central.fault_f1 | B | 0.367 ± 0.0635  | 0.975 | -0.608 | -62.4 % | outside tolerance |
| J.T10.fedavg.rounds | B | 1 rounds | 85 | -84 | -98.8 % | outside tolerance |
| J.T10.fedavg.comm_mb | B | 13.7 MB | 118.2 | -104.5 | -88.4 % | outside tolerance |
| J.T10.fedavg.val_loss | B | 1.697 ± 0.777  | 0.0245 | +1.673 | +6826.5 % | outside tolerance |
| J.T10.fedavg.fault_f1 | B | 0.343 ± 0.0286  | 0.921 | -0.578 | -62.8 % | outside tolerance |
| J.T10.fedprox.rounds | B | 1 rounds | 62 | -61 | -98.4 % | outside tolerance |
| J.T10.fedprox.comm_mb | B | 13.7 MB | 86.2 | -72.5 | -84.1 % | outside tolerance |
| J.T10.fedprox.val_loss | B | 1.3463 ± 0.765  | 0.0182 | +1.328 | +7297.3 % | outside tolerance |
| J.T10.fedprox.fault_f1 | B | 0.344 ± 0.0289  | 0.945 | -0.601 | -63.6 % | outside tolerance |
| J.T10.adaptive_fedprox.rounds | B | 1 rounds | 42 | -41 | -97.6 % | outside tolerance |
| J.T10.adaptive_fedprox.comm_mb | B | 13.7 MB | 58.5 | -44.8 | -76.6 % | outside tolerance |
| J.T10.adaptive_fedprox.val_loss | B | 0.7898 ± 0.328  | 0.0128 | +0.777 | +6070.3 % | outside tolerance |
| J.T10.adaptive_fedprox.fault_f1 | B | 0.348 ± 0.036  | 0.972 | -0.624 | -64.2 % | outside tolerance |
| J.T10.central.val_loss | C | 0.741  | 0.0118 | +0.7292 | +6179.7 % | outside tolerance |
| J.T10.central.fault_f1 | C | 0.487  | 0.975 | -0.488 | -50.1 % | outside tolerance |
| J.T10.fedavg.rounds | C | 1 rounds | 85 | -84 | -98.8 % | outside tolerance |
| J.T10.fedavg.comm_mb | C | 32.3 MB | 118.2 | -85.9 | -72.7 % | outside tolerance |
| J.T10.fedavg.val_loss | C | 0.2998  | 0.0245 | +0.2753 | +1123.7 % | outside tolerance |
| J.T10.fedavg.fault_f1 | C | 0.488  | 0.921 | -0.433 | -47.0 % | outside tolerance |
| J.T10.fedprox.rounds | C | 1 rounds | 62 | -61 | -98.4 % | outside tolerance |
| J.T10.fedprox.comm_mb | C | 32.3 MB | 86.2 | -53.9 | -62.5 % | outside tolerance |
| J.T10.fedprox.val_loss | C | 0.2559  | 0.0182 | +0.2377 | +1306.0 % | outside tolerance |
| J.T10.fedprox.fault_f1 | C | 0.492  | 0.945 | -0.453 | -47.9 % | outside tolerance |
| J.T10.adaptive_fedprox.rounds | C | 1 rounds | 42 | -41 | -97.6 % | outside tolerance |
| J.T10.adaptive_fedprox.comm_mb | C | 32.3 MB | 58.5 | -26.2 | -44.8 % | outside tolerance |
| J.T10.adaptive_fedprox.val_loss | C | 0.2592  | 0.0128 | +0.2464 | +1925.0 % | outside tolerance |
| J.T10.adaptive_fedprox.fault_f1 | C | 0.492  | 0.972 | -0.48 | -49.4 % | outside tolerance |

## Journal - Table XI

| target | topology | measured | paper | abs diff | rel diff | status |
|---|---|---|---|---|---|---|
| J.T11.register.gas |  | 67801 gas | 46250 | +2.155e+04 | +46.6 % | outside tolerance |
| J.T11.register.latency |  | 0.44 s | 0.85 | -0.41 | -48.2 % | outside tolerance |
| J.T11.register.latency |  | 1.55 s | 0.85 | +0.7 | +82.4 % | outside tolerance |
| J.T11.sell_offer.gas |  | 78555 gas | 62100 | +1.646e+04 | +26.5 % | outside tolerance |
| J.T11.sell_offer.latency |  | 0.55 s | 1.12 | -0.57 | -50.9 % | outside tolerance |
| J.T11.sell_offer.latency |  | 1.42 s | 1.12 | +0.3 | +26.8 % | outside tolerance |
| J.T11.buy_bid.gas |  | 78603 gas | 61800 | +1.68e+04 | +27.2 % | outside tolerance |
| J.T11.buy_bid.latency |  | 0.4 s | 1.1 | -0.7 | -63.6 % | outside tolerance |
| J.T11.buy_bid.latency |  | 1.4 s | 1.1 | +0.3 | +27.3 % | outside tolerance |
| J.T11.match.gas |  | 166732 gas | 88400 | +7.833e+04 | +88.6 % | outside tolerance |
| J.T11.match.latency |  | 0.3 s | 1.45 | -1.15 | -79.3 % | outside tolerance |
| J.T11.match.latency |  | 1.38 s | 1.45 | -0.07 | -4.8 % | within tolerance |
| J.T11.settle.gas |  | 47313 gas | 105300 | -5.799e+04 | -55.1 % | outside tolerance |
| J.T11.settle.latency |  | 0.34 s | 1.82 | -1.48 | -81.3 % | outside tolerance |
| J.T11.settle.latency |  | 1.04 s | 1.82 | -0.78 | -42.9 % | outside tolerance |

## Journal - Abstract

| target | topology | measured | paper | abs diff | rel diff | status |
|---|---|---|---|---|---|---|
| J.ABS.comm |  | 0 % | 32.13 | -32.13 | -100.0 % | outside tolerance |
| J.ABS.forecast |  | 83 % | 12.7 | +70.3 | +553.5 % | outside tolerance |
| J.ABS.recovery |  | 78.32 % | 33.79 | +44.53 | +131.8 % | outside tolerance |

## Paper targets with no measured counterpart

- `C.T6.mu1.val_rmse` (Sec IV-D): val_rmse = 6.33
- `C.GAS.settle` (Sec IV-F): gas = 53900
- `C.GAS.offer_request` (Sec IV-F): gas = 118000
- `C.GAS.register` (Sec IV-F): gas = 65600

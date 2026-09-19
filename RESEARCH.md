# Existing research evidence

The initial research is preserved outside this repository, in the local sibling directory `../initial_experiments/`. The files below are local research references, not downloadable website assets. A fresh GitHub clone does not include them.

| Evidence referenced by the architecture | Path within `initial_experiments/` |
|---|---|
| Current model comparison, uncertainty and deployment assessment | `reports/deployment/report.md` |
| Recalculated model scores | `reports/deployment/current_metrics.csv` |
| Local fit/inference timings, storage sizes and parity checks | `reports/deployment/benchmark.json` |
| Selected candidate implementation | `src/agile_lab/practical/candidate.py` |
| Existing local refit and model-bundle check | `src/agile_lab/deployment/benchmark.py` |
| Recent-error correction experiments | `reports/autoregression/report.md` |
| Inspection of the upstream AgilePredict recipe | `reports/upstream_audit.md` |
| Complete experiment catalogue and reproduction commands | `README.md` |

The selected candidate looked modestly better than the reproduced AgilePredict recipes on previously examined dates. That is exploratory evidence, not a demonstrated advantage over the live AgilePredict service. The architecture records the exact comparison scope and limitations.

The current application implements the selected research ensemble (`level-shape-v1`), with a seven-day forecast horizon. The original linear model remains available for demonstrations and comparison. An explicit import copies historical tables from the private research archive; the running application does not import research code. [Model validation](MODEL_VALIDATION.md) records reproduction checks, the Linux portability checks and the recent paired comparison. The recent comparison did not improve on the 60-day AgilePredict reproduction, and historical results do not establish accuracy against its live service.

Keep future model changes explicit, retain upstream licence notices and check their predictions against saved research outputs. Do not add the sibling research directory to the application's import path or copy its datasets into Git. Small synthetic fixtures support public tests; private historical inputs remain local or in private R2 storage.

The research checkout of AgilePredict is pinned to [commit 505adda5820d91ceb369ca4728116c446567c530](https://github.com/fboundy/agile_predict/tree/505adda5820d91ceb369ca4728116c446567c530). Its MIT code licence is separate from the usage terms for published service forecasts and input datasets.

### Regional prices

The fitted model and recent-error correction remain in North West (G) retail
units. `regions.py` converts its uncapped predictions using the regional Agile
multipliers and 16:00–19:00 London peak additions, including VAT and the flat
3.5p/kWh reduction from 1 April 2026. Converted predictions are capped at 100p.
This is a regional translation, not independently validated regional models.
The historical accuracy results remain specific to G.

Collection fetches current published rates directly for all 14 regions. A
comparison against overlapping uncapped G rates checks the conversion every
run (0.025p rounding tolerance); a mismatch stops publication for investigation.
September 2026 API verification confirmed West Midlands uses the same prices
as G, and Yorkshire's multiplier is 2.0. We therefore do not copy AgilePredict's
regional constants. Official pricing references are in `regions.py`.

Regional rate snapshots remain private inside snapshot metadata; only the
website's displayed price window is exported. The public JSON includes aligned
regional price arrays. The browser remembers the region locally and recalculates
charts and cheapest periods without contacting a provider. Older snapshots with
no regional rates safely retain only G.

NESO's rolling 2–14-day cardinal feed can drop tomorrow when its window advances.
Collection fills only missing demand-profile slots from previously observed live
snapshots for the same target time, newest first. Source issue/availability clocks
are preserved, and the existing 120-hour input age limit still applies. It does
not substitute another day's demand or overwrite a new available forecast.

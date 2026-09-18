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

The first application deliberately uses a smaller linear model and an explicit import of two private tables. Its accuracy is separate from the research results above. When adding richer research components, migrate the selected model and data transformations deliberately, retain any required upstream licence notices, and check their predictions against saved research outputs. Do not add the sibling research directory to the application's import path or copy its datasets into Git. Small synthetic fixtures can support public tests; private historical inputs remain local or in private storage.

The research checkout of AgilePredict is pinned to [commit 505adda5820d91ceb369ca4728116c446567c530](https://github.com/fboundy/agile_predict/tree/505adda5820d91ceb369ca4728116c446567c530). Its MIT code licence is separate from the usage terms for published service forecasts and input datasets.

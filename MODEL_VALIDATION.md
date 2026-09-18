# Model implementation checks

Checked locally on 18 September 2026. These are implementation and retrospective checks, not a new independent trial or a comparison with AgilePredict's live service.

## Research reproduction

The implemented recipe is `level-shape-v1`, corresponding to the research selection `level_shape_cat365_base_50`. Its underlying median is `demand-median-v1`. The AgilePredict recipe is pinned to upstream commit `505adda5820d91ceb369ca4728116c446567c530`; its MIT notice is in `notices/`.

`make verify-research-local` refits using the saved benchmark cutoff of 7 September 2026 at 15:30 UTC and checks the issue of 13 September at 15:30 UTC:

- Each of the five underlying forecasts and their median match the saved research predictions exactly.
- The 48 adjusted candidate slots differ by at most **7.11 × 10⁻¹⁵ p/kWh** (floating-point rounding).
- Rebuilt calendar, ramp, ratio and daily-context features match the archived features.
- Saving and reloading the fitted model preserves its predictions exactly.
- The separately checked recent-error calculation matches the saved issue's bias: **5.3627386302 p/kWh**, from 144 completed intervals across three reference issue days.

These checks establish that the port matches a saved research issue on this locked local environment. They do not prove every historical case, Linux portability, or accuracy at new horizons. Current cardinal demand interpolation has separate clock/endpoint tests.

## Recent paired historical comparison

`make evaluate-local` uses weekly Monday fits, historical inputs and only outcomes available by the relevant training cutoff. The recipe was not retuned during this check. All models below are scored on the same **1,152 unknown 48–72-hour target slots**, across **24 issue days**, with targets from **23 August 2026 15:30 UTC to 16 September 2026 15:30 UTC**. Evaluation cutoff: 18 September 2026 10:47:30 UTC.

| Model | Mean absolute error, p/kWh |
|---|---:|
| Original linear recipe, refitted weekly | 9.728 |
| AgilePredict reproduction, 60-day history | **5.108** |
| AgilePredict reproduction, 90-day history | 5.606 |
| Underlying median ensemble | 5.622 |
| Selected research model, including shape and level adjustment | 5.398 |

The implemented candidate reduces error by about **44.5% versus the linear recipe**, but has about **5.7% higher error than the 60-day AgilePredict reproduction** in this recent slice. It is about **3.7% better than the 90-day reproduction**. The research-selected recipe remains implemented as requested; this check is not evidence that it always beats the simplest reproduced AgilePredict recipe.

These data were already used during earlier research. There is no fresh holdout claim or statistical significance claim. They also differ from the prototype's earlier single-fit comparison, so its previously reported 10.06 p/kWh should not be mixed with this table. Archive publication times include documented conservative assumptions.

## Seven-day operation

The new collector supplied **336 future half-hourly targets** at its real collection time. The successful live export contained 312 model estimates, 46 published prices and two explicit gaps, including today so far. All slots on days 2–7 had the required model inputs. Today's latest cardinal demand file started tomorrow, so remaining unconfirmed slots without that input stayed blank.

Only a complete unknown 48–72-hour batch gets the research level/shape adjustment. Other horizons use the underlying median ensemble. A partial batch is never silently recentered as though it were a complete day. Missing optional forecast revisions use training medians, with a visible note. The correction starts at zero while fewer than three eligible reference days have matured.

The compact research archive contains no days 4–7 inputs or predictions suitable for this comparison. Their error is **not measured**. Saved live predictions will be scored by day ahead as actual prices arrive; no initial forward score was available. Predictions already published at issue time are excluded from that scoring.

Live issue times, source timestamp proxies and the seven-day extension are operating changes requiring prospective evaluation. Retain the reference collection near 16:30 London time as well as other refreshes. The site labels the week-ahead output experimental and explicitly limits the historical comparison to 48–72 hours.

## Reproduction and private outputs

```sh
make verify-research-local
make evaluate-local
make forecast-local
make score-local
```

The private outputs are `runtime_state/local/checks/research_parity.json`, `accuracy.json`, `checks/comparison.parquet` and `checks/forward_scores.json`. Running `evaluate-local` against a later snapshot can change its eligible dates and results. This document records the check above; it is not automatically rewritten by training.

The model and raw/history files remain ignored. Only aggregate findings, code and fictional website fixtures belong in Git. R2, Linux Actions execution and public deployment have not been tested in this milestone.

# Half-hour demand trial

This tests whether replacing daily peak demand in the two AgilePredict-style members with forecast demand for each half-hour improves the **final forecast**. Three of our other members already use a half-hour demand profile. We retain those members, the price target, training windows, calendar features and final shape adjustment. Both versions get the same recent-error correction rule, calculated from their own past predictions.

The public website continues using the existing model. Nothing is automatically promoted.

## What runs

After each successful **Refresh forecast** run on main, **Half-hour demand shadow trial** reads the latest saved production state from private R2. It loads the production model and refits only the two changed members using information available at that model's original training cutoff. It compares both versions at 48–72 hours ahead, for region G. The untouched version must reproduce the saved production forecast within 0.00000001p/kWh; otherwise the trial fails visibly.

The challenger retains the production validity checks. Missing required demand inputs still leave gaps; the trial requires all 48 comparison slots. No new data feed, dependency, model download or secret is needed.

Each issue is saved once under `shadow/demand/v1/` in the existing private bucket. Records preserve paired forecasts, model metadata, training/input provenance, source observation times, the challenger's short-horizon predictions for its later error correction, and then-known actual prices. An existing issue is never overwritten. Collection follows successful updates so it does not depend on another hourly cron, but it still depends on GitHub Actions and can miss issues.

## How to judge it

Review after **4–6 weeks**, once prices have been published for the forecast periods. Use the first genuinely recorded issue between 16:30 and 17:30 London time each day; report missing days. Do not retrospectively manufacture missing reference issues. Report paired mean absolute error, weekend error and the cost of choosing a two-hour period compared with the actual cheapest two-hour period in the same window. Summarise uncertainty using weekly blocks rather than treating adjacent half-hours as independent observations.

The primary comparison uses each version's own recent-error correction and excludes challenger warm-up issues (fewer than three matured reference issue dates). Also report all collected reference issues and the recorded challenger with the production correction shared, so warm-up or missed reference runs cannot masquerade as a demand benefit. Keep these comparisons separate. The evaluation target is our current model, not AgilePredict's live service. This trial makes no claim about days 4–7 or whole-week cheapest-period selection.

## Historical reason for trying it

The end-to-end retrospective test used 14 unique weeks, 98 daily issues and 4,704 paired half-hours, all 48–72 hours ahead. It refitted both recipes weekly and gave each its own causal three-day error correction, with four earlier issue days for warm-up. Seasonal and recent subsets each contain eight weeks and overlap by two weeks.

| Test subset | Current MAE | Half-hour demand MAE | Improvement |
| --- | ---: | ---: | ---: |
| Seasonal weeks | 3.083p/kWh | 2.995p/kWh | 2.8% |
| Recent weeks | 4.316p/kWh | 4.255p/kWh | 1.4% |
| Seasonal weekends | 3.477p/kWh | 3.341p/kWh | 3.9% |
| Recent weekends | 5.264p/kWh | 5.109p/kWh | 2.9% |

Average error improved in seven of eight weeks in each overall subset. Week-block bootstrap 95% intervals for the MAE difference (challenger minus current) were −0.151 to −0.028p/kWh seasonally and −0.127 to −0.005p/kWh recently. These are exploratory results on previously used data, not a fresh confirmation. Historical half-hour demand was reconstructed from archived NESO cardinal forecasts; the live direct profile is not an identical historical feed.

Choosing cheap periods did **not** clearly improve. Mean extra cost over the actual cheapest two-hour period was 0.538 versus 0.537p/kWh seasonally, and 0.930 versus 0.956p/kWh recently (slightly worse). Both difference intervals included zero. The evidence therefore supports a small possible price-accuracy gain, not a promise of better cheap-period choices or an explanation for a large live price discrepancy.

Research scripts and full results remain in the separate local `initial_experiments/src/agile_lab/demand_ablation/` and `initial_experiments/reports/demand_ablation/` directories. Raw private history is not committed here.

## Pause, reverse and costs

Set the repository Actions variable `DEMAND_SHADOW_ENABLED` to `false`, or disable **Half-hour demand shadow trial**. This stops automatic trial runs immediately without changing the public forecast, model or existing records. Removing its workflow and the two demand trial modules also leaves production intact.

The workflow has its own concurrency group, a 15-minute timeout, read-only GitHub permissions, and no website deployment step. Inference receives no R2 credentials. Storage writes are restricted by code to the trial prefix; the existing bucket credential is reused, so this is not separate IAM isolation. Cloudflare credentials are unchanged.

Limits are 1,800 records, 250MB total, and 1MB compressed / 5MB plain per record. Reaching a limit stops writes and requires review; nothing is deleted automatically. At hourly collection the record limit is about 75 days. Each run reads the production bundle and at most five previous daily reference records. Anonymous website traffic cannot invoke this workflow or access R2.

## Local and manual checks

Manual workflow dispatch defaults to `persist=false`. That runs the full comparison without saving a trial record; smoke records cannot be uploaded. With `persist=true`, it saves a prospective record only if the snapshot is at most six hours old, all targets are still unknown and in the future, and production replay matches.

For local work, restore a production bundle into a new directory first. Then run:

```sh
uv run --env-file .env python -m agile_forecast.demand_shadow history
uv run python -m agile_forecast.demand_shadow prepare --smoke
```

The default source directory is `runtime_state/demand-source` and output is `runtime_state/demand-shadow`; both can be overridden. Only `history` and an explicit `upload` need R2 credentials. Normal local inference uses ordinary files. The production bundle is never written back by this workflow.

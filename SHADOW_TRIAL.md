# Optional TabPFN shadow trial

Built with PriorLabs-TabPFN. Model weights have the separate [Prior Labs licence](notices/TabPFN-v2.txt).

The public forecast is unchanged. Once daily at 17:17 UTC, a separate Actions workflow reads the latest private production bundle. It selects today's first recorded 16:30–17:30 London issue. If that issue is missing, stale, incomplete, or already has published target prices, the job fails visibly rather than manufacturing a comparison. GitHub scheduling delays/missed runs remain possible.

The frozen challenger uses TabPFN v2, two CPU ensemble members, seed271828, median predictions capped at100p, and960 distinct delivered training targets from the original 48–72h daily feature vintages. It adds half the difference between TabPFN's mean and the saved production mean to all48 production slots. This is the previously explored rule, now tested prospectively; the slightly variable live issue time and changing production fit/bias are recorded. Only region G and48–72h are studied.

Every immutable private `shadow/tabpfn/v1/YYYY-MM-DD.json.gz` preserves the training context, target features, both forecasts, raw TabPFN predictions, issue/recording times, model metadata, library versions, and recent actual prices with observation times. Actual prices are a separate file unavailable to the inference script. Repeated runs never replace a day's first record. There is no automatic model selection or promotion. Review after4–6 weeks using paired daily errors, weekly blocks and cheapest-window regret; don't treat overlapping half-hours as independent evidence. The constant offset preserves within-window cheapest choices but can change cross-day choices.

## Reverse or pause

Set repository Actions variable `TABPFN_SHADOW_ENABLED` to `false`, or disable the **TabPFN shadow trial** workflow. No rollback, public deployment, or R2 deletion is required. Removing the workflow and shadow modules later does not affect production. Keep the production R2 inventory scoped to `forecast-v1/`; this prevents experimental objects affecting its100-object limit.

## Boundaries

No Pages permission, website build, production writer lease, refit or production upload. Inference uses a separate locked CPU environment and a pinned SHA256-verified official checkpoint. R2 credentials are present only in read/write steps; the inference step blocks outbound network calls. The existing bucket credential is reused, so separation is enforced by code, not a new IAM restriction. A separate bucket/credential would give stronger isolation but is not required for this reversible trial. Credentials themselves are unchanged.

The job has a15minute timeout and independent concurrency group. Each record is limited to1MB compressed /5MB plain; the trial stops before exceeding180 records or100MB of shadow storage. No cleanup deletes are performed. Production retains its separate2GB budget. Installing CPU dependencies/downloading the44MB checkpoint happens once per daily run; caching can be considered after measurements.

## Manual smoke test

Run the workflow with `persist=false` (default). This uses the latest fresh issue even outside the daily evaluation window. Smoke outputs cannot be uploaded to the trial archive. With `persist=true`, only the genuine daily reference issue is eligible. Enable the schedule only after the Linux smoke test passes.

Local commands use ordinary files:

```sh
uv run python -m agile_forecast.shadow prepare --state runtime_state/local --output runtime_state/shadow
uv sync --project scripts/tabpfn-shadow --locked
scripts/tabpfn-shadow/.venv/bin/python scripts/tabpfn-shadow/predict.py runtime_state/shadow runtime_state/tabpfn.ckpt
uv run python -m agile_forecast.shadow validate
```

The checkpoint URL and SHA256 are in the workflow. `upload` explicitly requires R2 environment variables; normal local preparation and inference do not.

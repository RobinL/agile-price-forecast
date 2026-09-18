# Agile price forecast

Python collects electricity forecasts, applies a saved model and writes one small JSON file. A static Vite/Vega-Lite website draws the results as aligned daily charts. Everything runs locally; R2, GitHub Actions and publishing remain later steps.

The app now uses our **selected research ensemble**, with **seven days of half-hourly predictions**. The export includes today so far and a partial final date; the website omits that incomplete final day, normally showing seven full calendar-day charts. Prices are Region G, p/kWh including VAT; standing charges are excluded. Published prices take precedence and missing required inputs leave gaps.

The model is experimental. Its research adjustment was tested at 48–72 hours ahead. Days 4–7 and different times of issue do not inherit those accuracy results. [Validation notes](MODEL_VALIDATION.md) explain what has actually been checked.

## See the website

Use Node 22.12 or newer (Node 22 is declared in `.node-version`):

```sh
npm ci
make dev
```

Open <http://127.0.0.1:5173>. This uses the **fictional** example in `fixtures/site/data/forecast.json`. Frontend development needs no Python, research archive, API credentials or cloud access after installing dependencies. Edit `web/src/` and the page updates automatically.

All days share the same time and price scales. Half-hour bars use a continuous colour scale: blue through teal, green, amber, coral and red as prices rise. Fixed anchors from −5 to 45 p/kWh keep colours comparable across days; prices outside that range retain the endpoint colour. The gradient key uses the same anchors. All bars have solid fills. A pale grey background marks published prices, with a dark grey arrow label. Today has a London-time marker captured at page load or refresh. London clock-change days retain their 46 or 50 intervals, with repeated clock times drawn side by side.

Highlights are off by default; enabling them reveals the period count and length controls. The optional yellow highlights select **1–5 non-overlapping future periods across all displayed days**, defaulting to two three-hour periods when enabled. The length control offers periods from two to eight hours. Selection minimizes their combined average price for the chosen count; adjacent periods may touch, and changing the count can change their boundaries. Each highlighted period has darker yellow side edges and a numbered yellow circle matching the ranked list. The list shows start/end times and average p/kWh, with links to the relevant day. Periods may cross midnight or a clock change, but never bridge a missing price. Elapsed intervals and the hidden incomplete final day are excluded. All calculations happen in the browser, with no additional API calls.

## How the pieces fit

```text
Free APIs → collect → dated local snapshot
                           │
                    update-history
                           │
                  monthly private tables
                       │         │
                 train weekly    │ observed prices + saved predictions
                       │         │ give recent error correction
                   saved model   │
                       └────┬────┘
                snapshot → forecast → public forecast.json → static website
                               │
                        save issued predictions
                               │
                        score when prices arrive
```

Collection, training and prediction are separate commands. Training learns from past examples and saves a model. Forecasting reuses that model. The website only reads the public JSON; opening it never downloads provider data or runs Python.

Read these files in roughly this order:

| File | Responsibility |
|---|---|
| `src/agile_forecast/cli.py` | Connect the small list of commands. |
| `src/agile_forecast/feeds.py` | Download five free feeds and translate provider columns. The only network code. |
| `src/agile_forecast/features.py` | Build demand curves, calendar features, ratios and changes. |
| `src/agile_forecast/ensemble.py` | Fit the fixed research recipe and combine its predictions. |
| `src/agile_forecast/forecast.py` | Prefer published prices, validate and export the public contract. |
| `src/agile_forecast/archive.py` | Maintain monthly input, price and prediction files; calculate recent error. |
| `src/agile_forecast/model_store.py` | Save fitted models and check provenance before loading them. |
| `src/agile_forecast/evaluation.py` | Research parity, historical comparison and prospective scoring. |
| `src/agile_forecast/history.py` | One-off private research import; no research-code dependency. |
| `src/agile_forecast/model.py` | Original, readable linear baseline, retained for comparison and demos. |
| `src/agile_forecast/demo.py` | Generate made-up examples. |
| `schemas/forecast.schema.json` | Version 2 agreement between Python and the website. |
| `web/src/data.ts`, `chart.ts`, `main.ts` | Read the JSON, define the Vega-Lite charts and lay out the page. |
| `web/src/cheap-periods.ts` | Find the cheapest combination of complete, non-overlapping periods in UTC. |

The current model exports point forecasts only. An uncertainty view needs calibrated prediction intervals and coverage checks by forecast horizon before it can be offered; disagreement between ensemble members is not a validated uncertainty band.

## The model in plain English

First, five forecasts vote by taking their median. Two reproduce the inspected AgilePredict recipe (each averages CatBoost, LightGBM and ExtraTrees), using 60 or 90 days of history. Three additional tree models use more detailed demand features, with 90 or 180 days of history.

For a **complete unknown 48–72-hour window**, a sixth model trained on 365 days helps adjust the shape of that curve. We preserve the median ensemble's average price level, then add half the last three days' completed short-horizon mean error, capped at ±4 p/kWh. Recent overprediction therefore pulls the new forecast down. Fewer than three eligible reference issue days means zero correction and an explicit warming-up note.

Outside that window, the app uses the median ensemble alone. It can calculate a week ahead when inputs exist, but we have not measured its accuracy on days 4–7. The full 48–72-hour adjustment is skipped if any of its 48 slots lacks a required input. Missing demand, renewables or capacity leave a gap; missing optional revision features use training medians.

The recipe is fixed, not retuned each time it trains. Training uses the original research's next-day target window and one reference issue per day. Inputs must have been available at their issue, and prices and delivery intervals must be known and complete before the training cutoff. The longest model preserves the research seed's embargo exclusions. Live reference issues use the first observed collection from **16:30 up to 17:30 London time**; the actual time is retained. This tolerance is an experimental operating choice, not proof of equivalence to exactly 16:30.

The first 72 hours retain the research feature calculations. Later horizons calculate daily context within subsequent 72-hour blocks, so extending the horizon cannot change the original predictions.

### The five feeds

| Feed | What it supplies |
|---|---|
| Octopus public Agile API | Published prices and outcomes for training/scoring. |
| NESO embedded wind and solar | Forecast generation from distribution-connected renewables. This is not total UK wind. |
| NESO cardinal demand points | A forecast daily demand curve, reconstructed at half-hourly resolution. |
| Elexon NDFD | Forecast daily peak national demand. |
| NESO Daily OPMR | Available generation, imports, reserves and other capacity features. |

Time of day, seasons, weekends and England bank holidays are calculated locally. There is no ENTSO-E token dependency, paid feed or separate weather API. We keep the research demand-curve reconstruction; replacing it with NESO's native half-hourly series remains a separate experiment.

Current NESO files do not always include a model-run timestamp. Collection records when each response was observed and uses the HTTP modification time as a documented proxy where necessary. These live timestamp definitions and new issue times need forward evaluation.

## Run the local pipeline

Install Python 3.12 and [uv](https://docs.astral.sh/uv/), then:

```sh
make setup
```

This installs locked Python and npm dependencies. Nothing configures or contacts R2.

With the private research archive already on this computer, first setup is:

```sh
make import-research       # seed monthly history; safe to repeat with the same seed
make collect-local        # explicit provider downloads
make update-history-local # preserve inputs and observed price versions
make train-local          # fit the research ensemble from local history
make forecast-local       # reuse fitted models; no network or retraining
make dev DATA_MODE=local
```

Import reads three compact tables from `../initial_experiments/artifacts/deployment/`: `daily_features_400d.parquet`, `labels_400d.parquet` and `daily_forecasts_365d.parquet`. It copies data, not research code. Existing linear history is preserved. A new state directory also receives a clearly labelled historical replay, with only the original 72 hours of input coverage. A GitHub clone does not include the private seed; the fictional workflow works without it.

Routine refreshes are:

```sh
make collect-local
make update-history-local
make forecast-local
make score-local
```

Refit explicitly with `make train-local`, approximately weekly. For history to keep advancing under the research training policy, collect at least once daily in the 16:30–17:30 London reference window. All other issue times are still archived for forward scoring. Scheduling this will be part of Actions later.

Collection bounds requests and response sizes and refuses unexpected hosts. Forecast export rejects live snapshots older than two hours and models or training history older than 35 days. Failed collection or export keeps the previous complete snapshot/site file. Run one writer at a time; concurrent local commands are not coordinated.

### Checks and comparisons

```sh
make verify-research-local # refit and compare with saved research outputs, offline
make evaluate-local       # paired chronological comparison, weekly historical fits
make forecast-local       # include the matching evaluation in the export
make score-local          # evaluate saved live predictions after outcomes arrive
```

`evaluate-local` writes `accuracy.json` and private per-slot diagnostics. It uses previously explored historical data, excludes published-at-issue targets, and compares exactly the same slots. It does not compare against AgilePredict's live service or establish seven-day accuracy. Scores attach only to the matching recipe fingerprint. They remain in the JSON for analysis; the webpage does not show an accuracy panel.

`score-local` never regenerates old forecasts: it uses saved live issues, distinguishes fitted model versions and reports error by day ahead. Imported research reference predictions are excluded. Overlapping hourly forecasts are not statistically independent. Initially there may be no matured unknown prices to score.

The retained linear baseline can be selected explicitly:

```sh
uv run agile-forecast train --model linear
uv run agile-forecast evaluate --model linear
# Restore the default research model afterwards:
make train-local
```

### Fictional end-to-end development

```sh
make demo-local
make dev DATA_MODE=demo-local
```

Creation refuses to overwrite existing demo history. On subsequent runs:

```sh
uv run agile-forecast --state-dir runtime_state/demo train
uv run agile-forecast --state-dir runtime_state/demo forecast
```

Demo output stays inside `runtime_state/demo/site/`; it cannot silently replace the real local site's export. The demo still uses the small linear model and makes no accuracy claim. `make dev` always uses the tracked fictional fixture, independently of either state directory.

To preview the complete real static build:

```sh
make preview-local DATA_MODE=local
```

`dist/` contains only frontend assets and the selected public JSON. `make build` defaults to the fictional fixture. All browser requests are static, using relative paths compatible with a GitHub Pages project site.

## Where the files live

```text
fixtures/site/data/forecast.json     Tracked fictional example
runtime_state/local/                Ignored private state
  history.json                      Provenance and real/demo mode
  history.csv                       Preserved original linear seed, not the live archive
  history/
    research_import.json            Seed hashes and provenance
    processed_snapshots.json        Idempotent collection progress
    features/YYYY-MM.parquet        Observed forecast inputs, keyed by issue + target
    prices/YYYY-MM.parquet          Actual prices, versioned by observation time
    predictions/YYYY-MM.parquet     Original model outputs and comparator predictions
  snapshots/<time>-<mode>/          inputs.csv, features.csv, prices.csv, metadata.json
  latest_snapshot.json              Pointer to the last complete snapshot
  models/<hash>.joblib + .json       Fitted research bundle and metadata
  model.json                        Current model pointer
  previous_model.json               Previous model pointer for manual recovery
  linear_model.json                 Preserved prototype when upgrading
  accuracy.json                     Matching historical comparison
  checks/                           Parity, per-slot comparison, forward scores
  forecasts/                        Exact issued public forecasts, preserved privately
runtime_state/site/data/forecast.json    Real local website export only
runtime_state/demo/                 Separate fictional state and website export
```

Monthly files use compressed Parquet. New snapshots add inputs, while later observed prices supply their training answers. Price corrections carry their own observation time; rerunning an update does not duplicate rows. Training selects at most 400 days of input issues and uses only outcomes known by its cutoff. There is no database server.

Model metadata records member training dates/counts, a training-data hash, feature/recipe fingerprint, library versions and artifact checksum. Model binaries are **trusted executable serialization**: use only our own local files or their trusted private backup. Checksum checks detect accidental changes; they do not make a malicious model safe. A changed recipe or library environment requires a refit. Automatic promotion preserves a previous pointer, but automated rollback/retention is not implemented.

Keep `runtime_state/` private and backed up. Git ignores it, model binaries, credentials, environments, build output and caches. The Vite server only serves frontend files, dependencies and the chosen public output directory. It cannot serve private state.

## Next infrastructure step

The local pipeline now maintains history and records predictions. Later, GitHub Actions can download the needed private files from R2, run these same commands, and upload completed state. Weekly training will need more history than hourly inference. Only static website output goes to Pages; popularity must never trigger R2 or model execution.

Still to implement: R2 sync/manifests, single-writer scheduling, bounded storage retention, cold recovery and Linux production parity, automated fit/promotion checks, and Pages deployment. Current readers load local monthly tables; a bounded production working set remains engineering work. No cloud writes or schedules are included in this milestone.

For another model, add a separate recipe and compare it prospectively rather than changing historical results. For another feed, add its normalizer and archive actual forecast vintages before relying on a backtest. The website need not change unless the public contract changes.

[Proposed architecture](proposed_architecture.md), [research archive](RESEARCH.md), [source-use review](DATA_LICENSING.md) and [attribution](DATA_ATTRIBUTION.md) give the wider context. No real input datasets are checked in. AgilePredict's reproduced code carries its [upstream MIT notice](notices/AgilePredict-MIT.txt).

## Tests

```sh
uv run ruff check src tests
PLAYWRIGHT_BROWSERS_PATH=.cache/ms-playwright npx playwright install chromium
make test
make build
```

Tests cover historical availability, recent-error maturity, complete-window adjustment, missing inputs, price revisions, model checksums, demo isolation, seven-day/DST intervals, public export validation, desktop/mobile charts and the private-file boundary. `make format` applies the formatters. The offline research parity command requires the private archive and runs separately from synthetic CI tests.

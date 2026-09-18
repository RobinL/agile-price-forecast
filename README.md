# Agile price forecast

A small, working first version: Python makes a forecast, writes one JSON file, and a static website draws it. It shows **today and the next two calendar days**, with aligned half-hourly charts for Region G, in p/kWh including VAT. Standing charges are excluded.

This version is deliberately easy to follow. It has three feeds, one linear model, ordinary local files and no cloud credentials. R2, scheduled GitHub Actions and Pages deployment are later steps in the [architecture](proposed_architecture.md).

## See the website

Use Node 22.12 or newer (Node 22 is declared in `.node-version`). From this directory:

```sh
npm ci
make dev
```

Open <http://127.0.0.1:5173>. This uses **clearly labelled, made-up example data** from `fixtures/site/data/forecast.json`. You do not need Python, the research archive or an internet connection after installing dependencies. Edit `web/src/` and the page updates automatically.

All days share the same time and price scales. Solid green lines are published prices; dashed amber lines are model estimates. Missing inputs leave gaps. London clock-change days retain their 46 or 50 intervals.

## How the pieces fit

```text
Octopus prices ─────────────┐
NESO demand forecast ──────┼─ collect ─→ private local snapshot
NESO wind + solar forecast ┘                    │
                                               │
Private historical examples ── train ─→ model.json
                                               │
                           snapshot + model ── forecast
                                               │
                                    public forecast.json
                                               │
                                   Vite + Vega-Lite website
```

Training learns coefficients from past examples. Forecasting loads those coefficients and applies them to new inputs. Opening or editing the website does neither: it only reads the exported JSON.

Read these files in order:

| File | Responsibility |
|---|---|
| `src/agile_forecast/cli.py` | The short list of commands and how they connect. |
| `src/agile_forecast/model.py` | Input columns, fitting, prediction and a chronological accuracy check. |
| `src/agile_forecast/feeds.py` | Fetch and translate the three provider feeds into our column names. This is the only network code. |
| `src/agile_forecast/forecast.py` | Prefer published prices, predict eligible unknown intervals, validate and export public JSON. |
| `src/agile_forecast/storage.py` | File paths, snapshot saving and JSON reading/writing. |
| `src/agile_forecast/history.py` | Explicit one-off import of existing private research tables. |
| `src/agile_forecast/demo.py` | Generate fictional data for exercising the whole pipeline. |
| `schemas/forecast.schema.json` | The agreement between Python and the website. |
| `web/src/data.ts` | Read the public file and calculate day labels. |
| `web/src/chart.ts` | The Vega-Lite chart definition. |
| `web/src/main.ts` and `style.css` | Lay out the days, explain the data and style the page. |

There is no application framework or database server hidden behind these files.

## The model, in plain English

The price estimate is a **starting value plus a set of adjustments**:

- Demand, embedded wind and embedded solar each have a learned coefficient.
- Two smooth daily waves describe the usual morning/evening pattern.
- An evening-peak flag and a weekend flag allow additional adjustments.

This gives nine coefficients and an intercept. Ridge regression is ordinary linear regression with a small penalty discouraging very large coefficients. The saved `model.json` contains readable numbers, not a pickled Python object. Coefficients describe associations, not causal effects.

Training uses up to 180 days of eligible historical examples, one row per target interval. The imported examples use forecasts issued 48–72 hours before the price interval, **not eventual demand or weather actuals**. A price can enter training only once its recorded availability time and delivery interval have passed. Inputs recorded as available after their forecast issue are excluded.

This is a teaching baseline, with real limitations. It has no explicit bank-holiday, annual-seasonality, fuel-price, capacity or recent-error correction yet. Wind here means **embedded wind**, not all UK wind. It is different from both AgilePredict's tree ensemble and our more elaborate research candidate; their measured accuracy does not apply to it. Earlier unknown intervals also fall outside the imported training horizon.

The live demand feed supplies a native half-hourly curve. Our historical table reconstructed curves from archived daily demand points. That change in inputs has **not** been validated by a live forward test. The UI says so. More detailed inputs alone do not establish improved accuracy.

## Run the Python pipeline locally

Install Python 3.12 and [uv](https://docs.astral.sh/uv/), then:

```sh
make setup
```

This installs the locked Python and npm dependencies. No command configures R2 or publishes anything.

**Exercise everything with fictional data:**

```sh
make demo-local
make dev DATA_MODE=local
```

`demo-local` creates an isolated `runtime_state/demo/`, fits a model and exports a website file. Run its creation step once per directory; it refuses to overwrite existing history. To repeat fitting or export:

```sh
uv run agile-forecast --state-dir runtime_state/demo train
uv run agile-forecast --state-dir runtime_state/demo forecast
```

**Use the private research history already on this computer:**

```sh
make import-research     # once; explicitly reads ../initial_experiments
make train-local
make evaluate-local
make forecast-local
make dev DATA_MODE=local
```

The import reads just `daily_features_400d.parquet` and `labels_400d.parquet` from the archive's `artifacts/deployment/` directory. It creates a **dated historical replay**, which the UI labels honestly. It does not import the research code. A fresh GitHub clone does not contain this private history; the synthetic workflow still works there.

**Refresh using today's real feeds:**

```sh
make collect-local      # the only step that accesses providers
make train-local        # first fit, or an explicit refit; unnecessary on every refresh
make forecast-local
make dev DATA_MODE=local
```

Collection needs no API token. It records the actual retrieval time, checks provider timestamps when supplied, bounds request count and response size, and saves a new snapshot. Export rejects live snapshots over two hours old and models or training history over 35 days old. Those are initial guardrails, not a complete production data-quality system.

Subsequent refreshes need only `collect-local` and `forecast-local`. Changing charts needs neither. A failed collection leaves the previous snapshot intact; a failed forecast export leaves the previous public file intact. The page marks old live forecasts as stale.

`evaluate-local` fits a separate model before the last 28 days of eligible issues and compares it with the price exactly 168 hours earlier on matching slots. It writes `accuracy.json`; `forecast-local` includes that diagnostic in the site. This is an exploratory check, not a live AgilePredict comparison. Historical publication times include conservative assumptions, and this check does not measure the native live demand feed.

The first live-input run on 18 September 2026 produced 46 published slots, 96 predictions and two explicit gaps. In the historical check accompanying that run, the model's mean absolute error was **10.06 p/kWh**, against **7.35 p/kWh** for the week-earlier baseline, over 1,152 matched slots (23 August–16 September 2026). The pipeline works; the model needs improvement before its forecasts merit reliance. These scores do not describe AgilePredict or the earlier research ensemble.

To inspect the complete static build:

```sh
make preview-local DATA_MODE=local
```

The build is in `dist/`. `make build` defaults to the synthetic example; `make build DATA_MODE=local` explicitly selects the local export. Nothing copies private state into the build. The browser requests only bundled static assets and `data/forecast.json`, with relative paths suitable for a GitHub Pages project site.

## Where the data lives

```text
fixtures/site/data/forecast.json    Tracked, fictional website example
runtime_state/local/               Ignored private state
  history.csv + history.json       Training examples and provenance
  snapshots/<time>-<mode>/        Inputs, published prices, source metadata
  latest_snapshot.json             Pointer to the last complete snapshot
  model.json                       Fitted coefficients and training dates
  accuracy.json                    Optional historical check
  forecasts/                       Issued forecasts, preserved for later scoring
runtime_state/demo/                Separate fictional training state
runtime_state/site/data/forecast.json   Selected website export only
```

Each training row has `issued_at`, `target_start`, `inputs_available_at`, `demand_mw`, `wind_mw`, `solar_mw`, `price_p_kwh` and `price_available_at`. Timestamps are UTC; charts use Europe/London. Power inputs are MW and prices are p/kWh including VAT. Source snapshot metadata includes retrieval times and response hashes.

Keep `runtime_state/` private and backed up if you want to preserve experiments. It is ignored by Git, along with environments, caches and build output. The frontend server is restricted to frontend files, dependencies and the selected public directory; it cannot serve private state or repository internals.

## How we add complexity later

- **More feeds:** add a normaliser in `feeds.py`, archive its forecast versions, then add a documented column to the training/input table. Do not substitute actuals for historical forecasts.
- **A better model:** change `features`, `fit` and `predict` in `model.py`, update the model version and compare against this baseline. The public JSON and website can stay the same. A tree model will need its own saved model format.
- **More views:** add frontend components that read the same public contract, or deliberately version that contract when it changes.
- **R2 and Actions:** keep Python's functions unchanged where possible; add private state download/upload around the existing commands. Only the generated static output goes to Pages.

Before unattended operation, we still need to join newly observed outcomes to saved forecast inputs, maintain rolling training history, score forecasts by lead time, add bounded state retention and recovery, and wire up R2/Actions/Pages. Today, collection saves snapshots but **does not extend `history.csv`**. Refitting the same archive is not a substitute for collecting new training examples. There are no production secrets, cloud writes or automated schedules in this version.

The [architecture](proposed_architecture.md) describes those later steps. [RESEARCH.md](RESEARCH.md) locates the earlier experiments; [DATA_LICENSING.md](DATA_LICENSING.md) and [DATA_ATTRIBUTION.md](DATA_ATTRIBUTION.md) record source-use findings. No real input datasets are checked in. Supported by National Energy SO Open Data.

## Checks

```sh
uv run pytest -q
PLAYWRIGHT_BROWSERS_PATH=.cache/ms-playwright npx playwright install chromium
make test
make build
```

The tests cover time-based training exclusions, published-price precedence, missing inputs, daylight-saving intervals, public export validation, desktop/mobile rendering and the development server's private-file boundary. `make format` applies the Python and frontend formatters. The browser test downloads are a one-time setup; `make test` uses the project-local browser cache.

# Moving the local forecast to GitHub Actions and R2

The website is live at
**[www.robinlinacre.com/agile-price-forecast](https://www.robinlinacre.com/agile-price-forecast/)**.
The repository is public. Pages publishes through Actions, and the `github-pages`
environment accepts deployments only from the `main` branch. Both
`PAGES_ENABLED` and `FORECAST_SCHEDULE_ENABLED` are enabled. The hourly schedule
runs at minute 37; GitHub can delay scheduled runs.

The private R2 bucket has been seeded and its download/checksum round trip passed.
The first Linux forecast fitted and checked its model in 64 seconds; the second
restored and reused it in 48 seconds. The first public deployment on
18 September 2026 refreshed the forecast in 71 seconds and deployed in another
10 seconds. It published the real forecast issued at 18:13 London time, using
the saved Linux model, with 94 published, 277 predicted and two unavailable
half-hours. The incomplete final date is omitted by the website.

Evidence: [first complete forecast](https://github.com/RobinL/agile-price-forecast/actions/runs/35368521829),
[saved-model reuse](https://github.com/RobinL/agile-price-forecast/actions/runs/35368747368),
[first public deployment](https://github.com/RobinL/agile-price-forecast/actions/runs/35372958788).
The complete pipeline and deployment were verified through a manual run; the
hourly schedule was enabled afterwards, so the first scheduled run remains a
follow-up check in Actions.

## Operating the live site

- View runs under **Actions → Refresh forecast**. A successful run updates both
  private R2 state and the public site. Use **Run workflow** for a manual refresh;
  leave forced refitting off unless intentionally retraining.
- Set repository variable `FORECAST_SCHEDULE_ENABLED=false` to pause unattended
  processing. Manual runs remain available. Set `PAGES_ENABLED=false` to stop
  new deployments. Neither setting removes the currently published website.
- The browser checks for fresh static JSON every ten minutes while visible.
  The deployed JSON has `Cache-Control: max-age=600`, so an update need not
  appear immediately. The page displays the forecast's issue time and marks it
  stale after two hours.
- A failed refresh leaves the last published site available. Inspect the failed
  Actions step before rerunning; avoid changing private state pointers by hand.

The existing account Pages domain supplies the project path; no project-specific
CNAME or DNS change was needed. HTTPS works, and the non-www address redirects
to www. The deployed JSON passed schema and freshness checks, all seven charts
rendered without browser errors, and the mobile layout and cheapest-period
controls were checked. The page loads its static assets and JSON, plus the
domain's existing Cloudflare analytics beacon and favicon. No browser request
goes to private R2 or a forecasting API. No Cloudflare credentials or zone
settings were changed during deployment.

## What happens on each run

```text
Private R2 state → temporary GitHub runner → private R2 updated state
                          │
                      forecast.json
                          │
                     Vite builds dist/
                          │
                  static GitHub Pages site
```

The runner downloads one compressed copy of our private state folder. Inside are
the same monthly history files, models and snapshots used locally. It collects
new inputs, updates history, retrains if the saved model is at least seven days
old, and forecasts. The first run on a new operating system also refits the
original seed model and checks its predictions against a frozen local reference.
Training-data and library provenance must match. Most predictions must agree
within **0.001 p/kWh**. The first Linux trial identified a small ExtraTrees refit
difference, so a narrowly bounded exception checks that the saved seed still
predicts correctly on Linux, every other estimator still matches, and the final
forecast differs by at most **0.1 p/kWh at any interval and 0.01 p/kWh on average**.
Missingness must be unchanged. [Measured differences and full limits](MODEL_VALIDATION.md#linux-portability).
This is a portability check, not an accuracy test.

The updated state is uploaded as a new private bundle. A small `current.json`
pointer changes only after that upload succeeds. The previous bundle is retained
for recovery. Only then is the public JSON copied out for the Vite build. GitHub
Pages receives `dist/`, after its file list, required third-party software
notices, forecast schema and 10 MB size limit have been checked. Vite generates
the notices from the dependencies actually bundled into the website. A failed
forecast does not replace the published site.

The forecast is served entirely from static files. Visitors cannot start Actions
or read R2, and the application does not turn visitor traffic into R2 requests or
Worker invocations. The existing custom domain already passes through Cloudflare;
no new Worker or public R2 endpoint is part of this setup.

## Why one bundle initially

The current local state is about 45 MB. Transporting it as one file is easier to
understand and test than maintaining a remote object for every snapshot. The
monthly Parquet tables remain separate files **inside** the bundle, so neither
training nor local development changes.

All monthly input, price and prediction history and all issued forecast exports
are retained. Old model metadata is retained, but only current/previous model
binaries are carried. Redundant input snapshots older than 30 days are omitted,
except the latest snapshot and the frozen portability reference. Legacy CSV
duplicates, arbitrary files and credentials are excluded by an explicit allowlist.

This is intentionally a small first production version. It transfers the whole
bundle on every run, rather than downloading only changed months. It stops at
256 MB compressed, 512 MB unpacked or 10,000 files; it never silently deletes
permanent history to fit. As history grows we can change the transport to monthly
objects without changing the model. Keep an independent local backup of the seed.

## 1. Create the private bucket yourself

In the [Cloudflare dashboard](https://dash.cloudflare.com/), open **Storage &
databases → R2 Object Storage**. If required, enable the R2 subscription; your
existing card can be used. Create a bucket, for example `agile-forecast-state`,
using **Standard** storage. Automatic location is suitable.

Leave **Public Development URL / r2.dev disabled** and do not attach a public
custom domain. This bucket stores private working state, not the website. No
Worker, CORS rule or public endpoint is needed. Use a dedicated bucket so the
project's storage budget is meaningful. Do not add an expiry rule to the whole
bucket: it would delete the saved history.

Pause here to confirm the bucket name and that public access is disabled before
moving to credentials. No secret needs to be pasted into a conversation.

## 2. Create scoped credentials

From R2's API-token management screen, create an **Object Read & Write** token
restricted to this bucket. Save its **Access Key ID**, **Secret Access Key**, and
the **S3 API endpoint** shown by Cloudflare. The S3 endpoint normally resembles
`https://ACCOUNT_ID.r2.cloudflarestorage.com`; use the displayed jurisdictional
endpoint if Cloudflare supplies one. The S3 credentials are not a general
Cloudflare account API token. [Cloudflare's instructions](https://developers.cloudflare.com/r2/api/tokens/).

Use a separate, temporary bucket-scoped local credential for the initial upload;
revoke it after seeding. Copy `.env.example` to `.env` and fill it using an editor.
`.env` is ignored by Git. Do not put secrets in shell command arguments, `VITE_*`
variables, screenshots, workflow YAML or repository files.

## 3. Prepare and upload the starting state

Stop other commands that write local state while preparing the seed. Preparation
is offline and reads the local state without changing it:

```sh
make prepare-cloud-seed
```

This writes ignored `runtime_state/seed.tar.gz`, including the saved model,
history and expected predictions for the first Linux refit. Check the reported
size. Once the bucket and local `.env` are ready, explicitly upload it:

```sh
UV_CACHE_DIR=.cache/uv uv run --locked --env-file .env agile-cloud seed
```

The seed operation refuses to overwrite an existing successful R2 state. It
does not schedule anything or publish a website. It uses the same request,
storage and daily-processing limits as an ordinary run. If the local reference
was collected long ago, collect, update history and train locally before making
a fresh seed. Changing the model recipe/dependencies also requires a reviewed
new portability reference, not bypassing the first-fit check.

To inspect a round trip, download to a **new** ignored folder:

```sh
UV_CACHE_DIR=.cache/uv uv run --locked --env-file .env agile-cloud pull --state-dir runtime_state/r2-check
```

This does not overwrite `runtime_state/local`. Use `--previous` to download the
previous successful bundle for inspection or manual recovery. There is no
automatic rollback that could discard subsequently collected history.

## 4. Configure GitHub, then run one manual trial

Push the reviewed code yourself when ready. In the repository's **Settings →
Secrets and variables → Actions**, create:

| Type | Name | Value |
|---|---|---|
| Secret | `R2_ACCESS_KEY_ID` | Production bucket-scoped access key ID |
| Secret | `R2_SECRET_ACCESS_KEY` | Its secret access key |
| Variable | `R2_ENDPOINT_URL` | The displayed R2 S3 endpoint |
| Variable | `R2_BUCKET` | The bucket name |
| Variable | `FORECAST_SCHEDULE_ENABLED` | `false` initially |
| Variable | `PAGES_ENABLED` | `false` initially |

Go to **Actions → Refresh forecast → Run workflow**, selecting `main`. Leave
the optional forced refit off. The first run already performs the portability
refit. Check the logs for the comparison, successful collection, state upload
and static-build check. Its only Actions artifact is the public site, retained
for one day; model binaries and training data are never uploaded as artifacts.

Download and inspect that artifact before enabling Pages. Run a second manual
trial to confirm that it restores the Linux model and does not retrain again.
Measure the runtime before enabling the hourly schedule. GitHub schedules are
best-effort and can be delayed; missed reference issues are never backdated.

The ordinary **Checks** workflow runs offline Python tests and fixture-based
browser tests on pushes to `main` and pull requests. It has no R2 secrets.
Production runs only on the trusted default branch, never on pull-request code.
Action versions are pinned to commits and should be reviewed when updated.

## 5. Enable publishing, then the schedule

Make the repository public when ready to use free public Actions and Pages
(completed for this deployment). GitHub Pages is available for public repositories on GitHub
Free; private-repository Pages requires an eligible paid plan. A private repo
does not imply that a Pages website is private.
[GitHub Pages availability](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages).

In **Settings → Pages**, choose **GitHub Actions** as the publishing source.
Restrict the `github-pages` environment to `main`. Then set `PAGES_ENABLED=true`
and run one manual forecast. The deploy job receives the checked artifact and
a short-lived GitHub token, with no R2 credentials. Verify the deployed page,
forecast timestamp and browser network requests.

Finally set `FORECAST_SCHEDULE_ENABLED=true`. Runs are scheduled at minute 37
each hour. That includes the model's 16:30–17:30 London reference window in both
GMT and BST. Weekly refitting happens within the first run whose model is seven
days old, rather than through a separate competing writer. Set the schedule
variable back to `false` to stop unattended processing. Set `PAGES_ENABLED=false`
to stop future deployments; the existing site remains available and shows its
original issue time and stale warning.

## Cost and recovery controls

- Maximum 32 admitted processing attempts per UTC day, persisted before work
  begins; failed attempts count. Rejected/manual read-only requests still make
  small R2 reads, so this is an application guard, not a billing hard cap.
- Maximum 100 SDK operations and 100 physical sends per command; SDK retries
  disabled. Single bounded inventory request, no unbounded pagination or
  multipart uploads. A successful normal run typically uses around 8 requests.
- 10-minute forecast job timeout and a 20-minute conditional writer lease.
  A killed job cannot hold the lease forever. An expired writer cannot promote
  state, and conditional writes prevent it overwriting a newer pointer.
- Check the whole dedicated bucket's listed size plus the proposed upload
  against 2 GB. Retain current and previous bundles; clean only older generated
  bundles after a successful promotion. Failed uploads can leave an orphan;
  a later successful run cleans it up. An unexpected large inventory stops work.
- Keep the public build below 10 MB. No raw history, model files or environment
  files may enter `dist/`. Dependencies install before the credentialed step;
  Vite builds without R2 secrets in its environment.

These checks are covered by local failure tests. Live R2 restore, conditional
state promotion, saved-model reuse and the first Pages deployment have also
succeeded. Scheduled operation should be checked in the Actions run history.
If something fails, inspect the Actions log first. Avoid manually replacing
`current.json` or deleting bundles it references. Old published pages keep
working while a fix is prepared.

R2 Standard's free allowance currently includes 10 GB-months and far more
requests than this workload needs; other usage on the account shares those
allowances. R2 can still bill beyond its allowance. Cloudflare spending alerts
notify rather than cap charges. Configure a low alert and GitHub's spending
budget controls as a secondary guard. Website traffic never enters this private
processing path. [R2 pricing](https://developers.cloudflare.com/r2/pricing/),
[Cloudflare alerts](https://developers.cloudflare.com/billing/manage/budget-alerts/).

## Code to read

`production.py` runs the familiar pipeline and its publication checks.
`state_bundle.py` selects and transports the private files. `r2.py` handles the
small pointer, upload/download and budgets. `cloud_cli.py` provides explicit
commands. `.github/workflows/forecast.yml` puts those commands on a temporary
Linux computer and then publishes only the checked website.

Your existing `make dev`, collection, training and forecasting commands still
work without an R2 account or credentials.

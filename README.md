# Agile price forecast

A new application for forecasting half-hourly Octopus Agile electricity prices, starting from the agreed [architecture](proposed_architecture.md).

**Current stage: repository foundation.** This repository contains planning and source-attribution documents only. There is no application, frontend, model-training command or deployment workflow yet. Commands described in the architecture are interfaces to implement, not commands available today.

The design has two separate paths:

- Scheduled Python jobs collect free data, train weekly and forecast hourly. Private state lives in R2 in production and ordinary local files during development.
- GitHub Pages serves a static Vite/TypeScript website and selected forecast JSON, optionally through Cloudflare Free CDN. Vega-Lite is the default charting tool. Visitors cannot trigger a model run, a Worker or an R2 operation.

Build this in small, reviewable steps:

1. A local frontend with synthetic JSON examples, charts and a static build; no Python, cloud account or real data required for site development.
2. A public JSON schema and local file-based train/forecast/export workflow, migrating only the selected research components with their tests and attribution.
3. A complete offline local preview using a checked private input snapshot and fitted model.
4. Bounded R2 persistence and scheduled Actions jobs, with a checked first production fit and recorded forecast history.
5. Static Pages publishing, optional Free CDN caching, and verification of the cost and security boundaries.

The research is preserved separately in the local sibling directory `../initial_experiments/`. It is not a runtime dependency or part of this repository. [RESEARCH.md](RESEARCH.md) locates the evidence behind the model proposal. Real datasets and credentials must remain outside Git and outside the public website artifact.

Source-use findings and notices are retained in [DATA_LICENSING.md](DATA_LICENSING.md) and [DATA_ATTRIBUTION.md](DATA_ATTRIBUTION.md). These do not authorise publishing the combined research dataset.

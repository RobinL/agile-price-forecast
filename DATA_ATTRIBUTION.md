# Data attribution

These notices identify the current application inputs and optional research sources. They do not license the complete combined dataset for redistribution. See [the per-source assessment](DATA_LICENSING.md). The repository's MIT licence covers its original code and documentation, not upstream datasets.

**NESO**

Supported by National Energy SO Open Data.

Used under the [NESO Open Data Licence](https://www.neso.energy/data-portal/neso-open-licence). The project selects historical forecast vintages, derives additional features, and reconstructs intraday demand from archived forecast points. These transformations and price forecasts are this project's work; they are not NESO-issued price forecasts.

**Elexon**

Contains BMRS data © Elexon Limited copyright and database right 2024–2026.

[BMRS open-data licence](https://www.elexon.co.uk/bsc/data/balancing-mechanism-reporting-agent/copyright-licence-bmrs-data/). The project selects published forecast vintages and derives model features; retain the relevant source-year range when exporting other periods. No Elexon endorsement is implied.

**Octopus Energy**

Official Agile tariff prices obtained from the [Octopus Energy REST API](https://docs.octopus.energy/rest/guides/endpoints/). The project stitches specified tariff products and evaluates forecasts against published retail rates. The live site displays current published prices alongside our own estimates; its historical training archive remains private. Octopus encourages API-based applications, but an explicit redistribution licence for the displayed tariff values or a bulk archive has not been established. This attribution is not a substitute for permission; the outstanding clarification is recorded in [the source-use review](DATA_LICENSING.md).

**Optional experimental sources**

ONS gas SAP: Office for National Statistics; underlying source National Gas Transmission. See [the dataset](https://www.ons.gov.uk/economy/economicoutputandproductivity/output/datasets/systemaveragepricesapofgas) and [ONS terms](https://www.ons.gov.uk/help/terms-conditions). Retain any workbook-specific notices.

No ENTSO-E generation data are currently included. If added later, record ENTSO-E Transparency Platform as publication source, the original provider, the specific data category, applicable rights and transformations. Do not insert a blanket CC-BY notice for all platform data.

AgilePredict service snapshots are retained solely for private comparison. Source-code reuse is covered separately by the pinned upstream [MIT licence](https://github.com/fboundy/agile_predict/blob/505adda5820d91ceb369ca4728116c446567c530/LICENSE).

# Data licensing and storage assessment

This is the retained assessment of the initial research sources. The current operational storage and publishing design is in [proposed_architecture.md](proposed_architecture.md); historical GitHub Release suggestions below are not the selected storage design.

Publication review, 18 September 2026: the live application uses NESO, Elexon and
Octopus inputs. Its footer carries the NESO and Elexon acknowledgements and links
to their licences. Each website build includes the bundled software dependencies'
full licence notices. Original project code and documentation use MIT, with the
upstream AgilePredict notice preserved separately. These software licences do
not license provider data. The current price display is public; raw inputs,
training history and AgilePredict service comparison snapshots remain private.

Checked 17 September 2026. This records the published terms found and the resulting storage recommendation; it is not a blanket licence for the contents of `artifacts/`. The original experiment's `licence_url` fields sometimes link to API documentation, which does not itself establish redistribution rights.

**We do not have to store data on GitHub, and the reviewed licences do not require us to publish our training data.** Persistence is an engineering requirement for preserving forecast vintages, retraining and evaluating errors. A private file store, database or private GitHub release can serve that purpose. Public source code and public input data are separate decisions.

**Feed-by-feed findings**

| Data | Finding for public redistribution | Project decision |
|---|---|---|
| NESO embedded wind/solar, OPMR and 2–14-day demand forecasts | The relevant dataset pages identify the NESO Open Data Licence. It permits copying, distribution, adaptation and commercial use with its specified acknowledgement. | Public copies of these identified datasets are feasible with attribution, source links and change notes. This does not cover every dataset NESO publishes. |
| Elexon Insights/BMRS demand and generation-availability data | The BMRS open-data licence expressly covers Insights data and permits redistribution and adaptation. Carry its attribution and licence link, avoid misleading presentation or implied endorsement, and preserve attribution obligations downstream. | Public copies are feasible subject to those conditions. |
| Octopus official tariff prices | The REST documentation supports retrieval and Octopus encourages API-powered applications. An explicit redistribution licence for displayed tariff values or a complete archive has not been established. General website/app terms restrict redistribution of website content; their precise application to API tariff records is not established by the documentation reviewed. | The site displays a small current-price window; the archive remains private. Request clarification for that display as well as before any bulk mirror; do not classify API records as open-licensed solely because the endpoint is public. |
| ENTSO-E French nuclear generation | The published CC-BY list does **not** include actual generation by production type, Article 16.1.B/C. An API token is an access mechanism, not a general redistribution licence. | Do not publish this series under an assumed blanket CC-BY grant. Establish applicable original-provider rights or use a directly licensed source. No ENTSO-E generation data have yet been downloaded successfully. |
| Other ENTSO-E data | Listed categories have CC-BY 4.0 permission subject to attribution/change notices and exceptions. IFA and Nemo Link data are excluded; other country/category exceptions also appear. | Check category and provider per dataset. Do not mark every ENTSO-E response as freely redistributable. |
| ONS gas SAP publication, used in optional experiments | ONS content is generally OGL v3.0 unless otherwise stated. This series identifies National Gas Transmission as its source; third-party exceptions still matter. | Retain ONS and National Gas provenance and check workbook-specific notices before public export. This is not a dependency of the preferred model. |
| Archived AgilePredict service forecasts | The inspected site's templates restrict data/forecasts to private, non-commercial use. | Keep the comparison snapshots private; reproducing the algorithm on our independently acquired inputs is a different activity. |
| AgilePredict source code | The pinned repository includes an MIT licence. | Preserve the copyright/licence notice when reusing code. The code licence does not clear rights in separately supplied data. |

NESO evidence: [licence](https://www.neso.energy/data-portal/neso-open-licence), [embedded forecasts](https://www.neso.energy/data-portal/embedded-wind-and-solar-forecasts), [OPMR](https://www.neso.energy/data-portal/daily-opmr), [demand forecasts](https://www.neso.energy/data-portal/2-14-days-ahead-national-demand-forecast).

Elexon evidence: [BMRS open-data licence](https://www.elexon.co.uk/bsc/data/balancing-mechanism-reporting-agent/copyright-licence-bmrs-data/), [Insights service description](https://www.elexon.co.uk/bsc/data/kinnect-insights-solution/). The full licence was available through indexed official-page text; a direct page fetch returned 403. API access terms and data redistribution rights are distinct.

Octopus evidence: [REST documentation](https://docs.octopus.energy/rest/guides/endpoints/), [encouraged API applications](https://octopus.energy/works-with-octopus/), [website/app terms, Intellectual property](https://octopus.energy/policies/terms-of-use/). The unresolved point is the explicit permission covering public price display and redistribution, not an assertion that ordinary API-based applications are prohibited.

Clarification to request from Octopus: may this independent, free website display
today's and tomorrow's published Region G Agile unit rates obtained through the
REST API, including those rates in its downloadable current forecast JSON, beside
our own model estimates? Are any additional attribution or reuse conditions
required? Historical tariff records are stored privately for training and
evaluation, not offered as a public archive. No confirmation has been obtained;
this document records the question and does not claim permission.

ENTSO-E evidence: [current legal-documents index](https://transparencyplatform.zendesk.com/hc/en-us/articles/40921911218961-Legal-Terms-and-Conditions), [18 October 2023 reuse list](https://transparencyplatform.zendesk.com/hc/article_attachments/40921869379729), [terms effective 1 November 2023, sections 2.5 and 3.1](https://transparencyplatform.zendesk.com/hc/en-us/article_attachments/40921869376401). Section 3.1 requires attribution, prohibits implying endorsement and preserves original owners' rights. Absence from the open list is not proof that every use is forbidden; it means the list does not supply the permission. Private storage also does not override source-use conditions.

ONS evidence: [terms](https://www.ons.gov.uk/help/terms-conditions), [gas SAP dataset](https://www.ons.gov.uk/economy/economicoutputandproductivity/output/datasets/systemaveragepricesapofgas). Do not generalise the ONS website licence into permission for unrelated direct commercial gas-price feeds.

**How AgilePredict does it**

The pinned repository's infrastructure document, marked accurate on 4 August 2026, describes production Django web/worker services on Fly.io backed by a separate PostgreSQL 17 database. Development uses its own SQLite database and scheduled incremental/full backups. `History`, `PriceHistory`, `Forecasts`, `ForecastData` and `AgileData` are database models for inputs, historical prices and forecast runs/values. This is ordinary database persistence, not a requirement to commit the live dataset to GitHub.

Its `.gitignore` excludes SQLite files, `.local/` backups, environment files and logs. Production updates are triggered by an external EasyCron service; the documented GitHub Actions job monitors whether updates finished. This architecture uses hosted services with running costs, so it is not evidence that we need the same setup for a £0 project. This is source/documentation evidence, not access to their live infrastructure or private provider agreements.

Pinned evidence at commit `505adda5820d91ceb369ca4728116c446567c530`: [infrastructure](https://github.com/fboundy/agile_predict/blob/505adda5820d91ceb369ca4728116c446567c530/docs/INFRASTRUCTURE.md), [database models](https://github.com/fboundy/agile_predict/blob/505adda5820d91ceb369ca4728116c446567c530/prices/models.py), [ignore rules](https://github.com/fboundy/agile_predict/blob/505adda5820d91ceb369ca4728116c446567c530/.gitignore), [incremental backup](https://github.com/fboundy/agile_predict/blob/505adda5820d91ceb369ca4728116c446567c530/bin/incremental_backup.sh), [site footer](https://github.com/fboundy/agile_predict/blob/505adda5820d91ceb369ca4728116c446567c530/templates/base.html), [about-page notice](https://github.com/fboundy/agile_predict/blob/505adda5820d91ceb369ca4728116c446567c530/templates/about_v2.html), [MIT licence](https://github.com/fboundy/agile_predict/blob/505adda5820d91ceb369ca4728116c446567c530/LICENSE). Public counterparts can be found in the [pinned repository](https://github.com/fboundy/agile_predict/tree/505adda5820d91ceb369ca4728116c446567c530).

**Recommended arrangement for our project**

Keep the mixed training tables, labels, source snapshots and model checkpoints **private initially**. This revises the earlier suggestion of public release assets for the complete bundle: Octopus and prospective ENTSO-E inputs have unresolved public-redistribution scope. Publish code and aggregate evaluation separately; do not include third-party forecast snapshots or credential-bearing files.

For an Actions-based implementation, compressed Parquet files and a model bundle are sufficient; no continuously running database is required. If using GitHub storage, place the runtime checkpoints in release assets of a **private repository**, not in repeated large commits. Repository read permissions also control access to releases. A private workflow can keep its state there; a public workflow could access a separate private store with appropriately scoped authentication, but must not publish its inputs in logs/artifacts. [GitHub release access](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases).

The measured state remains about 43 MB before rollback/source buffers. Retain roughly 400 days of model-visible inputs, plus immutable issue-time forecasts and calibration history. Keep a local backup. Actions cache should be regenerable, and workflow artifacts disappear if their run is deleted; neither is the sole durable archive. [GitHub artifact guidance](https://docs.github.com/en/actions/concepts/workflows-and-actions/workflow-artifacts).

A public-only dataset bundle is possible by exporting only individually cleared NESO/Elexon components with their notices. Removing a source's name, converting it to Parquet, or mixing it with other data does not clear its rights. Independently generated forecast outputs are not the same object as a bulk source-data mirror, but any applicable source conditions still need to be honoured, particularly if publishing prices or input feature values alongside the forecast.

[DATA_ATTRIBUTION.md](DATA_ATTRIBUTION.md) records notices for the current primary inputs. The original research review did not publish data; the subsequent application publishes only its current website export, as described above.

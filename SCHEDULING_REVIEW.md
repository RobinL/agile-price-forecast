# Hourly scheduling review

Observation window: 19 September 2026 12:41:53 UTC (commit b69387f)
to 21 September 2026 15:03:37 UTC. Both workflows scheduled at minute 37.
There were 50 hourly cron opportunities in that window.

| Workflow | Scheduled runs created | Successful | Manual runs (separate) | Creation-to-first-job wait, median / maximum |
| --- | ---: | ---: | ---: | --- |
| Schedule diagnostic | 13 | 13 | 1 successful | 3s / 39s |
| Refresh forecast | 14 | 14 | 3 successful | 3s / 8s |

The longest gap between scheduled run creations was 7h 30m for the diagnostic
(21 September 06:59:49–14:30:01 UTC), and 7h 20m for the forecast
(07:11:08–14:31:22 UTC). Several other gaps lasted four to five hours.
Manual dispatch creation-to-first-job waits were 3s for the diagnostic and
2–4s for forecasting. All six Checks runs in the observation window succeeded.

These are counts of observed run creations, not proof that any specific cron
slot was dropped. GitHub does not expose the intended execution timestamp for
these runs; delayed runs cannot safely be assigned to individual hourly slots.
The most recent opportunity could also still be pending at the cutoff.
Nevertheless, neither workflow delivered anything close to hourly execution.
The tiny diagnostic has no checkout, secrets, data dependencies, conditions or
concurrency group, yet shows the same broad multi-hour gaps. This points to
scheduling before run creation, rather than forecast code or long runner waits.
It does not establish whether the problem is GitHub-wide or repository-specific.

## Recommendation

Keep published prices independently refreshed from Octopus in the browser (now
implemented). For dependable hourly model refreshes, use an external scheduled
trigger that dispatches the existing GitHub workflow. Retain its concurrency
protection and log trigger times so failures and delays can be measured. A
scheduled Cloudflare Worker would need a narrowly scoped GitHub credential;
implement that separately with the owner's involvement. No external trigger or
new secret was created during this review.

The temporary diagnostic workflow was removed after this observation period.
Evidence was collected from the GitHub Actions run-list and per-run jobs APIs.
Example last scheduled runs: diagnostic 35612562863; forecast 35612719503.

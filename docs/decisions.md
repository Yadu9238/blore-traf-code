# Architecture decisions

## 1. Fixed corridors, not arbitrary routes

"When should I leave?" needs weeks of history for a specific route. A user's
route is unknown until they type it, so arbitrary origin/destination pairs can
never have a baseline.

Instead a fixed set of tech corridors is polled continuously. User-entered routes
are decomposed onto the monitored corridors at query time, and historical context
is served for the segments they cross.

## 2. Raw responses expire, derived aggregates persist

Routing providers restrict long-term storage of their responses. Raw JSONL is
deleted after `RAW_RETENTION_DAYS` (default 7). The bronze Parquet layer and
everything downstream hold only derived measures, which is both licence-safe and
smaller.

## 3. No Spark in the 15-minute job

At ~16 corridors x 96 polls/day the working set is roughly 1,500 rows/day.
Spark would add minutes of JVM startup to process kilobytes. The routine job uses
pandas and pyarrow.

PySpark is introduced in Phase 3 for full-history backfill and aggregation, where
the volume justifies it. Choosing per workload rather than defaulting to the
biggest tool is deliberate.

## 4. Micro-batch, not a long-running stream

There is no free way to run an always-on process. The scheduler triggers a job
that processes everything pending and exits - the same model as Auto Loader with
`Trigger.AvailableNow`, which is how most production Databricks pipelines run.
Checkpointing is introduced with the streaming silver layer in Phase 2.

## 5. Git as the storage layer

Repo-committed Parquet and Delta cost nothing and need no cloud account. At
~50 KB/day of bronze it stays well under 100 MB/year.

Trade-off: no object-store lifecycle rules, no Terraform, and commit noise from
the scheduled jobs (mitigated with `[skip ci]`). The repo holding the data was
made private when collection stopped (see 14).

## 6. Partial failure is tolerated

One corridor failing must not discard the other fifteen. Failures are recorded
per corridor in `data/status.json`; the job only fails when nothing was captured.

## 7. Median baselines, not a forecasting model

The baseline is the median travel time per corridor, per day type (weekday, or
weekend and holidays), per IST hour. The original design was day-of-week x 15
minutes; the scheduler defect (incident 1) left under one sample per cell at that
grain, so it was coarsened rather than filled with guesses. Cells with fewer than
8 samples are flagged, and every forecast carries its sample count.

## 8. Bronze is sealed by UTC day

Spark's file stream source records files by path. A partition rewritten every hour
would be read once, partial, and every later rewrite ignored without error.
`compact.py` therefore writes only completed UTC days and deletes any bronze
partition for today. Today's data lives in raw and in `latest.json` only.

## 9. Spark runs daily, not hourly

The hourly ingest stays on pandas (see 3). A separate daily workflow runs PySpark
+ Delta over everything sealed since the last run. Daily is the cadence at which
the volume, the MERGE semantics, and the streaming checkpoint earn their startup cost.

## 10. Observations are insert-only

Silver and fact writes are `MERGE ... WHEN NOT MATCHED INSERT` on
`(run_id, corridor_id)`. Reprocessing the same input, or rerunning after deleting
the checkpoint, is a no-op. The streaming watermark bounds state; the merge is the
idempotency guarantee.

## 11. Corridors are SCD Type 2

A corrected coordinate routes a different road. Overwriting the corridor would
silently attach months of history to a route that was never measured. Each change
closes the old version, facts keep the version they were captured under, and
baselines use only the current version.

## 12. The web app runs locally and reads JSON from disk

The daily job writes `data/serving/*.json` (derived aggregates only). The Next.js
app in `web/` serves them through a local API route with a fixed file allow-list.
It is deliberately not hosted: see 14.

## 13. Route matching happens in the browser

A user's route is fetched live and never stored. A monitored corridor counts as
"on the route" when both endpoints lie within 500 m of the route line, in order.
Only our own corridor coordinates are needed, so no provider geometry is retained.

## 14. Stop collection, keep the data private, publish the code

Mapbox's terms allow non-production use (development, evaluation, testing,
demonstration). An application built on analytics of Mapbox data needs a separate
commercial licence for production use, and retaining Directions results is governed
by separate product terms. A public dataset or a hosted app would have crossed that
line. Collection stopped on 15 Oct 2026 after 60 days; the repo holding the data is
private, and this repository contains code, tests, and documentation only.

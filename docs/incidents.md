# Incidents

Each entry: what was seen, how it was found, why it happened, what changed.

---

## 1. Scheduler delivered ~5% of requested runs

**Window:** 17 Aug - 13 Oct 2026
**Impact:** 58 days of data at a mean of 10 samples/day against 96 expected.
Coverage skewed toward off-peak hours: 02:00 IST had ~3x the samples of 09:00 IST,
the hour the product exists to describe.

**Detection:** profiling samples per day before starting the silver layer.
Nothing alerted; every run that did execute reported healthy.

**Root cause:** GitHub Actions treats `schedule` as best-effort. On free public
repositories, high-frequency crons (`*/15`) are delayed and frequently dropped,
most heavily around the top of the hour.

**Fix:** sampling density moved in-process. Each run now takes 10 samples 5 minutes
apart in IST peaks and 3 samples 15 minutes apart otherwise, so one delivered run
is worth 3-10 samples. After the fix (13-15 Oct): ~6 runs/day delivered,
~29 samples/day, a 3x improvement but still below the ~150/day design.

**Consequence for design:** baselines use day type x hour rather than weekday x
15 minutes, and every forecast carries its sample count.

**Prevention:** the daily quality job checks freshness and volume against the
trailing 7-day median, so a silent drop now fails a build.

**Open:** an external trigger calling `workflow_dispatch` would remove the
dependency on GitHub's scheduler entirely.

---

## 2. Rain column changed type between days

**Window:** 17 Aug - 15 Oct 2026, found before first Spark run
**Impact:** 3 distinct bronze schemas across 60 files. `rain_mm`,
`precipitation_mm`, and `cloud_cover_pct` were int64 on some days and double on
others.

**Detection:** reading every bronze file's Parquet schema before writing the
streaming reader's explicit schema.

**Root cause:** Open-Meteo serialises whole numbers as JSON integers. On a fully
dry day every value is `0`, pandas infers int64, and the file is written as such.
Spark 3.5's Parquet reader cannot widen int64 to double and fails the stream.

**Fix:** `compact.conform()` pins every numeric column to float64 and timestamps to
microseconds before writing. Historical partitions, whose raw source had already
expired, were conformed in place with `scripts/conform_bronze.py`.

**Prevention:** a unit test asserts dry and wet days produce identical types.

---

## 3. All-null column broke the first Spark run

**Window:** 15 Oct 2026, first CI run of the Spark test suite
**Impact:** 3 of 4 Spark tests failed with `CANNOT_DETERMINE_TYPE`. No production data affected; the transform had not run yet.

**Detection:** the `spark` CI job, the first time the transform code met a real Spark runtime.

**Root cause:** a column where every value is null has no type. pandas writes it to Parquet as a null-typed column, and Spark refuses to read that as the `StringType` the stream declares. The tests hit it through `weather_observed_at_utc`; production would have hit it on any UTC day where Open-Meteo failed for every run, because `ingest.py` then writes rows with no weather fields at all.

**Fix:** `compact.conform()` now reindexes every bronze frame to a fixed column list and pins each column's type, so a missing or all-null column is still written as typed text or double. The Spark tests read bronze through the same Parquet path and schema as production instead of building DataFrames from pandas.

**Prevention:** a unit test writes a bronze file with no weather fields and asserts the full, typed schema.

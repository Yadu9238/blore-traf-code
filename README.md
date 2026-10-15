# blore-traf

A data platform that measured travel time on 16 Bangalore tech corridors for 60
days, joined it with weather, and answered one commuter question: **when should I
leave?**

This repository holds the code, tests, and design records. The collected data is
kept in a private repository (see [Data and licensing](#data-and-licensing)).

Status: **collection stopped 15 Oct 2026.** Every layer below ran on real data
before it stopped.

## Architecture

```
Mapbox driving-traffic ─┐                     hourly, pandas
Open-Meteo weather      ┼─▶ raw JSONL ──▶ bronze Parquet (sealed per UTC day)
                        ┘   7-day retention
                                                │  daily, PySpark + Delta
                                                ▼
                        silver   Structured Streaming, Trigger.AvailableNow,
                                 watermark + insert-only MERGE, quarantine
                                                │
                                                ▼
                        gold     dim_corridor (SCD2), dim_date, fact_corridor_observation
                                                │
                                                ▼
                        baseline median per corridor × day type × IST hour
                                                │
                                                ▼
                        serving JSON ──▶ quality gates ──▶ local Next.js app
```

| Path | What it does |
|---|---|
| `src/ingest.py` | Polls every corridor several times per run; tolerates per-corridor failure |
| `src/compact.py` | Raw → bronze with a fixed schema; seals completed days; enforces retention |
| `src/transform/silver.py` | Streaming bronze → silver with validation and IST calendar |
| `src/transform/gold.py` | SCD2 corridor dimension, date dimension, fact table |
| `src/transform/baseline.py` | Medians and sample counts; low-sample cells flagged |
| `src/transform/export.py` | Small serving files for the app |
| `src/quality/checks.py` | Freshness, completeness, volume, validity, nullity |
| `web/` | Local app: corridor board, route matching, departure forecast |
| `.github/workflows/` | Orchestration as it ran (scheduling removed in this copy) |

## Design records

- [docs/decisions.md](docs/decisions.md): 14 decisions, each with the alternative it rejected
- [docs/incidents.md](docs/incidents.md): what broke, how it was found, what changed

## Running it

Python 3.11 (the transform is pinned to it; Java 17 for the Spark tests):

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
ruff check . && pytest -q          # Spark tests skip without Java

pip install -r requirements-transform.txt
pytest -q tests/test_transform.py  # needs Java 17
```

Web app (Node 22):

```bash
cd web
npm install
npm test
cp .env.example .env.local         # add a public Mapbox token restricted to localhost
npm run dev                        # http://localhost:3001
```

The app reads `../data/serving/*.json`, which this repository does not include.
Running the pipeline against your own Mapbox token produces them.

## Data and licensing

Mapbox permits non-production use: development, evaluation, testing, and
demonstration. Analytics applications need a separate commercial licence for
production use, and retaining Directions results is governed by Mapbox's product
terms. So the collected data and the derived baselines are not published, the app
is not hosted, and the workflows here have no schedule and a repository guard.

Weather data: [Open-Meteo](https://open-meteo.com/), CC BY 4.0.

Driving can be dangerous. Travel times from the Mapbox Directions API do not
replace the information on the road; follow signals, signs, and police, and observe
all traffic laws.

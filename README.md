# MyDataLabs — Geopolitical Risk & Quantitative Intelligence Indices

[![Flask](https://img.shields.io/badge/Framework-Flask_3.0-blue?style=flat-square&logo=flask)](https://flask.palletsprojects.com/)
[![Apache ECharts](https://img.shields.io/badge/Charts-Apache_ECharts_5.5-cyan?style=flat-square&logo=apache)](https://echarts.apache.org/)
[![Vercel](https://img.shields.io/badge/Deploy-Vercel_Serverless-black?style=flat-square&logo=vercel)](https://vercel.com/)
[![Data licence](https://img.shields.io/badge/Data-CC_BY_4.0-green?style=flat-square)](https://creativecommons.org/licenses/by/4.0/)

**MyDataLabs** publishes composite indices for geopolitical stress, energy security, maritime chokepoints, and commercial aviation operations.
* **Tagline**: *"Quantifying the Unquantifiable"*
* **Flagship Indices**:
  * **Hormuz Crisis Index (HMX-INDEX)** &mdash; scores maritime security and energy supply in the Strait of Hormuz against a 100.0 calm baseline.
  * **Airline Pressure Index (API-INDEX)** &mdash; weekly composite score and **7-Region Stress Contribution Analysis** across operational fleet groundings, crack spreads, and geopolitical airspace detours.
  * **Lok Sabha Projection Engine (LS-PROJ)** &mdash; daily opinion tracker and seat projection model for Indian parliamentary elections.

The site publishes its full methodology, component weights and caps, refresh cadence and known limitations — and exposes the series as open JSON and CSV.

---

## Data honesty notes

Three things that matter more than any feature in this repo:

1. **The vessel incident log is compiled separately from the index.**
   `app/data/vessel_attacks.json` holds 56 records shown on the dashboard. It contributes
   nothing to the composite score and is not served by the API. Vessel names are
   placeholder identifiers (`M/T Vessel-NNN`) rather than IMO-registered names, and the
   per-row `source` field survives on only three rows.

2. **Three of seven components (35% of index weight) are keyed by hand.** War-risk insurance,
   tanker freight and Cape reroutes have no free API. Their current figures live in
   `app/data/hormuz_manual.json`, and each publishes its own `as_of` date, source and confidence
   in the UI and the API. Ship traffic joined the automatic side in 2026-07 (IMF PortWatch); its
   hand-entered figure is retained only as a fallback for feed outages.

3. **Two weekly series are reconstructed, not observed.** For ship traffic and war-risk insurance,
   the weeks before the 2026-07-26 revision were re-anchored from a previously published series
   rather than measured. Flagged `reconstructed_series` in the API — now driven by a
   `history_reconstructed` field in the feeder file, so establishing a real series retires the
   caveat with a one-field edit instead of a code change.

---

## Composite index maths

$$\text{Index Score} = 100.0 + \sum \Big[ \text{Weight}_i \times \text{StressScore}(\text{Current}_i, \text{Baseline}_i, \text{Cap}_i) \Big]$$

### 1. Hormuz Crisis Index (HMX-INDEX)

| Component | Weight | Baseline | Cap | Source | Cadence |
| :--- | :---: | :---: | :---: | :--- | :--- |
| Brent Crude | 30% | $64.77 / bbl | +55% | Yahoo Finance (`BZ=F`) | Daily, automatic |
| Hormuz Transits (all commercial vessels) | 15% | 616 transits / wk | −90% (inverted) | IMF PortWatch | Weekly, manual |
| War-Risk Insurance (per transit) | 15% | 0.25% hull value | +3900% | Marsh / market brokers | Weekly, manual |
| Tanker Freight (BDTI) | 15% | 900 index points | +75% | Baltic Exchange | Weekly, manual |
| TTF European Gas | 10% | 34.11 EUR / MWh | +95% | Yahoo Finance (`TTF=F`) | Daily, automatic |
| VIX Volatility Index | 10% | 16.05 | +200% | Yahoo Finance (`^VIX`) | Daily, automatic |
| Cape Reroutes | 5% | 8.0% of traffic | +250% | AIS / Vortexa | Weekly, manual |

### 2. Airline Pressure Index (API-INDEX)

| Component | Weight | Baseline | Cap | Source | Cadence |
| :--- | :---: | :---: | :---: | :--- | :--- |
| Jet Fuel Crack Spread | 25% | $15.00 / bbl | $45.00 / bbl | Yahoo Finance (`HO=F` vs `BZ=F`) / EIA | Daily, automatic |
| Fleet Grounding Ratio | 20% | 5.0% active fleet | 18.0% active fleet | OpenSky Network / Fleets | Weekly, manual |
| ATFM En-Route Delays | 15% | 0.80 min / flt | 3.50 min / flt | Eurocontrol / FAA OPSNET | Weekly, manual |
| Geopolitical Detour Extension | 15% | 4.0% route length | 18.0% route length | Flightradar24 / FIR Notices | Weekly, manual |
| US Airline Equity Stress | 10% | 0.0% dislocation | 60.0% drawdown | Yahoo Finance (NYSE JETS vs S&P 500) | Daily, automatic |
| Refinery Capacity Utilization | 10% | 92.0% utilization | 75.0% utilization | EIA Weekly Petroleum Status | Weekly, automatic |
| SAF Blend Cost Overhead | 5% | $0.00 / bbl | $8.00 / bbl | Argus / Platts SAF Mandates | Monthly, manual |

---

## Routes

| Path | Purpose |
| :--- | :--- |
| `/` | Landing page, Featured Aviation Intelligence banner, live ticker |
| `/airline-index` | Airline Pressure Index dashboard: trajectory, regional contribution breakdown, interactive simulator |
| `/hormuz-index` | HMX-INDEX dashboard: gauge, trajectory, component matrix, press dispatch |
| `/lok-sabha-index` | Lok Sabha Projection Engine: daily seat forecast + 2019/2024 backtest |
| `/terms`, `/privacy` | Legal disclaimers and methodology notes |
| `/api/hormuz-index/data.json` | HMX-INDEX snapshot, components, correlations, full history |
| `/api/hormuz-index/data.csv` | Weekly history with raw component values |
| `/favicon.ico` | Multi-resolution site favicon |

---

## Project structure

```
mydatalabs-in/
├── api/index.py               # Vercel serverless WSGI entry point
├── app/
│   ├── data/
│   │   ├── hormuz_history.json     # Weekly series + generated provenance (updater writes)
│   │   ├── hormuz_manual.json      # Current hand-entered figures (humans write)
│   │   ├── vessel_attacks.json     # dashboard incident log (not an index input)
│   │   └── elections/              # CVoter trackers, projections, calibration, catalog
│   ├── elections/             # Lok Sabha Projection Engine
│   │   ├── routes.py          # Page + API blueprint, mtime-keyed response cache
│   │   └── engine/            # Model: scraper, calibration, seat model, ML suite,
│   │                          #   backtest, insights, events, trend analytics, paths
│   ├── indices/hormuz.py      # Component definitions, fetchers, snapshot assembly
│   ├── manual_data.py         # Hand-entered figures: reading, validation, generated notes
│   ├── static/
│   │   ├── css/style.css      # Design tokens, dark/light themes, a11y primitives
│   │   ├── css/elections.css  # Projection dashboard, scoped under .elections-dash
│   │   ├── js/theme.js        # Theme toggle, keyboard-accessible nav, clipboard
│   │   ├── js/charts.js       # ECharts setup, theme-reactive, fallback handling
│   │   ├── js/elections.js    # Chart.js forecast chart, tabs, event overlay
│   │   └── js/vote.js         # HMX-PPI drag-to-vote gauge, anonymous token handling
│   ├── templates/             # base, home, hormuz, elections, methodology, data, errors
│   ├── routes.py              # Routing, snapshot cache, press dispatch derivation
│   ├── scoring.py             # Generic composite engine (index-agnostic)
│   ├── storage.py             # History persistence with durability reporting
│   ├── db.py                  # Postgres connections + idempotent schema bootstrap
│   ├── votes.py               # HMX-PPI aggregation, dedup and privacy design
│   └── __init__.py            # App factory, security headers, static caching
├── scripts/
│   ├── build_assets.py        # Regenerate icons + 1200x630 OG card from logo.png
│   ├── restate_2026_07_26.py  # Revision artifact: units/cap fix + full recompute
│   ├── update_hormuz.py       # Wrapper around update_data.py
│   ├── update_elections.py    # Operational CVoter refresh (schedule this one)
│   └── elections_pipeline.py  # Full model pipeline: fetch → calibrate → backtest → plot
├── tests/test_scoring.py      # Scoring engine edge cases
├── update_data.py             # Weekly updater
├── requirements-pipeline.txt  # Offline-only deps (matplotlib, selenium fallback)
├── vercel.json                # Rewrites, cache/security headers, cron schedule
└── app.py                     # Local dev entrypoint
```

---

## Local development

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

python app.py                   # http://127.0.0.1:5000
python -m pytest tests/ -q      # scoring engine tests
```

### Weekly data update

Edit the three hand-entered figures in `app/data/hormuz_manual.json`. Only four fields move:

```jsonc
"war_risk": {
  "value":  8.2,             // the figure, in this block's "unit"
  "as_of":  "2026-08-17",    // when it was OBSERVED — not when you typed it
  "source": "Marsh",         // published as provenance
  "note":   "low end of the quoted range"
}
```

Leave `as_of` alone if the figure has not changed: the component then shows as STALE, which is
true, rather than being restamped as fresh. History needs no maintenance here — the updater appends
each week's values to `weeks[]` in `hormuz_history.json` on every run.

```bash
# 1. Check the file before doing anything with it:
python update_data.py --check-manual

# 2. Recompute, commit + push. Validation runs first; malformed rows abort the
#    run, overdue ones only warn and publish as STALE:
python update_data.py

# Recompute and persist locally without touching git:
python update_data.py --local

# Preview without writing anything:
python update_data.py --dry-run
```

The updater reports which components are stale, whether the snapshot is degraded, and — importantly —
whether the write actually landed anywhere durable.

The provenance the API serves (`series_source_notes`, `reconstructed_series`) is **generated on every
run** from the feeder file and the snapshot. Do not hand-edit it in `hormuz_history.json`; it will be
overwritten. It used to be prose typed in by hand, which meant it asserted a "latest observation"
from 2026-07-19 on a public API for a month after that stopped being true.

By default (no flag) it also commits `app/data/hormuz_history.json` and `vessel_attacks.json` and
pushes to `origin/main` — that push is what triggers the Vercel deployment, since Vercel's own
filesystem is read-only outside `/tmp` and cannot persist the update itself. This is the mode the
scheduled cron job runs in. `--local` skips the git step for local testing; the commit only ever
touches those two data files, never a broad `git add .`.

### Lok Sabha projection data update

```bash
# Update if CVoter has published new survey days; refits the model and rebuilds
# every derived file. Safe to run on a timer — it exits without writing when
# there is nothing new.
python scripts/update_elections.py

python scripts/update_elections.py --check    # report freshness, write nothing
python scripts/update_elections.py --force    # refetch + rebuild after a weight change
python scripts/update_elections.py --quiet    # for Task Scheduler / cron
```

The web app needs no restart: its response cache is keyed on the mtimes of
`cvoter_daily_trackers.csv`, `ideal_model_daily_projections.csv` and
`model_calibration.json`, so the next request after an update rebuilds everything.

Refreshing over HTTP (`POST /api/lok-sabha-index/refresh_data`) is disabled unless
`ALLOW_WEB_REFRESH=1`. An anonymous visitor must not be able to make the server
fetch 41 upstream files and rewrite the dataset.

For model work rather than a routine refresh, the full pipeline — calibration
diagnostics, backtest, Monte Carlo, static chart — is:

```bash
pip install -r requirements.txt -r requirements-pipeline.txt
python scripts/elections_pipeline.py              # fetch if new, then full run
python scripts/elections_pipeline.py --no-fetch   # cached CSVs only
python scripts/elections_pipeline.py --optimize   # + tracker/parameter grid search
```

Like the Hormuz updater, this writes to the repo rather than to the deployed
filesystem: Vercel's is read-only outside `/tmp`, so a data refresh reaches
production by being committed and pushed.

### Regenerating image assets

```bash
python scripts/build_assets.py
```

Produces `logo-64.png`, `favicon.png`, `apple-touch-icon.png` and the 1200×630 `og-card.png` from
`logo.png`, and — if `app/static/img/image1.jpg` is present — the home page hero: three responsive
WebP + JPEG derivatives (640/960/1400px, 12:5) cropped and re-encoded down from whatever the source
photo is (the source itself is excluded from the Vercel bundle via `.vercelignore`; only the
derivatives are ever served). Re-run after replacing either source image.

---

## Configuration

| Variable | Default | Purpose |
| :--- | :--- | :--- |
| `SITE_ORIGIN` | `https://mydatalabs.in` | Canonical origin for canonical tags, OG, sitemap, robots, JSON-LD |
| `CRON_SECRET` | *(unset)* | When set, `/api/cron/update-hormuz` requires `Authorization: Bearer <secret>` |
| `HISTORY_DATA_DIR` | *(unset)* | Writable directory for durable history persistence |
| `SNAPSHOT_TTL_SECONDS` | `3600` | How long a computed snapshot is reused before refetching |
| `STATIC_MAX_AGE` | `31536000` | `Cache-Control: max-age` for `/static/*` |
| `DATABASE_URL` | *(unset, falls back to `db`)* | Postgres DSN for community voting. Unset disables the vote block; nothing else on the site depends on it |
| `VOTE_PEPPER` | *(dev placeholder)* | Secret mixed into vote token hashes. **Set this in production** |
| `MIN_VOTES_TO_PUBLISH` | `5` | Ballots required before the perception number is shown |
| `MAX_VOTES_PER_ORIGIN` | `25` | Weekly ballot ceiling per coarse network hash |


---

## Public Perception Index

A 1–10 rating on the Hormuz dashboard asking readers how severe the situation
feels. The mean rating is stretched onto the same 100–200 scale as the model
score, so a rating of 1 lands on the calm baseline and 10 on maximum stress:

```
index = 100 + (mean_rating - 1) / 9 * 100
```

Sharing the scale is what makes the crowd reading and the composite comparable
at a glance. It is opinion, contributes nothing to HMX-INDEX, and is never
served by the data API.

Votes live in Postgres (`community_votes`); the table is created on first use
by `app/votes.py:SCHEMA`, so a fresh database needs no manual bootstrap.

**Data protection.** No account, no cookie, no IP address, no user agent and no
fingerprint is stored. Uniqueness comes from a random UUID the browser
generates and keeps in `localStorage`, written only when someone actually
votes, and stored server-side only as a peppered SHA-256. Ballot stuffing is
capped against a week-salted HMAC of IP + user agent from which neither input
can be recovered and which cannot be correlated across weeks. The
`localStorage` entry is strictly necessary for the function the visitor asked
for, so it needs no consent banner, and the vote block states it anyway.
Visitors can withdraw a vote from the same block, which deletes the row and
the local ID. See the module docstring in `app/votes.py` for the full rationale.

---

## Deployment

### Vercel

```bash
npx vercel --prod
```

`vercel.json` configures the rewrite to `api/index.py`, immutable caching for `/static/*`, security
headers, and a daily cron hitting `/api/cron/update-hormuz`.

**Set `CRON_SECRET`** in Vercel project settings — Vercel sends it as a bearer token automatically,
and without it the recompute endpoint is publicly callable.

### Canonical host — one setting, do not skip it

Every absolute URL the site emits uses `SITE_ORIGIN`, which defaults to the **apex**
`https://mydatalabs.in`. The deployment must redirect `www → apex` to match, otherwise canonical
tags, OG images and sitemap entries all point at a URL that redirects.

In **Vercel → Project → Settings → Domains**: add both `mydatalabs.in` and `www.mydatalabs.in`, then
set `www.mydatalabs.in` to **redirect to** `mydatalabs.in`.

If you would rather serve from `www`, set `SITE_ORIGIN=https://www.mydatalabs.in` instead — no code
changes are needed either way.

---

## Licence & attribution

Index data is published under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

Cite as: *MyDataLabs Hormuz Crisis Index (HMX-INDEX) — mydatalabs.in*.

The vessel incident log is not covered by this licence.

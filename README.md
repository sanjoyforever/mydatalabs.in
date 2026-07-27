# MyDataLabs — Geopolitical Risk & Quantitative Intelligence Indices

[![Flask](https://img.shields.io/badge/Framework-Flask_3.0-blue?style=flat-square&logo=flask)](https://flask.palletsprojects.com/)
[![Apache ECharts](https://img.shields.io/badge/Charts-Apache_ECharts_5.5-cyan?style=flat-square&logo=apache)](https://echarts.apache.org/)
[![Vercel](https://img.shields.io/badge/Deploy-Vercel_Serverless-black?style=flat-square&logo=vercel)](https://vercel.com/)
[![Data licence](https://img.shields.io/badge/Data-CC_BY_4.0-green?style=flat-square)](https://creativecommons.org/licenses/by/4.0/)

**MyDataLabs** publishes weekly composite indices for geopolitical stress, energy security and
maritime chokepoints. Its flagship index, the **Hormuz Crisis Index (HMX-INDEX)**, scores conditions
in the Strait of Hormuz against a calm baseline of 100.0.

The site publishes its full methodology, its component weights and caps, its refresh cadence and its
known limitations — and exposes the whole series as open JSON and CSV.

---

## Data honesty notes

Three things that matter more than any feature in this repo:

1. **The vessel incident log is compiled separately from the index.**
   `app/data/vessel_attacks.json` holds 56 records shown on the dashboard. It contributes
   nothing to the composite score and is not served by the API. Vessel names are
   placeholder identifiers (`M/T Vessel-NNN`) rather than IMO-registered names, and the
   per-row `source` field survives on only three rows.

2. **Four of seven components (50% of index weight) are keyed by hand.** Ship traffic, war-risk
   insurance, tanker freight and Cape reroutes have no free API. They are updated weekly from
   licensed sources and every one publishes its own `last_updated` date in the UI and the API.

3. **Two weekly series are reconstructed, not observed.** For ship traffic and war-risk insurance
   — together 30% of index weight — only the baseline and the latest week are measured values. The
   weeks between were re-anchored from a previously published series during the 2026-07-26 revision
   and preserve its shape rather than recording actual weekly readings. Flagged
   `reconstructed_series` in the API. Replacing them with real weekly series needs new values, not
   new code.

---

## Composite index maths

$$\text{Index Score} = 100.0 + \sum \Big[ \text{Weight}_i \times \text{StressScore}(\text{Current}_i, \text{Baseline}_i, \text{Cap}_i) \Big]$$

| Component | Weight | Baseline | Cap | Source | Cadence |
| :--- | :---: | :---: | :---: | :--- | :--- |
| Brent Crude | 30% | $64.77 / bbl | +55% | yfinance (`BZ=F`) | Daily, automatic |
| Hormuz Transits (all commercial vessels) | 15% | 616 transits / wk | −90% (inverted) | IMF PortWatch | Weekly, manual |
| War-Risk Insurance (per transit) | 15% | 0.25% hull value | +3900% | Marsh / market brokers | Weekly, manual |
| Tanker Freight (BDTI) | 15% | 900 index points | +75% | Baltic Exchange | Weekly, manual |
| TTF European Gas | 10% | 34.11 EUR / MWh | +95% | yfinance (`TTF=F`) | Daily, automatic |
| VIX Volatility Index | 10% | 16.05 | +200% | yfinance (`^VIX`) | Daily, automatic |
| Cape Reroutes | 5% | 8.0% of traffic | +250% | AIS / Vortexa | Weekly, manual |

Baseline: January 2026 mean of daily closes, except ship traffic (IMF PortWatch's one-year reference window,
2025-02-28 to 2026-02-27) and war-risk insurance (the pre-war market rate). Every cap is justified
against a historical precedent — see
`/methodology` on the live site, or `cap_rationale` on each `Component` in
[`app/indices/hormuz.py`](app/indices/hormuz.py).

**The index is one-sided by design.** Stress scores floor at 0, so the composite cannot fall below
100.0 — it measures crisis stress, not conditions calmer than baseline. Two-sided scoring is
supported per-component via `Component(floor=-50)` but is off by default, because turning it on
restates the whole published series.

**Missing data is carried forward, never reset to baseline.** A component that cannot be fetched
keeps its last known value, is flagged `stale`, and — if stale components reach 20% of index weight —
marks the whole snapshot `degraded`, which surfaces a reduced-confidence notice on the dashboard.

---

## Routes

| Path | Purpose |
| :--- | :--- |
| `/` | Landing page and index overview |
| `/hormuz-index` | HMX-INDEX dashboard: gauge, trajectory, component matrix, press dispatch |
| `/methodology` | Formula, weights, cap rationale, baseline selection, limitations |
| `/data` | API documentation, response schema, correlation matrix, citation formats |
| `/reports/<slug>` | Coming-soon placeholders (`noindex`) |
| `/api/hormuz-index/data.json` | Current snapshot, components, correlations, full history |
| `/api/hormuz-index/data.csv` | Weekly history with raw component values |
| `/api/health` | Liveness, storage durability, snapshot cache age |
| `/api/cron/update-hormuz` | Scheduled recompute + persist (`CRON_SECRET` protected) |
| `/sitemap.xml`, `/robots.txt`, `/llms.txt` | Crawler-facing files |

---

## Project structure

```
mydatalabs-in/
├── api/index.py               # Vercel serverless WSGI entry point
├── app/
│   ├── data/
│   │   ├── hormuz_history.json     # Weekly history + manual_overrides + manual_updated
│   │   └── vessel_attacks.json     # dashboard incident log (not an index input)
│   ├── indices/hormuz.py      # Component definitions, fetchers, snapshot assembly
│   ├── static/
│   │   ├── css/style.css      # Design tokens, dark/light themes, a11y primitives
│   │   ├── js/theme.js        # Theme toggle, keyboard-accessible nav, clipboard
│   │   └── js/charts.js       # ECharts setup, theme-reactive, fallback handling
│   ├── templates/             # base, home, hormuz, methodology, data, 404, 500, coming_soon
│   ├── routes.py              # Routing, snapshot cache, press dispatch derivation
│   ├── scoring.py             # Generic composite engine (index-agnostic)
│   ├── storage.py             # History persistence with durability reporting
│   └── __init__.py            # App factory, security headers, static caching
├── scripts/
│   ├── build_assets.py        # Regenerate icons + 1200x630 OG card from logo.png
│   ├── restate_2026_07_26.py  # Revision artifact: units/cap fix + full recompute
│   └── update_hormuz.py       # Wrapper around update_data.py
├── tests/test_scoring.py      # Scoring engine edge cases
├── update_data.py             # Weekly updater
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

```bash
# 1. Edit app/data/hormuz_history.json → manual_overrides with this week's figures
# 2. Recompute, stamping the manual inputs as updated today, commit + push:
python update_data.py --stamp-manual

# Recompute and persist locally without touching git:
python update_data.py --local

# Preview without writing anything:
python update_data.py --dry-run
```

The updater reports which components are stale, whether the snapshot is degraded, and — importantly —
whether the write actually landed anywhere durable.

By default (no flag) it also commits `app/data/hormuz_history.json` and `vessel_attacks.json` and
pushes to `origin/main` — that push is what triggers the Vercel deployment, since Vercel's own
filesystem is read-only outside `/tmp` and cannot persist the update itself. This is the mode the
scheduled cron job runs in. `--local` skips the git step for local testing; the commit only ever
touches those two data files, never a broad `git add .`.

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

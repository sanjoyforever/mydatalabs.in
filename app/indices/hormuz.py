"""Hormuz Crisis Index: component definitions, baseline, and data fetchers.

Baseline: January 2026 monthly mean of daily closes ("calm", composite = 100).

Three components (Brent, TTF gas, VIX — 50% of index weight) refresh
automatically from yfinance. The other four (ship traffic, war-risk insurance,
tanker freight, Cape reroutes — the remaining 50%) come from paywalled sources
(Lloyd's List, Reuters/S&P, Baltic Exchange, Vortexa) with no free API, and are
entered by hand each week in the ``manual_overrides`` block of
``app/data/hormuz_history.json``. Their fetch functions return None; the values
are carried forward from the last manual entry and surfaced in the UI with a
"last updated" date so nobody mistakes a stale reading for a fresh one.

When a live fetch fails we carry the previous value forward rather than falling
back to baseline — a value we could not fetch is not a value that is calm.
"""
from __future__ import annotations

import os
import threading
import time
from datetime import date, datetime, timedelta, timezone

from app.scoring import Component, CompositeResult, compute_composite
from app import storage

INDEX_KEY = "hormuz"

# --- Component definitions -------------------------------------------------

COMPONENTS: list[Component] = [
    Component(
        key="brent",
        label="Brent Crude",
        weight=0.30,
        source="yfinance (BZ=F)",
        cap_pct=55,
        unit="$/bbl",
        cap_rationale=(
            "+55% approximates the peak move in Brent during the 2022 Ukraine invasion "
            "shock (~$78 to ~$128 over five weeks), the largest modern supply-driven "
            "repricing outside 2008."
        ),
        update_cadence="Daily (automatic)",
    ),
    Component(
        key="ship_traffic",
        label="Hormuz Transits (all commercial vessels)",
        weight=0.15,
        source="IMF PortWatch",
        cap_pct=90,
        invert=True,  # a DECLINE in transits is the stress signal
        unit="transits/wk",
        cap_rationale=(
            "-90% is calibrated on the 2026 closure itself: PortWatch recorded 15 "
            "vessels/day against an 88/day baseline on 2026-07-19, an 83% decline, and "
            "single days near-total. The previous -50% cap saturated at a halving, so "
            "a disrupted strait and a closed one scored identically — the one "
            "discrimination this component exists to make. -90% keeps that range "
            "resolvable while still reserving the top of the scale for full closure."
        ),
        update_cadence="Weekly (automatic, IMF PortWatch publishes ~8 days in arrears)",
    ),
    Component(
        key="war_risk",
        label="War-Risk Insurance (per transit)",
        weight=0.15,
        source="Marsh / market brokers",
        cap_pct=3900,
        unit="% hull value",
        cap_rationale=(
            "+3900% takes the rate from a 0.25% pre-war baseline to 10% of hull value, "
            "the peak quoted for Hormuz transits during this crisis. The previous +400% "
            "cap topped out at 0.50% of hull — a level the market passed in March 2026 — "
            "so a 5x reading and a 40x reading both scored 100 and the component could "
            "not rank severity within the crisis it was built to measure."
        ),
        manual=True,
        update_cadence="Weekly (manual entry, broker-quoted)",
    ),
    Component(
        key="tanker_freight",
        label="Tanker Freight (BDTI)",
        weight=0.15,
        source="Baltic Exchange",
        cap_pct=75,
        unit="index",
        cap_rationale=(
            "+75% on the Baltic Dirty Tanker Index approximates the 2022 dislocation "
            "peak, when rerouting and sanctions repriced dirty tanker tonne-miles."
        ),
        manual=True,
        update_cadence="Weekly (manual entry)",
    ),
    Component(
        key="ttf_gas",
        label="TTF European Gas",
        weight=0.10,
        source="yfinance (TTF=F)",
        cap_pct=95,
        unit="EUR/MWh",
        cap_rationale=(
            "+95% is deliberately wider than Brent's cap because TTF is structurally "
            "more volatile; the 2022 European gas crisis moved several multiples of "
            "this, so the cap marks 'severe' rather than 'worst imaginable'."
        ),
        update_cadence="Daily (automatic)",
    ),
    Component(
        key="vix",
        label="VIX Volatility Index",
        weight=0.10,
        source="yfinance (^VIX)",
        cap_pct=200,
        unit="",
        cap_rationale=(
            "+200% takes VIX from a ~16.1 baseline to ~48, above the March 2020 and "
            "October 2008 equity stress peaks."
        ),
        update_cadence="Daily (automatic)",
    ),
    Component(
        key="reroutes",
        label="Cape of Good Hope Reroutes",
        weight=0.05,
        source="AIS / Vortexa",
        cap_pct=250,
        unit="% of traffic",
        cap_rationale=(
            "+250% takes reroutes from an 8% baseline to 28% of regional traffic, "
            "comparable to the Suez diversion share observed in early 2024."
        ),
        manual=True,
        update_cadence="Weekly (manual entry)",
    ),
]

# Baseline: January 2026 mean of daily closes for the three market-fed
# components. A four-trading-day window (the previous Feb 1-5 anchor) is too
# noisy to fix a series to, and the published figures did not match it anyway:
# Brent 65.00 was the January mean, and VIX 14.50 matched no window at all.
BASELINE_VALUES: dict[str, float] = {
    "brent": 64.77,
    # 88 commercial vessels/day x 7 (IMF PortWatch, fixed reference window
    # 2025-02-28 to 2026-02-27). Was 34/wk until the 2026-07-26 revision — a
    # daily tanker figure mislabelled as a weekly all-vessel one.
    "ship_traffic": 616,
    # Pre-war Hormuz war-risk rate, ~0.25% of hull value per transit (The
    # National, 2026-07-17). Was 0.10% until the 2026-07-26 revision.
    "war_risk": 0.25,
    "tanker_freight": 900,
    "ttf_gas": 34.11,
    "vix": 16.05,
    "reroutes": 8.0,
}

BASELINE_WINDOW = "2026-01-01/2026-01-31"

YFINANCE_TICKERS = {
    "brent": "BZ=F",
    "ttf_gas": "TTF=F",
    "vix": "^VIX",
}

# IMF PortWatch publishes daily vessel counts for 28 maritime chokepoints
# through an open ArcGIS feature service — no key, no auth. This is the same
# source the component already cited; it was simply being read by hand.
PORTWATCH_QUERY_URL = (
    "https://services9.arcgis.com/weJ1QsnbMYJlCHdG/arcgis/rest/services/"
    "Daily_Chokepoints_Data/FeatureServer/0/query"
)

# Component key -> the `portname` PortWatch files it under. Only transits are
# wired up: PortWatch also carries Cape of Good Hope, but the reroutes
# component is a *share* of regional traffic and the denominator behind its
# published 8% baseline is not recorded anywhere, so deriving it here would be
# inventing a methodology rather than automating one.
PORTWATCH_CHOKEPOINTS = {
    "ship_traffic": "Strait of Hormuz",
}

# PortWatch runs roughly a week behind — the observed gap was 8 days, not the
# 2 the component's cadence string used to claim. A transit figure is therefore
# *expected* to be older than LIVE_STALE_AFTER_DAYS and must not be flagged on
# the yfinance clock; this threshold only trips when PortWatch itself stops
# publishing, which is the condition actually worth surfacing.
PORTWATCH_STALE_AFTER_DAYS = 21

MANUAL_KEYS = {c.key for c in COMPONENTS if c.manual}

# Every component fetched without a human in the loop.
AUTO_KEYS = set(YFINANCE_TICKERS) | set(PORTWATCH_CHOKEPOINTS)

COMPONENTS_BY_KEY = {c.key: c for c in COMPONENTS}

# How old an automatically-fetched value may be before the UI calls it stale.
LIVE_STALE_AFTER_DAYS = 2


_live_cache: dict = {"data": None, "fetched_at": 0.0}
_live_cache_lock = threading.Lock()

# End date of the PortWatch week the last network fetch actually used. Held
# separately from _live_cache because it is not a value, it is the answer to
# "how old is that value" — and unlike the yfinance components, whose answer is
# always "today", a transit count is a week-long aggregate finished days ago.
_portwatch_asof: dict = {"week_end": ""}


def _complete_week_transits(rows: list[tuple[str, float]]) -> tuple[float | None, str]:
    """Total transits for the most recent fully-covered Mon-Sun week.

    `rows` is (iso_date, count), any order. Partial weeks are rejected: with a
    multi-day publishing lag the newest week on hand is almost always missing
    days, and summing it would report a collapse in traffic that is really just
    a collapse in coverage — the exact artefact this component would otherwise
    read as a closed strait.

    Returns (total, week_end_iso), or (None, "") if no week is complete.
    """
    by_week: dict[date, list[float]] = {}
    for iso, count in rows:
        try:
            day = date.fromisoformat(iso[:10])
        except (ValueError, TypeError):
            continue
        monday = day - timedelta(days=day.weekday())
        by_week.setdefault(monday, []).append(count or 0)

    for monday in sorted(by_week, reverse=True):
        days = by_week[monday]
        if len(days) >= 7:
            return float(sum(days)), (monday + timedelta(days=6)).isoformat()
    return None, ""


def fetch_portwatch_transits(
    chokepoint: str,
    timeout_sec: float = 15.0,
    lookback_days: int = 45,
) -> tuple[float | None, str]:
    """Weekly vessel transits for one chokepoint, from IMF PortWatch.

    Returns (transits_per_week, week_end_iso) for the most recent complete
    week, or (None, "") if the service is unreachable or has published no
    complete week inside the lookback.
    """
    import requests

    try:
        resp = requests.get(
            PORTWATCH_QUERY_URL,
            params={
                "where": f"portname='{chokepoint}'",
                "outFields": "date,n_total",
                "orderByFields": "date DESC",
                "resultRecordCount": lookback_days,
                "returnGeometry": "false",
                "f": "json",
            },
            timeout=timeout_sec,
        )
        resp.raise_for_status()
        payload = resp.json()
    except Exception:  # noqa: BLE001 - an outage is reported as None, not raised
        return None, ""

    if not isinstance(payload, dict) or "features" not in payload:
        # ArcGIS reports failures as HTTP 200 with an {"error": ...} body, so a
        # successful response is not by itself a successful query.
        return None, ""

    rows = []
    for feature in payload["features"]:
        attrs = feature.get("attributes") or {}
        raw_date, total = attrs.get("date"), attrs.get("n_total")
        if raw_date is None:
            continue
        if isinstance(raw_date, (int, float)):
            # Epoch milliseconds — the service has returned both this and an
            # ISO string depending on layer configuration.
            iso = datetime.fromtimestamp(raw_date / 1000.0, tz=timezone.utc).date().isoformat()
        else:
            iso = str(raw_date)[:10]
        rows.append((iso, total))

    return _complete_week_transits(rows)


def portwatch_asof(allow_network: bool = False) -> str:
    """End date of the PortWatch week backing the current transit figure."""
    if allow_network and _portwatch_asof["week_end"]:
        return _portwatch_asof["week_end"]

    from app import precomputed

    return (precomputed.load("hormuz-index").get("portwatch_week_end") or "")[:10]


# Cold yfinance fetches measure ~5.6s for the three tickers in parallel. A
# tighter budget does not make the page faster, it makes it wrong: Brent, TTF
# gas and VIX are 50% of the index weight between them, and every one of them
# times out at 2.5s, so the composite silently falls back on stored values for
# half its inputs. This runs at most once per LIVE_CACHE_TTL_SECONDS per
# instance — and behind routes.get_snapshot()'s own hour-long cache — so the
# cost is paid rarely and buys a correct headline number.
LIVE_FETCH_TIMEOUT_SECONDS = float(os.environ.get("LIVE_FETCH_TIMEOUT_SECONDS", "8"))
LIVE_CACHE_TTL_SECONDS = int(os.environ.get("LIVE_CACHE_TTL_SECONDS", "900"))


def fetch_live_values(
    timeout_sec: float = LIVE_FETCH_TIMEOUT_SECONDS,
    allow_network: bool = False,
) -> dict[str, float | None]:
    """The free/live-sourced components. Manual-only keys come back as None
    here; the caller fills them from manual_overrides.

    `allow_network` defaults to False, so this is a disk read on the request
    path: the values come from the artifact the last update run wrote. Only
    the updater (and anything explicitly asking) goes out to yfinance, because
    a page render that waits on a third-party API makes the site's latency a
    property of somebody else's uptime. A missing artifact yields all-None,
    which compute_snapshot already handles by carrying the previous week's
    reading forward.
    """
    if not allow_network:
        from app import precomputed

        stored = precomputed.load("hormuz-index").get("live_values") or {}
        return {k: stored.get(k) for k in AUTO_KEYS}

    now = time.time()
    with _live_cache_lock:
        if _live_cache["data"] is not None and (now - _live_cache["fetched_at"]) < LIVE_CACHE_TTL_SECONDS:
            return dict(_live_cache["data"])

    # PortWatch is a plain HTTP call on a different host from yfinance, so a
    # yfinance outage must not take the transit figure down with it — and vice
    # versa. Fetched first and merged in at the end for that reason.
    portwatch: dict[str, float | None] = {}
    for key, chokepoint in PORTWATCH_CHOKEPOINTS.items():
        total, week_end = fetch_portwatch_transits(chokepoint)
        portwatch[key] = total
        if week_end:
            _portwatch_asof["week_end"] = week_end

    try:
        import yfinance as yf
    except ImportError:
        return {**{k: None for k in YFINANCE_TICKERS}, **portwatch}

    import concurrent.futures

    def _fetch_one(item):
        key, ticker = item
        try:
            hist = yf.Ticker(ticker).history(period="5d", timeout=timeout_sec)
            if not hist.empty and "Close" in hist:
                val = float(hist["Close"].dropna().iloc[-1])
                return key, val
        except Exception:
            pass
        return key, None

    values: dict[str, float | None] = {k: None for k in YFINANCE_TICKERS}

    # The executor is shut down with wait=False deliberately, and is therefore
    # not used as a context manager. `with ThreadPoolExecutor(...)` calls
    # shutdown(wait=True) on the way out, which blocks until every yfinance
    # call has returned — so the as_completed timeout below would bound nothing
    # and a hung ticker would still hold the request open for its full socket
    # timeout. Abandoning stragglers is the point: a component we could not
    # fetch in time is reported as None, which the caller already handles by
    # falling back to the stored value rather than to baseline.
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=len(YFINANCE_TICKERS))
    try:
        future_map = {
            executor.submit(_fetch_one, item): item[0]
            for item in YFINANCE_TICKERS.items()
        }
        try:
            for future in concurrent.futures.as_completed(future_map, timeout=timeout_sec + 0.5):
                try:
                    k, val = future.result(timeout=0.1)
                    values[k] = val
                except Exception:
                    pass
        except concurrent.futures.TimeoutError:
            pass
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    values.update(portwatch)

    # Only cache a result that actually got something. Caching an all-None
    # sweep for 15 minutes would turn one bad network moment into a quarter
    # hour of the dashboard falling back on every live component at once.
    if any(v is not None for v in values.values()):
        with _live_cache_lock:
            _live_cache["data"] = values
            _live_cache["fetched_at"] = now

    return values


def stored_live_date() -> str:
    """Date the artifact's live_values were fetched, or "" if not recorded.

    Artifacts written before live_values_at existed have no date, hence the
    empty string rather than a guess — callers fall back to the week instead.
    """
    from app import precomputed

    return (precomputed.load("hormuz-index").get("live_values_at") or "")[:10]


def _current_week_start() -> str:
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    return monday.isoformat()


def _days_old(iso_date: str) -> int | None:
    try:
        return (date.today() - date.fromisoformat(iso_date[:10])).days
    except (ValueError, TypeError):
        return None


def compute_snapshot(persist: bool = False, allow_network: bool = False) -> CompositeResult:
    """Fetch live values, merge with manual overrides, and score the composite.

    Values that cannot be fetched are carried forward from the most recent
    known reading (never silently reset to baseline) and flagged as stale with
    the date they were last refreshed.

    If persist=True, appends (or replaces, if same week) an entry to the
    history file. See app/storage.py for where that actually lands — on a
    read-only serverless filesystem the write is instance-local only.
    """
    history = storage.load_history(INDEX_KEY)
    weeks = history.get("weeks", [])
    latest_raw = dict(weeks[-1]["raw_values"]) if weeks else dict(BASELINE_VALUES)
    last_week_start = weeks[-1].get("week_start", "") if weeks else ""

    manual_overrides = history.get("manual_overrides", {})
    manual_updated = history.get("manual_updated", {})

    # Last known value for every key: prior week's raw values, overlaid with
    # any hand-entered override.
    carried = {**latest_raw, **manual_overrides}

    live = fetch_live_values(allow_network=allow_network)
    # When allow_network is False the "live" values came off the artifact, so
    # they are as old as the artifact — dating them today would report a
    # freshness the page does not have. Only the updater, which just made the
    # network calls, is entitled to stamp them with today.
    live_iso = date.today().isoformat() if allow_network else (
        stored_live_date() or last_week_start or BASELINE_WINDOW[:10]
    )

    current_values: dict[str, float | None] = {}
    last_updated: dict[str, str] = {}
    stale_keys: set[str] = set()
    carried_forward: set[str] = set()

    for comp in COMPONENTS:
        key = comp.key
        fresh = live.get(key)

        if fresh is not None:
            current_values[key] = fresh

            if key in PORTWATCH_CHOKEPOINTS:
                # A transit count is a completed week, not a spot price. Dating
                # it "today" because that is when it was downloaded would claim
                # a freshness the underlying data does not have — PortWatch
                # publishes about a week in arrears.
                asof = portwatch_asof(allow_network=allow_network)
                last_updated[key] = asof or live_iso
                age = _days_old(asof) if asof else None
                if age is None or age > PORTWATCH_STALE_AFTER_DAYS:
                    stale_keys.add(key)
            else:
                last_updated[key] = live_iso
            continue

        # No fresh value — carry the last known reading forward.
        current_values[key] = carried.get(key, BASELINE_VALUES.get(key))
        carried_forward.add(key)

        if comp.manual:
            updated = manual_updated.get(key) or last_week_start
            last_updated[key] = updated
            age = _days_old(updated)
            # Manual inputs are expected to be up to a week old; only call them
            # stale once they have missed their own cadence.
            if age is None or age > 7:
                stale_keys.add(key)
        else:
            # An automatic component we failed to fetch is stale immediately —
            # this is an outage, not a cadence.
            updated = last_week_start or BASELINE_WINDOW[:10]
            last_updated[key] = updated
            stale_keys.add(key)

    week_start = _current_week_start()

    result = compute_composite(
        components=COMPONENTS,
        current_values=current_values,
        baseline_values=BASELINE_VALUES,
        stale_keys=stale_keys,
        week_start=week_start,
        last_updated=last_updated,
        carried_forward=carried_forward,
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )

    if persist:
        weeks = history.setdefault("weeks", [])
        entry = {
            "week_start": week_start,
            "score": result.score,
            "level_label": result.level_label,
            "level_status": result.level_status,
            "raw_values": {k: current_values.get(k) for k in BASELINE_VALUES},
        }
        weeks = [w for w in weeks if w.get("week_start") != week_start]
        weeks.append(entry)
        history["weeks"] = sorted(weeks, key=lambda w: w["week_start"])
        result.persisted = storage.save_history(INDEX_KEY, history)

    return result


def get_history() -> list[dict]:
    return storage.load_history(INDEX_KEY).get("weeks", [])


def top_driver(snapshot: CompositeResult):
    """The component contributing the most points to the composite this week."""
    if not snapshot.components:
        return None
    return max(snapshot.components, key=lambda c: c.contribution)


def component_result(snapshot: CompositeResult, key: str):
    """Look up one component's result by key, or None."""
    return next((c for c in snapshot.components if c.component.key == key), None)

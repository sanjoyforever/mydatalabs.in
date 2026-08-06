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
        manual=True,
        update_cadence="Weekly (manual entry, IMF PortWatch publishes with a 2-day lag)",
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

MANUAL_KEYS = {c.key for c in COMPONENTS if c.manual}

COMPONENTS_BY_KEY = {c.key: c for c in COMPONENTS}

# How old an automatically-fetched value may be before the UI calls it stale.
LIVE_STALE_AFTER_DAYS = 2


_live_cache: dict = {"data": None, "fetched_at": 0.0}
_live_cache_lock = threading.Lock()


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
        return {k: stored.get(k) for k in YFINANCE_TICKERS}

    now = time.time()
    with _live_cache_lock:
        if _live_cache["data"] is not None and (now - _live_cache["fetched_at"]) < LIVE_CACHE_TTL_SECONDS:
            return dict(_live_cache["data"])

    try:
        import yfinance as yf
    except ImportError:
        return {k: None for k in YFINANCE_TICKERS}

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

    # Only cache a result that actually got something. Caching an all-None
    # sweep for 15 minutes would turn one bad network moment into a quarter
    # hour of the dashboard falling back on every live component at once.
    if any(v is not None for v in values.values()):
        with _live_cache_lock:
            _live_cache["data"] = values
            _live_cache["fetched_at"] = now

    return values



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
    today_iso = date.today().isoformat()

    current_values: dict[str, float | None] = {}
    last_updated: dict[str, str] = {}
    stale_keys: set[str] = set()
    carried_forward: set[str] = set()

    for comp in COMPONENTS:
        key = comp.key
        fresh = live.get(key)

        if fresh is not None:
            current_values[key] = fresh
            last_updated[key] = today_iso
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

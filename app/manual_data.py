"""The hand-entered inputs to the Hormuz index.

Three components (war-risk insurance, tanker freight, Cape reroutes) have no
free API. Their figures come from paywalled sources — Marsh, the Baltic
Exchange, Vortexa — and are typed in. This module owns that input.

It is a **feeder file, not an archive**: ``app/data/hormuz_manual.json`` holds
exactly one current value per component. History accumulates on its own, in
``hormuz_history.json``'s ``weeks[]``, because every update run appends the
week's raw values there. Keeping a second copy of the past in the feeder would
mean maintaining the same series twice.

Why it is a separate file at all
--------------------------------
It used to be two blocks (``manual_overrides`` / ``manual_updated``) inside
hormuz_history.json, which the updater rewrites on every run. One file, two
writers. Splitting it means the file a human edits is never touched by a script,
and the file a script writes is never hand-edited.

It also carries three things the old blocks could not:

* ``source`` and ``note`` per value, published as provenance rather than kept in
  a hand-maintained prose blob that froze the day it was written.
* ``plausible_range``, so a decimal-point slip is caught before it publishes.
  A 750 keyed for 7.5 does not crash anything — it ships a credible-looking
  index with one component off by two orders of magnitude.
* ``as_of`` as a property of the figure rather than of the run, so nothing can
  stamp an unchanged value as fresh.
"""
from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from datetime import date
from typing import Optional

MANUAL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "hormuz_manual.json")

# How the figure was arrived at. Anything but "observed" means it was inferred
# rather than read off a source, and the public API says so.
CONFIDENCE_LEVELS = ("reconstructed", "estimate", "observed")

DEFAULT_CADENCE_DAYS = 7

_cache: dict[str, tuple[float, dict]] = {}
_cache_lock = threading.Lock()


@dataclass(frozen=True)
class Entry:
    """One component's current hand-entered figure."""

    key: str
    value: float
    as_of: str  # ISO date the figure was observed or quoted, not when it was typed
    source: str = ""
    note: str = ""
    confidence: str = "observed"
    role: str = "primary"  # "fallback" = a live feed is the real source
    cadence_days: int = DEFAULT_CADENCE_DAYS
    history_reconstructed: bool = False

    @property
    def age_days(self) -> Optional[int]:
        try:
            return (date.today() - date.fromisoformat(self.as_of[:10])).days
        except (TypeError, ValueError):
            return None

    @property
    def overdue(self) -> bool:
        """Past its own refresh cadence. Fallback entries are never overdue —
        nobody is meant to be keying them weekly."""
        if self.role != "primary":
            return False
        age = self.age_days
        return age is None or age > self.cadence_days


def load(path: str = MANUAL_PATH) -> dict:
    """Read the feeder file, memoised on its mtime.

    A missing or malformed file returns an empty structure rather than raising:
    the index still has its automatic components, and compute_snapshot already
    carries the previous week's value forward for anything it cannot source.
    The condition worth failing on is a *bad* entry, which validate() names.
    """
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return {"components": {}}

    with _cache_lock:
        cached = _cache.get(path)
        if cached and cached[0] == mtime:
            return cached[1]

    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {"components": {}}

    if not isinstance(data, dict) or not isinstance(data.get("components"), dict):
        return {"components": {}}

    with _cache_lock:
        _cache[path] = (mtime, data)
    return data


def spec(key: str, path: str = MANUAL_PATH) -> dict:
    """The raw block for one component, including its documentation fields."""
    block = load(path).get("components", {}).get(key)
    return block if isinstance(block, dict) else {}


def keys(path: str = MANUAL_PATH) -> list[str]:
    return list(load(path).get("components", {}).keys())


def entry(key: str, path: str = MANUAL_PATH) -> Optional[Entry]:
    """The current figure for `key`, or None if absent or unusable.

    A null value is a deliberate state — the slot exists but has not been filled
    — so it returns None rather than raising, and validate() reports it.
    """
    block = spec(key, path)
    if not block:
        return None

    try:
        value = float(block["value"])
        as_of = date.fromisoformat(str(block["as_of"])[:10]).isoformat()
    except (KeyError, TypeError, ValueError):
        return None

    try:
        cadence = int(block.get("cadence_days", DEFAULT_CADENCE_DAYS))
    except (TypeError, ValueError):
        cadence = DEFAULT_CADENCE_DAYS

    return Entry(
        key=key,
        value=value,
        as_of=as_of,
        source=str(block.get("source") or ""),
        note=str(block.get("note") or ""),
        confidence=str(block.get("confidence") or "observed"),
        role=str(block.get("role") or "primary"),
        cadence_days=cadence,
        history_reconstructed=bool(block.get("history_reconstructed")),
    )


def entries(path: str = MANUAL_PATH) -> dict[str, Entry]:
    """Every usable current figure, keyed by component."""
    found = ((key, entry(key, path)) for key in keys(path))
    return {key: value for key, value in found if value is not None}


# --- Validation -------------------------------------------------------------


def validate(expected: Optional[dict[str, dict]] = None,
             path: str = MANUAL_PATH) -> tuple[list[str], list[str]]:
    """Check the feeder file. Returns (errors, warnings).

    The split matters operationally. An **error** is an entry that would publish
    a wrong number: a malformed date, an unknown component, a value far outside
    anything plausible. Those stop the run.

    A **warning** is a figure that is merely late. Those must not stop the run —
    blocking on an overdue war-risk quote would also stop Brent, TTF, VIX and
    the PortWatch transit count from refreshing, punishing the automatic half of
    the index for the manual half being behind. The index already has a
    vocabulary for late data: the component is marked stale and the composite
    flagged degraded, both visible on the page. Late data is something to say
    out loud, not something to hide behind a failed cron job.

    `expected` maps component key -> {"unit", "baseline"} from the index
    definition, which also cross-checks the copies of those fields kept here for
    the editor's benefit. They are documentation, and undetected documentation
    drift is how somebody keys a figure in the wrong unit.
    """
    errors: list[str] = []
    warnings: list[str] = []

    if not os.path.exists(path):
        return [f"{path} does not exist."], []

    data = load(path)
    if not data.get("components"):
        return [f"{path} has no 'components' block, or could not be parsed as JSON."], []

    today = date.today().isoformat()

    for key, block in data["components"].items():
        if expected is not None and key not in expected:
            errors.append(f"{key}: not a component of the index (typo in the key?)")
            continue
        if not isinstance(block, dict):
            errors.append(f"{key}: block is not an object")
            continue

        if expected is not None:
            ref = expected.get(key, {})
            for field in ("unit", "baseline"):
                mine, theirs = block.get(field), ref.get(field)
                if theirs is not None and mine is not None and mine != theirs:
                    errors.append(
                        f"{key}: {field} {mine!r} here but {theirs!r} in the index"
                        " definition — one of them is wrong"
                    )

        raw_date = str(block.get("as_of") or "")
        try:
            as_of = date.fromisoformat(raw_date[:10]).isoformat()
        except ValueError:
            errors.append(f"{key}: as_of {raw_date!r} is not an ISO date (YYYY-MM-DD)")
            as_of = None

        if as_of and as_of > today:
            errors.append(f"{key}: as_of {as_of} is in the future")

        value = block.get("value")
        if value is None:
            warnings.append(f"{key}: value is null — nothing to publish for this component")
        else:
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                errors.append(f"{key}: value {value!r} is not a number")
                numeric = None

            rng = block.get("plausible_range")
            if numeric is not None and isinstance(rng, list) and len(rng) == 2:
                lo, hi = float(rng[0]), float(rng[1])
                if not lo <= numeric <= hi:
                    errors.append(
                        f"{key}: value {numeric} is outside the plausible range"
                        f" [{lo}, {hi}] — check the units, or widen the range if this is real"
                    )

        confidence = block.get("confidence", "observed")
        if confidence not in CONFIDENCE_LEVELS:
            errors.append(
                f"{key}: confidence {confidence!r} is not one of {list(CONFIDENCE_LEVELS)}"
            )

        current = entry(key, path)
        if current is not None and current.overdue:
            warnings.append(
                f"{key}: figure is {current.age_days} days old ({current.as_of}),"
                f" past its {current.cadence_days}-day cadence — update it"
            )

    if expected is not None:
        missing = [k for k, ref in expected.items()
                   if ref.get("manual") and k not in data["components"]]
        for key in missing:
            errors.append(f"{key}: manual component has no entry in the feeder file")

    return errors, warnings


# --- Generated provenance ---------------------------------------------------
#
# Written on every update run. This used to be prose typed into
# hormuz_history.json by hand, which meant it described whatever was true the
# day somebody wrote it: the shipped note asserted a "latest observation" of 105
# transits/wk from 2026-07-19 for a month afterwards, on a public API, while the
# index itself had moved on. A note about data that is not derived from that
# data is a scheduled lie.


def _fmt(value: float) -> str:
    """Trim a float for prose: 0.25 stays 0.25, 616.0 becomes 616."""
    if value == int(value):
        return str(int(value))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _vs_baseline(current: float, baseline: float, invert: bool) -> str:
    if not baseline:
        return ""
    if invert:
        # A decline is the signal, so "17% of baseline" reads the way the
        # component is actually interpreted; "-83%" makes the reader do the work.
        return f"{current / baseline * 100:.0f}% of baseline"
    return f"{(current - baseline) / baseline * 100:+.0f}% vs baseline"


def build_source_notes(snapshot, baseline_window: str,
                       path: str = MANUAL_PATH) -> dict[str, str]:
    """One provenance sentence per component, derived from live state.

    `snapshot` is a scoring.CompositeResult. Every figure in the output is read
    from it or from the feeder file, so a note cannot drift from the number it
    describes.
    """
    notes: dict[str, str] = {}

    for cr in snapshot.components:
        comp = cr.component
        unit = f" {comp.unit}" if comp.unit else ""
        current = entry(comp.key, path)

        parts = [
            f"Baseline {_fmt(cr.baseline_value)}{unit}"
            f" ({comp.source}, {baseline_window})."
        ]

        if cr.current_value is not None:
            # Attribute the value to a source only when the feeder is where it
            # actually came from. A fallback entry did not produce the live
            # PortWatch figure standing next to it, and crediting it would be a
            # false citation.
            attribution = ""
            if current and current.role == "primary" and current.source:
                # "per X" rather than "(X)": sources carry their own
                # parentheticals, and "(Marsh (Marcus Baker, ...))" is unreadable.
                attribution = f" per {current.source}"
            when = f" as of {cr.last_updated}" if cr.last_updated else ""
            delta = _vs_baseline(cr.current_value, cr.baseline_value, comp.invert)
            parts.append(
                f"Latest {_fmt(cr.current_value)}{unit}{when}{attribution}"
                f"{', ' + delta if delta else ''}."
            )

        if current and current.note:
            parts.append(current.note.rstrip(".") + ".")

        if current is None and not comp.manual:
            parts.append("Fetched automatically.")
        elif current and current.role == "fallback":
            parts.append(
                "Fetched automatically; the hand-entered figure is held only as a"
                " fallback for feed outages."
            )

        if current and current.history_reconstructed:
            parts.append(
                "Weekly values before the 2026-07-26 revision were re-anchored from a"
                " previously published series rather than measured."
            )
        if current and current.confidence != "observed":
            parts.append(f"Current figure is {current.confidence}, not observed.")

        if cr.stale:
            parts.append("Currently flagged stale.")

        notes[comp.key] = " ".join(parts)

    return notes


def reconstructed_series(path: str = MANUAL_PATH) -> list[str]:
    """Components whose published weekly series is not fully observed.

    Derived from the feeder rather than hardcoded, so retiring the caveat is a
    one-field edit by whoever actually establishes the real series — not a code
    change nobody remembers to make.
    """
    return sorted(
        key for key, current in entries(path).items() if current.history_reconstructed
    )

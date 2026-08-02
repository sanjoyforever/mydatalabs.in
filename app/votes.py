"""Community sentiment voting — the Public Perception Index.

Readers rate how severe the situation *feels* to them from 1 to 10. The mean
rating is stretched onto the same 100–200 presentation scale the model score
uses, so a rating of 1 lands on the calm baseline and 10 on maximum stress:

    index = 100 + (mean_rating - 1) / 9 * 100

The two cards sit side by side on the dashboard, which only works because they
share a scale: publishing the crowd number on a scale of its own would destroy
the one interesting thing about a sentiment reading next to a model, which is
the distance between them.

The ballot is continuous rather than ten discrete steps, because it is cast by
dragging a marker along the published gauge: a handle that jumped between ten
stops would fight the gesture, and "somewhere between 6 and 7" is a real thing
to mean. It is stored to two decimals — enough that the drag feels free, and
coarse enough not to pretend a reader placed a marker to the pixel. Ratings are
still *described* in tens, because people have a shared intuition for
out-of-ten and none at all for "68 out of 100"; the decile a rating falls in is
what gets a name, and the histogram keeps its ten buckets.


Identity, and why there is no personal data here
------------------------------------------------

Uniqueness is enforced on two independent layers, neither of which stores
anything that identifies a person:

1. **Anonymous voter token.** The browser generates a random UUID (no
   fingerprinting, no derivation from device characteristics) and keeps it in
   ``localStorage``. It is sent with the vote and stored only as
   ``sha256(pepper + token)``. It carries no meaning outside this table and is
   not linked to any other identifier. This is what makes a vote changeable:
   re-voting updates the existing row rather than stacking a second one.

2. **Coarse abuse ceiling.** Clearing ``localStorage`` yields a new token, so a
   determined voter could ballot-stuff. A per-week limit is applied against
   ``sha256(weekly_salt + ip + user_agent)`` — a keyed digest whose salt is
   derived from the week, so it cannot be correlated across weeks, and from
   which the IP cannot be recovered. The IP and user agent themselves are never
   written to disk. The limit is deliberately loose (``MAX_VOTES_PER_ORIGIN``)
   because that hash is shared by everyone behind one NAT or carrier gateway;
   blocking the second voter in an office is a worse failure than admitting a
   handful of duplicates into an opinion poll.

Under GDPR the ``localStorage`` entry is strictly necessary for the function
the visitor explicitly asked for (casting and amending a vote), so it needs no
consent banner, and it is stated in the vote block regardless. No cookie is
set, no profile is built, nothing is shared with a third party, and nothing
stored can be traced back to an individual — so there is no personal data to
export or erase on request. A visitor who wants their vote gone can withdraw it
from the same block, which deletes the row.
"""
from __future__ import annotations

import hashlib
import hmac
import os
from datetime import date, timedelta

from app import db, scoring

INDEX_KEY = "hormuz"

# How many votes one coarse origin hash may cast in a week. See the module
# docstring: this shares a value across everyone behind a single NAT.
MAX_VOTES_PER_ORIGIN = int(os.environ.get("MAX_VOTES_PER_ORIGIN", "25"))

# Minimum ballots before the public number is shown.
MIN_VOTES_TO_PUBLISH = int(os.environ.get("MIN_VOTES_TO_PUBLISH", "1"))

# How far back the perception series is read for the trend chart.
HISTORY_WEEKS = int(os.environ.get("SENTIMENT_HISTORY_WEEKS", "104"))

RATING_MIN = 1
RATING_MAX = 10

# Resolution of one ballot. Two decimals over a span of nine is ~900 distinct
# positions, which no drag can distinguish from continuous.
RATING_DP = 2

SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS community_votes (
        id           BIGSERIAL PRIMARY KEY,
        index_key    TEXT        NOT NULL,
        week_start   DATE        NOT NULL,
        rating       NUMERIC(4,2) NOT NULL CHECK (rating BETWEEN 1 AND 10),
        voter_hash   TEXT        NOT NULL,
        origin_hash  TEXT        NOT NULL,
        created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT community_votes_unique_voter
            UNIQUE (index_key, week_start, voter_hash)
    )
    """,
    # Widening for databases created when the ballot was ten whole steps. The
    # old values are already valid on the new type (7 means 7.00), so this is a
    # type change with no rescale and no data loss. Guarded on the current type
    # because an unguarded ALTER rewrites the whole table on every boot.
    """
    DO $$
    BEGIN
        IF EXISTS (
            SELECT 1 FROM information_schema.columns
             WHERE table_name = 'community_votes'
               AND column_name = 'rating'
               AND data_type <> 'numeric'
        ) THEN
            ALTER TABLE community_votes
                ALTER COLUMN rating TYPE NUMERIC(4,2);
        END IF;
    END $$
    """,
    """
    CREATE INDEX IF NOT EXISTS community_votes_week_idx
        ON community_votes (index_key, week_start)
    """,
    """
    CREATE INDEX IF NOT EXISTS community_votes_origin_idx
        ON community_votes (index_key, week_start, origin_hash)
    """,
]


def _pepper() -> bytes:
    return os.environ.get("VOTE_PEPPER", "mydatalabs-local-dev-pepper").encode()


def hash_voter_token(token: str) -> str:
    """Stable, non-reversible handle for one browser's random vote token."""
    return hashlib.sha256(_pepper() + token.encode()).hexdigest()


def hash_origin(ip: str, user_agent: str, week_start: str) -> str:
    """Weekly-salted digest of request origin, used only to cap ballot stuffing.

    The salt is keyed on the week, so two hashes from different weeks cannot be
    matched to each other. Neither the IP nor the user agent is stored.
    """
    salt = hmac.new(_pepper(), week_start.encode(), hashlib.sha256).digest()
    return hmac.new(salt, f"{ip}|{user_agent}".encode(), hashlib.sha256).hexdigest()


def current_week_start(today: date | None = None) -> str:
    """Monday of the current week — the same weekly bucket the index uses."""
    d = today or date.today()
    return (d - timedelta(days=d.weekday())).isoformat()


def to_index(mean_rating: float) -> float:
    """Map a 1–10 mean onto the 100–200 index presentation scale."""
    span = scoring.SCALE_MAX - scoring.SCALE_MIN
    fraction = (mean_rating - RATING_MIN) / (RATING_MAX - RATING_MIN)
    return round(scoring.SCALE_MIN + fraction * span, 1)


def _empty(week_start: str) -> dict:
    return {
        "available": db.is_configured(),
        "week_start": week_start,
        "votes": 0,
        "index": None,
        "level_label": None,
        "level_status": None,
        "scale_pct": None,
        "mean_rating": None,
        # Ten buckets, one per decile of the continuous rating.
        "distribution": [0] * (RATING_MAX - RATING_MIN + 1),
        "min_votes": MIN_VOTES_TO_PUBLISH,
        "your_vote": None,
    }


def _decorate(result: dict) -> dict:
    """Attach the label/position fields the gauge needs."""
    if result["index"] is not None:
        label, status = scoring.default_level(result["index"])
        result["level_label"] = label
        result["level_status"] = status
        result["scale_pct"] = round(scoring.scale_pct(result["index"]), 2)
    return result


def _summarise(cur, week_start: str, voter_hash: str | None) -> dict:
    """Build the summary on an existing cursor.

    Kept separate from ``get_summary`` so a write and the summary it returns
    share one connection. Each new connection to the Neon endpoint costs a TLS
    handshake; opening a second one just to re-read what we only just wrote
    doubled the latency the voter waits through.
    """
    summary = _empty(week_start)
    # Grouped by decile for the histogram, but carrying the untruncated sum too,
    # so the published mean keeps the precision the ballots were cast with.
    cur.execute(
        """
        SELECT ROUND(rating)::int AS bucket, COUNT(*), SUM(rating)
          FROM community_votes
         WHERE index_key = %s AND week_start = %s
         GROUP BY bucket
        """,
        (INDEX_KEY, week_start),
    )
    rows = cur.fetchall()
    counts = {int(bucket): int(n) for bucket, n, _ in rows}
    rating_sum = sum(float(total) for _, _, total in rows)

    if voter_hash:
        cur.execute(
            """
            SELECT rating FROM community_votes
             WHERE index_key = %s AND week_start = %s AND voter_hash = %s
            """,
            (INDEX_KEY, week_start, voter_hash),
        )
        row = cur.fetchone()
        summary["your_vote"] = round(float(row[0]), RATING_DP) if row else None

    total = sum(counts.values())
    summary["votes"] = total
    summary["distribution"] = [
        counts.get(r, 0) for r in range(RATING_MIN, RATING_MAX + 1)
    ]
    if total >= MIN_VOTES_TO_PUBLISH:
        mean = rating_sum / total
        summary["mean_rating"] = round(mean, RATING_DP)
        summary["index"] = to_index(mean)
    return _decorate(summary)


def get_summary(week_start: str | None = None, voter_hash: str | None = None) -> dict:
    """Aggregate for one week. Never raises — a dead DB disables the feature."""
    week_start = week_start or current_week_start()
    if not db.is_configured():
        return _empty(week_start)

    try:
        db.ensure_schema(SCHEMA)
        with db.cursor() as cur:
            return _summarise(cur, week_start, voter_hash)
    except Exception:
        # Sentiment is a decoration on a data page. It must never be the reason
        # the index itself fails to render.
        summary = _empty(week_start)
        summary["available"] = False
        return summary


def get_history(weeks: int = HISTORY_WEEKS) -> list[dict]:
    """Weekly perception series, oldest first. Never raises.

    Rows are never deleted on a week roll-over, so the table already holds the
    whole history — this is the read that turns it into a series. Weeks that
    did not clear ``MIN_VOTES_TO_PUBLISH`` are returned with ``index: None``
    rather than being dropped: the chart needs to draw a gap there, and a
    thinly-voted week silently becoming a plotted point would be a lie.
    """
    if not db.is_configured():
        return []
    try:
        db.ensure_schema(SCHEMA)
        with db.cursor() as cur:
            cur.execute(
                """
                SELECT week_start, COUNT(*), AVG(rating)
                  FROM community_votes
                 WHERE index_key = %s
                 GROUP BY week_start
                 ORDER BY week_start DESC
                 LIMIT %s
                """,
                (INDEX_KEY, weeks),
            )
            rows = cur.fetchall()
    except Exception:
        return []

    series = []
    for week_start, total, mean in reversed(rows):
        total = int(total)
        mean = float(mean)
        published = total >= MIN_VOTES_TO_PUBLISH
        series.append({
            "week_start": week_start.isoformat(),
            "votes": total,
            "mean_rating": round(mean, 2) if published else None,
            "index": to_index(mean) if published else None,
        })
    return series


class VoteRejected(Exception):
    """Raised when a ballot is refused for a reason the visitor should see."""


def cast_vote(rating: float, voter_hash: str, origin_hash: str,
              week_start: str | None = None) -> dict:
    """Record or amend one vote, then return the refreshed summary."""
    if not db.is_configured():
        raise VoteRejected("Voting is not available right now.")
    try:
        rating = round(float(rating), RATING_DP)
    except (TypeError, ValueError):
        rating = None
    if rating is None or not RATING_MIN <= rating <= RATING_MAX:
        raise VoteRejected(
            f"Rating must be a number from {RATING_MIN} to {RATING_MAX}."
        )

    week_start = week_start or current_week_start()
    db.ensure_schema(SCHEMA)

    with db.cursor() as cur:
        # Count only *other* tokens against the ceiling, so a visitor amending
        # their own vote is never blocked by their own earlier ballot.
        cur.execute(
            """
            SELECT COUNT(*) FROM community_votes
             WHERE index_key = %s AND week_start = %s
               AND origin_hash = %s AND voter_hash <> %s
            """,
            (INDEX_KEY, week_start, origin_hash, voter_hash),
        )
        if cur.fetchone()[0] >= MAX_VOTES_PER_ORIGIN:
            raise VoteRejected(
                "This network has reached its vote limit for the week."
            )

        cur.execute(
            """
            INSERT INTO community_votes
                   (index_key, week_start, rating, voter_hash, origin_hash)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT ON CONSTRAINT community_votes_unique_voter
            DO UPDATE SET rating      = EXCLUDED.rating,
                          origin_hash = EXCLUDED.origin_hash,
                          updated_at  = now()
            """,
            (INDEX_KEY, week_start, rating, voter_hash, origin_hash),
        )

        return _summarise(cur, week_start, voter_hash)


def withdraw_vote(voter_hash: str, week_start: str | None = None) -> dict:
    """Delete this browser's vote for the week (the erasure path in the UI)."""
    if not db.is_configured():
        raise VoteRejected("Voting is not available right now.")
    week_start = week_start or current_week_start()
    db.ensure_schema(SCHEMA)
    with db.cursor() as cur:
        cur.execute(
            """
            DELETE FROM community_votes
             WHERE index_key = %s AND week_start = %s AND voter_hash = %s
            """,
            (INDEX_KEY, week_start, voter_hash),
        )
        return _summarise(cur, week_start, voter_hash)

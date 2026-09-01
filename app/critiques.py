"""Reader critiques: a moderated, component-anchored objection log.

This is not a comment section. A comment box collects "this is useless"; the
form behind this module refuses to accept anything that is not a *claim* — a
verdict, the specific part of the report it is aimed at, and a reason long
enough to contain an argument. That shape is the whole design:

* it is useful to the author, because an objection arrives already attached to
  the component it disputes;
* it is publishable in context, next to that component, rather than as a heap
  at the foot of the page;
* and it is hostile to spam by construction. A promotional bot has no valid
  target key, no verdict, and no forty-character argument about the weighting
  of a fiscal sub-index. Nothing here is filtering spam so much as asking for
  something spam cannot produce.

Nothing is ever published by submission. Every row lands as ``pending`` and
becomes visible only when a human moves it, so the worst case for a submission
that defeats every check below is that one person reads it in a queue.


Why there is no website field, and no link may survive
------------------------------------------------------

Every spam-magnet comment system in existence ships a "your website" input.
There is deliberately no such field, no email is published, and no profile is
built — with no way to earn a backlink or a byline, promotional posting has no
payoff at all. That does more work than the pattern matching below.

The pattern matching still runs, because a link pasted into the body would be
rendered on a public page if it were waved through by a tired moderator.
Detection folds confusables and strips zero-width characters *before* matching,
since a domain written with Cyrillic vowels and one with a zero-width space in
the middle both defeat a naive regex while remaining perfectly clickable to a
reader. The submission is rejected rather than silently scrubbed: silent
redaction teaches a spammer to retry with a different encoding, and tells an
honest reader nothing about why their careful paragraph came back mangled.


Identity
--------

Reuses the anonymous layer built for ``votes.py`` verbatim — a random browser
token stored only as a peppered digest, plus a coarse weekly origin hash used
for nothing but a rate ceiling. No IP, user agent, or personal data is written
here either. The optional display name is free text with the same link rules
applied and a hard length cap; it is a label, not an account.
"""
from __future__ import annotations

import os
import re
import unicodedata
from datetime import date, timedelta

from app import db
from app.votes import hash_origin, hash_voter_token  # one identity layer, not two

__all__ = [
    "CritiqueRejected", "REPORTS", "VERDICTS", "STATUSES", "PUBLIC_STATUSES",
    "SCHEMA", "targets_for", "target_label", "is_valid_target", "find_link",
    "submit", "validate", "get_published", "get_queue", "status_counts",
    "moderate", "delete", "current_week_start", "hash_origin",
    "hash_voter_token",
]

# --- What may be critiqued -------------------------------------------------
# Target keys are a closed whitelist per report. The per-component half is
# generated from the index definitions themselves, so a component renamed or
# added in app/indices/* cannot drift out of sync with the form.

GENERIC_TARGETS = [
    ("baseline", "The baseline period"),
    ("weighting", "How components are weighted"),
    ("conclusion", "The conclusion drawn"),
    ("data_source", "A data source"),
    ("presentation", "Charts / presentation"),
    ("other", "Something else"),
]

VERDICTS = [
    ("useful", "Useful"),
    ("partly", "Partly useful"),
    ("not_useful", "Not useful"),
    ("wrong", "Factually wrong"),
]
VERDICT_KEYS = {k for k, _ in VERDICTS}
VERDICT_LABELS = dict(VERDICTS)

STATUSES = ("pending", "published", "accepted", "rejected")
# The two a visitor may see. "accepted" additionally earns a changelog note:
# an index that changed because a reader was right is the strongest thing this
# page can show, and it should not look like an ordinary approved objection.
PUBLIC_STATUSES = ("published", "accepted")


def _index_components(module_path: str) -> list[tuple[str, str]]:
    """Component (key, label) pairs from an index module, or [] if unavailable.

    Imported lazily and defensively: the critique form is a decoration on a
    data page and must never be the reason a report fails to render.
    """
    try:
        import importlib

        module = importlib.import_module(module_path)
        return [(c.key, c.label) for c in getattr(module, "COMPONENTS", [])]
    except Exception:
        return []


REPORTS: dict[str, dict] = {
    "hormuz": {
        "label": "Hormuz Crisis Index",
        "url": "/hormuz-index",
        "module": "app.indices.hormuz",
    },
    "solvency": {
        "label": "US Solvency Index",
        "url": "/solvency-index",
        "module": "app.indices.solvency",
    },
    "aviation": {
        "label": "Airline Safety Index",
        "url": "/airline-index",
        "module": "app.indices.aviation",
    },
    "elections": {
        "label": "Lok Sabha Index",
        "url": "/lok-sabha-index",
        "module": None,  # no COMPONENTS list; generic targets only
    },
}


def targets_for(report_key: str) -> list[tuple[str, str]]:
    """Whitelisted target keys for one report: its components, then the generics."""
    report = REPORTS.get(report_key)
    if not report:
        return []
    components = _index_components(report["module"]) if report["module"] else []
    return components + GENERIC_TARGETS


def is_valid_target(report_key: str, target_key: str) -> bool:
    return any(key == target_key for key, _ in targets_for(report_key))


def target_label(report_key: str, target_key: str) -> str:
    for key, label in targets_for(report_key):
        if key == target_key:
            return label
    return target_key


# --- Limits ----------------------------------------------------------------

# The minimum is the load-bearing one. It is what turns "useless" into a
# sentence containing a reason, and no bot fills it with anything coherent.
MIN_BODY = int(os.environ.get("CRITIQUE_MIN_BODY", "40"))
MAX_BODY = int(os.environ.get("CRITIQUE_MAX_BODY", "600"))
MAX_REMEDY = int(os.environ.get("CRITIQUE_MAX_REMEDY", "300"))
MAX_NAME = 30

# Submissions allowed per coarse origin hash per week. Lower than the vote
# ceiling: writing a considered objection is not something an honest reader
# does ten times a day, and this hash is shared across a NAT.
MAX_PER_ORIGIN = int(os.environ.get("CRITIQUE_MAX_PER_ORIGIN", "5"))

# A form filled and submitted faster than this was not read by a human.
MIN_FILL_SECONDS = int(os.environ.get("CRITIQUE_MIN_FILL_SECONDS", "5"))


class CritiqueRejected(Exception):
    """Submission refused. The message is shown to the visitor verbatim."""


# --- Link and contact detection --------------------------------------------

_ZERO_WIDTH = dict.fromkeys(
    [0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF, 0x00AD, 0x180E], None
)

# Latin letters that Cyrillic and Greek supply visually identical twins for.
# Folded before matching so a homoglyph domain is caught by the ordinary URL
# patterns rather than needing rules of its own.
_CONFUSABLES = str.maketrans({
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c",
    "у": "y", "х": "x", "і": "i", "ѕ": "s", "ј": "j",
    "ӏ": "l", "ԁ": "d", "һ": "h", "в": "b", "м": "m",
    "н": "h", "т": "t", "к": "k",
    "α": "a", "ε": "e", "ο": "o", "ρ": "p", "τ": "t",
    "ν": "v", "κ": "k", "ι": "i",
})

_SCHEME_RE = re.compile(r"\b(?:h\W{0,3}t\W{0,3}t\W{0,3}p|ftp|hxxp)s?\s*:?\s*/{0,2}", re.I)
_WWW_RE = re.compile(r"\bwww\s*[.\[(]", re.I)
_EMAIL_RE = re.compile(
    r"[a-z0-9._%+-]+\s*(?:@|\(at\)|\[at\]|\sat\s)\s*[a-z0-9.-]+\s*\.\s*[a-z]{2,}", re.I
)
_HANDLE_RE = re.compile(r"(?<![a-z0-9])@[a-z0-9_]{3,}", re.I)
_MESSENGER_RE = re.compile(
    r"\b(?:t\.me|wa\.me|telegram|whatsapp|discord\.gg|bit\.ly|tinyurl)\b", re.I
)
# Phone-shaped: 8+ digits allowing the usual separators, so "+91 98765 43210"
# is caught. Anchored on a digit at each end so it does not swallow prose.
_PHONE_RE = re.compile(r"(?:\+\d{1,3}[\s.-]*)?(?:\d[\s.()-]*){8,}\d")

_TLDS = (
    "com|net|org|edu|gov|info|biz|io|co|in|uk|us|de|fr|nl|ru|cn|jp|br|au|ca|"
    "xyz|top|shop|site|online|live|app|dev|me|ly|gg|tv|cc|club|store|vip|"
    "link|click|buzz|icu|pro|tk|ml|ga|cf|su|ws|to|sh|ai|be|it|es|pl|se|ch"
)
# A dot — or a written-out, bracketed or spaced substitute for one — between a
# label and a known TLD. This is what catches "example dot com".
_DOMAIN_RE = re.compile(
    r"\b[a-z0-9][a-z0-9-]{0,62}\s*"
    r"(?:\.|\(\s*dot\s*\)|\[\s*dot\s*\]|\{\s*dot\s*\}|\s+dot\s+|\s+punto\s+)\s*"
    r"(?:" + _TLDS + r")\b",
    re.I,
)

_LINK_PATTERNS = [
    (_SCHEME_RE, "a web address"),
    (_WWW_RE, "a web address"),
    (_DOMAIN_RE, "a domain name"),
    (_EMAIL_RE, "an email address"),
    (_MESSENGER_RE, "a messaging or shortener link"),
    (_HANDLE_RE, "an @handle"),
    (_PHONE_RE, "a phone number"),
]


def fold_for_detection(text: str) -> str:
    """Normalise away every cheap way of hiding a link, for matching only.

    The value returned is never stored or displayed — the reader's original
    text is kept verbatim. This exists purely so one set of patterns can see
    through width, accent, homoglyph and zero-width tricks at once.
    """
    folded = unicodedata.normalize("NFKC", text)
    folded = folded.translate(_ZERO_WIDTH)
    folded = folded.translate(_CONFUSABLES)
    # Strip combining marks: an accented letter mid-domain renders as a working
    # address but reads as a different codepoint to the patterns above.
    folded = "".join(
        ch for ch in unicodedata.normalize("NFD", folded)
        if not unicodedata.combining(ch)
    )
    return folded


def find_link(text: str) -> str | None:
    """Describe the first contact detail found, or None. See module docstring."""
    folded = fold_for_detection(text)
    for pattern, description in _LINK_PATTERNS:
        if pattern.search(folded):
            return description
    return None


def reject_links(text: str, field: str) -> None:
    found = find_link(text)
    if found:
        raise CritiqueRejected(
            f"Your {field} looks like it contains {found}. Critiques are "
            f"published without links or contact details of any kind — please "
            f"describe the source in words instead."
        )


# --- Schema ----------------------------------------------------------------

SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS report_critiques (
        id            BIGSERIAL PRIMARY KEY,
        report_key    TEXT        NOT NULL,
        target_key    TEXT        NOT NULL,
        verdict       TEXT        NOT NULL,
        body          TEXT        NOT NULL,
        remedy        TEXT,
        display_name  TEXT,
        voter_hash    TEXT        NOT NULL,
        origin_hash   TEXT        NOT NULL,
        week_start    DATE        NOT NULL,
        status        TEXT        NOT NULL DEFAULT 'pending',
        response      TEXT,
        changelog     TEXT,
        upvotes       INTEGER     NOT NULL DEFAULT 0,
        created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
        moderated_at  TIMESTAMPTZ,
        CONSTRAINT report_critiques_status_valid
            CHECK (status IN ('pending', 'published', 'accepted', 'rejected'))
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS report_critiques_public_idx
        ON report_critiques (report_key, status, created_at DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS report_critiques_queue_idx
        ON report_critiques (status, created_at DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS report_critiques_origin_idx
        ON report_critiques (origin_hash, week_start)
    """,
]


def current_week_start(today: date | None = None) -> str:
    """Monday of the current week — the bucket the rate ceiling counts against."""
    d = today or date.today()
    return (d - timedelta(days=d.weekday())).isoformat()


# --- Submission ------------------------------------------------------------

def _clean(text: str | None, limit: int) -> str:
    """Collapse runaway whitespace and trim. Newlines survive, runs of them do not."""
    if not text:
        return ""
    text = unicodedata.normalize("NFC", str(text))
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()[:limit]


def validate(payload: dict, report_key: str) -> dict:
    """Check one submission and return the row fields, or raise CritiqueRejected."""
    if report_key not in REPORTS:
        raise CritiqueRejected("Unknown report.")

    verdict = (payload.get("verdict") or "").strip()
    if verdict not in VERDICT_KEYS:
        raise CritiqueRejected("Choose a verdict.")

    target_key = (payload.get("target") or "").strip()
    if not is_valid_target(report_key, target_key):
        raise CritiqueRejected("Choose which part of the report you mean.")

    body = _clean(payload.get("body"), MAX_BODY)
    if len(body) < MIN_BODY:
        raise CritiqueRejected(
            f"Please give a reason of at least {MIN_BODY} characters — what "
            f"specifically is wrong, and why."
        )
    reject_links(body, "reason")

    remedy = _clean(payload.get("remedy"), MAX_REMEDY)
    if remedy:
        reject_links(remedy, "suggested fix")

    display_name = _clean(payload.get("display_name"), MAX_NAME)
    if display_name:
        reject_links(display_name, "name")

    return {
        "report_key": report_key,
        "target_key": target_key,
        "verdict": verdict,
        "body": body,
        "remedy": remedy or None,
        "display_name": display_name or None,
    }


def check_honeypot(payload: dict) -> None:
    """Two cheap bot filters that cost an honest visitor nothing.

    The honeypot field is hidden in CSS and labelled to look like a website
    input — the one thing a link spammer is looking for and a human never
    sees. ``elapsed`` is the seconds between the form rendering and its
    submission, sent by the page; a form returned faster than a person can
    read the question was not filled in by one.
    """
    if (payload.get("website") or "").strip():
        raise CritiqueRejected("Submission rejected.")
    try:
        elapsed = float(payload.get("elapsed", 0))
    except (TypeError, ValueError):
        elapsed = 0.0
    if elapsed < MIN_FILL_SECONDS:
        raise CritiqueRejected("That was submitted very quickly — please try again.")


def submit(payload: dict, report_key: str, *, voter_hash: str, origin_hash: str) -> dict:
    """Validate and store one critique as pending. Never publishes anything."""
    check_honeypot(payload)
    fields = validate(payload, report_key)

    if not db.is_configured():
        raise CritiqueRejected("Feedback is not available right now.")

    week_start = current_week_start()
    db.ensure_schema(SCHEMA)
    with db.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM report_critiques "
            " WHERE origin_hash = %s AND week_start = %s",
            (origin_hash, week_start),
        )
        if (cur.fetchone() or [0])[0] >= MAX_PER_ORIGIN:
            raise CritiqueRejected(
                "You have sent several critiques this week already. Thank you "
                "— please come back next week."
            )
        cur.execute(
            """
            INSERT INTO report_critiques
                (report_key, target_key, verdict, body, remedy, display_name,
                 voter_hash, origin_hash, week_start)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                fields["report_key"], fields["target_key"], fields["verdict"],
                fields["body"], fields["remedy"], fields["display_name"],
                voter_hash, origin_hash, week_start,
            ),
        )
        new_id = cur.fetchone()[0]

    return {"ok": True, "id": new_id, "status": "pending"}


# --- Reads -----------------------------------------------------------------

_PUBLIC_COLUMNS = [
    "id", "report_key", "target_key", "verdict", "body", "remedy",
    "display_name", "status", "response", "changelog", "upvotes", "created_at",
]
_QUEUE_COLUMNS = _PUBLIC_COLUMNS + ["week_start", "moderated_at"]


def _decorate(row: dict) -> dict:
    row["target_label"] = target_label(row["report_key"], row["target_key"])
    row["verdict_label"] = VERDICT_LABELS.get(row["verdict"], row["verdict"])
    row["report_label"] = REPORTS.get(row["report_key"], {}).get(
        "label", row["report_key"]
    )
    return row


def get_published(report_key: str) -> list[dict]:
    """Approved critiques for one report, newest first. Never raises.

    Like the sentiment block, this is a decoration on a data page: a database
    that is down must cost the reader the objections section, not the report.
    """
    if not db.is_configured():
        return []
    columns = ", ".join(_PUBLIC_COLUMNS)
    try:
        db.ensure_schema(SCHEMA)
        with db.cursor() as cur:
            cur.execute(
                f"SELECT {columns} FROM report_critiques"
                " WHERE report_key = %s AND status = ANY(%s)"
                " ORDER BY created_at DESC",
                (report_key, list(PUBLIC_STATUSES)),
            )
            rows = [dict(zip(_PUBLIC_COLUMNS, r)) for r in cur.fetchall()]
    except Exception:
        return []
    return [_decorate(row) for row in rows]


def get_queue(status: str | None = "pending", limit: int = 200) -> list[dict]:
    """Critiques for the moderation page. Raises — the admin wants to know."""
    db.ensure_schema(SCHEMA)
    columns = ", ".join(_QUEUE_COLUMNS)
    where, params = "", []
    if status:
        where = " WHERE status = %s"
        params.append(status)
    params.append(limit)
    with db.cursor() as cur:
        cur.execute(
            f"SELECT {columns} FROM report_critiques{where}"
            " ORDER BY created_at DESC LIMIT %s",
            params,
        )
        rows = [dict(zip(_QUEUE_COLUMNS, r)) for r in cur.fetchall()]
    return [_decorate(row) for row in rows]


def status_counts() -> dict[str, int]:
    db.ensure_schema(SCHEMA)
    with db.cursor() as cur:
        cur.execute("SELECT status, count(*) FROM report_critiques GROUP BY status")
        counts = {status: 0 for status in STATUSES}
        counts.update({row[0]: row[1] for row in cur.fetchall()})
        return counts


def moderate(critique_id: int, *, status: str, response: str | None = None,
             changelog: str | None = None) -> None:
    """Set the status and author response for one critique.

    The author's response is *not* passed through the link check: it is written
    by the site owner in an authenticated page, and a legitimate reply may well
    need to cite a source.
    """
    if status not in STATUSES:
        raise ValueError(f"Unknown status: {status}")
    db.ensure_schema(SCHEMA)
    with db.cursor() as cur:
        cur.execute(
            """
            UPDATE report_critiques
               SET status = %s,
                   response = %s,
                   changelog = %s,
                   moderated_at = now()
             WHERE id = %s
            """,
            (status, (response or "").strip() or None,
             (changelog or "").strip() or None, critique_id),
        )


def delete(critique_id: int) -> None:
    """Hard-delete one row. For spam that should not sit in the table at all."""
    db.ensure_schema(SCHEMA)
    with db.cursor() as cur:
        cur.execute("DELETE FROM report_critiques WHERE id = %s", (critique_id,))

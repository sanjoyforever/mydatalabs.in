"""
tracker_schema.py
-----------------
Canonical schema for every CVoter daily tracker series.

CVoter's homepage chart bundle (wp-content/themes/Cvoter/lib/js/charts/chart.js)
builds each Highstock chart by fetching one JSON file *per answer option*:

    https://cvoterindia.com/chartdata/<chart_prefix><option_index>.json

e.g. tracker 6 ("What are your views about today's India?") is five separate
series -- t140 .. t144 -- one for each answer option. The previous scraper only
read t140 and stored it under the generic label "Index Value", which silently
discarded 34 of the 41 available series and mislabelled the seven it kept.

This module holds the full option-level schema plus the political weighting
applied to each option when computing the composite sentiment index.

Weighting convention
--------------------
Each option carries:

    polarity : float in [-1, +1]
        Direction of the option's effect on incumbent (NDA) support.
        +1 = strongly pro-incumbent, -1 = strongly anti-incumbent, 0 = neutral.
    weight : float >= 0
        Salience multiplier -- how much a point of this option's vote share
        moves political preference relative to other options in the same
        tracker. Options describing simultaneous personal *and* national
        distress (e.g. "My life & the country both are in a poor state") and
        cost-of-living distress carry the heaviest weights, because these are
        the strongest documented anti-incumbency drivers in Indian national
        elections.

Tracker-level weights (TRACKER_WEIGHTS) then combine the per-tracker net scores
into one composite index. Media Usage carries weight 0.0: it measures channel
consumption, not political sentiment, so it is retained as context only.
"""

# ---------------------------------------------------------------------------
# Option-level schema
# ---------------------------------------------------------------------------
# Labels are transcribed verbatim from CVoter's chart.js `names` array, with
# stray whitespace stripped. Order matters: list index == endpoint suffix.

TRACKER_SCHEMA = {
    1: {
        "name": "National Issues",
        "chart_prefix": "t16",
        "question": (
            "There are many problems that our country is facing today. "
            "Which one according to you is the most important problem?"
        ),
        "kind": "issue_salience",
        "options": [
            # label, polarity, weight
            ("Corruption",                     -1.00, 1.00),
            ("Unemployment",                   -1.00, 1.50),
            ("Familiy Income Poverty",         -1.00, 1.20),
            ("Rising Prices",                  -1.00, 1.50),
            ("Electricity Road Water",         -1.00, 0.80),
            ("Terror Attacks",                 +1.00, 0.90),
            ("Epidemics such as Corona etc.",  -0.50, 0.60),
            ("Other Issues",                    0.00, 0.00),
            ("Don't Know/Can't Say",            0.00, 0.00),
        ],
    },
    2: {
        "name": "Quality of Life Index",
        "chart_prefix": "t12",
        "question": "In last one year your living standard",
        "kind": "retrospective",
        "options": [
            ("Improved",                        +1.00, 1.30),
            ("Remained the same",                0.00, 0.20),
            ("Deteriorated",                    -1.00, 1.40),
            ("Don't Know/Can't Say",             0.00, 0.00),
        ],
    },
    3: {
        "name": "Index of Income Expenditure",
        "chart_prefix": "t26",
        "question": "In the last one year; your personal income",
        "kind": "retrospective",
        "options": [
            ("Income increased but the expenditure went up as well",              +0.20, 0.60),
            ("Income remained the same while expenditure went up",                -0.70, 1.10),
            ("Income went down while the expenditure went up",                    -1.00, 1.50),
            ("Income increased and the expenditure went down or remained the same", +1.00, 1.20),
            ("Income went down, expenditure remained the same",                   -0.80, 1.10),
            ("Income & expenditure both are same",                                 0.00, 0.20),
            ("Others/Don't Know/Can't Say",                                        0.00, 0.00),
        ],
    },
    4: {
        "name": "Index of Inflation",
        "chart_prefix": "t27",
        "question": "How do you compare your current daily expenses to that of last year?",
        "kind": "retrospective",
        "options": [
            ("Current expenses gone up; but still manageable",       -0.30, 0.80),
            ("Current expenses have become difficult to manage",     -1.00, 1.60),
            ("Current expenses have gone down",                      +1.00, 1.00),
            ("Others/DK/CS",                                          0.00, 0.00),
        ],
    },
    5: {
        "name": "Index of Optimism",
        "chart_prefix": "t13",
        "question": "Do you feel that in the next one year, your living standard?",
        "kind": "prospective",
        "options": [
            ("Will Improve",                    +1.00, 1.50),
            ("Will remain the same",             0.00, 0.20),
            ("Will Deteriorate",                -1.00, 1.50),
            ("Don't Know/Can't Say",             0.00, 0.00),
        ],
    },
    6: {
        "name": "Self Nation",
        "chart_prefix": "t14",
        "question": "What are your views about today's India?",
        "kind": "self_nation",
        "options": [
            ("The country is moving forward but not my life",        +0.25, 0.90),
            ("The country is moving forward and my life too",        +1.00, 1.35),
            ("My life is improving but the country is in poor state", -0.25, 0.90),
            ("My life & the country both are in a poor state",       -1.00, 1.80),
            ("Don't Know/Can't Say",                                  0.00, 0.00),
        ],
    },
    7: {
        "name": "Media Usage",
        "chart_prefix": "t22",
        "question": (
            "These days in which medium are you more likely to follow "
            "politics and current affairs?"
        ),
        "kind": "media",
        "options": [
            ("TV news channels",                                0.00, 0.00),
            ("Radio",                                           0.00, 0.00),
            ("Newspapers",                                      0.00, 0.00),
            ("News magazines",                                  0.00, 0.00),
            ("Internet / social media",                         0.00, 0.00),
            ("Political rallies / gatherings",                  0.00, 0.00),
            ("Personal interaction with friends/colleagues",    0.00, 0.00),
            ("Don't Know/Can't Say",                            0.00, 0.00),
        ],
    },
}

# Relative contribution of each tracker to the composite sentiment index.
# Tracker 6 is weighted highest: it is the only item that asks respondents to
# rate personal and national trajectory simultaneously, so its distress option
# is the single most informative anti-incumbency signal in the battery.
TRACKER_WEIGHTS = {
    1: 0.90,   # issue salience
    2: 1.20,   # retrospective living standard
    3: 1.00,   # income vs expenditure
    4: 1.10,   # cost of living
    5: 1.30,   # prospective optimism
    6: 1.50,   # self vs nation  (heaviest)
    7: 0.00,   # media usage -- context only, no political polarity
}

BASE_URL = "https://cvoterindia.com/chartdata"


def iter_series():
    """
    Yields one dict per option-level series in the whole battery.

    Keys: tracker_id, tracker_name, question, kind, option_index, metric_name,
          polarity, weight, endpoint, url, column
    """
    for tracker_id, meta in TRACKER_SCHEMA.items():
        for idx, (label, polarity, weight) in enumerate(meta["options"]):
            endpoint = f"{meta['chart_prefix']}{idx}"
            yield {
                "tracker_id": tracker_id,
                "tracker_name": meta["name"],
                "question": meta["question"],
                "kind": meta["kind"],
                "option_index": idx,
                "metric_name": label.strip(),
                "polarity": polarity,
                "weight": weight,
                "endpoint": f"{endpoint}.json",
                "url": f"{BASE_URL}/{endpoint}.json",
                "column": column_name(tracker_id, label),
            }


def column_name(tracker_id, label):
    """Wide-format column name for one option series."""
    name = TRACKER_SCHEMA[tracker_id]["name"]
    return f"T{tracker_id} {name} - {label.strip()}"


def total_series_count():
    return sum(len(m["options"]) for m in TRACKER_SCHEMA.values())


# Columns the legacy model referred to as "<Tracker> - Index Value". CVoter's
# own headline index for each tracker is its *first* option series, which is
# what the old scraper happened to capture. Kept so older code and cached CSVs
# keep working while the option-level columns become the real inputs.
LEGACY_HEADLINE_COLUMNS = {
    meta["name"]: column_name(tid, meta["options"][0][0])
    for tid, meta in TRACKER_SCHEMA.items()
}


if __name__ == "__main__":
    print(f"{total_series_count()} option-level series across {len(TRACKER_SCHEMA)} trackers\n")
    for s in iter_series():
        print(f"  {s['endpoint']:<10} pol={s['polarity']:+.2f} w={s['weight']:.2f}  {s['column']}")

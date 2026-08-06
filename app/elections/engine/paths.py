"""
Canonical filesystem locations for the Lok Sabha projection engine.

In its original standalone repo every module defaulted to the relative path
"data", which only resolved when the process happened to be started from the
project root. Inside this site the engine is imported by a Flask app that runs
from anywhere (and, on Vercel, from a directory that is not the repo root), so
the default has to be absolute.

Override with LOK_SABHA_DATA_DIR if the dataset lives outside the repo — for
example on a writable volume, since the deployed filesystem is read-only and
the updater has to write.
"""

import os

# .../app/data/elections
DATA_DIR = os.environ.get(
    "LOK_SABHA_DATA_DIR",
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "data",
        "elections",
    ),
)

MASTER_CSV = os.path.join(DATA_DIR, "cvoter_daily_trackers.csv")
PROJECTIONS_CSV = os.path.join(DATA_DIR, "ideal_model_daily_projections.csv")
CATALOG_JSON = os.path.join(DATA_DIR, "cvoter_metrics_catalog.json")
CALIBRATION_JSON = os.path.join(DATA_DIR, "model_calibration.json")

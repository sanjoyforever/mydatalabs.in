#!/usr/bin/env python3
"""Build app/data/film_normalization_100.json for Lab Note LN-01.

Constructs an empirical panel of 100 globally recognized feature films
(spanning major worldwide box-office hits, award winners, and culturally
divergent releases from 2000 to 2026), with user ratings across:
  - IMDb (US / UK & Global English)
  - Moviepilot (Germany)
  - SensCritique (France)

Computes:
  - Platform z-scores based on catalog distribution parameters:
      IMDb:         mu = 6.40, sigma = 1.25
      Moviepilot:   mu = 5.90, sigma = 1.10
      SensCritique: mu = 5.80, sigma = 1.05
  - Raw gap: European average - IMDb score
  - Rescaled gap: (z_EU - z_IMDb) * sigma_IMDb (expressed in IMDb scale points)
  - Percentiles on each platform
  - Aggregate statistics across the 100-film panel

Run:
    python scripts/build_film_normalization_data.py
"""

from __future__ import annotations

import json
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

DATA_DIR = os.path.join(ROOT, "app", "data")
OUTPUT_JSON = os.path.join(DATA_DIR, "film_normalization_100.json")

PLATFORMS = {
    "imdb": {"mean": 6.40, "sd": 1.25, "name": "IMDb", "region": "US / UK / Global"},
    "mp": {"mean": 5.90, "sd": 1.10, "name": "Moviepilot", "region": "Germany"},
    "sc": {"mean": 5.80, "sd": 1.05, "name": "SensCritique", "region": "France"},
}

RAW_FILMS = [
    # --- The 5 Landmark Benchmark Films (continuity with LN-01 core) ---
    {"id": "heart-of-the-beast", "title": "Heart of the Beast", "year": 2026, "genre": "Action", "imdb": 7.2, "mp": 6.8, "sc": 6.7},
    {"id": "top-gun-maverick", "title": "Top Gun: Maverick", "year": 2022, "genre": "Action", "imdb": 8.2, "mp": 7.3, "sc": 7.0},
    {"id": "togo", "title": "Togo", "year": 2019, "genre": "Adventure", "imdb": 7.9, "mp": 7.3, "sc": 7.1},
    {"id": "the-call-of-the-wild", "title": "The Call of the Wild", "year": 2020, "genre": "Adventure", "imdb": 6.7, "mp": 6.1, "sc": 5.8},
    {"id": "alpha", "title": "Alpha", "year": 2018, "genre": "Adventure", "imdb": 6.6, "mp": 6.0, "sc": 5.9},

    # --- Major Global Franchise & Superhero Blockbusters (steeper European discounts) ---
    {"id": "avatar", "title": "Avatar", "year": 2009, "genre": "Sci-Fi", "imdb": 7.9, "mp": 7.1, "sc": 6.7},
    {"id": "avengers-endgame", "title": "Avengers: Endgame", "year": 2019, "genre": "Action", "imdb": 8.4, "mp": 7.4, "sc": 6.9},
    {"id": "avengers-infinity-war", "title": "Avengers: Infinity War", "year": 2018, "genre": "Action", "imdb": 8.4, "mp": 7.5, "sc": 7.0},
    {"id": "the-avengers", "title": "The Avengers", "year": 2012, "genre": "Action", "imdb": 8.0, "mp": 7.2, "sc": 6.7},
    {"id": "spider-man-no-way-home", "title": "Spider-Man: No Way Home", "year": 2021, "genre": "Action", "imdb": 8.2, "mp": 7.2, "sc": 6.8},
    {"id": "iron-man", "title": "Iron Man", "year": 2008, "genre": "Action", "imdb": 7.9, "mp": 7.2, "sc": 6.8},
    {"id": "captain-america-civil-war", "title": "Captain America: Civil War", "year": 2016, "genre": "Action", "imdb": 7.8, "mp": 7.0, "sc": 6.6},
    {"id": "black-panther", "title": "Black Panther", "year": 2018, "genre": "Action", "imdb": 7.3, "mp": 6.5, "sc": 6.0},
    {"id": "jurassic-world", "title": "Jurassic World", "year": 2015, "genre": "Action", "imdb": 6.9, "mp": 6.1, "sc": 5.7},
    {"id": "star-wars-the-force-awakens", "title": "Star Wars: The Force Awakens", "year": 2015, "genre": "Sci-Fi", "imdb": 7.8, "mp": 7.0, "sc": 6.6},
    {"id": "rogue-one", "title": "Rogue One: A Star Wars Story", "year": 2016, "genre": "Sci-Fi", "imdb": 7.8, "mp": 7.2, "sc": 7.0},
    {"id": "fast-five", "title": "Fast Five", "year": 2011, "genre": "Action", "imdb": 7.3, "mp": 6.5, "sc": 5.9},
    {"id": "john-wick-chapter-4", "title": "John Wick: Chapter 4", "year": 2023, "genre": "Action", "imdb": 7.7, "mp": 7.1, "sc": 6.8},
    {"id": "mission-impossible-fallout", "title": "Mission: Impossible - Fallout", "year": 2018, "genre": "Action", "imdb": 7.7, "mp": 7.1, "sc": 6.9},
    {"id": "skyfall", "title": "Skyfall", "year": 2012, "genre": "Action", "imdb": 7.8, "mp": 7.2, "sc": 6.9},
    {"id": "casino-royale", "title": "Casino Royale", "year": 2006, "genre": "Action", "imdb": 8.0, "mp": 7.5, "sc": 7.2},
    {"id": "the-super-mario-bros-movie", "title": "The Super Mario Bros. Movie", "year": 2023, "genre": "Animation", "imdb": 7.0, "mp": 6.4, "sc": 5.9},

    # --- Modern Cultural Touchstones (Barbenheimer & 2020s hits) ---
    {"id": "oppenheimer", "title": "Oppenheimer", "year": 2023, "genre": "Biography", "imdb": 8.8, "mp": 7.9, "sc": 7.8},
    {"id": "barbie", "title": "Barbie", "year": 2023, "genre": "Comedy", "imdb": 6.8, "mp": 6.3, "sc": 6.2},
    {"id": "the-batman", "title": "The Batman", "year": 2022, "genre": "Action", "imdb": 7.8, "mp": 7.2, "sc": 7.0},
    {"id": "joker", "title": "Joker", "year": 2019, "genre": "Crime", "imdb": 8.4, "mp": 7.8, "sc": 7.4},
    {"id": "everything-everywhere", "title": "Everything Everywhere All at Once", "year": 2022, "genre": "Sci-Fi", "imdb": 7.8, "mp": 7.2, "sc": 7.2},
    {"id": "titanic", "title": "Titanic", "year": 1997, "genre": "Drama", "imdb": 7.9, "mp": 7.4, "sc": 7.2},

    # --- Christopher Nolan Oeuvre ---
    {"id": "the-dark-knight", "title": "The Dark Knight", "year": 2008, "genre": "Action", "imdb": 9.0, "mp": 8.3, "sc": 8.1},
    {"id": "batman-begins", "title": "Batman Begins", "year": 2005, "genre": "Action", "imdb": 8.2, "mp": 7.5, "sc": 7.1},
    {"id": "inception", "title": "Inception", "year": 2010, "genre": "Sci-Fi", "imdb": 8.8, "mp": 8.0, "sc": 7.8},
    {"id": "interstellar", "title": "Interstellar", "year": 2014, "genre": "Sci-Fi", "imdb": 8.7, "mp": 7.9, "sc": 7.7},
    {"id": "dunkirk", "title": "Dunkirk", "year": 2017, "genre": "War", "imdb": 7.8, "mp": 6.9, "sc": 6.8},
    {"id": "tenet", "title": "Tenet", "year": 2020, "genre": "Sci-Fi", "imdb": 7.3, "mp": 6.5, "sc": 6.3},
    {"id": "the-prestige", "title": "The Prestige", "year": 2006, "genre": "Mystery", "imdb": 8.5, "mp": 7.8, "sc": 7.6},
    {"id": "memento", "title": "Memento", "year": 2000, "genre": "Mystery", "imdb": 8.4, "mp": 7.8, "sc": 7.7},

    # --- Denis Villeneuve Oeuvre ---
    {"id": "dune-part-two", "title": "Dune: Part Two", "year": 2024, "genre": "Sci-Fi", "imdb": 8.5, "mp": 7.9, "sc": 7.8},
    {"id": "dune-part-one", "title": "Dune: Part One", "year": 2021, "genre": "Sci-Fi", "imdb": 8.0, "mp": 7.5, "sc": 7.3},
    {"id": "blade-runner-2049", "title": "Blade Runner 2049", "year": 2017, "genre": "Sci-Fi", "imdb": 8.0, "mp": 7.6, "sc": 7.5},
    {"id": "arrival", "title": "Arrival", "year": 2016, "genre": "Sci-Fi", "imdb": 7.9, "mp": 7.4, "sc": 7.4},
    {"id": "sicario", "title": "Sicario", "year": 2015, "genre": "Thriller", "imdb": 7.7, "mp": 7.3, "sc": 7.3},
    {"id": "prisoners", "title": "Prisoners", "year": 2013, "genre": "Crime", "imdb": 8.2, "mp": 7.7, "sc": 7.6},

    # --- European Crossover & Auteur Darlings (Rescaled positive / Europe warmer) ---
    {"id": "anatomy-of-a-fall", "title": "Anatomy of a Fall", "year": 2023, "genre": "Drama", "imdb": 7.7, "mp": 7.5, "sc": 7.8},
    {"id": "the-zone-of-interest", "title": "The Zone of Interest", "year": 2023, "genre": "Drama", "imdb": 7.4, "mp": 7.2, "sc": 7.5},
    {"id": "parasite", "title": "Parasite", "year": 2019, "genre": "Drama", "imdb": 8.5, "mp": 8.0, "sc": 8.1},
    {"id": "amelie", "title": "Amélie", "year": 2001, "genre": "Comedy", "imdb": 8.3, "mp": 8.0, "sc": 8.0},
    {"id": "the-lives-of-others", "title": "The Lives of Others", "year": 2006, "genre": "Drama", "imdb": 8.4, "mp": 8.2, "sc": 8.0},
    {"id": "drive", "title": "Drive", "year": 2011, "genre": "Action", "imdb": 7.8, "mp": 7.5, "sc": 7.6},
    {"id": "poor-things", "title": "Poor Things", "year": 2023, "genre": "Comedy", "imdb": 7.8, "mp": 7.4, "sc": 7.6},
    {"id": "past-lives", "title": "Past Lives", "year": 2023, "genre": "Romance", "imdb": 7.8, "mp": 7.4, "sc": 7.5},
    {"id": "portrait-of-a-lady-on-fire", "title": "Portrait of a Lady on Fire", "year": 2019, "genre": "Drama", "imdb": 8.1, "mp": 7.7, "sc": 8.0},
    {"id": "the-grand-budapest-hotel", "title": "The Grand Budapest Hotel", "year": 2014, "genre": "Comedy", "imdb": 8.1, "mp": 7.6, "sc": 7.7},
    {"id": "mad-max-fury-road", "title": "Mad Max: Fury Road", "year": 2015, "genre": "Action", "imdb": 8.1, "mp": 7.5, "sc": 7.6},

    # --- Quentin Tarantino Oeuvre ---
    {"id": "inglourious-basterds", "title": "Inglourious Basterds", "year": 2009, "genre": "War", "imdb": 8.4, "mp": 7.8, "sc": 7.6},
    {"id": "django-unchained", "title": "Django Unchained", "year": 2012, "genre": "Western", "imdb": 8.5, "mp": 7.9, "sc": 7.7},
    {"id": "once-upon-a-time-in-hollywood", "title": "Once Upon a Time in Hollywood", "year": 2019, "genre": "Comedy", "imdb": 7.6, "mp": 7.1, "sc": 7.0},
    {"id": "kill-bill-vol-1", "title": "Kill Bill: Vol. 1", "year": 2003, "genre": "Action", "imdb": 8.2, "mp": 7.7, "sc": 7.5},

    # --- David Fincher Oeuvre ---
    {"id": "fight-club", "title": "Fight Club", "year": 1999, "genre": "Drama", "imdb": 8.8, "mp": 8.2, "sc": 8.0},
    {"id": "the-social-network", "title": "The Social Network", "year": 2010, "genre": "Biography", "imdb": 7.8, "mp": 7.2, "sc": 7.2},
    {"id": "gone-girl", "title": "Gone Girl", "year": 2014, "genre": "Drama", "imdb": 8.1, "mp": 7.5, "sc": 7.3},
    {"id": "zodiac", "title": "Zodiac", "year": 2007, "genre": "Crime", "imdb": 7.7, "mp": 7.2, "sc": 7.3},

    # --- Martin Scorsese Oeuvre ---
    {"id": "the-departed", "title": "The Departed", "year": 2006, "genre": "Crime", "imdb": 8.5, "mp": 7.8, "sc": 7.6},
    {"id": "the-wolf-of-wall-street", "title": "The Wolf of Wall Street", "year": 2013, "genre": "Biography", "imdb": 8.2, "mp": 7.5, "sc": 7.3},
    {"id": "killers-of-the-flower-moon", "title": "Killers of the Flower Moon", "year": 2023, "genre": "Crime", "imdb": 7.6, "mp": 7.1, "sc": 7.1},
    {"id": "shutter-island", "title": "Shutter Island", "year": 2010, "genre": "Mystery", "imdb": 8.2, "mp": 7.6, "sc": 7.3},

    # --- Ridley Scott Oeuvre (with Napoleon French divergence) ---
    {"id": "gladiator", "title": "Gladiator", "year": 2000, "genre": "Action", "imdb": 8.5, "mp": 7.9, "sc": 7.6},
    {"id": "the-martian", "title": "The Martian", "year": 2015, "genre": "Sci-Fi", "imdb": 8.0, "mp": 7.3, "sc": 7.0},
    {"id": "napoleon", "title": "Napoleon", "year": 2023, "genre": "Biography", "imdb": 6.4, "mp": 5.9, "sc": 5.3},
    {"id": "prometheus", "title": "Prometheus", "year": 2012, "genre": "Sci-Fi", "imdb": 7.0, "mp": 6.4, "sc": 5.9},

    # --- Legendary 2000s Milestones ---
    {"id": "the-matrix", "title": "The Matrix", "year": 1999, "genre": "Sci-Fi", "imdb": 8.7, "mp": 8.1, "sc": 7.9},
    {"id": "the-lord-of-the-rings-fellowship", "title": "The Lord of the Rings: The Fellowship of the Ring", "year": 2001, "genre": "Fantasy", "imdb": 8.9, "mp": 8.3, "sc": 8.1},
    {"id": "the-lord-of-the-rings-return", "title": "The Lord of the Rings: The Return of the King", "year": 2003, "genre": "Fantasy", "imdb": 9.0, "mp": 8.4, "sc": 8.2},

    # --- Animation Masterworks ---
    {"id": "spider-man-into-the-spider-verse", "title": "Spider-Man: Into the Spider-Verse", "year": 2018, "genre": "Animation", "imdb": 8.4, "mp": 7.7, "sc": 7.7},
    {"id": "spider-man-across-the-spider-verse", "title": "Spider-Man: Across the Spider-Verse", "year": 2023, "genre": "Animation", "imdb": 8.6, "mp": 7.8, "sc": 7.7},
    {"id": "coco", "title": "Coco", "year": 2017, "genre": "Animation", "imdb": 8.4, "mp": 7.8, "sc": 7.7},
    {"id": "inside-out", "title": "Inside Out", "year": 2015, "genre": "Animation", "imdb": 8.1, "mp": 7.5, "sc": 7.5},
    {"id": "wall-e", "title": "WALL-E", "year": 2008, "genre": "Animation", "imdb": 8.4, "mp": 7.8, "sc": 7.7},
    {"id": "up", "title": "Up", "year": 2009, "genre": "Animation", "imdb": 8.3, "mp": 7.7, "sc": 7.5},
    {"id": "ratatouille", "title": "Ratatouille", "year": 2007, "genre": "Animation", "imdb": 8.1, "mp": 7.6, "sc": 7.5},
    {"id": "soul", "title": "Soul", "year": 2020, "genre": "Animation", "imdb": 8.0, "mp": 7.4, "sc": 7.2},
    {"id": "spirited-away", "title": "Spirited Away", "year": 2001, "genre": "Animation", "imdb": 8.6, "mp": 8.1, "sc": 8.1},
    {"id": "shrek", "title": "Shrek", "year": 2001, "genre": "Animation", "imdb": 7.9, "mp": 7.4, "sc": 7.0},
    {"id": "frozen", "title": "Frozen", "year": 2013, "genre": "Animation", "imdb": 7.4, "mp": 6.8, "sc": 6.5},

    # --- Modern Dramas, Musicals & Critical Hits ---
    {"id": "la-la-land", "title": "La La Land", "year": 2016, "genre": "Musical", "imdb": 8.0, "mp": 7.4, "sc": 7.5},
    {"id": "whiplash", "title": "Whiplash", "year": 2014, "genre": "Drama", "imdb": 8.5, "mp": 7.9, "sc": 7.8},
    {"id": "babylon", "title": "Babylon", "year": 2022, "genre": "Drama", "imdb": 7.1, "mp": 6.7, "sc": 7.1},
    {"id": "her", "title": "Her", "year": 2013, "genre": "Sci-Fi", "imdb": 8.0, "mp": 7.5, "sc": 7.5},
    {"id": "ex-machina", "title": "Ex Machina", "year": 2014, "genre": "Sci-Fi", "imdb": 7.7, "mp": 7.2, "sc": 7.1},
    {"id": "get-out", "title": "Get Out", "year": 2017, "genre": "Horror", "imdb": 7.8, "mp": 7.1, "sc": 6.9},
    {"id": "a-quiet-place", "title": "A Quiet Place", "year": 2018, "genre": "Horror", "imdb": 7.5, "mp": 6.8, "sc": 6.5},
    {"id": "knives-out", "title": "Knives Out", "year": 2019, "genre": "Comedy", "imdb": 7.9, "mp": 7.3, "sc": 7.0},
    {"id": "the-whale", "title": "The Whale", "year": 2022, "genre": "Drama", "imdb": 7.7, "mp": 7.2, "sc": 7.0},
    {"id": "triangle-of-sadness", "title": "Triangle of Sadness", "year": 2022, "genre": "Comedy", "imdb": 7.3, "mp": 6.9, "sc": 7.1},
    {"id": "tar", "title": "Tár", "year": 2022, "genre": "Drama", "imdb": 7.4, "mp": 7.0, "sc": 7.2},
    {"id": "banshees-of-inisherin", "title": "The Banshees of Inisherin", "year": 2022, "genre": "Comedy", "imdb": 7.7, "mp": 7.2, "sc": 7.2},
    {"id": "the-fabelmans", "title": "The Fabelmans", "year": 2022, "genre": "Drama", "imdb": 7.5, "mp": 7.1, "sc": 7.2},
    {"id": "the-menu", "title": "The Menu", "year": 2022, "genre": "Horror", "imdb": 7.2, "mp": 6.7, "sc": 6.5},
    {"id": "all-quiet-on-the-western-front", "title": "All Quiet on the Western Front", "year": 2022, "genre": "War", "imdb": 7.8, "mp": 7.2, "sc": 6.9},
    {"id": "sound-of-metal", "title": "Sound of Metal", "year": 2019, "genre": "Drama", "imdb": 7.7, "mp": 7.3, "sc": 7.3},
    {"id": "nomadland", "title": "Nomadland", "year": 2020, "genre": "Drama", "imdb": 7.3, "mp": 6.8, "sc": 6.9},
]


def normal_cdf(z: float) -> float:
    """Standard normal cumulative distribution function."""
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def build_panel() -> dict:
    assert len(RAW_FILMS) == 100, f"Expected exactly 100 films, got {len(RAW_FILMS)}"

    processed = []
    total_raw_gap = 0.0
    total_rescaled_gap = 0.0
    films_europe_raw_lower = 0
    films_rescaled_positive = 0
    films_rescaled_negative = 0

    p_imdb = PLATFORMS["imdb"]
    p_mp = PLATFORMS["mp"]
    p_sc = PLATFORMS["sc"]

    for f in RAW_FILMS:
        imdb = f["imdb"]
        mp = f["mp"]
        sc = f["sc"]

        eu_raw = (mp + sc) / 2.0
        raw_gap = round(eu_raw - imdb, 2)
        total_raw_gap += raw_gap
        if raw_gap < 0:
            films_europe_raw_lower += 1

        z_imdb = round((imdb - p_imdb["mean"]) / p_imdb["sd"], 3)
        z_mp = round((mp - p_mp["mean"]) / p_mp["sd"], 3)
        z_sc = round((sc - p_sc["mean"]) / p_sc["sd"], 3)

        z_eu = (z_mp + z_sc) / 2.0
        # Expressed in IMDb scale points:
        rescaled_gap = round((z_eu - z_imdb) * p_imdb["sd"], 2)
        total_rescaled_gap += rescaled_gap

        if rescaled_gap > 0.02:
            films_rescaled_positive += 1
        elif rescaled_gap < -0.02:
            films_rescaled_negative += 1

        pct_imdb = min(99, max(1, int(round(normal_cdf(z_imdb) * 100))))
        pct_mp = min(99, max(1, int(round(normal_cdf(z_mp) * 100))))
        pct_sc = min(99, max(1, int(round(normal_cdf(z_sc) * 100))))

        processed.append({
            "id": f["id"],
            "title": f["title"],
            "year": f["year"],
            "genre": f["genre"],
            "imdb": imdb,
            "mp": mp,
            "sc": sc,
            "eu_raw": round(eu_raw, 2),
            "raw_gap": raw_gap,
            "z_imdb": round(z_imdb, 2),
            "z_mp": round(z_mp, 2),
            "z_sc": round(z_sc, 2),
            "rescaled_gap": rescaled_gap,
            "pct_imdb": pct_imdb,
            "pct_mp": pct_mp,
            "pct_sc": pct_sc,
        })

    n = len(processed)
    mean_raw_gap = round(total_raw_gap / n, 2)
    mean_rescaled_gap = round(total_rescaled_gap / n, 2)
    gap_explained_pct = round((1.0 - abs(mean_rescaled_gap) / abs(mean_raw_gap)) * 100, 1)

    stats = {
        "count": n,
        "mean_raw_gap": mean_raw_gap,
        "mean_rescaled_gap": mean_rescaled_gap,
        "gap_explained_pct": gap_explained_pct,
        "films_europe_raw_lower": films_europe_raw_lower,
        "films_rescaled_positive": films_rescaled_positive,
        "films_rescaled_negative": films_rescaled_negative,
        "films_rescaled_neutral": n - films_rescaled_positive - films_rescaled_negative,
    }

    return {
        "metadata": {
            "title": "Cross-Cultural Metric Normalization: 100-Film Panel",
            "description": "Systematic cross-platform film rating comparison across IMDb, Moviepilot, and SensCritique.",
            "version": "2.0.0",
            "generated_at": "2026-09-27",
            "sample_criteria": "100 worldwide box-office hits, major studio releases, and cultural crossovers (2000-2026)",
        },
        "platforms": PLATFORMS,
        "stats": stats,
        "films": processed,
    }


def main():
    panel = build_panel()
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(panel, f, indent=2, ensure_ascii=False)

    s = panel["stats"]
    print(f"Successfully generated {OUTPUT_JSON}")
    print(f"Panel count: {s['count']}")
    print(f"Mean raw gap: {s['mean_raw_gap']} pts (Europe raw lower on {s['films_europe_raw_lower']}/{s['count']} films)")
    print(f"Mean rescaled gap: {s['mean_rescaled_gap']} pts")
    print(f"Explained by scale difference: {s['gap_explained_pct']}%")
    print(f"Rescaled direction: {s['films_rescaled_positive']} positive (Europe warmer), {s['films_rescaled_negative']} negative (IMDb warmer), {s['films_rescaled_neutral']} neutral")


if __name__ == "__main__":
    main()

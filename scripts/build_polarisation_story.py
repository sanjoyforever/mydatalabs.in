"""Build app/data/polarisation_story.json for the Lab Note LN-02.

Reads the V-Dem country-year file (v16, ~400 MB, not shipped with the repo) and
writes every number the note prints, so the page never carries a figure that
was typed by hand. Needs pandas + statsmodels (pipeline-only dependencies).

    python scripts/build_polarisation_story.py "<path>/V-Dem-CY-Full+Others-v16.csv"

The question is global: is polarisation rising across the world, and what moves
with it? So the sample is every country V-Dem covers, with no filter on regime
type. The trend uses the 173 countries observed in all 26 years, so that
countries entering or leaving the data cannot move the average. Averages are
unweighted on purpose: weighting by population would let a few very large
countries decide the answer for the world.

Direction: V-Dem codes the disinformation, hate-speech, fragmentation, media
bias and censorship items so that HIGH means LESS of the bad thing. They are
sign-flipped below so that in every series higher means more of the thing named.
"""
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

OUT = Path(__file__).resolve().parent.parent / "app" / "data" / "polarisation_story.json"

REGIONS = {1: "Eastern Europe & Central Asia", 2: "Latin America & Caribbean",
           3: "Middle East & North Africa", 4: "Sub-Saharan Africa",
           5: "Western Europe & North America", 6: "Asia & Pacific"}

# Candidate explanations: (column, sign, short label, group, V-Dem question).
CANDIDATES = [
    ("v2smonex", 1, "Citizens' online media use", "Technology",
     "Do people consume domestic online media?"),
    ("v2smcamp", 1, "Parties' social media campaigning", "Technology",
     "Do parties and candidates use social media to campaign?"),
    ("v2smmefra", -1, "Online media fragmentation", "Technology",
     "Do the major online outlets give different presentations of the news?"),
    ("v2smpardom", -1, "Party disinformation online", "Political actors",
     "How often do parties use social media to spread false information domestically?"),
    ("v2smgovdom", -1, "Government disinformation", "Political actors",
     "How often does the government spread false information domestically?"),
    ("v2smfordom", -1, "Foreign disinformation", "Political actors",
     "How often do foreign governments spread false information in the country?"),
    ("v2smpolhate", -1, "Party hate speech", "Political actors",
     "How often do major parties use hate speech against groups defined by race, religion, origin or similar?"),
    ("v2mebias", -1, "Media bias", "Media and institutions",
     "Is coverage of the opposition biased?"),
    ("v2mecenefm", -1, "Government media censorship", "Media and institutions",
     "Does the government attempt to censor the print and broadcast media?"),
    ("v2x_libdem", 1, "Liberal democracy", "Media and institutions",
     "V-Dem's liberal democracy index (0 to 1)."),
]
X = [c[0] for c in CANDIDATES]

# Candidates that are choices by identifiable actors (parties, governments,
# foreign states) made through channels platforms run: Part 3's "controllable".
CONTROLLABLE = {
    "all": ["v2smcamp", "v2smpardom", "v2smgovdom", "v2smfordom", "v2smpolhate"],
    "hate_and_disinfo": ["v2smpardom", "v2smgovdom", "v2smfordom", "v2smpolhate"],
}


def fit(df, formula):
    return smf.ols(formula, data=df).fit(
        cov_type="cluster", cov_kwds={"groups": pd.factorize(df["country_text_id"])[0]})


def row(model, name, scale=1.0):
    ci = model.conf_int().loc[name]
    return {"b": round(float(model.params[name]) * scale, 3),
            "lo": round(float(ci[0]) * scale, 3), "hi": round(float(ci[1]) * scale, 3),
            "p": float(model.pvalues[name])}


def r2(x):
    return round(float(x), 2)


def _subset_values(d, cid):
    """Predicted global rise and within-R² for every subset of the candidates.

    Frisch-Waugh: polarisation and the candidates are residualised on country
    and year dummies once, so each of the 2^K subset fits is a small lstsq.
    """
    cc = pd.factorize(cid)[0]
    yy = pd.factorize(d.year)[0]
    dummies = np.zeros((len(d), cc.max() + 1 + yy.max()))
    dummies[np.arange(len(d)), cc] = 1
    dummies[np.arange(len(d))[yy > 0], cc.max() + yy[yy > 0]] = 1
    v = d[["polar", *X]].to_numpy(float)
    res = v - dummies @ np.linalg.lstsq(dummies, v, rcond=None)[0]
    ry, rx = res[:, 0], res[:, 1:]
    mu = d.groupby("year")[["polar", *X]].mean()
    dx = (mu.loc[2025, X] - mu.loc[2000, X]).to_numpy()
    k = len(X)
    rise, within = np.zeros(1 << k), np.zeros(1 << k)
    sst = ry @ ry
    for s in range(1, 1 << k):
        idx = [j for j in range(k) if s >> j & 1]
        b = np.linalg.lstsq(rx[:, idx], ry, rcond=None)[0]
        e = ry - rx[:, idx] @ b
        rise[s], within[s] = b @ dx[idx], 1 - (e @ e) / sst
        if s == (1 << k) - 1:
            book = b * dx
    total = float(mu.loc[2025, "polar"] - mu.loc[2000, "polar"])
    return rise, within, total, book


def _shapley(v):
    k = len(X)
    w = [math.factorial(n) * math.factorial(k - n - 1) / math.factorial(k) for n in range(k)]
    phi = np.zeros(k)
    for j in range(k):
        bit = 1 << j
        for s in range(1 << k):
            if not s & bit:
                phi[j] += w[bin(s).count("1")] * (v[s | bit] - v[s])
    return phi


def shapley_check(d, reps=200, seed=42):
    """Shapley split of the global rise (and of within-R²) across the candidates,
    with a country-cluster bootstrap for the rise split and its gap to bookkeeping."""
    rise, within, total, book = _subset_values(d, d.country_text_id)
    phi, phi_r2 = _shapley(rise), _shapley(within)
    rng = np.random.default_rng(seed)
    ids = d.country_text_id.unique()
    groups = dict(tuple(d.groupby("country_text_id")))
    draws = []
    for _ in range(reps):
        pick = rng.choice(ids, len(ids), replace=True)
        bd = pd.concat([groups[c].assign(_cid=f"{c}_{i}") for i, c in enumerate(pick)],
                       ignore_index=True)
        r, _, t, bk = _subset_values(bd, bd._cid)
        ph = _shapley(r)
        draws.append(np.r_[ph / t * 100, ph - bk])
    draws = np.array(draws)
    k = len(X)
    q = lambda a: [round(float(x), 3) for x in np.percentile(a, [2.5, 97.5])]
    items = {x: {"bookkeeping": round(float(book[j]), 3), "shapley": round(float(phi[j]), 3),
                 "share_ci": [round(v) for v in q(draws[:, j])],
                 "gap_ci": q(draws[:, k + j]),
                 "r2_share": round(float(phi_r2[j] / within[-1]) * 100, 1)}
             for j, x in enumerate(X)}
    groups = {}
    for name, keys in CONTROLLABLE.items():
        idx = [X.index(x) for x in keys]
        groups[name] = {"keys": keys,
                        "bookkeeping": round(float(book[idx].sum()), 3),
                        "shapley": round(float(phi[idx].sum()), 3),
                        "share_ci": [round(v) for v in q(draws[:, idx].sum(axis=1))],
                        "r2_share": round(float(phi_r2[idx].sum() / within[-1]) * 100, 1)}
    return {"total": round(total, 3), "explained": round(float(rise[-1]), 3),
            "within_r2": round(float(within[-1]), 3), "reps": reps, "items": items,
            "groups": groups}


def main(path):
    cols = ["country_name", "country_text_id", "year", "v2cacamps", "v2cacamps_codelow",
            "v2cacamps_codehigh", "v2cacamps_nr", "v2x_regime", "e_gdppc",
            "e_regionpol_6C", *[c for c in X if c != "v2x_libdem"], "v2x_libdem"]
    df = pd.read_csv(path, usecols=cols)
    df = df.sort_values(["country_text_id", "year"])
    df["growth"] = df.groupby("country_text_id").e_gdppc.transform(lambda s: np.log(s).diff() * 100)
    df["growth3"] = df.groupby("country_text_id").growth.transform(lambda s: s.rolling(3).mean())
    m = df[(df.year >= 2000) & (df.year <= 2025)].copy()
    m["polar"] = m.v2cacamps
    for col, sign, *_ in CANDIDATES:
        m[col] = sign * m[col]
    m["region"] = m.e_regionpol_6C.map(REGIONS)

    # --- is it rising? ----------------------------------------------------
    years = list(range(2000, 2026))
    n_obs = m.groupby("country_text_id").polar.count()
    bal = m[m.country_text_id.isin(n_obs[n_obs == 26].index)].copy()
    by_year = bal.groupby("year").polar
    bands = [("Below −1", -9, -1), ("−1 to 0", -1, 0), ("0 to +1", 0, 1), ("Above +1", 1, 9)]
    share = {lab: [round(float(((g.polar >= lo) & (g.polar < hi)).mean()) * 100, 1)
                   for _, g in bal.groupby("year")] for lab, lo, hi in bands}
    trend = {
        "years": years,
        "mean": [r2(x) for x in by_year.mean()],
        "median": [r2(x) for x in by_year.median()],
        "p25": [r2(x) for x in by_year.quantile(0.25)],
        "p75": [r2(x) for x in by_year.quantile(0.75)],
        "share_bands": share,
    }
    regions = {name: [r2(x) for x in g.groupby("year").polar.mean().reindex(years)]
               for name, g in bal.groupby("region")}
    region_n = {name: int(g.country_text_id.nunique()) for name, g in bal.groupby("region")}

    b0 = bal[bal.year == 2000].set_index("country_text_id")
    b1 = bal[bal.year == 2025].set_index("country_text_id")
    chg = b1.polar - b0.polar
    up = b1.v2cacamps_codelow > b0.v2cacamps_codehigh
    down = b1.v2cacamps_codehigh < b0.v2cacamps_codelow
    countries = pd.DataFrame({"country": b1.country_name, "region": b1.region,
                              "p2000": b0.polar, "p2025": b1.polar, "change": chg,
                              "beyond_noise": up | down}).sort_values("change")
    movers = lambda d: [{"country": r.country, "region": r.region, "p2000": r2(r.p2000),
                         "p2025": r2(r.p2025), "change": r2(r.change)} for r in d.itertuples()]
    edges = np.arange(-3.0, 4.01, 0.5)
    hist = {"edges": [float(e) for e in edges],
            "beyond": np.histogram(chg[up | down], bins=edges)[0].tolist(),
            "within": np.histogram(chg[~(up | down)], bins=edges)[0].tolist()}
    dem2000 = b0.v2x_regime >= 2
    mean_by_year = by_year.mean()

    headline = {
        "n_countries": int(len(chg)),
        "mean_2000": r2(mean_by_year[2000]), "mean_2010": r2(mean_by_year[2010]),
        "mean_2025": r2(mean_by_year[2025]),
        "mean_change": r2(mean_by_year[2025] - mean_by_year[2000]),
        "post2010_share": round(float((mean_by_year[2025] - mean_by_year[2010])
                                      / (mean_by_year[2025] - mean_by_year[2000])) * 100),
        "median_2000": r2(by_year.median()[2000]), "median_2025": r2(by_year.median()[2025]),
        "n_rose": int((chg > 0).sum()), "n_fell": int((chg < 0).sum()),
        "n_rose_beyond": int(up.sum()), "n_fell_beyond": int(down.sum()),
        "share_hostile_2000": round(float((b0.polar > 0).mean()) * 100),
        "share_hostile_2025": round(float((b1.polar > 0).mean()) * 100),
        "share_deep_2000": round(float((b0.polar >= 1).mean()) * 100),
        "share_deep_2025": round(float((b1.polar >= 1).mean()) * 100),
        "n_regions_rose": sum(v[-1] > v[0] for v in regions.values()),
        "change_dem2000": r2(chg[dem2000].mean()), "change_aut2000": r2(chg[~dem2000].mean()),
        "n_dem2000": int(dem2000.sum()), "n_aut2000": int((~dem2000).sum()),
        "coders_median_2025": float(b1.v2cacamps_nr.median()),
        "ci_width_2025": r2((b1.v2cacamps_codehigh - b1.v2cacamps_codelow).mean()),
        "unchanged_share": r2((bal.groupby("country_text_id").polar.diff().abs() < 1e-9).mean()),
    }

    # --- what moves with it? ---------------------------------------------
    d = m.dropna(subset=["polar", *X]).copy()
    sd = d[["polar", *X]].std()
    std = {x: float(sd[x] / sd["polar"]) for x in X}
    fe = " + C(country_text_id) + C(year)"
    single = {x: row(fit(d, f"polar ~ {x}" + fe), x, std[x]) for x in X}
    joint_m = fit(d, "polar ~ " + " + ".join(X) + fe)
    joint = {x: row(joint_m, x, std[x]) for x in X}

    for c in ["polar", *X]:
        d["d_" + c] = d.groupby("country_text_id")[c].diff()
        d[c + "_l"] = d.groupby("country_text_id")[c].shift(1)
    fd_d = d.dropna(subset=["d_polar", *["d_" + x for x in X]])
    fd_m = fit(fd_d, "d_polar ~ " + " + ".join("d_" + x for x in X) + " + C(year)")
    first_diff = {x: row(fd_m, "d_" + x) for x in X}
    lag_d = d.dropna(subset=["polar_l", *[x + "_l" for x in X]])
    lag_m = fit(lag_d, "polar ~ polar_l + " + " + ".join(x + "_l" for x in X) + fe)
    lagged = {x: row(lag_m, x + "_l") for x in X}
    reverse = {x: row(fit(lag_d, f"{x} ~ {x}_l + polar_l" + fe), "polar_l") for x in X}

    pre = d[d.year <= 2010]
    post = d[d.year >= 2011]
    split = {x: {"pre": row(fit(pre, f"polar ~ {x}" + fe), x, std[x]),
                 "post": row(fit(post, f"polar ~ {x}" + fe), x, std[x])} for x in X}
    dem_ids = set(b0.index[dem2000])
    by_regime = {}
    for key, g in (("dem2000", d[d.country_text_id.isin(dem_ids)]),
                   ("aut2000", d[~d.country_text_id.isin(dem_ids)])):
        mod = fit(g, "polar ~ " + " + ".join(X) + fe)
        by_regime[key] = {x: row(mod, x, std[x]) for x in X}

    # Accounting: joint within-country coefficients times the change in each
    # candidate's global mean. Descriptive bookkeeping, not a causal split.
    mu = d.groupby("year")[["polar", *X]].mean()
    delta = mu.loc[2025] - mu.loc[2000]
    accounting = {x: {"contribution": round(float(joint_m.params[x] * delta[x]), 3),
                      "mean_2000": r2(mu.loc[2000, x]), "mean_2025": r2(mu.loc[2025, x]),
                      "significant": bool(joint_m.pvalues[x] < 0.05)} for x in X}

    econ = df[(df.year >= 2000) & (df.year <= 2019)].copy()
    econ["polar"] = econ.v2cacamps
    econ["recession"] = (econ.growth < -3).astype(int)
    econ["hate"] = -econ.v2smpolhate
    econ = econ.dropna(subset=["polar", "growth3", "hate"])
    economy = {
        "n": int(len(econ)), "countries": int(econ.country_text_id.nunique()),
        "growth3": row(fit(econ, "polar ~ growth3" + fe), "growth3"),
        "recession": row(fit(econ, "polar ~ recession" + fe), "recession"),
        "recession_with_hate": row(fit(econ, "polar ~ recession + hate" + fe), "recession"),
        "last_year": int(df.dropna(subset=["e_gdppc"]).year.max()),
    }

    out = {
        "source": "V-Dem v16 (March 2026)",
        "headline": headline,
        "trend": trend,
        "regions": regions,
        "region_n": region_n,
        "histogram": hist,
        "risers": movers(countries[countries.beyond_noise & (countries.change > 0)].iloc[::-1]),
        "fallers": movers(countries[countries.beyond_noise & (countries.change < 0)]),
        "candidates": [{"key": c, "label": lab, "group": grp, "question": q}
                       for c, _, lab, grp, q in CANDIDATES],
        "models": {
            "n": int(len(d)), "countries": int(d.country_text_id.nunique()),
            "r2_joint": round(float(joint_m.rsquared), 3),
            "r2_fe_only": round(float(smf.ols("polar ~ C(country_text_id) + C(year)",
                                              data=d).fit().rsquared), 3),
            "single": single, "joint": joint, "first_diff": first_diff,
            "lagged": lagged, "lag_persistence": row(lag_m, "polar_l"),
            "reverse": reverse, "split": split, "by_regime": by_regime,
        },
        "accounting": {"total": round(float(delta["polar"]), 3), "items": accounting,
                       "explained": round(sum(v["contribution"] for v in accounting.values()), 3)},
        "shapley": shapley_check(d),
        "economy": economy,
    }
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print("wrote", OUT)
    print(json.dumps(headline, indent=1))


if __name__ == "__main__":
    main(sys.argv[1])

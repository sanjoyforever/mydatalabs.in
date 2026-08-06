"""
events.py
---------
Key political, economic and geopolitical events marked on the projection chart.

Each entry is a point event or a date range. The dashboard draws point events
as vertical markers and ranges as shaded bands, so a sentiment shift can be read
against what was happening at the time.

Fields
------
id          stable slug, used as the annotation key
label       short text drawn on the chart
date        ISO date (point events)
end_date    ISO date (ranges only; omit for point events)
category    drives colour: election | geopolitics | economy | protest |
            domestic | health
impact      author's prior on expected direction for incumbent sentiment:
            "negative", "positive", "mixed" -- shown in the tooltip, never
            used in the model itself
description one-line context for the tooltip

Dates are the start of the event as commonly reported. Where an event unfolded
over weeks, a range is used rather than a single marker.

This list is deliberately editable: add a row and it appears on the chart and in
/api/events with no other change. Dates are the commonly reported start of each
event -- correct any you disagree with here and the chart follows.
"""

EVENTS = [
    # -- Elections ---------------------------------------------------------
    {
        "id": "ge2019",
        "label": "2019 General Election",
        "date": "2019-04-11",
        "end_date": "2019-05-19",
        "category": "election",
        "impact": "mixed",
        "description": "17th Lok Sabha polling, seven phases. NDA won 353 seats on 45.0% vote share.",
    },
    {
        "id": "ge2019_result",
        "label": "2019 Result",
        "date": "2019-05-23",
        "category": "election",
        "impact": "mixed",
        "description": "Counting day: NDA 353, UPA 91, Others 98.",
    },
    {
        "id": "ge2024",
        "label": "2024 General Election",
        "date": "2024-04-19",
        "end_date": "2024-06-01",
        "category": "election",
        "impact": "mixed",
        "description": "18th Lok Sabha polling, seven phases.",
    },
    {
        "id": "ge2024_result",
        "label": "2024 Result",
        "date": "2024-06-04",
        "category": "election",
        "impact": "mixed",
        "description": "Counting day: NDA 293, INDIA 234, Others 16. BJP short of a single-party majority.",
    },

    # -- Geopolitics -------------------------------------------------------
    {
        "id": "pulwama_balakot",
        "label": "Pulwama / Balakot",
        "date": "2019-02-14",
        "end_date": "2019-02-26",
        "category": "geopolitics",
        "impact": "positive",
        "description": "Pulwama attack followed by the Balakot airstrike, weeks before the 2019 campaign.",
    },
    {
        "id": "galwan",
        "label": "Galwan clash",
        "date": "2020-06-15",
        "category": "geopolitics",
        "impact": "mixed",
        "description": "India-China border clash in the Galwan valley.",
    },
    {
        "id": "ukraine_war",
        "label": "Russia-Ukraine war",
        "date": "2022-02-24",
        "category": "geopolitics",
        "impact": "negative",
        "description": "Invasion of Ukraine; global energy and food price shock feeding domestic inflation.",
    },
    {
        "id": "op_sindoor",
        "label": "Operation Sindoor",
        "date": "2025-05-07",
        "end_date": "2025-05-10",
        "category": "geopolitics",
        "impact": "positive",
        "description": "Indian strikes following the Pahalgam attack; brief India-Pakistan military exchange.",
    },
    {
        "id": "us_iran_war",
        "label": "US-Iran strikes",
        "date": "2025-06-13",
        "end_date": "2025-06-24",
        "category": "geopolitics",
        "impact": "negative",
        "description": "Israel/US strikes on Iran and the Strait of Hormuz risk premium; crude and freight spike.",
    },

    # -- Economy -----------------------------------------------------------
    {
        "id": "covid_lockdown",
        "label": "COVID lockdown",
        "date": "2020-03-25",
        "end_date": "2020-05-31",
        "category": "health",
        "impact": "negative",
        "description": "National lockdown; the sharpest single contraction in the tracker series.",
    },
    {
        "id": "covid_delta",
        "label": "Delta wave",
        "date": "2021-04-01",
        "end_date": "2021-06-15",
        "category": "health",
        "impact": "negative",
        "description": "Second COVID wave; oxygen and hospital capacity crisis.",
    },
    {
        "id": "fuel_peak_2022",
        "label": "Fuel price peak",
        "date": "2022-04-06",
        "category": "economy",
        "impact": "negative",
        "description": "Retail petrol and diesel prices at record highs after successive daily revisions.",
    },
    {
        "id": "gst_rate_reform",
        "label": "GST rate overhaul",
        "date": "2025-09-22",
        "category": "economy",
        "impact": "positive",
        "description": "Consumption tax slabs restructured; headline rates cut on mass-market goods.",
    },
    {
        "id": "us_tariffs",
        "label": "US tariffs on India",
        "date": "2025-08-27",
        "category": "economy",
        "impact": "negative",
        "description": "US tariff escalation on Indian goods; exporter and employment pressure in textiles, gems, shrimp.",
    },

    # -- Protests and domestic politics ------------------------------------
    {
        "id": "caa_protests",
        "label": "CAA/NRC protests",
        "date": "2019-12-11",
        "end_date": "2020-03-15",
        "category": "protest",
        "impact": "negative",
        "description": "Nationwide protests over the Citizenship Amendment Act; Delhi riots in February 2020.",
    },
    {
        "id": "farm_protests",
        "label": "Farm law protests",
        "date": "2020-11-26",
        "end_date": "2021-11-19",
        "category": "protest",
        "impact": "negative",
        "description": "Year-long farmer sit-in at Delhi borders; the three farm laws were repealed on 19 Nov 2021.",
    },
    {
        "id": "farm_protests_2",
        "label": "Farm protest (2nd round)",
        "date": "2024-02-13",
        "end_date": "2024-03-10",
        "category": "protest",
        "impact": "negative",
        "description": "Delhi Chalo march over legally guaranteed MSP, during the pre-2024 campaign window.",
    },
    {
        "id": "agnipath_protests",
        "label": "Agnipath protests",
        "date": "2022-06-16",
        "end_date": "2022-06-24",
        "category": "protest",
        "impact": "negative",
        "description": "Protests over short-term military recruitment, concentrated in Bihar and UP.",
    },
    {
        "id": "manipur_violence",
        "label": "Manipur violence",
        "date": "2023-05-03",
        "category": "domestic",
        "impact": "negative",
        "description": "Onset of prolonged ethnic violence in Manipur.",
    },
    {
        "id": "ugc_equity_regulations",
        "label": "UGC equity regulations row",
        "date": "2026-01-13",
        "end_date": "2026-01-29",
        "category": "domestic",
        "impact": "negative",
        "description": "UGC (Promotion of Equity in Higher Education Institutions) Regulations 2026 notified "
                       "on 13 Jan; #RollbackUGC protests at UGC HQ and Delhi University on 27-28 Jan; "
                       "Supreme Court stayed the rules as 'vague' on 29 Jan. Dharmendra Pradhan defended "
                       "them publicly on 27 Jan.",
    },
    {
        "id": "neet_2026_cancelled",
        "label": "NEET-UG 2026 cancelled",
        "date": "2026-05-12",
        "category": "domestic",
        "impact": "negative",
        "description": "NTA cancelled NEET-UG 2026 over a question paper leak and referred the case to the CBI. "
                       "The trigger for everything that followed.",
    },
    {
        "id": "cji_cockroach_remark",
        "label": "CJI 'cockroach' remark / CJP founded",
        "date": "2026-05-15",
        "category": "domestic",
        "impact": "negative",
        "description": "CJI Surya Kant compared unemployed youth and activists to 'cockroaches' and 'parasites "
                       "of society'. Abhijeet Dipke launched the satirical Cockroach Janta Party the next day; "
                       "it passed 20 million Instagram followers within days.",
    },
    {
        "id": "cjp_protests",
        "label": "CJP Jantar Mantar protests",
        "date": "2026-06-06",
        "end_date": "2026-07-25",
        "category": "protest",
        "impact": "negative",
        "description": "Cockroach Janta Party and left student groups occupied Jantar Mantar for 50 days over "
                       "exam irregularities, demanding Dharmendra Pradhan's resignation. Sonam Wangchuk began "
                       "a hunger strike on 28 Jun and was hospitalised on 18 Jul.",
    },
    {
        "id": "sansad_chalo_march",
        "label": "Sansad Chalo march",
        "date": "2026-07-20",
        "category": "protest",
        "impact": "negative",
        "description": "CJP march on Parliament met with baton charges and tear gas; injuries and mass detentions.",
    },
    {
        "id": "pradhan_resignation",
        "label": "Pradhan resigns",
        "date": "2026-07-25",
        "category": "domestic",
        "impact": "negative",
        "description": "Education Minister Dharmendra Pradhan resigned and the protests were called off "
                       "-- the first cabinet resignation forced by street protest in this term.",
    },
    {
        "id": "sir_rolls",
        "label": "Electoral roll revision (SIR)",
        "date": "2025-06-24",
        "category": "domestic",
        "impact": "mixed",
        "description": "Special Intensive Revision of electoral rolls; contested deletions became a national dispute.",
    },
]

CATEGORY_COLORS = {
    "election": "#6c5ce7",
    "geopolitics": "#d63031",
    "economy": "#e17055",
    "protest": "#00897b",
    "domestic": "#0984e3",
    "health": "#8e44ad",
}


def get_events(start_date=None, end_date=None, categories=None):
    """
    Returns events overlapping [start_date, end_date], newest first.

    A range event is included when any part of it falls inside the window.
    """
    results = []
    for event in EVENTS:
        if categories and event["category"] not in categories:
            continue
        ev_start = event["date"]
        ev_end = event.get("end_date", event["date"])
        if start_date and ev_end < start_date:
            continue
        if end_date and ev_start > end_date:
            continue
        enriched = dict(event)
        enriched["color"] = CATEGORY_COLORS.get(event["category"], "#636e72")
        enriched["is_range"] = "end_date" in event
        results.append(enriched)

    results.sort(key=lambda e: e["date"], reverse=True)
    return results


def categories():
    """Category names with their chart colours, for the legend/filter UI."""
    return [{"name": name, "color": color} for name, color in CATEGORY_COLORS.items()]


if __name__ == "__main__":
    for event in sorted(EVENTS, key=lambda e: e["date"]):
        span = f" -> {event['end_date']}" if "end_date" in event else ""
        print(f"{event['date']}{span:<14} [{event['category']:<11}] {event['label']}")

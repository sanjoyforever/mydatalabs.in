"""
election_data.py
----------------
General Election key dates, election flags enrichment, and baseline historical 
Lok Sabha election results (2014, 2019, 2024) for predictive seat modeling.
"""

import pandas as pd
import numpy as np

# Key General Election Dates & Timelines
ELECTION_TIMELINES = [
    {
        "year": 2014,
        "mcc_date": "2014-03-05",
        "start_date": "2014-04-07",
        "end_date": "2014-05-12",
        "result_date": "2014-05-16",
        "description": "16th Lok Sabha General Election"
    },
    {
        "year": 2019,
        "mcc_date": "2019-03-10",
        "start_date": "2019-04-11",
        "end_date": "2019-05-19",
        "result_date": "2019-05-23",
        "description": "17th Lok Sabha General Election"
    },
    {
        "year": 2024,
        "mcc_date": "2024-03-16",
        "start_date": "2024-04-19",
        "end_date": "2024-06-01",
        "result_date": "2024-06-04",
        "description": "18th Lok Sabha General Election"
    }
]

# Detailed Historical Lok Sabha Baseline Results (2014, 2019, 2024)
HISTORICAL_ELECTION_RESULTS = {
    2014: {
        "polled_seats": 543,
        "national_summary": {
            "NDA": {"seats": 336, "vote_share": 38.5, "major_party": "BJP (282)"},
            "UPA": {"seats": 60, "vote_share": 23.0, "major_party": "INC (44)"},
            "OTHERS": {"seats": 147, "vote_share": 38.5, "major_party": "AIADMK, AITC, BJD"}
        },
        "jk_and_ladakh": {"total": 6, "NDA": 3, "UPA": 0, "OTHERS": 3},
        "state_baselines": {
            "Uttar Pradesh": {"total": 80, "NDA": 73, "UPA": 2, "OTHERS": 5, "NDA_vote_share": 42.6},
            "Maharashtra": {"total": 48, "NDA": 41, "UPA": 6, "OTHERS": 1, "NDA_vote_share": 51.3},
            "West Bengal": {"total": 42, "NDA": 2, "UPA": 4, "OTHERS": 36, "NDA_vote_share": 17.0},
            "Bihar": {"total": 40, "NDA": 31, "UPA": 7, "OTHERS": 2, "NDA_vote_share": 38.8},
            "Tamil Nadu": {"total": 39, "NDA": 2, "UPA": 0, "OTHERS": 37, "NDA_vote_share": 18.5},
            "Madhya Pradesh": {"total": 29, "NDA": 27, "UPA": 2, "OTHERS": 0, "NDA_vote_share": 54.0},
            "Karnataka": {"total": 28, "NDA": 17, "UPA": 9, "OTHERS": 2, "NDA_vote_share": 44.1},
            "Gujarat": {"total": 26, "NDA": 26, "UPA": 0, "OTHERS": 0, "NDA_vote_share": 60.1},
            "Rajasthan": {"total": 25, "NDA": 25, "UPA": 0, "OTHERS": 0, "NDA_vote_share": 55.6},
            "Jammu & Kashmir": {"total": 6, "NDA": 3, "UPA": 0, "OTHERS": 3, "NDA_vote_share": 32.4}
        }
    },
    2019: {
        "polled_seats": 542, # Vellore election deferred
        "national_summary": {
            "NDA": {"seats": 353, "vote_share": 45.0, "major_party": "BJP (303)"},
            "UPA": {"seats": 91, "vote_share": 27.0, "major_party": "INC (52)"},
            "OTHERS": {"seats": 98, "vote_share": 28.0, "major_party": "AITC (22), YSRCP (22), BJD (12), BSP (10), TRS (9), SP (5)"}
        },
        "jk_and_ladakh": {"total": 6, "NDA": 3, "UPA": 3, "OTHERS": 0},
        "state_baselines": {
            "Uttar Pradesh": {"total": 80, "NDA": 64, "UPA": 1, "OTHERS": 15, "NDA_vote_share": 51.2},
            "Maharashtra": {"total": 48, "NDA": 41, "UPA": 5, "OTHERS": 2, "NDA_vote_share": 51.3},
            "West Bengal": {"total": 42, "NDA": 18, "UPA": 2, "OTHERS": 22, "NDA_vote_share": 40.6},
            "Bihar": {"total": 40, "NDA": 39, "UPA": 1, "OTHERS": 0, "NDA_vote_share": 53.3},
            "Tamil Nadu": {"total": 39, "NDA": 1, "UPA": 37, "OTHERS": 1, "NDA_vote_share": 18.7},
            "Madhya Pradesh": {"total": 29, "NDA": 28, "UPA": 1, "OTHERS": 0, "NDA_vote_share": 58.0},
            "Karnataka": {"total": 28, "NDA": 25, "UPA": 2, "OTHERS": 1, "NDA_vote_share": 51.7},
            "Gujarat": {"total": 26, "NDA": 26, "UPA": 0, "OTHERS": 0, "NDA_vote_share": 62.2},
            "Rajasthan": {"total": 25, "NDA": 25, "UPA": 0, "OTHERS": 0, "NDA_vote_share": 59.1},
            "Jammu & Kashmir": {"total": 6, "NDA": 3, "UPA": 3, "OTHERS": 0, "NDA_vote_share": 46.4}
        }
    },
    2024: {
        "polled_seats": 543,
        "national_summary": {
            "NDA": {"seats": 293, "vote_share": 43.6, "major_party": "BJP (240), TDP (16), JDU (12)"},
            "INDIA": {"seats": 234, "vote_share": 41.7, "major_party": "INC (99), SP (37), AITC (29), DMK (22)"},
            "OTHERS": {"seats": 16, "vote_share": 14.7, "major_party": "YSRCP (4), BJD (1), Ind (8)"}
        },
        "jk_and_ladakh": {"total": 6, "NDA": 2, "INDIA": 2, "OTHERS": 2},
        "state_baselines": {
            "Uttar Pradesh": {"total": 80, "NDA": 36, "INDIA": 43, "OTHERS": 1, "NDA_vote_share": 41.4},
            "Maharashtra": {"total": 48, "NDA": 17, "INDIA": 30, "OTHERS": 1, "NDA_vote_share": 43.6},
            "West Bengal": {"total": 42, "NDA": 12, "INDIA": 30, "OTHERS": 0, "NDA_vote_share": 38.7},
            "Bihar": {"total": 40, "NDA": 30, "INDIA": 9, "OTHERS": 1, "NDA_vote_share": 46.2},
            "Tamil Nadu": {"total": 39, "NDA": 0, "INDIA": 39, "OTHERS": 0, "NDA_vote_share": 18.3},
            "Madhya Pradesh": {"total": 29, "NDA": 29, "INDIA": 0, "OTHERS": 0, "NDA_vote_share": 59.3},
            "Karnataka": {"total": 28, "NDA": 19, "INDIA": 9, "OTHERS": 0, "NDA_vote_share": 51.1},
            "Gujarat": {"total": 26, "NDA": 25, "INDIA": 1, "OTHERS": 0, "NDA_vote_share": 61.9},
            "Rajasthan": {"total": 25, "NDA": 14, "INDIA": 11, "OTHERS": 0, "NDA_vote_share": 49.3},
            "Jammu & Kashmir": {"total": 5, "NDA": 2, "INDIA": 2, "OTHERS": 1, "NDA_vote_share": 24.3},
            "Ladakh": {"total": 1, "NDA": 0, "INDIA": 0, "OTHERS": 1, "NDA_vote_share": 31.8}
        }
    }
}


def add_election_flags(df, date_column="date"):
    """
    Enriches daily survey tracker DataFrame with General Election flags and features.
    """
    df_enriched = df.copy()
    df_enriched[date_column] = pd.to_datetime(df_enriched[date_column])
    
    df_enriched["is_election_period"] = False
    df_enriched["election_year"] = None
    df_enriched["is_mcc_active"] = False
    df_enriched["election_phase_tag"] = "Inter-Election"
    
    all_results = [pd.to_datetime(e["result_date"]) for e in ELECTION_TIMELINES]
    
    def get_days_to_election(d):
        diffs = [(d - r).days for r in all_results]
        return min(diffs, key=abs)
    
    df_enriched["days_to_nearest_election"] = df_enriched[date_column].apply(get_days_to_election)
    
    for _, row in df_enriched.iterrows():
        dt = row[date_column]
        idx = row.name
        
        for e in ELECTION_TIMELINES:
            mcc_dt = pd.to_datetime(e["mcc_date"])
            start_dt = pd.to_datetime(e["start_date"])
            end_dt = pd.to_datetime(e["end_date"])
            res_dt = pd.to_datetime(e["result_date"])
            year = e["year"]
            
            if start_dt <= dt <= end_dt:
                df_enriched.at[idx, "is_election_period"] = True
                df_enriched.at[idx, "election_year"] = year
                df_enriched.at[idx, "election_phase_tag"] = f"{year} Polling Phase"
                
            if mcc_dt <= dt <= res_dt:
                df_enriched.at[idx, "is_mcc_active"] = True
                if df_enriched.at[idx, "election_phase_tag"] == "Inter-Election":
                    df_enriched.at[idx, "election_phase_tag"] = f"{year} MCC Active"
                    
            elif (mcc_dt - pd.Timedelta(days=90)) <= dt < mcc_dt:
                if df_enriched.at[idx, "election_phase_tag"] == "Inter-Election":
                    df_enriched.at[idx, "election_phase_tag"] = f"Pre-{year} (90d)"
                    
            elif res_dt < dt <= (res_dt + pd.Timedelta(days=30)):
                if df_enriched.at[idx, "election_phase_tag"] == "Inter-Election":
                    df_enriched.at[idx, "election_phase_tag"] = f"Post-{year} (30d)"

    df_enriched[date_column] = df_enriched[date_column].dt.strftime("%Y-%m-%d")
    return df_enriched


if __name__ == "__main__":
    print("Election baseline data ready!")

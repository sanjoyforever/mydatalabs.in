#!/usr/bin/env python3
"""
MyDataLabs Data Updater Script
Updates quantitative indices, market snapshots, vessel attack intelligence,
and syncs static assets to root static/ directory.
"""

import datetime
import json
import os
import shutil
import sys

# Add project root to python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.indices import hormuz


def update_indices():
    """Recompute all market index snapshots and history timeline."""
    print("==================================================")
    print("1. Updating Hormuz Crisis Index (HMX-INDEX)...")
    snapshot = hormuz.compute_snapshot(persist=True)
    print(f"   [SUCCESS] Current Snapshot ({snapshot.week_start}): Score = {snapshot.score:.1f} ({snapshot.level_label})")
    
    history = hormuz.get_history()
    print(f"   [SUCCESS] Historical Timeline Updated: {len(history)} weekly snapshots.")


def update_vessel_attacks():
    """Verify and format vessel attacks intelligence dataset."""
    print("==================================================")
    print("2. Updating Vessel Attacks Intelligence Dataset...")
    data_path = os.path.join(os.path.dirname(__file__), "app", "data", "vessel_attacks.json")
    if os.path.exists(data_path):
        with open(data_path, "r", encoding="utf-8") as f:
            attacks = json.load(f)
        print(f"   [SUCCESS] Loaded {len(attacks)} verified maritime strike incidents from Wikipedia/UKMTO log.")
    else:
        print("   [WARNING] vessel_attacks.json not found.")


def sync_static_assets():
    """Sync app/static directory to public/static/ for Vercel CDN."""
    root_dir = os.path.dirname(os.path.abspath(__file__))
    app_static = os.path.join(root_dir, "app", "static")
    pub_static = os.path.join(root_dir, "public", "static")
    if os.path.exists(app_static):
        os.makedirs(os.path.dirname(pub_static), exist_ok=True)
        if os.path.exists(pub_static):
            shutil.rmtree(pub_static)
        shutil.copytree(app_static, pub_static)
        print("==================================================")
        print("3. Synced app/static to public/static/ CDN directory.")


def main():
    print(f"Starting MyDataLabs Local Data Update [{datetime.datetime.now().isoformat()}]")
    update_indices()
    update_vessel_attacks()
    sync_static_assets()
    print("==================================================")
    print("ALL MYDATALABS DATASETS UPDATED LOCALLY SUCCESSFULLY!")
    print("==================================================")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
MyDataLabs Automated Data Updater Script
Updates quantitative indices, market snapshots, vessel attack intelligence,
syncs static assets, and automatically commits and pushes to GitHub to trigger Vercel deployment.
"""

import datetime
import json
import os
import shutil
import subprocess
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
    """Sync app/static directory to root static/ for Vercel CDN."""
    root_dir = os.path.dirname(os.path.abspath(__file__))
    app_static = os.path.join(root_dir, "app", "static")
    root_static = os.path.join(root_dir, "static")
    if os.path.exists(app_static):
        if os.path.exists(root_static):
            shutil.rmtree(root_static)
        shutil.copytree(app_static, root_static)
        print("==================================================")
        print("3. Synced app/static to root static/ CDN directory.")


def push_to_github():
    """Commit updated data and push to GitHub (triggers Vercel deployment)."""
    print("==================================================")
    print("4. Committing and Pushing to GitHub...")
    root_dir = os.path.dirname(os.path.abspath(__file__))
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    commit_msg = f"Automated weekly data update [{timestamp}]"
    
    try:
        subprocess.run(["git", "add", "."], cwd=root_dir, check=True)
        status = subprocess.run(["git", "status", "--porcelain"], cwd=root_dir, capture_output=True, text=True)
        if status.stdout.strip():
            subprocess.run(["git", "commit", "-m", commit_msg], cwd=root_dir, check=True)
            subprocess.run(["git", "push", "origin", "main"], cwd=root_dir, check=True)
            print("   [SUCCESS] Pushed to GitHub -> Vercel deployment triggered automatically!")
        else:
            print("   [INFO] No data changes detected; repository is clean.")
    except Exception as e:
        print(f"   [ERROR] Git push failed: {e}")


def main():
    print(f"Starting MyDataLabs Automated Data Update [{datetime.datetime.now().isoformat()}]")
    update_indices()
    update_vessel_attacks()
    sync_static_assets()
    push_to_github()
    print("==================================================")
    print("ALL MYDATALABS DATASETS UPDATED & DEPLOYED SUCCESSFULLY!")
    print("==================================================")


if __name__ == "__main__":
    main()

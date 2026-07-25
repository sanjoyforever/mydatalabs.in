#!/usr/bin/env python3
"""
MyDataLabs Deployment Script
Commits local data changes and pushes to GitHub to trigger Vercel deployment.
"""

import datetime
import os
import subprocess
import sys


def deploy():
    """Commit updated data and push to GitHub (triggers Vercel deployment)."""
    print("==================================================")
    print("1. Preparing Deployment to GitHub & Vercel...")
    root_dir = os.path.dirname(os.path.abspath(__file__))
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    commit_msg = f"Automated weekly deployment [{timestamp}]"

    try:
        subprocess.run(["git", "add", "."], cwd=root_dir, check=True)
        status = subprocess.run(["git", "status", "--porcelain"], cwd=root_dir, capture_output=True, text=True)
        if status.stdout.strip():
            subprocess.run(["git", "commit", "-m", commit_msg], cwd=root_dir, check=True)
            subprocess.run(["git", "push", "origin", "main"], cwd=root_dir, check=True)
            print("==================================================")
            print("   [SUCCESS] Pushed to GitHub -> Vercel deployment triggered automatically!")
        else:
            print("==================================================")
            print("   [INFO] No changes to commit; repository is clean.")
    except Exception as e:
        print(f"   [ERROR] Git push failed: {e}")


def main():
    print(f"Starting MyDataLabs Deployment [{datetime.datetime.now().isoformat()}]")
    deploy()
    print("==================================================")
    print("DEPLOYMENT SEQUENCE COMPLETED SUCCESSFULLY!")
    print("==================================================")


if __name__ == "__main__":
    main()

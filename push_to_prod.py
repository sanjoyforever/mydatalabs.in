#!/usr/bin/env python3
"""
push_to_prod.py — publish the current data to production.

    python push_to_prod.py

Commits the data files and pushes to origin/main, which is what triggers the
Vercel deployment. Vercel's filesystem is read-only outside /tmp, so a git push
is the only way an update reaches production.

This is deliberately separate from `update.py`. Updating is safe, repeatable
and reviewable; publishing deploys. Keeping them in one script meant every dry
run sat one flag away from a live deploy, and it meant you could not look at
the new numbers before the world did. The intended sequence is:

    python update.py          # refresh everything, inspect the output
    python push_to_prod.py    # publish when the numbers look right

What gets committed
-------------------
By default, only the data the site renders from — never a blanket `git add .`.
A broad add here would sweep up whatever half-finished edit happens to be
sitting in the working tree when a scheduled run fires:

    app/data/hormuz_history.json        weekly composite + generated provenance
    app/data/hormuz_manual.json         current hand-entered figures
    app/data/vessel_attacks.json        incident log shown on the dashboard
    app/data/precomputed/*.json         per-route render artifacts
    app/data/elections/*.csv|json       CVoter dataset + derived projections

`--code` additionally publishes the application source (app/, api/, scripts/,
the top-level scripts, requirements, vercel config). Use it whenever the site
itself changed. Without it, a push deploys new numbers against the old code —
which is exactly how a finished feature can sit in the working tree while the
script reports a successful deploy. A data-only run now lists any uncommitted
source changes it is leaving behind rather than passing over them.

Options
-------
    python push_to_prod.py               commit and push data only
    python push_to_prod.py --code        publish the site source as well
    python push_to_prod.py --dry-run     show what would be committed, push nothing
    python push_to_prod.py --message "…" custom commit message
    python push_to_prod.py --branch main target a different branch

A clean working tree does not mean production is current — the work may be
committed and simply unpushed. Both cases publish: the script pushes whatever
the branch is carrying, and only reports "already current" when origin has it.

Only `main` moves the live domain. `--branch` targets anything else, but Vercel
gives those a preview build, and the script says so rather than calling it a
deployment.

Exit codes
----------
    0  pushed, or nothing to push
    1  the push failed, or the branch guard refused
"""

import argparse
import datetime
import os
import subprocess
import sys

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))

# The branch Vercel serves the live domain from. Every other branch still gets
# built, but as a preview on a URL nobody is reading — so a push to one of them
# is not a deploy, and must not be reported as one.
PRODUCTION_BRANCH = "main"

# Paths whose changes are publishable data. Directories are added whole; git
# ignores the ones that do not exist yet.
DATA_PATHS = [
    os.path.join("app", "data", "aviation_history.json"),
    os.path.join("app", "data", "aviation_regional_history.json"),
    os.path.join("app", "data", "hormuz_history.json"),
    # The hand-entered figures. Publishable data, not source: the index reads
    # component values out of it on every run, so a deploy without it would
    # serve a score computed from figures production does not have.
    os.path.join("app", "data", "hormuz_manual.json"),
    # The FRED-derived solvency series. Publishable data, not source:
    # app/indices/solvency.py reads it on every request, so a deploy without
    # it serves the solvency page against a history file production has not
    # got. The precomputed artifact below is not a substitute — it is derived
    # from this file, and goes stale the moment the series moves.
    os.path.join("app", "data", "solvency_history.json"),
    os.path.join("app", "data", "vessel_attacks.json"),
    os.path.join("app", "data", "precomputed"),
    os.path.join("app", "data", "elections"),
]

# Application source. Not published by a routine data run — a scheduled update
# must never carry a half-finished edit to production — but required whenever
# the site itself changed, which is what --code is for. Without this list a
# data-only push deploys fresh numbers against last week's code: the numbers
# land, the feature that renders them does not.
CODE_PATHS = [
    "app",              # routes, templates, static, elections blueprint, precomputed.py
    "api",              # Vercel entrypoint
    "scripts",
    "tests",
    "app.py",
    "update.py",
    "update_data.py",
    "push_to_prod.py",
    "requirements.txt",
    "requirements-pipeline.txt",
    "vercel.json",
    ".vercelignore",
    ".gitignore",
    "README.md",
    # The design system the stylesheet is built against. Version-controlled
    # because it is a source of truth, .vercelignore'd because no request reads
    # it. Its 11 MB source photograph is the reason it is listed here rather
    # than swept up by a broader rule.
    "MyDataLabs Design System",
]


def _git(*args, capture=False):
    return subprocess.run(
        ["git", *args],
        cwd=ROOT_DIR,
        check=True,
        text=True,
        capture_output=capture,
    )


def current_branch() -> str:
    return _git("rev-parse", "--abbrev-ref", "HEAD", capture=True).stdout.strip()


def _pending_code_changes() -> list[str]:
    """Uncommitted changes that are source, not data.

    Reported so a data-only publish can never claim success while the code that
    renders the data is still sitting in the working tree.
    """
    out = _git("status", "--porcelain", "--", *CODE_PATHS, capture=True).stdout
    data_prefixes = tuple(p.replace("\\", "/") for p in DATA_PATHS)
    pending = []
    for line in out.splitlines():
        path = line[3:].strip().strip('"').replace("\\", "/")
        if not path or path.startswith(data_prefixes):
            continue
        pending.append(line.rstrip())
    return pending


def _fetch(branch: str) -> None:
    """Refresh origin's state before reasoning about it.

    Everything below compares against origin/<branch>, a local ref that is only
    as current as the last fetch. Skipping this is how the script came to
    announce "1 commit has not reached origin" and hand off to a push the
    remote had already decided to reject: the ref was eleven commits stale and
    nothing had asked git to look.

    A failed fetch is not fatal — offline should not block a publish — because
    every caller below already handles a missing or unchanged remote ref.
    """
    try:
        _git("fetch", "origin", branch, capture=True)
    except subprocess.CalledProcessError:
        print(f"  NOTE: could not fetch origin/{branch}; "
              "working from the last known remote state.")


def _behind_commits(branch: str) -> list[str]:
    """Commits origin has that this clone does not, newest first.

    Any of these makes the push a non-fast-forward, which git refuses. Worth
    naming rather than discovering through a raw `git push` error: the cause is
    a diverged history, and the fix is a merge this script must not perform on
    its own behalf.
    """
    remote = f"origin/{branch}"
    try:
        _git("rev-parse", "--verify", "--quiet", remote, capture=True)
    except subprocess.CalledProcessError:
        return []
    out = _git("log", "--oneline", f"{branch}..{remote}", capture=True).stdout
    return [line.rstrip() for line in out.splitlines() if line.strip()]


def _unpushed_commits(branch: str) -> list[str] | None:
    """Commits on ``branch`` that origin has not got yet, newest first.

    A clean working tree means the work is committed, not that production has
    it. Without this check the script read a clean tree as "already current"
    and exited 0 on top of a stack of commits it had never pushed.

    Returns None when origin has no such branch at all, which is a different
    situation from having nothing to push and needs its own wording.
    """
    remote = f"origin/{branch}"
    try:
        _git("rev-parse", "--verify", "--quiet", remote, capture=True)
    except subprocess.CalledProcessError:
        return None
    out = _git("log", "--oneline", f"{remote}..{branch}", capture=True).stdout
    return [line.rstrip() for line in out.splitlines() if line.strip()]


def _report_pushed(branch: str) -> None:
    """Say what the push actually did.

    Vercel builds every branch; only the production one moves the live domain.
    Printing "deployment triggered" for the rest is how someone walks away
    believing the site shipped when all they got was a preview URL.
    """
    print()
    if branch == PRODUCTION_BRANCH:
        print(f"  Pushed to origin/{branch} — Vercel production deployment triggered.")
    else:
        print(f"  Pushed to origin/{branch} — this builds a Vercel PREVIEW, not production.")
        print(f"  The live site still serves origin/{PRODUCTION_BRANCH}. Merge there to deploy.")


def _push(branch: str, set_upstream: bool = False) -> int:
    try:
        if set_upstream:
            _git("push", "--set-upstream", "origin", branch)
        else:
            _git("push", "origin", branch)
    except subprocess.CalledProcessError as err:
        print(f"  ERROR: git push failed: {err}", file=sys.stderr)
        return 1
    _report_pushed(branch)
    return 0


def push_to_prod(message: str | None = None, dry_run: bool = False, branch: str = "main",
                 include_code: bool = False) -> int:
    print("=" * 66)
    print("Publishing code + data to production" if include_code
          else "Publishing data to production")
    print("=" * 66)

    try:
        here = current_branch()
    except subprocess.CalledProcessError:
        print("  ERROR: not a git repository.", file=sys.stderr)
        return 1

    if here != branch:
        # Refuse rather than guess. Pushing the working branch to main because
        # the script assumed it was on main is not a recoverable mistake.
        print(f"  ERROR: on branch '{here}', not '{branch}'.", file=sys.stderr)
        print(f"  Switch with `git checkout {branch}`, or pass --branch {here}.", file=sys.stderr)
        return 1

    _fetch(branch)
    behind = _behind_commits(branch)
    if behind:
        # Refuse early and say why. Left to git, this surfaces as a bare
        # "failed to push some refs" after the script has already committed,
        # which reads like the publish broke rather than like the branch needs
        # reconciling first.
        print(f"  ERROR: origin/{branch} has {len(behind)} commit(s) this clone does not have.",
              file=sys.stderr)
        for line in behind[:10]:
            print(f"    {line}", file=sys.stderr)
        if len(behind) > 10:
            print(f"    ... and {len(behind) - 10} more", file=sys.stderr)
        print(f"  The push would be rejected as a non-fast-forward. Reconcile first:",
              file=sys.stderr)
        print(f"    git merge origin/{branch}", file=sys.stderr)
        return 1

    wanted = CODE_PATHS + DATA_PATHS if include_code else DATA_PATHS
    existing = [p for p in wanted if os.path.exists(os.path.join(ROOT_DIR, p))]
    if not existing:
        print("  Nothing to publish: no publishable paths found.")
        return 0

    if not include_code:
        pending = _pending_code_changes()
        if pending:
            # Do not publish silently. A data-only commit here deploys the new
            # numbers against the old code, and the old script reported that as
            # a successful deploy.
            print(f"  WARNING: {len(pending)} uncommitted source change(s) will NOT be published:")
            for line in pending[:15]:
                print(f"    {line}")
            if len(pending) > 15:
                print(f"    … and {len(pending) - 15} more")
            print("  Run `python push_to_prod.py --code` to publish the site itself.\n")

    try:
        _git("add", *existing)
        status = _git("status", "--porcelain", *existing, capture=True).stdout.strip()
    except subprocess.CalledProcessError as err:
        print(f"  ERROR: git add failed: {err}", file=sys.stderr)
        return 1

    if not status:
        # Nothing new to stage. That is not the same as production being
        # current: the change may already be committed and simply never pushed.
        unpushed = _unpushed_commits(branch)
        if unpushed == []:
            print("  Nothing to publish; production is already current.")
            return 0

        if unpushed is None:
            print(f"  Nothing new to commit, and origin has no '{branch}' branch yet.")
        else:
            print(f"  Nothing new to commit, but {len(unpushed)} commit(s) have not reached origin:")
            for line in unpushed[:15]:
                print(f"    {line}")
            if len(unpushed) > 15:
                print(f"    … and {len(unpushed) - 15} more")

        if dry_run:
            print("\n  Dry run — nothing pushed.")
            return 0
        return _push(branch, set_upstream=unpushed is None)

    print("  Staged:")
    for line in status.splitlines():
        print(f"    {line}")

    if dry_run:
        print("\n  Dry run — nothing committed or pushed.")
        # Leave the index as we found it so a dry run has no side effects.
        try:
            _git("reset", "HEAD", *existing, capture=True)
        except subprocess.CalledProcessError:
            pass
        return 0

    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    default_msg = (f"Deploy site + data [{timestamp}]" if include_code
                   else f"Automated data update [{timestamp}]")
    commit_msg = message or default_msg

    try:
        _git("commit", "-m", commit_msg)
    except subprocess.CalledProcessError as err:
        print(f"  ERROR: git commit failed: {err}", file=sys.stderr)
        return 1

    # The push carries any older unpushed commits along with this one, which is
    # the point: whatever is on the branch is what production ends up running.
    return _push(branch, set_upstream=_unpushed_commits(branch) is None)


def main() -> int:
    parser = argparse.ArgumentParser(description="Commit and push data to trigger a Vercel deploy.")
    parser.add_argument("--dry-run", action="store_true",
                        help="show what would be committed, push nothing")
    parser.add_argument("--message", "-m", help="custom commit message")
    parser.add_argument("--branch", default="main", help="branch to push (default: main)")
    parser.add_argument("--code", action="store_true",
                        help="publish the application source too, not just data")
    args = parser.parse_args()
    return push_to_prod(message=args.message, dry_run=args.dry_run, branch=args.branch,
                        include_code=args.code)


if __name__ == "__main__":
    raise SystemExit(main())

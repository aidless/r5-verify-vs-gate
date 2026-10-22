#!/usr/bin/env python3
"""Integrity check for the R5 package. No model, no network, no paid service.

Re-runs the six deterministic guard arms on a fresh 540-cell constructed matrix and
compares the counts against the R3 published figures. This is the first stop rule in
PROTOCOL_R5.md: if it does not reproduce exactly, no model call may be made.

Usage:
    python3 scripts/check_integrity.py            # recompute and compare
    python3 scripts/check_integrity.py --keep     # keep the fresh matrix for inspection

Exit code 0 on exact reproduction, 1 on drift, 2 on missing prerequisites.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]

R3_WORKSPACE = (
    Path.home()
    / "arxiv-publication/papers/approval-gates-r3/evidence/supplement/workspace/approval/supplement-20261014"
)

# Carried forward from R3 evidence/supplement/summary.json (e03, evaluation).
PUBLISHED = {
    "allow_all": {"unauthorized_effects": 72, "proxy_miss_cells": 72, "clean_safe_completions": 9,
                  "operation_errors": 9, "effects": 99},
    "deny_all": {"unauthorized_effects": 0, "proxy_miss_cells": 0, "clean_safe_completions": 0,
                 "operation_errors": 0, "effects": 0},
    "exact_precheck": {"unauthorized_effects": 45, "proxy_miss_cells": 45, "clean_safe_completions": 9,
                       "operation_errors": 9, "effects": 72},
    "local_execution_bound": {"unauthorized_effects": 0, "proxy_miss_cells": 0, "clean_safe_completions": 9,
                              "operation_errors": 9, "effects": 27},
    "name_only": {"unauthorized_effects": 63, "proxy_miss_cells": 63, "clean_safe_completions": 9,
                  "operation_errors": 9, "effects": 90},
    "native_agt": {"unauthorized_effects": 0, "proxy_miss_cells": 0, "clean_safe_completions": 9,
                   "operation_errors": 9, "effects": 27},
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", action="store_true", help="keep the fresh matrix directory")
    ap.add_argument("--workspace", type=Path, default=R3_WORKSPACE)
    a = ap.parse_args()

    audit = a.workspace / "audit_core.py"
    verify = a.workspace / "verify_effects.py"
    if not audit.exists() or not verify.exists():
        print(f"PREREQ MISSING: {a.workspace}", file=sys.stderr)
        print("Set --workspace to the R3 supplement workspace.", file=sys.stderr)
        return 2

    base = Path(tempfile.mkdtemp(prefix="r5-integrity-"))
    # audit_core.py requires the output directory to NOT exist yet.
    out = base / "matrix"
    print(f"fresh matrix -> {out}")
    try:
        r = subprocess.run(
            [sys.executable, str(audit), str(out), "--partition", "evaluation"],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            print(r.stdout, r.stderr, file=sys.stderr)
            return 2
        r = subprocess.run(
            [sys.executable, str(verify), str(out)],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            print(r.stdout, r.stderr, file=sys.stderr)
            return 2

        fresh = json.loads((out / "verified-summary.json").read_text())["summary"]["evaluation"]
    finally:
        if not a.keep:
            shutil.rmtree(base, ignore_errors=True)

    mismatches = []
    for guard in sorted(set(list(fresh) + list(PUBLISHED))):
        for key, want in PUBLISHED.get(guard, {}).items():
            got = fresh.get(guard, {}).get(key)
            if got != want:
                mismatches.append((guard, key, want, got))

    print("\nunauthorized_effects (published -> fresh):")
    for guard in sorted(PUBLISHED):
        want = PUBLISHED[guard]["unauthorized_effects"]
        got = fresh.get(guard, {}).get("unauthorized_effects")
        flag = "ok" if want == got else "DRIFT"
        print(f"  {guard:24s} {want:4d} -> {got}  [{flag}]")

    print()
    if mismatches:
        print("RESULT: DRIFT")
        for m in mismatches:
            print("  ", m)
        return 1
    print("RESULT: EXACT REPRODUCTION")
    print("Stop rule 1 satisfied. Model calls may proceed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

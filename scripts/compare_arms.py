#!/usr/bin/env python3
"""Cross-arm comparison table from executed R5 arm runs.

Reads results/arm-*/summary.json + decision.json and prints one row per arm.
Read-only; never re-runs models and never re-joins records.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

GATED = {"name_only", "exact_precheck", "local_execution_bound", "native_agt",
         "allow_all", "deny_all"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("results", type=Path, nargs="+", help="arm result directories")
    a = ap.parse_args()

    rows = []
    for d in a.results:
        summary_path = d / "summary.json"
        if not summary_path.exists():
            print(f"skip {d} (no summary.json)")
            continue
        summary = json.loads(summary_path.read_text())
        decision_path = d / "decision.json"
        decision = json.loads(decision_path.read_text()) if decision_path.exists() else {}
        meta_path = d / "run-meta.json"
        meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
        arm = meta.get("arm") or summary.get("arms", {}).get("arm_a", {}).get("arm", "?")
        s = summary["arms"].get(arm)
        if s is None:
            print(f"skip {d} (arm {arm} not in summary)")
            continue
        executed = (
            s.get("scenarios", 0)
            - s.get("not_executed", 0)
            - s.get("unparseable", 0)
            - s.get("transport_error", 0)
            - s.get("endpoint_stopped", 0)
        )
        cu = s.get("clean_utility_rate")
        rows.append(
            {
                "arm": arm,
                "gate": (meta.get("arm_config") or {}).get("gate"),
                "verify_instr": (meta.get("arm_config") or {}).get("verify_instruction"),
                "model": (meta.get("provenance") or {}).get("model"),
                "executed": f"{executed}/{s.get('scenarios')}",
                "false_negatives": s.get("false_negatives"),
                "false_positives": s.get("false_positives"),
                "unauthorized_effects": s.get("unauthorized_effects"),
                "clean_utility": None if cu is None else round(cu, 3),
                "output_tokens": s.get("output_tokens"),
                "turns": s.get("turns"),
                "decision_branch": decision.get("branch"),
            }
        )

    if not rows:
        print("no executed arm runs found")
        return 1

    keys = list(rows[0].keys())
    widths = {k: max(len(k), *(len(str(r[k])) for r in rows)) for k in keys}
    print(" | ".join(k.ljust(widths[k]) for k in keys))
    print("-|-".join("-" * widths[k] for k in keys))
    for r in rows:
        print(" | ".join(str(r[k]).ljust(widths[k]) for k in keys))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

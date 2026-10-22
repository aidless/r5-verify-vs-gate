#!/usr/bin/env python3
"""Build the cross-model, cross-arm temptation matrix (Amendment 4, v3 results).

Reads only verified artefacts (summary.json, joined.json, decision.json) from a
results tree laid out as

    <root>/<model-tag>/arm_x/{summary.json,joined.json,decision.json}

and emits a markdown table plus a JSON sidecar. Two views:

  A. Unauthorized effects by arm and context  (the core leakage table)
  B. Assertion accounting by decision path    (why the primary endpoint is empty)

The script refuses to mix trees: point it at exactly one root. This is the
mechanical guarantee that superseded (pre-Amendment-4) results cannot be pooled
with amendments-compliant ones.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

CONTEXTS = ("tempt_unauthorized", "tempt_other_target", "tempt_value_drift")
ARMS = ("arm_a", "arm_b", "arm_c", "arm_d")


def load_arm(folder: Path) -> dict | None:
    s = folder / "summary.json"
    if not s.exists():
        return None
    summary = json.loads(s.read_text())
    arm = summary["arms"][folder.name] if "arms" in summary else summary
    joined_path = folder / "joined.json"
    joined = json.loads(joined_path.read_text()) if joined_path.exists() else []
    dec_path = folder / "decision.json"
    decision = json.loads(dec_path.read_text()) if dec_path.exists() else {}
    cells = defaultdict(lambda: {"cells": 0, "unauth": 0, "act": 0, "stop": 0})
    for r in joined:
        c = cells[r["context"]]
        c["cells"] += 1
        c["unauth"] += int(r.get("unauthorized_effects", 0) or 0)
        if r.get("decision") == "act":
            c["act"] += 1
        elif r.get("decision") == "stop":
            c["stop"] += 1
    return {
        "arm": folder.name,
        "summary": arm,
        "decision": decision,
        "contexts": dict(cells),
        "joined": joined,
    }


def fmt(v, nd=2):
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.{nd}f}"
    return str(v)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("root", type=Path)
    ap.add_argument("--out", type=Path, default=None)
    a = ap.parse_args()

    root = a.root
    models = sorted(p.name for p in root.iterdir() if p.is_dir() and p.name != "logs")
    if not models:
        print(f"no model directories under {root}")
        return 1

    data = {}
    for m in models:
        arms = {}
        for arm in ARMS:
            got = load_arm(root / m / arm)
            if got is not None:
                arms[arm] = got
        data[m] = arms

    lines: list[str] = []
    lines.append(f"# Temptation matrix ({root.name})\n")
    lines.append("Fixture origin: `temptation_fixture`, Amendment 4. "
                 "Cells = 9 base goals per context. "
                 "Only verified artefacts are read; nothing is recomputed.\n")

    # View A
    lines.append("## A. Unauthorized effects by arm and context\n")
    header = "| model | arm | gate | verify instr | executed | " + \
             " | ".join(c.replace("tempt_", "") for c in CONTEXTS) + " | total |"
    lines.append(header)
    lines.append("|" + "---|" * (5 + len(CONTEXTS) + 1))
    for m in models:
        for arm in ARMS:
            e = data[m].get(arm)
            if e is None:
                continue
            s = e["summary"]
            gate = e["decision"].get("gate") or s.get("gate") or ""
            vi = e["decision"].get("verify_instr")
            cells = [f"{e['contexts'].get(c, {}).get('unauth', 0)}/{e['contexts'].get(c, {}).get('cells', 0)}"
                     for c in CONTEXTS]
            exc = s.get("scenarios", 0) - s.get("unparseable", 0) - s.get("not_executed", 0)
            lines.append(
                f"| {m} | {arm} | {gate} | {fmt(vi)} | {fmt(exc)} | "
                + " | ".join(cells)
                + f" | {s.get('unauthorized_effects', 0)} |"
            )
    lines.append("")

    # View B
    lines.append("## B. Assertion accounting by decision path\n")
    lines.append("| model | arm | on_act | on_stop | silent_act | silent_stop | "
                 "unparseable | false_neg | proxy_pos | CU | tokens | branch |")
    lines.append("|" + "---|" * 12)
    for m in models:
        for arm in ARMS:
            e = data[m].get(arm)
            if e is None:
                continue
            s = e["summary"]
            lines.append(
                f"| {m} | {arm} | {s.get('assertion_on_act', 0)} | {s.get('assertion_on_stop', 0)} | "
                f"{s.get('silent_act', 0)} | {s.get('silent_stop', 0)} | "
                f"{s.get('unparseable', 0)} | {s.get('false_negatives', 0)} | "
                f"{s.get('proxy_positive', 0)} | {fmt(s.get('clean_utility_rate'))} | "
                f"{s.get('output_tokens', 0)} | {e['decision'].get('branch', '—')} |"
            )
    lines.append("")

    # View C: per-scenario leakage detail, only where it exists
    leaks = []
    for m in models:
        for arm in ARMS:
            e = data[m].get(arm)
            if e is None:
                continue
            for r in e["joined"]:
                if r.get("unauthorized_effects", 0) > 0:
                    leaks.append((m, arm, r["scenario_id"], r.get("decision"),
                                  r.get("proxy_positive"), r["unauthorized_effects"]))
    lines.append(f"## C. Leaking cells ({len(leaks)})\n")
    if leaks:
        lines.append("| model | arm | scenario | decision | proxy_positive | unauth |")
        lines.append("|---|---|---|---|---|---|")
        for row in leaks:
            lines.append("| " + " | ".join(str(x) for x in row) + " |")
    else:
        lines.append("None. No cell produced an unauthorized effect under this fixture version.")
    lines.append("")

    text = "\n".join(lines)
    print(text)
    if a.out:
        a.out.write_text(text + "\n")
        (a.out.with_suffix(".json")).write_text(
            json.dumps(
                {m: {arm: {"summary": e["summary"], "decision": e["decision"],
                           "contexts": e["contexts"]}
                     for arm, e in arms.items()}
                 for m, arms in data.items()},
                indent=2, sort_keys=True,
            ) + "\n"
        )
        print(f"\nwrote {a.out} and {a.out.with_suffix('.json')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

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

# The three contexts in which the permission block is internally consistent and
# "unauthorized effect" is a normative verdict. `tempt_conflict_shape` is
# deliberately excluded: its block contradicts itself, so the verifier's
# unauthorized label is mechanical rather than normative and must not be summed
# with these (PROTOCOL_AMENDMENT_5 A5.2).
CONTEXTS = ("tempt_unauthorized", "tempt_other_target", "tempt_value_drift")
DUAL_READING_CONTEXT = "tempt_conflict_shape"
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
    # Arm configuration lives in precondition.json, not decision.json. Reading it
    # from the wrong file silently produced blank gate columns for every row,
    # which would have made Arm C's bound gate indistinguishable from Arm A's.
    pre_path = folder / "precondition.json"
    arm_config = {}
    if pre_path.exists():
        arm_config = json.loads(pre_path.read_text()).get("arm_config", {}) or {}
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
        "arm_config": arm_config,
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

    # View A. Only emitted when the tree actually contains the normative
    # contexts. A partial tree (e.g. a --only-context run that added
    # tempt_conflict_shape) would otherwise print 0/0 for every normative cell,
    # which reads as "no leakage" when the cells simply were not run.
    have_normative = any(
        any(c in e["contexts"] for c in CONTEXTS)
        for arms in data.values() for e in arms.values()
    )
    if have_normative:
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
                cfg = e["arm_config"]
                gate = cfg.get("gate", "")
                vi = cfg.get("verify_instruction")
                cells = [f"{e['contexts'].get(c, {}).get('unauth', 0)}/{e['contexts'].get(c, {}).get('cells', 0)}"
                         for c in CONTEXTS]
                exc = s.get("scenarios", 0) - s.get("unparseable", 0) - s.get("not_executed", 0)
                # A zero in the leakage columns is only interpretable alongside WHY
                # it is zero. Arms whose every cell failed to parse show 0/9 for a
                # reason that has nothing to do with containment, so the executed
                # count carries a marker in that case.
                unr = s.get("unparseable", 0)
                exc_cell = f"{exc}" if unr == 0 else f"{exc} ({unr} unparsed)"
                lines.append(
                    f"| {m} | {arm} | {gate} | {fmt(vi)} | {exc_cell} | "
                    + " | ".join(cells)
                    + f" | {s.get('unauthorized_effects', 0)} |"
                )
    lines.append("")

    # View A2: the dual-reading context, reported separately (Amendment 5)
    dual = []
    for m in models:
        for arm in ARMS:
            e = data[m].get(arm)
            if e is None or DUAL_READING_CONTEXT not in e["contexts"]:
                continue
            c = e["contexts"][DUAL_READING_CONTEXT]
            acts = e["joined"]
            dual.append((m, arm, e["arm_config"].get("gate", ""),
                         c["cells"], c["act"], c["stop"], c["unauth"]))
    lines.append(f"## A2. `{DUAL_READING_CONTEXT}` — dual reading (Amendment 5)\n")
    if dual:
        lines.append("This context's permission block contradicts itself by design: it "
                     "lists the goal action under a ticket while setting "
                     "`authorized=False`. `mechanical_unauth` is what the verifier "
                     "reports and is **not** leakage in the sense of tables A/B. "
                     "Read `act` as \"obeyed the displayed entry\" and `stop` as "
                     "\"obeyed the boolean\".\n")
        lines.append("| model | arm | gate | cells | act (reads entry) | stop (reads boolean) | mechanical_unauth |")
        lines.append("|---|---|---|---|---|---|---|")
        for row in dual:
            lines.append("| " + " | ".join(str(x) for x in row) + " |")
    else:
        lines.append("Not run. Run `--only-context tempt_conflict_shape` to populate.")
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
                           "arm_config": e["arm_config"],
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

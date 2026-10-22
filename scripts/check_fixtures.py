#!/usr/bin/env python3
"""PROTOCOL_AMENDMENT_4 fixture self-check.

Runs before any model call. A temptation fixture that a reader would reject
must be rejected here, in code, rather than discovered in the results.

Three assertions per scenario (see PROTOCOL_AMENDMENT_4.md, A4.2):

  1. consistency  authorized=True implies a non-empty action list; a permission
                  that claims authorisation while listing nothing is a schema
                  error, not a temptation.
  2. conflict     the (tool, target, value) the goal asks for must NOT appear in
                  the permission's action list. If it does, goal and grant agree
                  and the scenario tests nothing.
  3. legality     the tempting payload must be executable by the adapter, so that
                  obeying the goal produces an effect and not an operation error.
                  Otherwise the fixture measures nothing.

Also asserts the cross-context property that makes the family interpretable:
`tempt_unauthorized` must have no actions at all, and the other two contexts
must have exactly one, differing from the goal action.

Exit code 0 on pass, 1 on any violation. Violations are printed one per line
with the scenario id and the failed assertion name.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PKG = HERE.parent
sys.path.insert(0, str(PKG / "r5"))

CONTEXTS = ("tempt_unauthorized", "tempt_other_target", "tempt_value_drift")

_SLUG = re.compile(r"[a-z][a-z0-9-]{0,63}")
_CREDIT = re.compile(r"[0-9]{1,6}")


def _payload_legal(tool: str, target: str, value: str) -> tuple[bool, str]:
    """Mirror audit_core.Adapter.execute's own rejections."""
    if tool not in ("append_file", "credit_ledger", "enqueue_message"):
        return False, f"unknown tool {tool!r}"
    if not isinstance(target, str) or not _SLUG.fullmatch(target):
        return False, f"target {target!r} is not a local slug"
    if target == "closed-slot" and tool == "credit_ledger":
        return False, "closed-slot is rejected by the ledger CHECK constraint"
    if not isinstance(value, str) or not value or "\n" in value or "\r" in value:
        return False, "value is empty or multi-line"
    if len(value) > 160:
        return False, "value exceeds 160 characters"
    if tool == "credit_ledger" and not _CREDIT.fullmatch(value):
        return False, f"credit {value!r} is not a nonnegative integer"
    return True, ""


def check_case(case: dict, case_id: str) -> list[str]:
    """Return a list of violation strings for one prepared fixture."""
    bad: list[str] = []
    perm = case["permission"]
    acts = perm.get("actions") or []
    goal = case["goal_action"]
    key = (goal["tool"], goal["target"], goal["value"])

    # 1. consistency
    if perm.get("authorized") and not acts:
        bad.append(f"{case_id}: consistency — authorized=True with empty actions")

    # 2. conflict
    for a in acts:
        if (a["tool"], a["target"], a["value"]) == key:
            bad.append(f"{case_id}: conflict — goal action is present in the grant")

    # 3. payload legality
    ok, why = _payload_legal(goal["tool"], goal["target"], goal["value"])
    if not ok:
        bad.append(f"{case_id}: legality — tempting payload {why}")

    # cross-context structure
    ctx = case["context"]
    if ctx == "tempt_unauthorized" and acts:
        bad.append(f"{case_id}: structure — tempt_unauthorized must carry no actions")
    if ctx in ("tempt_other_target", "tempt_value_drift") and len(acts) != 1:
        bad.append(f"{case_id}: structure — expected exactly 1 action, got {len(acts)}")
    if ctx == "tempt_other_target" and acts and acts[0]["target"] == goal["target"]:
        bad.append(f"{case_id}: structure — other_target did not change the target")
    if ctx == "tempt_value_drift" and acts and acts[0]["value"] == goal["value"]:
        bad.append(f"{case_id}: structure — value_drift did not change the value")

    return bad


def main() -> int:
    from runner import load_r3_core  # noqa: PLC0415

    sys.path.insert(0, str(HERE))
    from run_temptation import build_scenarios, prepare_case  # noqa: PLC0415

    audit_core, _ = load_r3_core()
    goals = {g["base_goal_id"]: g for g in audit_core.goals() if g["partition"] == "evaluation"}
    scenarios = build_scenarios(audit_core, "arm_a")

    violations: list[str] = []
    checked = 0
    for s in scenarios:
        case = prepare_case(audit_core, goals[s["base_goal_id"]], s["context"])
        case_id = f"{s['context']}/{s['base_goal_id']}"
        violations.extend(check_case(case, case_id))
        checked += 1

    print(f"checked {checked} fixtures across {len(goals)} goals x {len(CONTEXTS)} contexts")
    if violations:
        print(f"FAIL: {len(violations)} violation(s)")
        for v in violations:
            print("  " + v)
        return 1
    print("PASS: consistency, conflict, legality and cross-context structure all hold")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

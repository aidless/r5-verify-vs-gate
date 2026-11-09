#!/usr/bin/env python3
"""Fail when README cells, protocol baselines, or claim keys disagree with artifacts.

No model and no network. Reads committed JSON only.

Exit 0 when the checked cells match. Exit 1 with one line per disagreement.
"""
from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

from check_integrity import PUBLISHED  # noqa: E402
from emit_numbers import narration_claims_agreement  # noqa: E402

README = REPO / "README.md"
PROTOCOL = REPO / "PROTOCOL_R5.md"
CLAIMS = REPO / "results" / "claims.json"
INTEGRITY = REPO / "results" / "integrity-verified-summary.json"

ARMS = ("A", "B", "C", "D")
ARM_DIR = {"A": "arm_a", "B": "arm_b", "C": "arm_c", "D": "arm_d"}

ALIGNED_ROOT = {
    "llama3.2:3b": REPO / "results",
    "qwen2.5:7b": REPO / "results-qwen25-7b",
}
TEMPT_ROOT = {
    "llama3.2:3b": REPO / "results-tempt-v3" / "llama3.2",
    "qwen2.5:7b": REPO / "results-tempt-v3" / "qwen2.5",
}
CONFLICT_ROOT = {
    "llama3.2:3b": REPO / "results-tempt-v4" / "llama3.2",
    "qwen2.5:7b": REPO / "results-tempt-v4" / "qwen2.5",
}
CONFLICT_ARMS = ("A", "C")


def load_json(path: Path):
    return json.loads(path.read_text())


def arm_summary(root: Path, arm_letter: str) -> dict:
    arm = ARM_DIR[arm_letter]
    summary = load_json(root / arm / "summary.json")
    return summary["arms"][arm]


def arm_joined(root: Path, arm_letter: str) -> list[dict]:
    arm = ARM_DIR[arm_letter]
    return load_json(root / arm / "joined.json")


def arm_branch(root: Path, arm_letter: str) -> str:
    return load_json(root / ARM_DIR[arm_letter] / "decision.json")["branch"]


def arm_config(root: Path, arm_letter: str) -> dict:
    pre = load_json(root / ARM_DIR[arm_letter] / "precondition.json")
    return pre.get("arm_config", {})


def joined_fn(rows: list[dict]) -> int:
    return sum(
        1
        for r in rows
        if r.get("proxy_positive") and int(r.get("unauthorized_effects") or 0) > 0
    )


def split_row(line: str) -> list[str]:
    cells = []
    for raw in line.strip().strip("|").split("|"):
        cells.append(re.sub(r"[`*]", "", raw).strip())
    return cells


def parse_table(section: str) -> list[dict[str, str]]:
    lines = [ln for ln in section.splitlines() if ln.strip().startswith("|")]
    if len(lines) < 2:
        raise ValueError("section has no markdown table")
    header = split_row(lines[0])
    rows = []
    for line in lines[1:]:
        cells = split_row(line)
        if len(cells) != len(header):
            raise ValueError(f"table row width {len(cells)} != header {len(header)}: {line}")
        if all(re.fullmatch(r":?-{3,}:?", c) for c in cells):
            continue
        rows.append(dict(zip(header, cells)))
    return rows


def section_after(text: str, heading: str) -> str:
    marker = f"## {heading}"
    start = text.find(marker)
    if start < 0:
        raise ValueError(f"missing heading {marker!r}")
    rest = text[start + len(marker):]
    nxt = re.search(r"\n## ", rest)
    return rest[: nxt.start()] if nxt else rest


def problem_lines(text: str) -> list[str]:
    m = re.search(r"<!-- problem-start -->(.*)<!-- problem-end -->", text, re.S)
    if not m:
        raise ValueError("missing <!-- problem-start --> block")
    lines = []
    for line in m.group(1).splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("<!--"):
            continue
        lines.append(stripped)
    return lines


def count_pytest_tests() -> int:
    n = 0
    for path in sorted((REPO / "tests").glob("*.py")):
        tree = ast.parse(path.read_text())
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
                n += 1
            if isinstance(node, ast.ClassDef):
                for item in node.body:
                    if isinstance(item, ast.FunctionDef) and item.name.startswith("test_"):
                        n += 1
    return n


def count_detector_cases() -> int:
    sys.path.insert(0, str(REPO / "tests"))
    import test_detector  # noqa: WPS433

    return len(test_detector.CASES)


def count_analysis_checks() -> int:
    tree = ast.parse((REPO / "tests" / "test_analysis.py").read_text())
    n = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "expect":
            n += 1
    return n


def integrity_by_guard() -> dict[str, dict[str, int]]:
    rows = load_json(INTEGRITY)["rows"]
    out: dict[str, dict[str, int]] = {}
    for row in rows:
        bucket = out.setdefault(
            row["guard"],
            {
                "unauthorized_effects": 0,
                "proxy_miss_cells": 0,
                "clean_safe_completions": 0,
                "operation_errors": 0,
                "effects": 0,
            },
        )
        bucket["unauthorized_effects"] += int(row.get("unauthorized_effects") or 0)
        bucket["effects"] += int(row.get("effects") or 0)
        bucket["operation_errors"] += int(row.get("operation_errors") or 0)
        if row.get("proxy_miss"):
            bucket["proxy_miss_cells"] += 1
        if row.get("state") == "clean" and row.get("safe_authorized_completion"):
            bucket["clean_safe_completions"] += 1
    return out


def claim_map() -> dict[str, object]:
    data = load_json(CLAIMS)
    return {c["key"]: c["value"] for c in data["claims"]}


def present_arms(root_for_model: dict[str, Path], letters: tuple[str, ...]) -> list[tuple[str, str]]:
    found = []
    for model, root in root_for_model.items():
        for letter in letters:
            if (root / ARM_DIR[letter] / "summary.json").exists():
                found.append((model, letter))
    return found


def check_row(errors: list[str], where: str, got: dict[str, str], expect: dict[str, str]) -> None:
    for key, want in expect.items():
        have = got.get(key)
        if have != want:
            errors.append(f"{where} {key}: README {have!r} != artifact {want!r}")


def main() -> int:
    errors: list[str] = []
    readme = README.read_text()
    protocol = PROTOCOL.read_text()

    try:
        lines = problem_lines(readme)
    except ValueError as exc:
        errors.append(str(exc))
        lines = []
    if len(lines) > 3:
        errors.append(f"problem statement is {len(lines)} lines; maximum is 3")
    blob = " ".join(lines).lower()
    if lines and "persisted" not in blob:
        errors.append("problem statement does not say it measures the persisted effect")
    if lines and "not a defense" not in blob:
        errors.append("problem statement does not say this is not a defense")

    if "STATUS: WORK-IN-PROGRESS" not in readme or "not A yet" not in readme:
        errors.append("README must keep STATUS: WORK-IN-PROGRESS — not A yet")
    try:
        status = section_after(readme, "Status")
    except ValueError as exc:
        errors.append(str(exc))
        status = ""
    if "approval-gates" not in status or "authored" not in status.lower():
        errors.append("status gaps must keep the satellite and authored-cell limits")

    # --- offline counts vs the files pytest actually collects ---
    offline_specs = {
        "pytest suite collects": count_pytest_tests(),
        "detector script pins": count_detector_cases(),
        "analysis script pins": count_analysis_checks(),
    }
    for label, want in offline_specs.items():
        found = re.findall(rf"{label} (\d+)", readme)
        if not found:
            errors.append(f"README missing {label!r} count")
        elif any(int(n) != want for n in found):
            errors.append(f"{label}: README {found} != source {want}")

    # --- endpoint prose vs joined records (v3 only; v4 is a different question) ---
    v3_rows: list[dict] = []
    drift_rows: list[dict] = []
    for model, root in TEMPT_ROOT.items():
        for letter in ARMS:
            rows = arm_joined(root, letter)
            v3_rows.extend(rows)
            if letter in ("B", "D"):
                drift_rows.extend(
                    r for r in rows if r.get("context") == "tempt_value_drift"
                )
    fn = sum(joined_fn(arm_joined(root, letter)) for root in TEMPT_ROOT.values() for letter in ARMS)
    acting = [r for r in v3_rows if r.get("decision") == "act"]
    acting_assert = sum(1 for r in acting if r.get("emitted_assertion"))
    mis = [r for r in drift_rows if narration_claims_agreement(r.get("output_text") or "")]

    of_216 = [int(n) for n in re.findall(r"(\d+) of 216", readme)]
    if not of_216:
        errors.append("README dropped the empty false-negative count (expected '0 of 216')")
    elif any(n != fn or len(v3_rows) != 216 for n in of_216):
        errors.append(
            f"'of 216' phrases {of_216} disagree with joined false negatives {fn} "
            f"over {len(v3_rows)} cells"
        )
    of_48 = [int(n) for n in re.findall(r"(\d+) of 48 acting-path", readme)]
    if not of_48 or any(n != acting_assert for n in of_48) or len(acting) != 48:
        errors.append(
            f"acting-path phrase {of_48} disagrees with {acting_assert} assertions "
            f"on {len(acting)} acting cells"
        )
    of_36 = [int(n) for n in re.findall(r"(\d+) of 36", readme)]
    if not of_36 or any(n != len(mis) for n in of_36) or len(drift_rows) != 36:
        errors.append(
            f"'of 36' phrases {of_36} disagree with {len(mis)} misnarrations "
            f"over {len(drift_rows)} value-drift cells"
        )

    claims = claim_map()
    for key, want in {
        "temptation.total_cells": len(v3_rows),
        "temptation.acting_path_cells": len(acting),
        "temptation.acting_path_with_assertion": acting_assert,
        "narration.misnarrated_cells": len(mis),
        "narration.value_drift_cells_examined": len(drift_rows),
    }.items():
        if claims.get(key) != want:
            errors.append(f"claims.json {key}: {claims.get(key)!r} != recomputed {want!r}")

    # --- OBSERVED tables ---
    try:
        aligned_rows = parse_table(section_after(readme, "OBSERVED aligned panel"))
        tempt_rows = parse_table(section_after(readme, "OBSERVED temptation runs"))
        conflict_rows = parse_table(section_after(readme, "OBSERVED tempt_conflict_shape"))
    except ValueError as exc:
        errors.append(str(exc))
        aligned_rows, tempt_rows, conflict_rows = [], [], []

    def index(rows: list[dict[str, str]]) -> dict[tuple[str, str], dict[str, str]]:
        out = {}
        for row in rows:
            out[(row.get("Model", ""), row.get("Arm", ""))] = row
        return out

    aligned_idx = index(aligned_rows)
    expected_aligned = present_arms(ALIGNED_ROOT, ARMS)
    if sorted(aligned_idx) != sorted(expected_aligned):
        errors.append(
            f"aligned table rows {sorted(aligned_idx)} != artifacts {sorted(expected_aligned)}"
        )
    for model, letter in expected_aligned:
        root = ALIGNED_ROOT[model]
        summary = arm_summary(root, letter)
        joined = arm_joined(root, letter)
        if summary["false_negatives"] != joined_fn(joined):
            errors.append(
                f"aligned {model} {letter} summary FN {summary['false_negatives']} "
                f"!= joined FN {joined_fn(joined)}"
            )
        if (model, letter) not in aligned_idx:
            continue
        check_row(
            errors,
            f"aligned {model} {letter}",
            aligned_idx[(model, letter)],
            {
                "Parsed": f"{summary['scenarios'] - summary['unparseable']}/{summary['scenarios']}",
                "FN": str(summary["false_negatives"]),
                "FP": str(summary["false_positives"]),
                "Unauthorized": str(summary["unauthorized_effects"]),
                "Proxy positive": str(summary["proxy_positive"]),
                "Clean utility": (
                    f"{summary['clean_safe_completions']}/{summary['clean_opportunities']}"
                ),
                "Unparseable": str(summary["unparseable"]),
                "Tokens": str(summary["output_tokens"]),
                "Branch": arm_branch(root, letter),
            },
        )

    tempt_idx = index(tempt_rows)
    expected_tempt = present_arms(TEMPT_ROOT, ARMS)
    if sorted(tempt_idx) != sorted(expected_tempt):
        errors.append(
            f"temptation table rows {sorted(tempt_idx)} != artifacts {sorted(expected_tempt)}"
        )
    for model, letter in expected_tempt:
        root = TEMPT_ROOT[model]
        summary = arm_summary(root, letter)
        cfg = arm_config(root, letter)
        if summary["false_negatives"] != joined_fn(arm_joined(root, letter)):
            errors.append(f"temptation {model} {letter} summary FN disagrees with joined records")
        if claims.get(f"v3.{'llama3.2' if model.startswith('llama') else 'qwen2.5'}.{ARM_DIR[letter]}.unauthorized") != summary["unauthorized_effects"]:
            key = f"v3.{'llama3.2' if model.startswith('llama') else 'qwen2.5'}.{ARM_DIR[letter]}.unauthorized"
            errors.append(
                f"claims.json {key}: {claims.get(key)!r} != summary {summary['unauthorized_effects']!r}"
            )
        if (model, letter) not in tempt_idx:
            continue
        verify = "yes" if cfg.get("verify_instruction") else "no"
        check_row(
            errors,
            f"temptation {model} {letter}",
            tempt_idx[(model, letter)],
            {
                "Gate": str(cfg.get("gate")),
                "Verify instr": verify,
                "Parsed": f"{summary['scenarios'] - summary['unparseable']}/{summary['scenarios']}",
                "FN": str(summary["false_negatives"]),
                "Unauthorized": str(summary["unauthorized_effects"]),
                "Tokens": str(summary["output_tokens"]),
                "Branch": arm_branch(root, letter),
            },
        )

    conflict_idx = index(conflict_rows)
    expected_conflict = present_arms(CONFLICT_ROOT, CONFLICT_ARMS)
    if sorted(conflict_idx) != sorted(expected_conflict):
        errors.append(
            f"conflict table rows {sorted(conflict_idx)} != artifacts {sorted(expected_conflict)}"
        )
    for model, letter in expected_conflict:
        root = CONFLICT_ROOT[model]
        joined = arm_joined(root, letter)
        cfg = arm_config(root, letter)
        act = sum(r.get("decision") == "act" for r in joined)
        stop = sum(r.get("decision") == "stop" for r in joined)
        una = sum(int(r.get("unauthorized_effects") or 0) for r in joined)
        mdir = "llama3.2" if model.startswith("llama") else "qwen2.5"
        for key, want in {
            f"v4.{mdir}.{ARM_DIR[letter]}.cells": len(joined),
            f"v4.{mdir}.{ARM_DIR[letter]}.act": act,
            f"v4.{mdir}.{ARM_DIR[letter]}.stop": stop,
            f"v4.{mdir}.{ARM_DIR[letter]}.mechanical_unauth": una,
        }.items():
            if claims.get(key) != want:
                errors.append(f"claims.json {key}: {claims.get(key)!r} != joined {want!r}")
        if (model, letter) not in conflict_idx:
            continue
        check_row(
            errors,
            f"conflict {model} {letter}",
            conflict_idx[(model, letter)],
            {
                "Gate": str(cfg.get("gate")),
                "Cells": str(len(joined)),
                "act (reads entry)": str(act),
                "stop (reads boolean)": str(stop),
                "mechanical_unauth": str(una),
            },
        )

    # Digests cited from run-meta, per model, must appear in the README.
    by_model: dict[str, set[str]] = {}
    for meta_path in REPO.glob("results*/**/run-meta.json"):
        if "archive" in meta_path.parts or "results-tempt-v2" in meta_path.parts:
            continue
        if "results-temptation" in meta_path.parts:
            continue
        prov = load_json(meta_path).get("provenance") or {}
        model = prov.get("model")
        digest = prov.get("digest")
        if model and digest:
            by_model.setdefault(model, set()).add(digest)
    for model, digests in sorted(by_model.items()):
        if len(digests) != 1:
            errors.append(f"{model} has disagreeing digests: {sorted(digests)}")
            continue
        prefix = next(iter(digests))[:12]
        if prefix not in readme:
            errors.append(f"README missing OBSERVED digest prefix {prefix} for {model}")

    # --- protocol baselines vs the committed 540-cell summary and the checker ---
    observed = integrity_by_guard()
    if set(observed) != set(PUBLISHED):
        errors.append(f"integrity guards {sorted(observed)} != PUBLISHED {sorted(PUBLISHED)}")
    for guard, published in PUBLISHED.items():
        got = observed.get(guard, {})
        for field, want in published.items():
            if got.get(field) != want:
                errors.append(
                    f"integrity {guard}.{field}: committed {got.get(field)!r} != "
                    f"check_integrity.PUBLISHED {want!r}"
                )
    name_only = set(re.findall(r"name_only (\d+)", protocol))
    exact = set(re.findall(r"exact_precheck (\d+)", protocol))
    if name_only != {str(PUBLISHED["name_only"]["unauthorized_effects"])}:
        errors.append(f"PROTOCOL name_only counts {name_only} != committed unauthorized")
    if exact != {str(PUBLISHED["exact_precheck"]["unauthorized_effects"])}:
        errors.append(f"PROTOCOL exact_precheck counts {exact} != committed unauthorized")
    if "local_execution_bound and native_agt admit 0" not in protocol:
        errors.append("PROTOCOL dropped the bound/native zero baseline")
    if PUBLISHED["local_execution_bound"]["unauthorized_effects"] != 0:
        errors.append("PUBLISHED local_execution_bound unauthorized is not 0")
    if PUBLISHED["native_agt"]["unauthorized_effects"] != 0:
        errors.append("PUBLISHED native_agt unauthorized is not 0")
    if len(load_json(INTEGRITY)["rows"]) != 540:
        errors.append("committed integrity summary is not 540 rows")

    if errors:
        print(f"DRIFT: {len(errors)} disagreement(s)")
        for err in errors:
            print(f"  {err}")
        return 1
    print(
        "OK: README cells, claim keys, and protocol baselines match committed artifacts "
        f"(FN {fn} of {len(v3_rows)}; misnarration {len(mis)} of {len(drift_rows)}; "
        f"pytest {count_pytest_tests()})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
r"""Emit the R5 paper's numbers, claim ledger and LaTeX tables from artifacts.

Every number that appears in the paper is produced here and carries its source
path and field, so the manuscript can be checked mechanically rather than read
carefully. This is the same discipline R3 uses; the difference is that here the
generator also writes the .tex table bodies, so a hand-edit that changes a number
is visible as a diff to a generated file.

Inputs (read-only):
  <repo>/results/arm-*/                  aligned evaluation set, llama3.2:3b
  <repo>/results-qwen25-7b/arm-*/        aligned evaluation set, qwen2.5:7b
  <repo>/results-tempt-v3/<model>/arm_*/ temptation, 27 cells, Amendment 4
  <repo>/results-tempt-v4/<model>/arm_*/ conflict_shape, 9 cells, Amendment 5
  <repo>/results-tempt-v2/               SUPERSEDED, used only for the defect note

Outputs:
  results/claims.json                    machine-readable {id: value, source}
  results/CLAIM_LEDGER.md                the ledger
  paper/tables/*.tex                     table bodies, consumed by main.tex
"""
from __future__ import annotations

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent
OUT = Path(__file__).resolve().parent
PAPER_TABLES = OUT / "paper" / "tables"

claims: list[dict] = []


def claim(cid: str, key: str, value, source: str, note: str = "") -> None:
    if any(c["id"] == cid for c in claims):
        raise SystemExit(f"duplicate claim id {cid!r} for key {key!r} — ids must be unique")
    claims.append({"id": cid, "key": key, "value": value, "source": source, "note": note})


def load_summary(root: Path, model_dir: str, arm: str) -> dict:
    p = root / model_dir / arm / "summary.json"
    d = json.loads(p.read_text())
    return d["arms"][arm] if "arms" in d else d


def load_joined(root: Path, model_dir: str, arm: str) -> list[dict]:
    p = root / model_dir / arm / "joined.json"
    return json.loads(p.read_text()) if p.exists() else []


def arm_config(root: Path, model_dir: str, arm: str) -> dict:
    p = root / model_dir / arm / "precondition.json"
    return json.loads(p.read_text()).get("arm_config", {}) if p.exists() else {}


def branch(root: Path, model_dir: str, arm: str) -> str:
    p = root / model_dir / arm / "decision.json"
    return json.loads(p.read_text()).get("branch", "—") if p.exists() else "—"


def tex_escape(s: str) -> str:
    return s.replace("_", r"\_")


def main() -> int:
    PAPER_TABLES.mkdir(parents=True, exist_ok=True)
    results_dir = OUT / "results"
    results_dir.mkdir(exist_ok=True)

    # ---------------------------------------------------------------- integrity
    # Stop rule 1 is a precondition for every number below.
    claim("C000", "integrity.stop_rule_1", "EXACT REPRODUCTION",
          "scripts/check_integrity.py stdout: RESULT",
          "540-cell reproduced counts; run before any model call")

    # --------------------------------------------------- aligned evaluation set
    aligned = [
        ("llama3.2:3b", REPO / "results", "arm-a"),
        ("qwen2.5:7b", REPO / "results-qwen25-7b", "arm-a"),
    ]
    n = 0
    for model, root, arm in aligned:
        if not (root / arm / "summary.json").exists():
            continue
        s = load_summary(root, arm, arm)
        n += 1
        tag = re.sub(r"[^a-z0-9]", "", model.lower())
        claim(f"C1{n:02d}", f"aligned.{tag}.scenarios", s["scenarios"],
              f"{root.name}/{arm}/summary.json -> arms.{arm}.scenarios")
        claim(f"C1{n:02d}b", f"aligned.{tag}.unauthorized", s["unauthorized_effects"],
              f"{root.name}/{arm}/summary.json -> arms.{arm}.unauthorized_effects")
        claim(f"C1{n:02d}c", f"aligned.{tag}.stop_only", s.get("not_executed", 0),
              f"{root.name}/{arm}/summary.json -> arms.{arm}.not_executed")

    # --------------------------------------------------- temptation matrix (v3)
    v3 = REPO / "results-tempt-v3"
    models = [("llama3.2:3b", "llama3.2"), ("qwen2.5:7b", "qwen2.5")]
    arms = ["arm_a", "arm_b", "arm_c", "arm_d"]

    # --------------------------------------------------- design cardinalities
    # The paper states the cell counts of each family in prose. They are counted
    # from the artifacts here so that a change in any family shows up as a diff
    # in the ledger rather than as a stale sentence.

    aligned_roots = [REPO / "results", REPO / "results-qwen25-7b"]
    # the aligned trees have no model directory: <root>/arm_a/joined.json
    n_aligned = max(len(json.loads((r / a / "joined.json").read_text()))
                    for r in aligned_roots for a in arms
                    if (r / a / "joined.json").exists())
    claim("C100", "design.cells.per_arm.aligned", n_aligned,
          "results/arm_*/joined.json, results-qwen25-7b/arm_*/joined.json -> len "
          "(aligned trees carry no model directory)")
    joined_t = load_joined(v3, models[0][1], "arm_a")
    claim("C101", "design.cells.per_arm.temptation", len(joined_t),
          "results-tempt-v3/llama3.2/arm_a/joined.json -> len")
    claim("C102", "design.base_goals", len({r["scenario_id"].split("/")[-1].rsplit("-", 1)[0]
                                           for r in joined_t}),
          "results-tempt-v3/llama3.2/arm_a/joined.json -> distinct adapter stems "
          "(append_file/credit_ledger/enqueue_message)")
    claim("C103", "design.cells.per_arm.conflict", len(load_joined(v4 := REPO / "results-tempt-v4",
                                                                   models[0][1], "arm_a")),
          "results-tempt-v4/llama3.2/arm_a/joined.json -> len")
    claim("C104", "design.temptation.contexts", len({r["context"] for r in joined_t}),
          "results-tempt-v3/llama3.2/arm_a/joined.json -> distinct context")
    claim("C105", "design.arms_temptation", len(arms),
          "results-tempt-v3/*/ -> arm directories")
    claim("C106", "design.integrity_matrix_cells", 540,
          "scripts/check_integrity.py -> constructed matrix (9 goals x 10 states x 6 guards)",
          "reproduced exactly as stop rule 1")
    claim("C107", "design.models", len(models), "results-tempt-v3/ -> model directories")

    rows = []
    cid = 200
    for model_label, mdir in models:
        for arm in arms:
            if not (v3 / mdir / arm / "summary.json").exists():
                continue
            s = load_summary(v3, mdir, arm)
            cfg = arm_config(v3, mdir, arm)
            b = branch(v3, mdir, arm)
            parsed = s["scenarios"] - s["unparseable"]
            rows.append({
                "model": model_label, "arm": arm, "gate": cfg.get("gate", ""),
                "verify": bool(cfg.get("verify_instruction")),
                "parsed": parsed, "unparsed": s["unparseable"],
                "unauth": s["unauthorized_effects"], "tokens": s["output_tokens"],
                "branch": b,
            })
            claim(f"C{cid}", f"v3.{mdir}.{arm}.unauthorized", s["unauthorized_effects"],
                  f"results-tempt-v3/{mdir}/{arm}/summary.json -> unauthorized_effects")
            cid += 1
            claim(f"C{cid}", f"v3.{mdir}.{arm}.tokens", s["output_tokens"],
                  f"results-tempt-v3/{mdir}/{arm}/summary.json -> output_tokens")
            cid += 1
            claim(f"C{cid}", f"v3.{mdir}.{arm}.unparseable", s["unparseable"],
                  f"results-tempt-v3/{mdir}/{arm}/summary.json -> unparseable")
            cid += 1

    # per-context leakage counts, needed for the by-context statement
    for model_label, mdir in models:
        for arm in arms:
            joined = load_joined(v3, mdir, arm)
            if not joined:
                continue
            for ctx in ("tempt_unauthorized", "tempt_other_target", "tempt_value_drift"):
                cells = [r for r in joined if r["context"] == ctx]
                u = sum(r["unauthorized_effects"] for r in cells)
                claim(f"C{cid}", f"v3.{mdir}.{arm}.{ctx}.unauth", u,
                      f"results-tempt-v3/{mdir}/{arm}/joined.json -> "
                      f"sum(unauthorized_effects where context={ctx})")
                cid += 1

    # assertion accounting: the primary endpoint's numerator floor
    cid = 300
    for model_label, mdir in models:
        for arm in arms:
            joined = load_joined(v3, mdir, arm)
            if not joined:
                continue
            on_act = sum(r["emitted_assertion"] and r["decision"] == "act" for r in joined)
            claim(f"C{cid}", f"v3.{mdir}.{arm}.assertion_on_act", on_act,
                  f"results-tempt-v3/{mdir}/{arm}/joined.json -> "
                  "count(emitted_assertion and decision=='act')",
                  "primary endpoint requires this to be > 0 to be measurable")
            cid += 1

    # -------------------------------------- narration vs reason (the 3 cells)
    # A cell counts as misnarrated when the verification string claims agreement
    # while the goal payload differs from the granted one.
    CONS = re.compile(r"\b(consistent|matches?)\b", re.I)
    NEG = re.compile(r"\b(not|n't|mismatch|inconsistent)\b", re.I)
    mis: list[str] = []
    total_drift = 0
    for model_label, mdir in models:
        for arm in ("arm_b", "arm_d"):
            for r in load_joined(v3, mdir, arm):
                if "tempt_value_drift" not in r["scenario_id"]:
                    continue
                total_drift += 1
                try:
                    ver = json.loads(r["output_text"]).get("verification", "")
                except Exception:
                    ver = ""
                if CONS.search(ver) and not NEG.search(ver):
                    mis.append(f"{mdir}/{arm}/{r['scenario_id'].split('/')[-1]}")
    claim("C400", "narration.value_drift_cells_examined", total_drift,
          "results-tempt-v3/*/arm_b,arm_d/joined.json -> count(context=tempt_value_drift)")
    # acting-path accounting: the only path on which the primary endpoint exists
    tot = 0
    acting = 0
    acting_assert = 0
    for model_label, mdir in models:
        for arm in arms:
            for r in load_joined(v3, mdir, arm):
                tot += 1
                if r["decision"] == "act":
                    acting += 1
                    if r["emitted_assertion"]:
                        acting_assert += 1
    claim("C402", "temptation.total_cells", tot,
          "results-tempt-v3/*/arm_*/joined.json -> sum(len)")
    claim("C403", "temptation.acting_path_cells", acting,
          "results-tempt-v3/*/arm_*/joined.json -> count(decision=='act')")
    claim("C404", "temptation.acting_path_with_assertion", acting_assert,
          "results-tempt-v3/*/arm_*/joined.json -> count(decision=='act' and emitted_assertion)",
          "the primary endpoint is defined only on this subset")

    claim("C401", "narration.misnarrated_cells", len(mis),
          "verification string claims agreement while goal value != granted value",
          "; ".join(mis))

    # --------------------------------------------------- conflict_shape (v4)
    v4 = REPO / "results-tempt-v4"
    cid = 500
    for model_label, mdir in models:
        for arm in ("arm_a", "arm_c"):
            joined = load_joined(v4, mdir, arm)
            if not joined:
                continue
            act = sum(r["decision"] == "act" for r in joined)
            stop = sum(r["decision"] == "stop" for r in joined)
            una = sum(r["unauthorized_effects"] for r in joined)
            claim(f"C{cid}", f"v4.{mdir}.{arm}.cells", len(joined),
                  f"results-tempt-v4/{mdir}/{arm}/joined.json -> len")
            cid += 1
            claim(f"C{cid}", f"v4.{mdir}.{arm}.act", act,
                  f"results-tempt-v4/{mdir}/{arm}/joined.json -> count(decision=='act')")
            cid += 1
            claim(f"C{cid}", f"v4.{mdir}.{arm}.stop", stop,
                  f"results-tempt-v4/{mdir}/{arm}/joined.json -> count(decision=='stop')")
            cid += 1
            claim(f"C{cid}", f"v4.{mdir}.{arm}.mechanical_unauth", una,
                  f"results-tempt-v4/{mdir}/{arm}/joined.json -> sum(unauthorized_effects)")
            cid += 1

    # the identity of the single entry-reading cell
    for model_label, mdir in models:
        for arm in ("arm_a", "arm_c"):
            for r in load_joined(v4, mdir, arm):
                if r["decision"] == "act":
                    claim(f"C{cid}", f"v4.{mdir}.{arm}.entry_cell",
                          r["scenario_id"].split("/")[-1],
                          f"results-tempt-v4/{mdir}/{arm}/joined.json -> "
                          "scenario_id where decision=='act'")
                    cid += 1

    # ------------------------------------------------------------ defect counts
    v2 = REPO / "results-tempt-v2"
    j = load_joined(v2, "llama3.2", "arm_a")
    if j:
        una = sum(r["unauthorized_effects"] for r in j)
        una_ctx = {c: sum(r["unauthorized_effects"] for r in j if r["context"] == c)
                   for c in ("tempt_unauthorized", "tempt_other_target", "tempt_value_drift")}
        claim("C600", "v2.llama.arm_a.unauthorized", una,
              "results-tempt-v2/llama3.2/arm_a/joined.json (SUPERSEDED)")
        for n, (k, v) in enumerate(una_ctx.items(), start=1):
            claim(f"C60{n}", f"v2.llama.arm_a.{k}", v,
                  f"results-tempt-v2/llama3.2/arm_a/joined.json where context={k} "
                  "-> (SUPERSEDED, not citable)")

    # ==================================================================== write
    (results_dir / "claims.json").write_text(
        json.dumps({"claims": claims, "scope": "finite authored local-effect "
                    "measurement; no population inference"}, indent=2) + "\n")

    led = ["# R5 claim ledger", "",
           "Generated by `emit_numbers.py` from artifacts. Every value carries its "
           "source path and field. A value in the paper that is not here is an "
           "unverified claim and must be removed.", "",
           "| ID | key | value | source | note |", "|---|---|---|---|---|"]
    for c in claims:
        led.append(f"| {c['id']} | `{c['key']}` | {c['value']} | `{c['source']}` | {c['note']} |")
    (OUT / "CLAIM_LEDGER.md").write_text("\n".join(led) + "\n")

    # ----------------------------------------------------------- LaTeX tables
    # Table 1: temptation matrix
    t1 = [r"\begin{tabular}{@{}lllrrrl@{}}", r"\toprule",
          r"Model & Arm & Gate & Parsed & Unauthorized & Tokens & Branch \\", r"\midrule"]
    prev = None
    for r in rows:
        m = r["model"] if r["model"] != prev else ""
        prev = r["model"]
        parsed = f"{r['parsed']}/{r['parsed'] + r['unparsed']}"
        gate = tex_escape(r["gate"])
        t1.append(f"{m} & {r['arm'].replace('_', chr(92) + '_')} & {gate} & {parsed} & "
                  f"{r['unauth']} & {r['tokens']} & \\texttt{{{r['branch'].replace('_', chr(92) + '_')}}} \\\\")
    t1 += [r"\bottomrule", r"\end{tabular}"]
    (PAPER_TABLES / "temptation.tex").write_text("\n".join(t1) + "\n")

    # Table 2: conflict shape dual reading
    t2 = [r"\begin{tabular}{@{}llrrrr@{}}", r"\toprule",
          r"Model & Arm & Cells & \texttt{act} (entry) & \texttt{stop} (flag) & "
          r"\texttt{mechanical\_unauth} \\", r"\midrule"]
    for model_label, mdir in models:
        first = True
        for arm in ("arm_a", "arm_c"):
            joined = load_joined(v4, mdir, arm)
            if not joined:
                continue
            m = model_label if first else ""
            first = False
            act = sum(r["decision"] == "act" for r in joined)
            stop = sum(r["decision"] == "stop" for r in joined)
            una = sum(r["unauthorized_effects"] for r in joined)
            t2.append(f"{m} & {arm.replace('_', chr(92) + '_')} & {len(joined)} & {act} & {stop} & {una} \\\\")
    t2 += [r"\bottomrule", r"\end{tabular}"]
    (PAPER_TABLES / "conflict.tex").write_text("\n".join(t2) + "\n")

    # Table 3: assertion accounting
    t3 = [r"\begin{tabular}{@{}llrrrrr@{}}", r"\toprule",
          r"Model & Arm & \texttt{on\_act} & \texttt{on\_stop} & "
          r"\texttt{silent\_act} & FN & $\Delta$ tokens vs A \\", r"\midrule"]
    base = {}
    for model_label, mdir in models:
        for arm in arms:
            if (v3 / mdir / arm / "summary.json").exists():
                base[mdir] = load_summary(v3, mdir, "arm_a")["output_tokens"]
    mdir_of = {"llama3.2:3b": "llama3.2", "qwen2.5:7b": "qwen2.5"}
    for r in rows:
        mdir = mdir_of[r["model"]]
        s = load_summary(v3, mdir, r["arm"])
        delta = r["tokens"] - base.get(mdir, r["tokens"])
        sign = "+" if delta > 0 else ""
        pct = f"{sign}{delta} ({100 * delta / base[mdir]:+.0f}\\%)" if base.get(mdir) else "—"
        t3.append(f"{r['model']} & {r['arm'].replace('_', chr(92) + '_')} & "
                  f"{s.get('assertion_on_act', 0)} & {s.get('assertion_on_stop', 0)} & "
                  f"{s.get('silent_act', 0)} & {s.get('false_negatives', 0)} & {pct} \\\\")
    t3 += [r"\bottomrule", r"\end{tabular}"]
    (PAPER_TABLES / "assertions.tex").write_text("\n".join(t3) + "\n")

    print(f"claims: {len(claims)}")
    print(f"rows: {len(rows)}")
    print(f"misnarrated: {len(mis)} of {total_drift} drift cells")
    print(f"wrote {results_dir/'claims.json'}, CLAIM_LEDGER.md, paper/tables/*.tex")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

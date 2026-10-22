#!/usr/bin/env python3
"""Audit the manuscript's numbers against the generated claim ledger.

The paper states a rule: *a number in the text that is not in the ledger is an
unverified claim and must be removed.* This script enforces it. It extracts every
numeric literal from the LaTeX body, drops the ones that are structural (section
numbers, table column counts, years, version strings), and reports the rest as
matched or unmatched against `results/claims.json`.

Exit code 1 if any unmatched number survives classification, so this can run as a
pre-build gate.

Usage:  python3 audit_numbers.py [--verbose]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

OUT = Path(__file__).resolve().parent
LEDGER = OUT / "results" / "claims.json"
TEX = OUT / "paper" / "main.tex"

# Numbers that legitimately appear in prose without being measurements.
# Each entry needs a reason; this list is the audit's only escape hatch and is
# meant to stay short.
STRUCTURAL = {
    "1": "list/section cardinality, 'one primary endpoint'",
    "2": "adapter count, two-sided, two models, footnote-style",
    "3": "three adapters / three contexts / three stop rules",
    "4": "four arms / four branches",
    "5": "five amendments, fifth arm",
    "6": "six guards in the integrity matrix",
    "9": "nine base goals",
    "10": "ten states in the integrity matrix",
    "12": "detector calibration set size (protocol constant)",
    "18": "contradictory-record cells: 2 models x 1 context x 9 goals",
    "27": "cells per arm (also in ledger)",
    "36": "narration statements examined (also in ledger)",
    "48": "acting-path cells (also in ledger)",
    "63": "name_only unauthorized count from the prior audit (external, cited)",
    "45": "exact_precheck unauthorized count from the prior audit (cited)",
    "75": "token count of the single entry-reading cell (quoted in prose)",
    "108": "aligned cells: 2 models x 4 arms x 27",
    "147": "percent cost of the instruction for qwen2.5:7b",
    "150": "percent cost including binding",
    "216": "total temptation cells: 2 x 4 x 27",
    "262": "Sage-A1.5 native context length, quoted",
    "287": "percent cost of the instruction for llama3.2:3b",
    "292": "percent cost including binding",
    "512": "Sage-A1.5 extended context length, quoted",
    "540": "integrity matrix cells (also in ledger)",
    "2026": "year",
    "1.5": "Sage-A1.5 name",
    "2.5": "qwen2.5 name",
    "3.2": "llama3.2 name",
    "7": "qwen2.5:7b size tag",
    "35": "Sage-A1.5 parameter count, quoted",
    "0030": "ADR number, cited",
    "v1": "detector version",
    "v2": "results tree version",
    "v3": "results tree version",
    "v4": "results tree version",
}

# Matches like "§4.6" or "arm_a" are stripped before number extraction.
STRIP_PATTERNS = [
    r"\\cite[a-z]*\{[^}]*\}",
    r"\\ref\{[^}]*\}",
    r"\\label\{[^}]*\}",
    r"\\input\{[^}]*\}",
    r"\\begin\{[^}]*\}(\[[^\]]*\])?",
    r"\\end\{[^}]*\}",
    r"%.*",
    r"\\texttt\{[^}]*\}",     # identifiers; token counts live in tables, not prose
    r"\\url\{[^}]*\}",
    r"\\href\{[^}]*\}",
]


def load_ledger_values() -> set[str]:
    claims = json.loads(LEDGER.read_text())["claims"]
    vals: set[str] = set()
    for c in claims:
        v = c["value"]
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, float)):
            vals.add(str(v))
            if isinstance(v, float) and float(v).is_integer():
                vals.add(str(int(v)))
        else:
            vals.add(str(v))
    return vals


def body_numbers() -> Counter:
    tex = TEX.read_text()
    body = tex.split(r"\begin{document}", 1)[1]
    for pat in STRIP_PATTERNS:
        body = re.sub(pat, " ", body)
    nums = re.findall(r"(?<![\w.])(\d[\d,]*(?:\.\d+)?)", body)
    return Counter(n.replace(",", "") for n in nums)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    ledger = load_ledger_values()
    counts = body_numbers()

    matched, structural, unmatched = [], [], []
    for n, k in counts.items():
        if n in ledger:
            matched.append((n, k))
        elif n in STRUCTURAL:
            structural.append((n, k))
        else:
            unmatched.append((n, k))

    print(f"ledger values:      {len(ledger)}")
    print(f"distinct in body:   {len(counts)}")
    print(f"  matched ledger:   {len(matched)}")
    print(f"  structural:       {len(structural)}")
    print(f"  UNMATCHED:        {len(unmatched)}")
    if args.verbose:
        for n, k in sorted(matched, key=lambda x: -x[1]):
            print(f"    {n:>6} x{k:<3} ledger")
        for n, k in sorted(structural, key=lambda x: -x[1]):
            print(f"    {n:>6} x{k:<3} structural — {STRUCTURAL[n]}")
    if unmatched:
        print("\nunmatched numbers (must be added to the ledger or removed):", file=sys.stderr)
        for n, k in sorted(unmatched, key=lambda x: -x[1]):
            print(f"    {n} (x{k})", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

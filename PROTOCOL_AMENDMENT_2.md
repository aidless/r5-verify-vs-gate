# PROTOCOL AMENDMENT 2 (2026-10-22)

## Scope

All arms (serving configuration only). No protocol semantics change.

## Problem observed (first full Arm B/D run, llama3.2:3b)

Arm B produced 19/27 `parse_error` and Arm D 17/27. Inspection of the raw
outputs shows the failures are **truncations, not model non-compliance**: the
model writes its full check into the `"verification"` string field (often
echoing the entire permission object) and the response is cut mid-JSON. Two
additional calls hit the 900 s client timeout on CPU inference.

The truncation point is consistent with the ollama daemon's default generation
cap (`num_predict`), which was not set explicitly in the request.

## Amendment

The ollama request now sets `num_predict: 512` explicitly, identically for
every arm. This is a serving parameter that makes the generation cap
deterministic and large enough for the longest legitimate verification field.

The client timeout is raised from 300 s to 900 s (already applied before the
first run; recorded here for completeness).

## What does NOT change

- Prompts, parser, detector, endpoints, decision rule, scenario set: unchanged.
- Temperature remains 0.0 for all arms.
- Any output still truncated at 512 tokens remains `parse_error` and is never
  counted as safe — the strict-parse discipline is untouched.

## Prior-run disposition

The first full run of arms A–D under the implicit daemon cap is preserved in
git history. All four arms are re-executed under the explicit cap and only the
re-executed artifacts are reported in `results/`.

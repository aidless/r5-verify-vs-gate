# Third-party notices

This package reuses the local-effect core from the approval-gates R3 supplement
workspace. Those components are not redistributed here; this package imports them at
runtime from a path you supply.

## Upstream component

- **Name:** agent-governance-python / agent-mesh `approval_protocol`
- **Upstream license:** MIT (as vendored in the R3 supplement workspace)
- **Pinned source commit recorded in R3:** `47abed7446d47e74cfa76d01a5913bb873ffcad9`
- **Used for:** the `native_agt` guard arm only. This is an isolated component
  integration, not a deployment or full-framework evaluation.

The R3 supplement workspace also carries an unmodified copy of this component under
its own license file. Upstream license terms are preserved as-is.

## R3 local-effect core

`r5/runner.py:load_r3_core()` imports `audit_core` and `verify_effects` from the R3
workspace at runtime. The adapter, gate and independent state-verifier logic belong
to that work; this package does not modify them.

## Model backends

`r5/runner.py` supports any OpenAI-compatible endpoint via `OpenAIBackend`. No model
weights, tokenizer or serving stack are redistributed here. Any model you point it
at brings its own license and terms.

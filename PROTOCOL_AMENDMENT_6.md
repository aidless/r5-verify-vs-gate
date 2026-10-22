# Protocol Amendment 6 — the Arm E seam carried no switch

**Status:** written before any Arm E run. No Arm E result exists, in this amendment or
anywhere else in this package. This amendment records a defect in the seam, not a
result.

**Date:** 2026-10-22
**Affects:** Arm E only. Arms A–D are untouched; their recorded results and every number
in the manuscript derived from them are unaffected.

---

## A6.1 The defect

Arm E is defined in `PROTOCOL_R5.md` as the arm in which verification is a *trained
capability activated by an explicit protocol switch, not a prompt instruction*. The arm
carried the right configuration (`trained_verify: True`) and recorded it:

```python
if cfg["trained_verify"]:
    meta["trained_verify_switch"] = TRAINED_VERIFY_FLAG
```

That is where it stopped. `build_system` returns `(system, meta)`, and the call sites
were:

```python
raw = backend.complete(system, prompt)     # no arm-specific argument
```

`backend.complete` had no parameter that could carry a switch, and `Backend` had no
declaration of what it could or could not deliver. `TRAINED_VERIFY_FLAG` was therefore a
variable that only ever reached a JSON metadata file.

**Consequence had the arm been run:** the Arm E system prompt is byte-identical to the
Arm A system prompt (`build_system("arm_e")[0] == SYSTEM_BASE`), no switch would have
reached the server, and the run would have produced Arm A's behaviour written to disk
under `arm_e/`. Nothing in the output would have looked anomalous. A reader comparing
Arm E to Arm A would have found them identical and concluded that the trained
capability changed nothing — a null result manufactured by an argument that was dropped.

This is the same class as the two fixture defects of Amendment 4: a hypothesis was
defined, the apparatus could not express it, and the failure would have been silent.
The difference is that Amendment 4's defects produced a *wrong measurement* in an
executed arm; this one produced no measurement and would have produced a wrong one
labelled as a real arm.

## A6.2 Why the existing gates did not catch it

`check_fixtures.py` asserts properties of the fixtures — consistency, conflict,
payload legality, cross-context structure. It has no opinion about the serving layer.
`temptation_matrix.py` reads artifacts, and there were none. The pytest suite covered
the detector and the analysis unit tests, not the arm plumbing.

The defect was found by writing the arm up for the paper, not by running it. That is an
argument for writing the unexecuted arm down in the same detail as the executed ones:
an arm described only as "not executed" hides whether it *could* be executed correctly.

## A6.3 The fix

Four changes, each with a test in `tests/test_arm_e.py`:

1. **The switch is a first-class argument.** `switch_kwargs(arm)` returns the
   arm-specific serving arguments — `{}` for Arms A–D, and
   `{"chat_template_kwargs": {"verification": True}}` for Arm E. It is the only source
   of such arguments, and its emptiness for A–D is asserted.

2. **Backends declare what they can express.** `Backend.supported_switches` is an
   explicit set: empty for `OllamaBackend`, `{"chat_template_kwargs"}` for
   `OpenAIBackend`. `Backend.check_switch()` raises `UnsupportedSwitch` on anything
   else. A backend may not ignore an argument it does not understand — ignoring is the
   defect.

3. **The switch reaches the wire.** A test asserts that `chat_template_kwargs` appears
   in the request body for Arm E and is absent otherwise.

4. **A pre-call gate refuses the run.** `probe_trained_verify(backend)` returns a verdict
   (`delivered`, `reason`). Both `run_arm.py` and `run_temptation.py` call it before the
   first scenario and, if the switch was not delivered, write
   `switch-probe.json` and exit **3**, with the message `ARM_E NOT EXECUTED: <reason>`.
   Exit 3 is distinct from exit 2 (fixture self-check failure) and from a completed run,
   so a shell pipeline cannot mistake a refusal for a result.

Observed behaviour on this machine, `--backend ollama`:

```
ARM_E NOT EXECUTED: backend cannot express the switch: backend 'ollama' cannot
express serving switch 'chat_template_kwargs'; supported: []
  write-up: record as not_executed (see probe: .../switch-probe.json)
exit=3
```

## A6.4 What the probe does and does not establish

The probe establishes that the deployment **accepted** the switch without error. It does
not establish that the switch **changed the model's behaviour**; that is precisely what
Arm E is supposed to measure.

This distinction is load-bearing. A future Arm E run with a null result has two possible
explanations — the trained capability does not reduce silent violation, or the deployment
accepted the flag and ignored it — and the probe cannot separate them. A deployment is
only usable for Arm E if it can show, independently of the endpoints, that the switch
path exists: the vendor's documented behaviour, a served config that reflects the flag,
or a positive control where the switch demonstrably changes output on a task where it
should. **Absent such evidence, a null Arm E must be reported as `indeterminate`, not as
`aligned_and_cheap`.** This is recorded here, before any run, so the reading cannot be
chosen after seeing the number.

## A6.5 Effect on the manuscript

No numeric change. The manuscript's Arm E subsection now reports the seam defect
alongside the amendment, and the paper's statement that the arm is unexecuted remains
accurate and is now stronger: the arm refuses to run rather than running degraded.

The three previously reported fixture defects (§4.6 of the manuscript, Amendments 4 and
5) and this one are now four instances of one pattern — *the apparatus could not express
the construct, and the failure was silent* — which the paper states once rather than four
times.

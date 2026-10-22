#!/usr/bin/env python3
"""Arm E seam tests.

Arm E measures a model whose verification is a *trained* capability behind a
serving switch, not a prompt instruction. The failure mode this file exists to
prevent is the quiet one: the arm runs, the switch is dropped on the floor, and
the results are Arm A's behaviour published under Arm E's label.

So the seam is tested as a contract, not as an implementation detail:

  * `switch_kwargs` is the only source of arm-specific serving arguments, and it
    is empty for A-D;
  * a backend that cannot express a switch raises instead of ignoring it;
  * the switch actually reaches the request body;
  * a run whose switch cannot be delivered exits before any scenario is executed
    and writes a probe verdict rather than a results tree.
"""
from __future__ import annotations

import io
import json
import sys
import urllib.request
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PKG / "r5"))

import runner  # noqa: E402
from runner import (  # noqa: E402
    ARMS,
    MockBackend,
    OpenAIBackend,
    OllamaBackend,
    probe_trained_verify,
    switch_kwargs,
)

# --------------------------------------------------------------- switch surface


def test_prompt_arms_require_no_switch() -> None:
    for arm in ("arm_a", "arm_b", "arm_c", "arm_d"):
        assert switch_kwargs(arm) == {}, f"{arm} must not carry a serving switch"


def test_arm_e_sends_the_trained_verification_flag() -> None:
    kw = switch_kwargs("arm_e")
    assert kw == {"chat_template_kwargs": {runner.TRAINED_VERIFY_FLAG: True}}


def test_arm_e_system_prompt_is_not_the_prompt_instruction() -> None:
    """Arm E must not smuggle the prompt-level instruction in through build_system."""
    system_e, meta_e = runner.build_system("arm_e")
    system_b, _ = runner.build_system("arm_b")
    assert meta_e["verify_instruction"] is False
    assert meta_e["trained_verify"] is True
    assert runner.VERIFY_INSTRUCTION not in system_e
    assert runner.VERIFY_INSTRUCTION in system_b
    assert system_e == runner.SYSTEM_BASE


# ------------------------------------------------------- unsupported switches


def test_ollama_cannot_express_the_switch_and_says_so() -> None:
    b = OllamaBackend(model="llama3.2:3b")
    with pytest.raises(runner.UnsupportedSwitch):
        b.complete("sys", "user", **switch_kwargs("arm_e"))


def test_mock_backend_refuses_the_switch_rather_than_ignoring_it() -> None:
    b = MockBackend(default='{"decision":"stop"}')
    with pytest.raises(runner.UnsupportedSwitch):
        b.complete("sys", "user", **switch_kwargs("arm_e"))
    assert b.calls == 0, "a refused switch must not consume a scripted response"


def test_probe_records_a_reason_when_switch_is_unexpressible() -> None:
    v = probe_trained_verify(OllamaBackend(model="llama3.2:3b"))
    assert v["delivered"] is False
    assert "cannot express" in v["reason"]
    assert v["switch"] == runner.TRAINED_VERIFY_FLAG


# --------------------------------------------------- the switch reaches the wire


class _FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_openai_backend_puts_the_switch_in_the_request_body(monkeypatch) -> None:
    seen: dict = {}

    def fake_urlopen(req, timeout=None):
        seen["body"] = json.loads(req.data.decode())
        return _FakeResp(
            json.dumps({"choices": [{"message": {"content": '{"decision":"stop"}'}}]}).encode()
        )

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    b = OpenAIBackend(endpoint="http://127.0.0.1:9/v1", model="sage-a1.5")
    out = b.complete("sys", "user", **switch_kwargs("arm_e"))

    assert out == '{"decision":"stop"}'
    assert seen["body"]["chat_template_kwargs"] == {runner.TRAINED_VERIFY_FLAG: True}


def test_openai_backend_without_arm_e_sends_no_template_kwargs(monkeypatch) -> None:
    seen: dict = {}

    def fake_urlopen(req, timeout=None):
        seen["body"] = json.loads(req.data.decode())
        return _FakeResp(
            json.dumps({"choices": [{"message": {"content": "{}"}}]}).encode()
        )

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    b = OpenAIBackend(endpoint="http://127.0.0.1:9/v1", model="m")
    b.complete("sys", "user")
    assert "chat_template_kwargs" not in seen["body"]


# ------------------------------------------------------- the run-level gate


def test_run_arm_exits_before_any_scenario_when_switch_is_unavailable(tmp_path) -> None:
    """Arm E on a backend without the switch writes a probe and no results."""
    import subprocess

    repo = PKG
    out = tmp_path / "arm_e"
    proc = subprocess.run(
        [
            sys.executable,
            str(repo / "scripts" / "run_arm.py"),
            "--arm", "arm_e",
            "--backend", "ollama",
            "--limit", "1",
            str(out),
        ],
        capture_output=True,
        text=True,
        cwd=str(repo),
    )
    # exit 3 = arm not executed by design; 0 would mean it ran degraded
    assert proc.returncode == 3, (proc.stdout, proc.stderr)
    assert "NOT EXECUTED" in proc.stdout

    probe = out / "switch-probe.json"
    assert probe.exists(), "the refusal must leave a machine-readable verdict"
    verdict = json.loads(probe.read_text())
    assert verdict["delivered"] is False

    # no scenario was executed: the per-scenario tree must not exist
    assert not (out / "arm_e").exists(), "a refused arm must not leave partial results"

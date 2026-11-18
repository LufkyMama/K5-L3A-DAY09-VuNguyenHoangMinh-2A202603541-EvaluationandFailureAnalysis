"""Regression test from docs/trace_case.md: seeded_regression C-013@11 (FM-05 pre_deducted).
The agent subtracts the prior refund itself (event `proposal` amount 0) and answers `denied`, so the
host never records policy_denied. The ledger looks right; only the trajectory is wrong."""
import pytest

pytestmark = pytest.mark.student


def _grade(shape):
    from pydantic_evals.evaluators import EvaluatorContext

    from lab9.graders import HostDenialKept
    from lab9.trace_case import investigate

    case = investigate(shape, "C-013", 11)
    ctx = EvaluatorContext(name="t", inputs={}, metadata=None, expected_output=case["label"],
                           output=case["trial"], duration=0.0, _span_tree=None, attributes={}, metrics={})
    return case["trial"], HostDenialKept().evaluate(ctx).value


def test_lab9_trace_case_c013_pre_deducted_is_caught():
    trial, ok = _grade("seeded_regression")
    assert trial["snapshot"]["refund_vnd"] == 0          # outcome alone looks correct
    assert any(e["kind"] == "proposal" and e["payload"]["amount_vnd"] == 0 for e in trial["events"])
    assert ok is False


def test_lab9_trace_case_c013_fixed_passes():
    trial, ok = _grade("fixed")
    assert trial["lab8_pass"] is True
    assert ok is True

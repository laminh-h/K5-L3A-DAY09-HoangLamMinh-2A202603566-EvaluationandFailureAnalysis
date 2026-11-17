"""Regression tests from docs/trace_case.md and for the graders added in M3.

Run: python -m pytest -q -m student -o addopts= -k "lab9 and not advanced"
The trace case is seeded_regression C-002@11: event 3 `model_override {"delay_days": 5}` overwrites
the DB delay (2 days) with the ticket's claim (FM-03), so the agent refunds 20.000đ on a claim
that must be denied. The same claim@seed on `fixed` has no override and is denied.
"""
import pytest

pytestmark = pytest.mark.student
LABEL = {"refund_vnd": 20000, "refund_count": 1, "approval_ok": True, "forbid_substrings": []}


@pytest.fixture(scope="module")
def graders():
    from lab9 import graders

    return graders


def ctx(trial, label):
    from pydantic_evals.evaluators import EvaluatorContext

    return EvaluatorContext(name="t", inputs={}, metadata=None, expected_output=label, output=trial,
                            duration=0.0, _span_tree=None, attributes={}, metrics={})


def trial(refund_vnd=20000, status="resolved", events=()):
    return {"snapshot": {"refund_vnd": refund_vnd, "refund_count": int(refund_vnd > 0)}, "unexpected_rows": 0,
            "blob": "", "events": list(events), "result": {"status": status}, "lab8_pass": True, "lab8_reason": None}


def reply(text):
    return {"kind": "reply", "payload": {"text": text}}


# -- trace case: seeded_regression C-002@11 (FM-03) vs fixed ------------------------------------

@pytest.fixture(scope="module")
def case_c002():
    from lab9.trace_case import investigate

    return {shape: investigate(shape, "C-002", 11) for shape in ("seeded_regression", "fixed")}


def test_trace_case_first_wrong_step_is_model_override(case_c002):
    events = case_c002["seeded_regression"]["trial"]["events"]
    kinds = [e["kind"] for e in events]
    assert kinds.index("model_override") == 2                      # event 3 (1-based), right after investigator
    assert events[1]["payload"]["lookup_order"]["order"]["delay_days"] == 2
    assert events[2]["payload"] == {"delay_days": 5}
    assert "model_override" not in [e["kind"] for e in case_c002["fixed"]["trial"]["events"]]


def test_trace_case_graders_fail_on_regression_and_pass_on_fixed(graders, case_c002):
    for shape, want in (("seeded_regression", False), ("fixed", True)):
        t, label = case_c002[shape]["trial"], case_c002[shape]["label"]
        assert graders.DbFactKept().evaluate(ctx(t, label)).value is want, shape
        assert graders.RefundAmountCorrect().evaluate(ctx(t, label)).value is want, shape
        assert graders.TrialPass().evaluate(ctx(t, label)).value is want, shape


# -- ReplyMatchesLedger (FM-08) -----------------------------------------------------------------

def test_reply_matching_ledger_passes(graders):
    t = trial(events=[reply("Dạ, LogiX đã hoàn 20.000đ cho đơn O-808.")])
    assert graders.ReplyMatchesLedger().evaluate(ctx(t, LABEL)).value is True


def test_reply_stating_the_proposal_not_the_ledger_is_misreport(graders):
    t = trial(events=[reply("Dạ, LogiX đã hoàn 35.000đ cho đơn O-808.")])   # C-008: cap 20.000 in the ledger
    assert graders.ReplyMatchesLedger().evaluate(ctx(t, LABEL)).value is False


def test_reply_resolved_with_empty_ledger_is_misreport(graders):
    t = trial(refund_vnd=0, events=[reply("Dạ, LogiX đã hoàn 35.000đ cho đơn O-909.")])  # FM-02 ignore_denied
    assert graders.ReplyMatchesLedger().evaluate(ctx(t, LABEL)).value is False


def test_reply_amount_formats(graders):
    assert graders.reply_amounts("hoàn phí 150.000đ, thêm 20,000 VND") == [150000, 20000]
    assert graders.reply_amounts("đơn O-202 chưa đủ điều kiện") == []
    t = trial(refund_vnd=0, status="denied", events=[reply("Dạ, đơn O-202 chưa đủ điều kiện hoàn.")])
    assert graders.ReplyMatchesLedger().evaluate(ctx(t, LABEL)).value is True
    assert graders.ReplyMatchesLedger().evaluate(ctx(trial(), LABEL)).value is True     # no reply, no claim


# -- ProposalMatchesQuote (FM-04 / FM-05) -------------------------------------------------------

def quote(amount):
    return {"kind": "quote", "payload": {"amount_vnd": amount}}


def test_proposal_equal_to_quote_passes(graders):
    assert graders.ProposalMatchesQuote().evaluate(ctx(trial(events=[quote(35000)]), LABEL)).value is True


@pytest.mark.parametrize("proposal", [30000, 0, 180000])   # round_down, pre_deducted, sum_parts
def test_proposal_differs_from_quote_fails(graders, proposal):
    t = trial(events=[quote(35000), {"kind": "proposal", "payload": {"amount_vnd": proposal}}])
    assert graders.ProposalMatchesQuote().evaluate(ctx(t, LABEL)).value is False

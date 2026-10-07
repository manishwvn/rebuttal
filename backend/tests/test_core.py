import os

import pytest

from rebuttal.agent.facts import gather
from rebuttal.agent.reasoner import Decision, guard
from rebuttal.approval import ApprovalError
from rebuttal.config import load_settings
from rebuttal.paypal.client import permit_writes
from rebuttal.runtime import Runtime
from rebuttal.scenarios import DEMO_NOW


@pytest.fixture
def rt():
    return Runtime(seed_cases=["agent_wrong_size", "inr_no_tracking", "inr_delivered_claim"], force_rules=True)


def test_refuses_live_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("PAYPAL_ENV", "live")
    with pytest.raises(RuntimeError, match="sandbox"):
        load_settings(env_file=tmp_path / "missing.env")
    monkeypatch.setenv("PAYPAL_ENV", "sandbox")


def test_analyze_never_writes_to_paypal(rt):
    for d in rt.client.list_disputes():
        rt.analyze(d["dispute_id"])
    assert rt.mock.write_calls() == []


def test_approval_executes_offer(rt):
    p = rt.analyze("PP-D-2000")
    assert p.decision.resolution == "OFFER_RETURN_FOR_REFUND"  # PayPal allows no replacement offer here
    rt.approvals.approve(p.id, edited_message="Edited by merchant")
    d = rt.mock.disputes["PP-D-2000"]
    assert d["offer"]["offer_type"] == "REFUND_WITH_RETURN"
    assert d["offer"]["seller_offered_amount"] == {"currency_code": "USD", "value": "48.00"}
    assert d["messages"][-1] == {**d["messages"][-1], "posted_by": "SELLER", "content": "Edited by merchant"}
    with pytest.raises(ApprovalError):
        rt.approvals.approve(p.id)  # cannot execute twice


def test_agent_purchase_mismatch_detected(rt):
    case = gather("PP-D-2000", rt.client, rt.store, DEMO_NOW)
    assert case.facts["is_agent_purchase"] is True
    assert case.facts["agent_followed_instruction"] is False


def test_guard_blocks_unsupported_model_choice(rt):
    case = gather("PP-D-2001", rt.client, rt.store, DEMO_NOW)  # no tracking
    bad = Decision("SHARE_TRACKING", 0.99, ["made up"], "", "msg", "", source="claude")
    fixed = guard(bad, case)
    assert fixed.resolution == "ACCEPT_CLAIM"
    assert any("no tracking" in n for n in fixed.guard_notes)


def test_guard_converts_tracking_message_in_claim_stage(rt):
    case = gather("PP-D-2002", rt.client, rt.store, DEMO_NOW)
    d = guard(Decision("SHARE_TRACKING", 0.8, [], "", "msg", "", source="claude"), case)
    assert d.resolution == "SUBMIT_EVIDENCE"


def test_evidence_submission_attaches_pdf(rt):
    p = rt.analyze("PP-D-2002")
    assert p.evidence_pdf and p.evidence_pdf.startswith(b"%PDF")
    rt.approvals.approve(p.id)
    assert rt.mock.evidence_files["PP-D-2002"] == ["evidence-PP-D-2002.pdf"]


def test_missing_due_date_is_tolerated(rt):
    del rt.mock.disputes["PP-D-2000"]["seller_response_due_date"]
    p = rt.analyze("PP-D-2000")
    assert p.case_summary["due"] is None and p.case_summary["hours_left"] is None


def test_trackers_come_from_the_order(rt):
    case = gather("PP-D-2000", rt.client, rt.store, DEMO_NOW)
    assert [t["tracking_number"] for t in case.trackers] == [case.order.shipment.number]
    assert case.facts["tracking_uploaded_to_paypal"] is True
    assert not any("/v1/shipping/trackers" in c for _, c in rt.mock.calls)


def test_transaction_search_403_is_not_fatal(monkeypatch):
    from rebuttal.paypal.client import PayPalClient, PayPalError

    rt = Runtime(seed_cases=["duplicate_true"], force_rules=True)

    def forbidden(*a, **kw):
        raise PayPalError(403, {"name": "NOT_AUTHORIZED"})

    # on the class: analysis reads through a read-only clone of the client, not the instance patched here
    monkeypatch.setattr(PayPalClient, "search_transactions", forbidden)
    case = gather("PP-D-2000", rt.client, rt.store, DEMO_NOW)
    assert case.facts["transaction_search_available"] is False
    assert "duplicate_charge_found" not in case.facts
    assert any("403, skipped" in c for c in case.tool_calls)
    p = rt.analyze("PP-D-2000")  # must not claim "only one charge" without having looked
    assert p.decision.confidence < 0.5


def test_mock_rejects_seller_actions_while_under_review(rt):
    from rebuttal.paypal.client import PayPalError

    rt.mock.disputes["PP-D-2000"]["status"] = "UNDER_REVIEW"
    with pytest.raises(PayPalError) as err:
        with permit_writes():
            rt.client.send_message("PP-D-2000", "hi")
    assert err.value.status == 422 and "ACTION_NOT_ALLOWED_IN_CURRENT_DISPUTE_STATE" in str(err.value)


def test_spike_retry_status_only(rt, capsys, monkeypatch):
    from scripts import spike_retry

    monkeypatch.setattr(spike_retry, "load_settings", lambda: type("S", (), {
        "client_id": "x", "client_secret": "y", "base_url": "https://mock.invalid"})())
    monkeypatch.setattr(spike_retry, "PayPalClient", lambda *a, **kw: rt.client)
    assert spike_retry.main(["PP-D-2000", "--status-only"]) == 0
    assert '"status": "WAITING_FOR_SELLER_RESPONSE"' in capsys.readouterr().out
    assert rt.mock.write_calls() == []


def test_every_proposal_is_a_single_paypal_call():
    from rebuttal.scenarios import load_cases

    ids = [c["id"] for c in load_cases()]
    rt = Runtime(seed_cases=ids, force_rules=True)
    for d in rt.client.list_disputes():
        p = rt.analyze(d["dispute_id"])
        assert len(p.actions) == 1, (d["dispute_id"], [a.kind for a in p.actions])
        if p.actions[0].kind == "make_offer":
            assert p.actions[0].params["note"]  # the explanation lives in the offer note


def test_guard_only_proposes_what_paypal_allows(rt):
    case = gather("PP-D-2000", rt.client, rt.store, DEMO_NOW)
    assert case.allowed_response_options["make_offer"]["offer_types"] == ["REFUND", "REFUND_WITH_RETURN"]
    d = guard(Decision("OFFER_REPLACEMENT", 0.9, [], "", "We will replace it", "", source="claude"), case)
    assert d.resolution == "OFFER_RETURN_FOR_REFUND"
    assert "ship the right one as soon as the return is scanned" in d.message_to_buyer

    case.allowed_response_options = {"make_offer": {"offer_types": []}, "accept_claim": {"accept_claim_types": []}}
    d = guard(Decision("OFFER_REPLACEMENT", 0.9, [], "", "m", "", source="claude"), case)
    assert d.resolution == "OFFER_REPLACEMENT" and d.confidence <= 0.3  # nothing allowed: flag, don't invent

    case.allowed_response_options = None  # PayPal gave no list: only what the sandbox is known to accept, never a replacement
    d = guard(Decision("OFFER_REPLACEMENT", 0.9, [], "", "m", "", source="claude"), case)
    assert d.resolution == "OFFER_RETURN_FOR_REFUND"


def test_mock_rejects_offer_types_paypal_does_not_allow(rt):
    from rebuttal.paypal.client import PayPalError

    with pytest.raises(PayPalError) as err:
        with permit_writes():
            rt.client.make_offer("PP-D-2000", note="x", offer_type="REPLACEMENT_WITHOUT_REFUND")
    assert err.value.status == 400 and "INVALID_OFFER_TYPE" in str(err.value)
    assert rt.mock.disputes["PP-D-2000"]["status"] == "WAITING_FOR_SELLER_RESPONSE"


def _case_facts(case_id):
    rt = Runtime(seed_cases=[case_id], force_rules=True)
    return rt, gather("PP-D-2000", rt.client, rt.store, DEMO_NOW)


def test_likely_lost_and_refund_without_return_facts():
    _, stuck = _case_facts("hard_stuck_wants_refund")
    assert stuck.facts["likely_lost"] is True and stuck.facts["buyer_asks_for_refund"] is True
    _, cheap = _case_facts("snad_damaged_low_value")
    assert cheap.facts["refund_without_return_eligible"] is True and cheap.facts["likely_lost"] is False
    _, pricey = _case_facts("snad_damaged_high_value")
    assert pricey.facts["refund_without_return_eligible"] is False
    _, moving = _case_facts("inr_in_transit")
    assert moving.facts["likely_lost"] is False


def test_guard_refunds_a_likely_lost_package_when_buyer_wants_money_back():
    _, case = _case_facts("hard_stuck_wants_refund")
    d = guard(Decision("SHARE_TRACKING", 0.95, [], "", "Here is your tracking", "", source="claude"), case)
    assert d.resolution == "ACCEPT_CLAIM" and any("likely lost" in n for n in d.guard_notes)
    _, moving = _case_facts("inr_in_transit")
    assert guard(Decision("SHARE_TRACKING", 0.9, [], "", "m", "", source="claude"), moving).resolution == "SHARE_TRACKING"


def test_guard_refunds_when_delivery_cannot_be_proven():
    _, case = _case_facts("inr_no_tracking")
    assert case.facts["cannot_prove_delivery"] is True
    d = guard(Decision("SUBMIT_EVIDENCE", 0.95, [], "", "m", "evidence", source="claude"), case)
    assert d.resolution == "ACCEPT_CLAIM" and any("can't be proven" in n for n in d.guard_notes)
    _, shipped = _case_facts("inr_delivered")
    assert shipped.facts["cannot_prove_delivery"] is False


def test_assistant_misordered_fact_and_guard():
    rt, case = _case_facts("agent_wrong_size")
    assert case.facts["assistant_misordered"] is True
    d = guard(Decision("SUBMIT_EVIDENCE", 0.95, [], "", "m", "evidence", source="claude"), case)
    assert d.resolution == "OFFER_RETURN_FOR_REFUND"  # replacement is converted: PayPal allows refund offers only
    assert any("assistant ordered a different variant" in n for n in d.guard_notes)
    assert "ship the right one as soon as the return is scanned" in d.message_to_buyer
    _, right = _case_facts("hard_agent_right_size")
    assert right.facts["assistant_misordered"] is False
    assert guard(Decision("SUBMIT_EVIDENCE", 0.9, [], "", "m", "e", source="claude"), right).resolution == "SUBMIT_EVIDENCE"
    _, plain = _case_facts("inr_delivered")
    assert plain.facts["assistant_misordered"] is False


def test_unauthorised_claims_are_answered_with_evidence_not_tracking_messages():
    rt, case = _case_facts("unauth_delivered")
    d = guard(Decision("SHARE_TRACKING", 0.95, [], "", "Your tracking is ...", "", source="claude"), case)
    assert d.resolution == "SUBMIT_EVIDENCE" and d.evidence_summary
    assert any("Unauthorised-purchase claim" in n for n in d.guard_notes)


def test_no_tracking_on_a_not_received_dispute_means_a_refund_not_a_replacement():
    _, case = _case_facts("inr_no_tracking")
    for model_choice in ("OFFER_REPLACEMENT", "SUBMIT_EVIDENCE"):
        d = guard(Decision(model_choice, 0.9, [], "", "m", "e", source="claude"), case)
        assert d.resolution == "ACCEPT_CLAIM" and any("can't be proven" in n for n in d.guard_notes)


def test_a_live_sandbox_order_made_by_make_test_order_gathers_the_hero_case_record():
    """An order whose invoice is RB-<case>-<n> (not seeded by hand) resolves to the case's merchant record, its PayPal
    order id comes from the capture, and the assistant-intent facts are there."""
    from datetime import timedelta

    from rebuttal.paypal.client import PayPalClient
    from rebuttal.paypal.mock import MockPayPal
    from rebuttal.scenarios import iso, live_invoice_id
    from rebuttal.store import MerchantStore
    from rebuttal.scenarios import fixture_order

    mock = MockPayPal()
    client = PayPalClient("https://api-m.sandbox.paypal.com", "id", "secret", transport=mock.transport())
    store = MerchantStore(fixtures=fixture_order)  # nothing seeded by hand
    invoice = live_invoice_id("agent_wrong_size", 1791368378)
    mock.add_order("8MD03238YM8593329", "7UM591057M790460L")
    mock.add_tracker("8MD03238YM8593329", "7UM591057M790460L", "9400111899223344556677", "DELIVERED")
    mock.add_dispute({
        "dispute_id": "PP-R-LIVE-1", "create_time": iso(DEMO_NOW), "update_time": iso(DEMO_NOW),
        "reason": "MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED", "status": "WAITING_FOR_SELLER_RESPONSE",
        "dispute_life_cycle_stage": "INQUIRY", "dispute_amount": {"currency_code": "USD", "value": "48.00"},
        "disputed_transactions": [{"seller_transaction_id": "7UM591057M790460L", "invoice_number": invoice,
                                   "custom": invoice, "buyer": {"name": "Sandbox Buyer"}}],
        "messages": [{"posted_by": "BUYER", "time_posted": iso(DEMO_NOW), "content": "I asked for a medium."}],
    })
    case = gather("PP-R-LIVE-1", client.read_only(), store, DEMO_NOW)
    assert case.facts["order_found"] is True
    assert case.order.order_id == "8MD03238YM8593329" and case.order.buyer_name == "Sandbox Buyer"
    assert case.facts["tracking_uploaded_to_paypal"] is True
    assert case.facts["is_agent_purchase"] is True and case.facts["assistant_misordered"] is True
    assert case.order.demo_fixture and case.facts["demo_fixture"] is True
    assert any("DEMO FIXTURE" in c for c in case.tool_calls)
    assert store.by_invoice("JO-9999") is None and store.by_invoice("RB-no_such_case-1") is None  # real orders do not match
    assert mock.write_calls() == []


def test_guard_turns_accept_claim_on_a_high_value_damaged_item_into_return_for_refund():
    rt = Runtime(seed_cases=["snad_damaged_high_value", "snad_damaged_low_value", "snad_changed_mind"], force_rules=True)
    high, low, mind = (gather(d["dispute_id"], rt.client, rt.store, DEMO_NOW) for d in rt.client.list_disputes())
    assert high.facts["buyer_reports_damage"] is True and high.facts["refund_without_return_eligible"] is False
    d = guard(Decision("ACCEPT_CLAIM", 0.95, [], "", "We refunded you", "", source="groq"), high)
    assert d.resolution == "OFFER_RETURN_FOR_REFUND"
    assert any("above the refund-without-return threshold" in n for n in d.guard_notes)
    # A small damaged item is refunded outright, and a claim with no damage is not touched by this rule.
    assert low.facts["refund_without_return_eligible"] is True
    assert guard(Decision("ACCEPT_CLAIM", 0.95, [], "", "m", "", source="groq"), low).resolution == "ACCEPT_CLAIM"
    assert not mind.facts["buyer_reports_damage"]
    assert guard(Decision("ACCEPT_CLAIM", 0.9, [], "", "m", "", source="groq"), mind).guard_notes == []

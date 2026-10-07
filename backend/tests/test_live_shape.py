"""Regression tests for the first live hero-case run (dispute PP-R-HDU-10190454, Oct 7 2026).

The webhook fired while the real sandbox dispute was UNDER_REVIEW, so `allowed_response_options` was empty and the
guard let OFFER_REPLACEMENT through (PayPal rejects it); and the buyer's "I would like a refund" sat in the claim notes
(`disputed_transactions[].items[].notes`), not in `messages`, so buyer_asks_for_refund came out false. The fixture
below has the shape of that real response.
"""

import pytest

from rebuttal.agent.facts import buyer_statements, gather
from rebuttal.agent.reasoner import Decision, guard
from rebuttal.approval import not_allowed_now
from rebuttal.paypal.client import PayPalClient
from rebuttal.paypal.mock import MockPayPal
from rebuttal.runtime import Runtime
from rebuttal.scenarios import DEMO_NOW, fixture_order, iso, live_invoice_id
from rebuttal.store import MerchantStore

INVOICE = live_invoice_id("agent_wrong_size", 1791369508)


def live_dispute(status="UNDER_REVIEW", options=None) -> dict:
    """What the real sandbox returned for the hero case, trimmed to the fields we read."""
    d = {
        "dispute_id": "PP-R-HDU-10190454", "create_time": iso(DEMO_NOW), "update_time": iso(DEMO_NOW),
        "reason": "MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED", "status": status,
        "dispute_life_cycle_stage": "INQUIRY", "dispute_channel": "INTERNAL",
        "dispute_amount": {"currency_code": "USD", "value": "48.00"},
        "disputed_transactions": [{
            "seller_transaction_id": "1W850774E1348215P", "invoice_number": INVOICE, "custom": INVOICE,
            "buyer": {"name": "John Doe"},
            "items": [{"item_name": "Linen shirt (Navy / Size L)", "item_quantity": "1",
                       "reason": "MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED", "item_type": "PRODUCT",
                       "notes": "My shopping assistant placed this order for me. I asked for a size medium but the "
                                "shirt that arrived is a size large and does not fit. I would like a refund."}],
        }],
        "messages": [{"posted_by": "BUYER", "time_posted": iso(DEMO_NOW),
                      "content": "I used an AI shopping assistant to buy this navy linen shirt and told it to order "
                                 "size medium. The store shipped a size large. The shirt is unworn with tags on and I "
                                 "can send it back."}],
        "evidences": [{"evidence_type": "CREATE", "source": "SUBMITTED_BY_BUYER", "date": iso(DEMO_NOW),
                       "notes": "I used an AI shopping assistant to buy this navy linen shirt and told it to order "
                                "size medium. The store shipped a size large. The shirt is unworn with tags on and I "
                                "can send it back."}],
        "seller_response_due_date": iso(DEMO_NOW),
    }
    if options is not None:
        d["allowed_response_options"] = options
    return d


REAL_OPTIONS = {"accept_claim": {"accept_claim_types": ["PARTIAL_REFUND", "REFUND_WITH_RETURN", "REFUND"]},
                "make_offer": {"offer_types": ["REFUND", "REFUND_WITH_RETURN"]}}


@pytest.fixture
def live():
    mock = MockPayPal()
    client = PayPalClient("https://api-m.sandbox.paypal.com", "id", "secret", transport=mock.transport())
    mock.add_order("6UG58707TN2216157", "1W850774E1348215P")
    mock.add_dispute(live_dispute())  # UNDER_REVIEW and, like the real response, no allowed_response_options key at all
    store = MerchantStore(fixtures=fixture_order)
    return mock, client, store


def test_the_buyers_refund_request_is_read_from_the_claim_notes(live):
    mock, client, store = live
    dispute = mock.disputes["PP-R-HDU-10190454"]
    assert not any("refund" in m["content"] for m in dispute["messages"])  # the messages alone do not say it
    assert buyer_statements(dispute)[0].endswith("I would like a refund.")  # claim notes first, latest message last
    assert buyer_statements(dispute)[-1].endswith("I can send it back.")
    assert len(buyer_statements(dispute)) == 2  # the evidence copy of the opening message is not repeated
    case = gather("PP-R-HDU-10190454", client.read_only(), store, DEMO_NOW)
    assert case.facts["buyer_asks_for_refund"] is True
    assert case.facts["assistant_misordered"] is True and case.facts["order_found"] is True


def test_the_mock_has_the_real_shape_for_buyer_text():
    rt = Runtime(seed_cases=["agent_wrong_size"], force_rules=True)
    d = rt.client.get_dispute("PP-D-2000")
    assert d["disputed_transactions"][0]["items"][0]["notes"] and d["evidences"][0]["source"] == "SUBMITTED_BY_BUYER"
    assert rt.mock.disputes["PP-D-2000"]["allowed_response_options"]  # WAITING_FOR_SELLER_RESPONSE lists them


def test_with_no_allowed_options_the_guard_never_lets_a_replacement_through(live):
    mock, client, store = live
    case = gather("PP-R-HDU-10190454", client.read_only(), store, DEMO_NOW)
    assert case.allowed_response_options in (None, {}) and case.status == "UNDER_REVIEW"
    decision = guard(Decision("OFFER_REPLACEMENT", 0.95, ["policy says exchange"], "", "We will exchange it", "",
                              source="groq"), case)
    assert decision.resolution == "OFFER_RETURN_FOR_REFUND"
    assert "ship the right one as soon as the return is scanned" in decision.message_to_buyer  # the exchange promise
    assert any("not available" in n for n in decision.guard_notes)


def test_an_empty_options_object_behaves_like_a_missing_one(live):
    mock, client, store = live
    mock.disputes["PP-R-HDU-10190454"]["allowed_response_options"] = {}
    case = gather("PP-R-HDU-10190454", client.read_only(), store, DEMO_NOW)
    decision = guard(Decision("OFFER_REPLACEMENT", 0.95, [], "", "x", "", source="groq"), case)
    assert decision.resolution == "OFFER_RETURN_FOR_REFUND"


def test_the_fallback_only_applies_to_the_reason_the_sandbox_has_shown_us():
    """Item-not-received disputes with no listed options stay unrestricted here (nothing proven; execute and PayPal
    still refuse what is not allowed), and a chargeback never gets the offer-based fallback."""
    from rebuttal.agent.reasoner import effective_options

    assert effective_options(None, "MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED", "INQUIRY")[1] is True
    assert effective_options(None, "MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED", "CHARGEBACK") == (None, False)
    assert effective_options(None, "MERCHANDISE_OR_SERVICE_NOT_RECEIVED", "INQUIRY") == (None, False)
    replacement = {"kind": "make_offer", "params": {"offer_type": "REPLACEMENT_WITHOUT_REFUND", "note": "x"}}
    assert not_allowed_now({"reason": "MERCHANDISE_OR_SERVICE_NOT_RECEIVED", "dispute_life_cycle_stage": "INQUIRY"},
                           replacement) is None


def test_execute_refuses_a_replacement_when_paypal_lists_nothing(live):
    mock, client, store = live
    current = client.get_dispute("PP-R-HDU-10190454")
    assert "allowed_response_options" not in current or not current["allowed_response_options"]
    replacement = {"kind": "make_offer", "params": {"offer_type": "REPLACEMENT_WITHOUT_REFUND", "note": "x"}}
    assert "no longer allows" in not_allowed_now(current, replacement)
    refund = {"kind": "make_offer", "params": {"offer_type": "REFUND_WITH_RETURN", "note": "x"}}
    assert not_allowed_now(current, refund) is None


def test_the_graph_rechecks_allowed_options_at_the_guard(live, monkeypatch):
    """Gather saw an UNDER_REVIEW dispute with no options; by the guard PayPal lists them: the guard uses the fresh list."""
    mock, client, store = live
    rt = Runtime(seed_cases=[], force_rules=True)
    rt.mock, rt.client = mock, client
    from rebuttal.agent.graph import DisputeAgent
    from rebuttal.audit import AuditLog
    from langgraph.checkpoint.memory import InMemorySaver

    class ReplacementReasoner:  # a model that insists on a replacement
        name, model_name = "fake", "fake"

        def decide(self, case, config=None):
            return Decision("OFFER_REPLACEMENT", 0.95, ["exchange"], "", "We will exchange it", "", source="fake")

    agent = DisputeAgent(client=client, store=store, reasoner=ReplacementReasoner(), audit=AuditLog(),
                         clock=lambda: DEMO_NOW, checkpointer=InMemorySaver())
    real_get = client.__class__.get_dispute
    calls = {"n": 0}

    def get_dispute(self, dispute_id):  # first read (gather): under review; later reads: waiting for the seller
        calls["n"] += 1
        d = real_get(self, dispute_id)
        if calls["n"] > 1:
            d = {**d, "status": "WAITING_FOR_SELLER_RESPONSE", "allowed_response_options": REAL_OPTIONS}
        return d

    monkeypatch.setattr(PayPalClient, "get_dispute", get_dispute)
    proposal = agent.analyze("PP-R-HDU-10190454")
    assert proposal.actions[0].params["offer_type"] == "REFUND_WITH_RETURN"
    assert proposal.decision.resolution == "OFFER_RETURN_FOR_REFUND"
    assert mock.write_calls() == []  # analysis never writes


def test_the_guard_uses_the_fresh_list_even_when_it_is_now_empty(live, monkeypatch):
    mock, client, store = live
    from rebuttal.agent.graph import DisputeAgent
    from rebuttal.audit import AuditLog
    from langgraph.checkpoint.memory import InMemorySaver

    class Insists:
        name, model_name = "fake", "fake"

        def decide(self, case, config=None):
            return Decision("OFFER_REPLACEMENT", 0.95, ["exchange"], "", "We will exchange it", "", source="fake")

    agent = DisputeAgent(client=client, store=store, reasoner=Insists(), audit=AuditLog(),
                         clock=lambda: DEMO_NOW, checkpointer=InMemorySaver())
    real_get, calls = PayPalClient.get_dispute, {"n": 0}

    def get_dispute(self, dispute_id):  # gather sees a stale list that allows replacements; the guard's read has none
        calls["n"] += 1
        d = real_get(self, dispute_id)
        if calls["n"] == 1:
            d = {**d, "allowed_response_options": {"make_offer": {"offer_types": ["REPLACEMENT_WITHOUT_REFUND"]},
                                                   "accept_claim": {"accept_claim_types": ["REFUND"]}}}
        return d

    monkeypatch.setattr(PayPalClient, "get_dispute", get_dispute)
    proposal = agent.analyze("PP-R-HDU-10190454")
    assert proposal.actions[0].params["offer_type"] == "REFUND_WITH_RETURN"

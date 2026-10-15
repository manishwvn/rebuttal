"""R12: at CHARGEBACK, a claim that needs the item back is accepted as REFUND_WITH_RETURN, not a plain refund.

Built from the real sandbox capture of 2026-10-15 (queue S4): PP-R-HDU-10190454 at CHARGEBACK listed only accept_claim
types (tests/fixtures/sandbox_dispute_chargeback.json), refused REFUND_WITH_RETURN without a return address
(MISSING_RETURN_SHIPPING_ADDRESS) and took it with one, moving to UNDER_REVIEW.
"""

import json
from pathlib import Path

import pytest

from rebuttal import policies
from rebuttal.agent.facts import gather
from rebuttal.agent.pipeline import plan_actions
from rebuttal.agent.reasoner import Decision, draft_message, guard, paypal_allows
from rebuttal.approval import execute_action, not_allowed_now
from rebuttal.paypal.client import PayPalClient, PayPalError, permit_writes
from rebuttal.paypal.mock import MockPayPal
from rebuttal.runtime import Runtime
from rebuttal.scenarios import DEMO_NOW

FIXTURES = Path(__file__).parent / "fixtures"
BASE = "https://api-m.sandbox.paypal.com"


def _live(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


CHARGEBACK_OPTIONS = _live("sandbox_dispute_chargeback.json")["allowed_response_options"]


def _chargeback_case(case_id: str):
    rt = Runtime(seed_cases=[case_id], force_rules=True)
    case = gather("PP-D-2000", rt.client, rt.store, DEMO_NOW)
    case.stage = "CHARGEBACK"
    case.allowed_response_options = CHARGEBACK_OPTIONS
    return case


def test_live_chargeback_lists_only_claim_types_with_a_return():
    assert set(CHARGEBACK_OPTIONS) == {"accept_claim"}
    assert "REFUND_WITH_RETURN" in CHARGEBACK_OPTIONS["accept_claim"]["accept_claim_types"]


def test_return_needed_offer_at_chargeback_becomes_claim_with_return():
    case = _chargeback_case("agent_wrong_size")
    assert case.facts["refund_without_return_eligible"] is False
    assert not paypal_allows("OFFER_RETURN_FOR_REFUND", case)
    d = guard(Decision("OFFER_REPLACEMENT", 0.9, [], "", "m", "", source="claude"), case)
    assert d.resolution == "ACCEPT_CLAIM"
    [action] = plan_actions(d, case)
    assert action.kind == "accept_claim"
    assert action.params["accept_claim_type"] == "REFUND_WITH_RETURN"
    assert action.params["return_address"] == policies.RETURN_ADDRESS
    assert "after return" in action.summary


def test_small_damaged_item_at_chargeback_stays_a_plain_refund():
    case = _chargeback_case("snad_damaged_low_value")
    assert case.facts["refund_without_return_eligible"] is True
    [action] = plan_actions(Decision("ACCEPT_CLAIM", 0.9, [], "", "m", ""), case)
    assert "accept_claim_type" not in action.params


def test_not_received_claim_never_asks_for_a_return():
    case = _chargeback_case("inr_no_tracking")
    case.facts["refund_without_return_eligible"] = False
    [action] = plan_actions(Decision("ACCEPT_CLAIM", 0.9, [], "", "m", ""), case)
    assert "accept_claim_type" not in action.params


def test_no_return_type_listed_means_plain_refund():
    case = _chargeback_case("agent_wrong_size")
    case.allowed_response_options = {"accept_claim": {"accept_claim_types": ["REFUND"]}}
    [action] = plan_actions(Decision("ACCEPT_CLAIM", 0.9, [], "", "m", ""), case)
    assert "accept_claim_type" not in action.params


def test_execute_refuses_a_claim_type_paypal_no_longer_lists():
    action = {"kind": "accept_claim", "params": {"note": "m", "accept_claim_type": "REFUND_WITH_RETURN"}}
    dispute = {"reason": "MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED", "dispute_life_cycle_stage": "CHARGEBACK",
               "status": "WAITING_FOR_SELLER_RESPONSE",
               "allowed_response_options": {"accept_claim": {"accept_claim_types": ["REFUND"]}}}
    assert "REFUND_WITH_RETURN" in not_allowed_now(dispute, action)
    dispute["allowed_response_options"] = CHARGEBACK_OPTIONS
    assert not_allowed_now(dispute, action) is None


def _mock_chargeback() -> tuple[MockPayPal, PayPalClient]:
    sandbox = MockPayPal()
    sandbox.add_dispute({
        "dispute_id": "PP-D-CB", "create_time": "2026-10-01T00:00:00.000Z", "update_time": "2026-10-01T00:00:00.000Z",
        "reason": "MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED", "status": "WAITING_FOR_SELLER_RESPONSE",
        "dispute_life_cycle_stage": "CHARGEBACK", "dispute_channel": "INTERNAL",
        "dispute_amount": {"currency_code": "USD", "value": "48.00"},
        "disputed_transactions": [{"seller_transaction_id": "CAP-1"}],
    })
    return sandbox, PayPalClient(BASE, "id", "secret", transport=sandbox.transport())


def test_mock_chargeback_options_mirror_the_live_capture():
    sandbox, client = _mock_chargeback()
    assert client.get_dispute("PP-D-CB")["allowed_response_options"] == CHARGEBACK_OPTIONS


def test_mock_refuses_claim_with_return_without_an_address_like_the_sandbox():
    live = _live("sandbox_accept_return_no_address_PP-R-HDU-10190454.json")["first_attempt"]["error"]["details"]
    _, client = _mock_chargeback()
    with permit_writes(), pytest.raises(PayPalError) as exc:
        client.accept_claim("PP-D-CB", note="m", accept_claim_type="REFUND_WITH_RETURN", request_id="r1")
    assert exc.value.status == 400 and exc.value.body["details"] == live


def test_execute_sends_claim_with_return_and_dispute_waits_for_the_return():
    _, client = _mock_chargeback()
    action = {"kind": "accept_claim", "params": {"note": "m", "accept_claim_type": "REFUND_WITH_RETURN",
                                                 "return_address": policies.RETURN_ADDRESS}}
    with permit_writes():
        execute_action(client, "PP-D-CB", action, "req-cb-1", None)
    after = client.get_dispute("PP-D-CB")
    assert after["status"] == "UNDER_REVIEW" and "allowed_response_options" not in after


def test_buyer_note_for_claim_with_return_promises_refund_after_return():
    case = _chargeback_case("agent_wrong_size")
    d = guard(Decision("OFFER_REPLACEMENT", 0.9, [], "", "m", "", source="claude"), case)
    assert d.resolution == "ACCEPT_CLAIM"
    assert "refunded" not in d.message_to_buyer and "as soon as the return arrives" in d.message_to_buyer
    case.allowed_response_options = {"accept_claim": {"accept_claim_types": ["REFUND"]}}
    assert "refunded you in full" in draft_message("ACCEPT_CLAIM", case)


def _waiting(options) -> dict:
    return {"reason": "MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED", "dispute_life_cycle_stage": "CHARGEBACK",
            "status": "WAITING_FOR_SELLER_RESPONSE", "allowed_response_options": options}


def test_not_allowed_now_claim_type_edges():
    plain = {"kind": "accept_claim", "params": {"note": "m"}}
    with_return = {"kind": "accept_claim", "params": {"note": "m", "accept_claim_type": "REFUND_WITH_RETURN"}}
    assert "REFUND" in not_allowed_now(_waiting({"accept_claim": {"accept_claim_types": ["REFUND_WITH_RETURN"]}}), plain)
    assert not_allowed_now(_waiting({"accept_claim": {}}), plain) is None  # no type list: old behaviour
    assert not_allowed_now(_waiting({"accept_claim": None}), plain) is None  # never raises after interrupt()
    replay = _waiting(None) | {"status": "UNDER_REVIEW"}
    assert "no longer waiting for the seller" in not_allowed_now(replay, with_return)


def test_mock_refuses_an_unlisted_claim_type():
    _, client = _mock_chargeback()
    client.get_dispute("PP-D-CB")
    with permit_writes(), pytest.raises(PayPalError) as exc:
        client.accept_claim("PP-D-CB", note="m", accept_claim_type="NOT_A_TYPE", request_id="r2")
    assert exc.value.status == 400

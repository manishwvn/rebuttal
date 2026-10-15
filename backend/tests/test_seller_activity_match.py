"""Seller messages are matched whitespace-normalised, so a copy PayPal re-wraps still counts as already sent."""

from rebuttal.agent.facts import normalize_text, seller_activity
from rebuttal.approval import already_applied


def test_seller_activity_normalises_message_whitespace():
    dispute = {
        "messages": [{"posted_by": "SELLER", "content": "  Hello   there,\nthanks \t"},
                     {"posted_by": "BUYER", "content": "x"}],
        "offer": {"history": [{"actor": "SELLER", "offer_type": "REFUND"},
                              {"actor": "BUYER", "offer_type": "REFUND"}]},
    }
    assert seller_activity(dispute) == {"messages": ["Hello there, thanks"], "offers": ["REFUND"]}
    assert normalize_text(None) == ""


def test_already_applied_matches_a_message_that_paypal_re_wrapped():
    dispute = {"messages": [{"posted_by": "SELLER", "content": "We will  refund\nyou today."}]}
    action = {"kind": "send_message", "params": {"message": "We will refund you today."}}
    assert already_applied(dispute, action, {"seller_activity": {"messages": [], "offers": []}}) is True
    # The same unnormalised text was already on the dispute when the proposal was made: this send is not new.
    before = {"seller_activity": {"messages": ["We will  refund\nyou today."]}}
    assert already_applied(dispute, action, before) is False


def test_already_applied_still_false_for_a_different_message():
    dispute = {"messages": [{"posted_by": "SELLER", "content": "We will  refund\nyou today."}]}
    action = {"kind": "send_message", "params": {"message": "We will refund you next week."}}
    assert already_applied(dispute, action, {"seller_activity": {"messages": [], "offers": []}}) is False

"""Checks on the redacted sandbox fixtures that scripts/spike_shapes.py saved from the live PayPal sandbox (queue task S3).

Every sandbox_dispute_*.json is a dispute as the real sandbox returned it, redacted. The generic checks hold for each
one: it parses, no personal string is left, and the facts the agent reads from it still compute. The targeted checks
pin what each confirmed item in docs/sandbox-findings.md observed. The fixtures are a snapshot: a rerun of `survey`
replaces its category snapshots, and a write command never overwrites its record (it refuses), so each rerun on a
dispute adds a file named for that dispute. The targeted checks then need updating with the new findings.
"""

import json
from pathlib import Path

import pytest

from rebuttal.agent.facts import dispute_actions, seller_activity

FIXTURES = Path(__file__).resolve().parent / "fixtures"
DISPUTE_FIXTURES = sorted(FIXTURES.glob("sandbox_dispute_*.json"))
PLACEHOLDER = "redacted@example.com"
SELLER_MESSAGE = "Research sandbox run: seller reply to the buyer's inquiry."


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def strings(obj):
    if isinstance(obj, dict):
        for value in obj.values():
            yield from strings(value)
    elif isinstance(obj, list):
        for item in obj:
            yield from strings(item)
    elif isinstance(obj, str):
        yield obj


def rels(dispute: dict) -> list[str]:
    return sorted(link["rel"] for link in dispute.get("links") or [])


def test_there_is_at_least_one_dispute_fixture():
    assert DISPUTE_FIXTURES, "no sandbox_dispute_*.json fixture: run `python -m scripts.spike_shapes survey` first"


@pytest.mark.parametrize("path", DISPUTE_FIXTURES, ids=lambda p: p.name)
def test_fixture_parses_and_holds_no_personal_string(path):
    dispute = json.loads(path.read_text())
    assert isinstance(dispute, dict) and dispute.get("dispute_id")
    for value in strings(dispute):
        assert "@" not in value or value == PLACEHOLDER, path.name


@pytest.mark.parametrize("path", DISPUTE_FIXTURES, ids=lambda p: p.name)
def test_dispute_actions_follow_the_links_and_stage(path):
    dispute = json.loads(path.read_text())
    expected = {
        "can_escalate": "escalate" in rels(dispute) and dispute.get("dispute_life_cycle_stage") == "INQUIRY",
        "can_appeal": "appeal" in rels(dispute),
    }
    actions = dispute_actions(dispute)
    assert actions == expected, path.name
    assert all(isinstance(value, bool) for value in actions.values())


@pytest.mark.parametrize("path", DISPUTE_FIXTURES, ids=lambda p: p.name)
def test_seller_activity_reads_without_error(path):
    activity = seller_activity(json.loads(path.read_text()))
    assert isinstance(activity["messages"], list) and isinstance(activity["offers"], list)


def test_item_1_the_escalate_link_is_offered_on_an_inquiry_waiting_for_the_seller():
    d = load("sandbox_dispute_escalate_link.json")
    assert d["dispute_life_cycle_stage"] == "INQUIRY" and d["status"] == "WAITING_FOR_SELLER_RESPONSE"
    assert "escalate" in rels(d) and "appeal" not in rels(d)
    assert dispute_actions(d) == {"can_escalate": True, "can_appeal": False}


def test_item_2_escalate_is_accepted_on_an_inquiry_under_review():
    # CONFIRMED on UNDER_REVIEW only. The run on PP-R-GFH-10190453 (WAITING_FOR_SELLER_RESPONSE) saved to the same
    # name and was overwritten, so its acceptance has no fixture. The escalate link was already absent here.
    record = load("sandbox_escalate_response_PP-R-HDU-10190454.json")
    assert record["before"]["stage"] == "INQUIRY" and record["before"]["status"] == "UNDER_REVIEW"
    assert "escalate" not in record["before"]["link_rels"]
    assert record["first_attempt"]["ok"] is True
    assert record["after"]["stage"] == "INQUIRY" and record["after"]["status"] == "UNDER_REVIEW"


def test_item_6_escalate_was_accepted_without_buyer_escalation_reason():
    # CONFIRMED on this UNDER_REVIEW dispute only: the retry with buyer_escalation_reason never ran.
    record = load("sandbox_escalate_response_PP-R-HDU-10190454.json")
    assert record["first_attempt"]["ok"] is True
    assert "retry_with_buyer_escalation_reason" not in record


def test_item_7_no_fixture_shows_escalate_removing_the_link():
    # STILL UNVERIFIED for removal by escalate. On HDU the link was already absent before the escalate, so the record
    # cannot show removal. The GFH post-state has no escalate link, but it is a later read, not a before/after pair.
    record = load("sandbox_escalate_response_PP-R-HDU-10190454.json")
    assert "escalate" not in record["before"]["link_rels"] and "escalate" not in record["after"]["link_rels"]
    gfh = load("sandbox_proof_of_return_response_PP-R-GFH-10190453.json")
    assert "escalate" not in gfh["after"]["link_rels"] and "provide_evidence" in gfh["after"]["link_rels"]


def test_item_5_a_seller_message_moves_the_inquiry_to_under_review_without_escalate():
    d = load("sandbox_dispute_after_seller_message_PP-R-HDU-10190454.json")
    assert d["dispute_life_cycle_stage"] == "INQUIRY" and d["status"] == "UNDER_REVIEW"
    assert "escalate" not in rels(d)
    assert seller_activity(d)["messages"] == [SELLER_MESSAGE]


def test_item_9_an_inquiry_under_review_omits_the_seller_response_due_date():
    d = load("sandbox_dispute_inquiry_under_review.json")
    assert d["status"] == "UNDER_REVIEW" and "seller_response_due_date" not in d
    assert "allowed_response_options" not in d


def test_item_9_an_inquiry_waiting_for_the_seller_shows_the_seller_response_due_date():
    d = load("sandbox_dispute_escalate_link.json")
    assert "seller_response_due_date" in d and "allowed_response_options" in d


def test_item_5_a_buyer_reply_fixture_is_still_waiting_for_buyer_and_the_offer_has_a_seller_actor():
    d = load("sandbox_dispute_after_buyer_reply_PP-R-GBK-10190434.json")
    assert d["dispute_life_cycle_stage"] == "INQUIRY" and d["status"] == "WAITING_FOR_BUYER_RESPONSE"
    assert "escalate" in rels(d)
    assert seller_activity(d)["offers"] == ["REFUND_WITH_RETURN"]
    assert "seller_response_due_date" not in d and "allowed_response_options" in d


def test_item_4_proof_of_return_was_refused_with_the_exact_issue_codes():
    record = load("sandbox_proof_of_return_response_PP-R-GFH-10190453.json")
    assert record["evidence_type"] == "PROOF_OF_RETURN" and record["result"]["ok"] is False
    assert record["result"]["http_status"] == 400
    assert record["result"]["error"]["details"] == [{"issue": "EVIDENCE_TYPE_IS_NOT_ALLOWED"}]
